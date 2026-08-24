# -*- coding: utf-8 -*-
"""斗地主本地游戏服务器。

- 静态文件服务（游戏页面 / css / js）
- JSON API（状态查询 / 人类动作 / 设置）
- 机器人异步调度（按设置的延迟自动出牌）

只监听 127.0.0.1，完全本地运行。
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import unquote, urlparse

from engine import PHASE_BIDDING, PHASE_PLAYING, Game

GAME_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8765
SERVER_VERSION = "1.2.0"
MIN_BOT_DELAY_MS = 500
MAX_BOT_DELAY_MS = 5000
MAX_REQUEST_BODY = 64 * 1024


class GameServer:
    """持有对局实例并负责机器人调度。"""

    def __init__(self, bot_delay_ms: int = 900,
                 auto_pilot: bool = False, seed: Optional[int] = None,
                 state_path: Optional[str] = None):
        self.lock = threading.RLock()
        self.game = Game(seed=seed)
        self.bot_delay_ms = max(MIN_BOT_DELAY_MS,
                                min(MAX_BOT_DELAY_MS, int(bot_delay_ms)))
        self.auto_pilot = bool(auto_pilot)
        self.started = False
        self.state_path = state_path
        self._tick_lock = threading.Lock()
        self._scheduled = None  # (actor, version)
        self._timer: Optional[threading.Timer] = None
        self._load_state()

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            d = self.game.snapshot()
            d["settings"] = {
                "bot_delay_ms": self.bot_delay_ms,
                "auto_pilot": self.auto_pilot,
                "started": self.started,
            }
            return d

    def _load_state(self) -> None:
        if not self.state_path or not os.path.isfile(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.game = Game.from_state(saved["game"])
            settings = saved.get("settings", {})
            self.bot_delay_ms = max(
                MIN_BOT_DELAY_MS,
                min(MAX_BOT_DELAY_MS, int(settings.get("bot_delay_ms", self.bot_delay_ms))),
            )
            self.auto_pilot = bool(settings.get("auto_pilot", False))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            # 损坏或旧版本存档不能阻止游戏启动；保留文件供排查并回退为新局。
            self.game = Game()
            self.auto_pilot = False

    def _save_state(self) -> None:
        if not self.state_path:
            return
        directory = os.path.dirname(os.path.abspath(self.state_path))
        tmp = "%s.tmp.%d" % (self.state_path, os.getpid())
        try:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(tmp, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({
                    "version": SERVER_VERSION,
                    "game": self.game.export_state(),
                    "settings": {
                        "bot_delay_ms": self.bot_delay_ms,
                        "auto_pilot": self.auto_pilot,
                    },
                }, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.state_path)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def act(self, payload: dict) -> dict:
        """处理人类动作，返回 {ok, error?, hint?, state}。"""
        action = str(payload.get("action", ""))
        with self.lock:
            g = self.game
            if action in {"start", "bid", "play", "pass", "new_round",
                          "set_delay", "set_auto"} and "expected_version" in payload:
                try:
                    expected = int(payload["expected_version"])
                except (TypeError, ValueError):
                    return {"ok": False, "error": "状态版本格式错误",
                            "state": self.snapshot()}
                if expected != g.version:
                    return {"ok": False, "conflict": True,
                            "error": "牌局已在另一个标签页更新，请确认最新状态后重试",
                            "state": self.snapshot()}
            try:
                if action == "start":
                    if not self.started:
                        self.started = True
                        g.version += 1
                elif action == "bid":
                    if not self.started:
                        raise ValueError("请先点击开始游戏")
                    g.bid(g.human, int(payload.get("bid", 0)))
                elif action == "play":
                    if not self.started:
                        raise ValueError("请先点击开始游戏")
                    raw = payload.get("cards", [])
                    if not isinstance(raw, list):
                        raise ValueError("出牌数据格式错误")
                    g.play(g.human, [int(c) for c in raw])
                elif action == "pass":
                    if not self.started:
                        raise ValueError("请先点击开始游戏")
                    g.pass_turn(g.human)
                elif action == "hint":
                    return {"ok": True, "hint": g.hint(),
                            "state": self.snapshot()}
                elif action == "new_round":
                    self._cancel_schedule()
                    self.started = True
                    g._new_round()
                elif action == "set_delay":
                    self.bot_delay_ms = max(
                        MIN_BOT_DELAY_MS,
                        min(MAX_BOT_DELAY_MS, int(payload.get("ms", 900))),
                    )
                    self._cancel_schedule()
                    g.version += 1
                elif action == "set_auto":
                    self.auto_pilot = bool(payload.get("on", False))
                    if not self.auto_pilot:
                        self._cancel_schedule(human_only=True)
                    g.version += 1
                else:
                    return {"ok": False, "error": "未知动作：%s" % action,
                            "state": self.snapshot()}
            except (ValueError, TypeError) as e:
                return {"ok": False, "error": str(e), "state": self.snapshot()}
            self._save_state()
            self._schedule()
            return {"ok": True, "state": self.snapshot()}

    # ------------------------------------------------------------------
    # 机器人调度
    # ------------------------------------------------------------------

    def _next_actor(self) -> Optional[int]:
        g = self.game
        if not self.started:
            return None
        if g.phase in (PHASE_BIDDING, PHASE_PLAYING):
            actor = g.turn
            if actor != g.human or self.auto_pilot:
                return actor
        return None

    def _schedule(self) -> None:
        actor = self._next_actor()
        if actor is None:
            return
        version = self.game.version
        with self._tick_lock:
            if self._scheduled is not None:
                return
            self._scheduled = (actor, version)
        delay = self.bot_delay_ms / 1000.0
        t = threading.Timer(delay, self._bot_tick)
        t.daemon = True
        self._timer = t
        t.start()

    def _cancel_schedule(self, human_only: bool = False) -> None:
        with self._tick_lock:
            if human_only and self._scheduled is not None \
                    and self._scheduled[0] != self.game.human:
                return
            timer = self._timer
            self._timer = None
            self._scheduled = None
        if timer is not None:
            timer.cancel()

    def _bot_tick(self) -> None:
        with self._tick_lock:
            scheduled = self._scheduled
            self._scheduled = None
            self._timer = None
        if scheduled is None:
            return
        actor, version = scheduled
        try:
            with self.lock:
                g = self.game
                if g.phase in (PHASE_BIDDING, PHASE_PLAYING) \
                        and g.turn == actor and g.version == version \
                        and self.started \
                        and (actor != g.human or self.auto_pilot):
                    g.bot_move(actor)
                    self._save_state()
        except Exception:
            import traceback
            traceback.print_exc()
        self._schedule()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "Doudizhu/" + SERVER_VERSION
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5.0)

    def version_string(self) -> str:
        return self.server_version

    def _send(self, code: int, body: bytes, ctype: str,
              cache_control: str = "no-store", headers: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, obj, headers: Optional[dict] = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8", headers=headers)

    def _allowed_host(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        return origin in ("http://127.0.0.1:%d" % port,
                          "http://localhost:%d" % port)

    def _static(self, path: str) -> None:
        rel = path.lstrip("/")
        if not rel:
            rel = "index.html"
        full = os.path.realpath(os.path.join(GAME_DIR, rel))
        try:
            inside = os.path.commonpath((GAME_DIR, full)) == GAME_DIR
        except ValueError:
            inside = False
        if not inside or not os.path.isfile(full):
            self._json(404, {"error": "资源不存在"})
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:20]
        cache = "no-cache" if rel == "index.html" else "public, max-age=3600"
        if self.headers.get("If-None-Match") == etag:
            self._send(304, b"", ctype, cache, {"ETag": etag})
            return
        self._send(200, body, ctype, cache, {"ETag": etag})

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed_host():
            self._json(421, {"error": "无效的本地主机"})
            return
        path = unquote(urlparse(self.path).path)
        if path == "/api/health":
            self._json(200, {
                "service": "doudizhu", "version": SERVER_VERSION,
                "pid": os.getpid(), "instance_id": self.server.instance_id,
            })
            return
        if path == "/api/state":
            self._json(200, self.server.dsh.snapshot(), {
                "X-Doudizhu-Token": self.server.action_token,
            })
            return
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "接口不存在"})
            return
        self._static(path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed_host() or not self._same_origin():
            self._json(403, {"ok": False, "error": "拒绝跨站请求"})
            return
        path = unquote(urlparse(self.path).path)
        if path != "/api/action":
            self._json(404, {"error": "接口不存在"})
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._json(415, {"ok": False, "error": "仅接受 application/json"})
            return
        if not secrets.compare_digest(
                self.headers.get("X-Doudizhu-Token", ""), self.server.action_token):
            self._json(403, {"ok": False, "error": "无效的本地会话令牌"})
            return
        try:
            if "Content-Length" not in self.headers:
                self._json(411, {"ok": False, "error": "缺少请求长度"})
                return
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > MAX_REQUEST_BODY:
                self._json(413, {"ok": False, "error": "请求内容过大"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:
            self._json(400, {"ok": False, "error": "请求格式错误"})
            return
        result = self.server.dsh.act(payload)
        code = 200 if result.get("ok") else (409 if result.get("conflict") else 422)
        self._json(code, result)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json(403, {"error": "不支持跨站预检"})

    def log_message(self, fmt, *args):  # 静默访问日志，避免刷屏
        pass


class DoudizhuHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._request_slots = threading.BoundedSemaphore(32)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def create_server(port: int = DEFAULT_PORT, bot_delay_ms: int = 900,
                   auto_pilot: bool = False, seed: Optional[int] = None,
                   state_path: Optional[str] = None):
    """创建（未启动）服务器；port=0 时自动分配端口。"""
    dsh = GameServer(bot_delay_ms=bot_delay_ms, auto_pilot=auto_pilot,
                     seed=seed, state_path=state_path)
    httpd = DoudizhuHTTPServer(("127.0.0.1", port), Handler)
    httpd.dsh = dsh
    httpd.action_token = secrets.token_urlsafe(32)
    httpd.instance_id = secrets.token_hex(16)
    return httpd


def _write_pidfile(path: str, data: dict) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def run_server(port: int = DEFAULT_PORT, open_browser: bool = False,
               pidfile: Optional[str] = None,
               state_path: Optional[str] = None) -> None:
    """启动游戏服务器并打开浏览器。"""
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = create_server(p, state_path=state_path)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("错误：端口 %d-%d 均被占用，无法启动游戏服务器。" % (port, port + 19))
        sys.exit(1)

    url = "http://127.0.0.1:%d/" % port
    if pidfile:
        try:
            _write_pidfile(pidfile, {
                "pid": os.getpid(), "port": port,
                "instance_id": httpd.instance_id,
            })
        except OSError:
            pass  # 写不了 pidfile 不影响运行
    print("=" * 46, flush=True)
    print("  斗地主游戏服务器已启动", flush=True)
    print("  请在浏览器打开: %s" % url, flush=True)
    print("  停止服务器: python3 scripts/stop_game.py", flush=True)
    print("=" * 46, flush=True)
    if open_browser:
        # 仅供用户显式要求系统浏览器时使用；Codex 插件默认由内置 Browser 打开。
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")
    finally:
        httpd.server_close()
        if pidfile and os.path.exists(pidfile):
            try:
                os.remove(pidfile)
            except OSError:
                pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="斗地主游戏服务器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="起始端口")
    parser.add_argument("--no-browser", action="store_true", help="兼容参数；默认不打开系统浏览器")
    parser.add_argument("--system-browser", action="store_true", help="显式使用系统默认浏览器")
    parser.add_argument("--pidfile", default=None, help="写入 pid/port 的 JSON 文件")
    parser.add_argument("--state-path", default=None, help="持久化本地牌局状态的 JSON 文件")
    args = parser.parse_args()
    run_server(port=args.port, open_browser=args.system_browser and not args.no_browser,
               pidfile=args.pidfile, state_path=args.state_path)
