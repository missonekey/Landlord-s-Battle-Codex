# -*- coding: utf-8 -*-
"""斗地主本地游戏服务器。

- 静态文件服务（游戏页面 / css / js）
- JSON API（状态查询 / 人类动作 / 设置）
- 机器人异步调度（按设置的延迟自动出牌）

只监听 127.0.0.1，完全本地运行。
"""
from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from engine import PHASE_BIDDING, PHASE_PLAYING, Game

GAME_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8765
APP_ID = "codex-doudizhu"
APP_VERSION = "1.2.1"
MAX_BODY_BYTES = 16 * 1024
MAX_HTTP_WORKERS = 32
SESSION_COOKIE = "ddz_session"
PUBLIC_FILES = {
    "index.html",
    "css/style.css",
    "js/main.js",
    "js/render.js",
    "assets/favicon.svg",
}


class GameServer:
    """持有对局实例并负责机器人调度。"""

    def __init__(self, bot_delay_ms: int = 900,
                 auto_pilot: bool = False, seed: Optional[int] = None):
        self.lock = threading.RLock()
        self.game = Game(seed=seed)
        self.session_token = secrets.token_urlsafe(24)
        self.bot_delay_ms = max(0, min(5000, int(bot_delay_ms)))
        self.auto_pilot = bool(auto_pilot)
        self._tick_lock = threading.Lock()
        self._scheduled: Optional[Tuple[int, int]] = None  # (actor, version)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            d = self.game.snapshot()
            d["settings"] = {
                "bot_delay_ms": self.bot_delay_ms,
                "auto_pilot": self.auto_pilot,
            }
            return d

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def act(self, payload: dict) -> dict:
        """处理人类动作，返回 {ok, error?, hint?, state}。"""
        action = str(payload.get("action", ""))
        with self.lock:
            g = self.game
            try:
                if action == "bid":
                    g.bid(g.human, int(payload.get("bid", 0)))
                elif action == "play":
                    raw = payload.get("cards", [])
                    if not isinstance(raw, list):
                        raise ValueError("出牌数据格式错误")
                    g.play(g.human, [int(c) for c in raw])
                elif action == "pass":
                    g.pass_turn(g.human)
                elif action == "hint":
                    return {"ok": True, "hint": g.hint(),
                            "state": self.snapshot()}
                elif action == "new_round":
                    g._new_round()
                elif action == "set_delay":
                    self.bot_delay_ms = max(0, min(5000, int(payload.get("ms", 900))))
                elif action == "set_auto":
                    self.auto_pilot = bool(payload.get("on", False))
                else:
                    return {"ok": False, "error": "未知动作：%s" % action,
                            "state": self.snapshot()}
            except (ValueError, TypeError, OverflowError) as e:
                return {"ok": False, "error": str(e), "state": self.snapshot()}
            self._schedule()
            return {"ok": True, "state": self.snapshot()}

    # ------------------------------------------------------------------
    # 机器人调度
    # ------------------------------------------------------------------

    def _next_actor(self) -> Optional[int]:
        g = self.game
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
        t.start()

    def _bot_tick(self) -> None:
        with self._tick_lock:
            scheduled = self._scheduled
            self._scheduled = None
        if scheduled is None:
            return
        actor, version = scheduled
        try:
            with self.lock:
                g = self.game
                if g.phase in (PHASE_BIDDING, PHASE_PLAYING) \
                        and g.turn == actor and g.version == version \
                        and self._next_actor() == actor:
                    g.bot_move(actor)
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self._schedule()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "Doudizhu/%s" % APP_VERSION
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def _send(self, code: int, body: bytes, ctype: str,
              cache_control: str = "no-store",
              headers: Optional[Dict[str, str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, obj, conditional: bool = False) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        if conditional:
            etag = '"%s"' % hashlib.sha256(body).hexdigest()[:24]
            if self.headers.get("If-None-Match") == etag:
                self._send(304, b"", "application/json; charset=utf-8",
                           "private, no-cache", {"ETag": etag})
                return
            self._send(code, body, "application/json; charset=utf-8",
                       "private, no-cache", {"ETag": etag})
            return
        self._send(code, body, "application/json; charset=utf-8")

    def _allowed_hosts(self):
        port = self.server.server_address[1]
        return {"127.0.0.1:%d" % port, "localhost:%d" % port}

    def _host_allowed(self) -> bool:
        return self.headers.get("Host", "").lower() in self._allowed_hosts()

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin.lower() in {"http://%s" % host for host in self._allowed_hosts()}

    def _session_allowed(self) -> bool:
        raw = self.headers.get("Cookie", "")
        try:
            cookie = SimpleCookie()
            cookie.load(raw)
            value = cookie.get('%s_%d' % (SESSION_COOKIE, self.server.server_address[1]))
            return value is not None and secrets.compare_digest(
                value.value, self.server.dsh.session_token)
        except (CookieError, ValueError):
            return False

    def _static(self, path: str) -> None:
        rel = path.lstrip("/")
        if not rel:
            rel = "index.html"
        if rel not in PUBLIC_FILES:
            self._json(404, {"error": "资源不存在"})
            return
        full = os.path.realpath(os.path.join(GAME_DIR, rel))
        if os.path.commonpath((GAME_DIR, full)) != GAME_DIR or not os.path.isfile(full):
            self._json(404, {"error": "资源不存在"})
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:24]
        cache_control = "private, no-cache" if rel == "index.html" else "public, max-age=3600"
        headers = {"ETag": etag}
        if rel == "index.html":
            headers["Set-Cookie"] = "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (
                '%s_%d' % (SESSION_COOKIE, self.server.server_address[1]), self.server.dsh.session_token)
        if self.headers.get("If-None-Match") == etag:
            self._send(304, b"", ctype, cache_control, headers)
            return
        self._send(200, body, ctype, cache_control, headers)

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._json(403, {"error": "无效的请求主机"})
            return
        path = unquote(urlparse(self.path).path)
        if path == "/api/health":
            self._json(200, {"ok": True, "app": APP_ID, "version": APP_VERSION})
            return
        if path == "/api/state":
            self._json(200, self.server.dsh.snapshot(), conditional=True)
            return
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "接口不存在"})
            return
        self._static(path)

    def do_POST(self) -> None:  # noqa: N802
        # 失败分支可能尚未读取请求体，关闭连接防止残留字节被当作下一条请求。
        self.close_connection = True
        if not self._host_allowed() or not self._origin_allowed():
            self._json(403, {"ok": False, "error": "请求来源不受信任"})
            return
        path = unquote(urlparse(self.path).path)
        if path != "/api/action":
            self._json(404, {"error": "接口不存在"})
            return
        if not self._session_allowed():
            self._json(403, {"ok": False, "error": "会话校验失败，请刷新页面"})
            return
        ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            self._json(415, {"ok": False, "error": "仅接受 JSON 请求"})
            return
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self._json(400, {"ok": False, "error": "不支持分块请求"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                self.close_connection = True
                self._json(413, {"ok": False, "error": "请求体大小无效"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:
            self._json(400, {"ok": False, "error": "请求格式错误"})
            return
        result = self.server.dsh.act(payload)
        code = 200 if result.get("ok") else 422
        self._json(code, result)

    def log_message(self, fmt, *args):  # 静默访问日志，避免刷屏
        pass


class LimitedThreadingHTTPServer(ThreadingHTTPServer):
    """限制并发请求线程，避免本地异常页面无限制造线程。"""

    daemon_threads = True
    request_queue_size = MAX_HTTP_WORKERS

    def __init__(self, *args, **kwargs):
        self._worker_slots = threading.BoundedSemaphore(MAX_HTTP_WORKERS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._worker_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


def create_server(port: int = DEFAULT_PORT, bot_delay_ms: int = 900,
                   auto_pilot: bool = False, seed: Optional[int] = None):
    """创建（未启动）服务器；port=0 时自动分配端口。"""
    dsh = GameServer(bot_delay_ms=bot_delay_ms, auto_pilot=auto_pilot, seed=seed)
    httpd = LimitedThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.dsh = dsh
    return httpd


def run_server(port: int = DEFAULT_PORT, open_browser: bool = True,
               pidfile: Optional[str] = None) -> None:
    """启动游戏服务器并打开浏览器。"""
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = create_server(p)
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
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(pidfile, flags, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "port": port}, f)
        except OSError:
            pass  # 写不了 pidfile 不影响运行
    print("=" * 46, flush=True)
    print("  斗地主游戏服务器已启动", flush=True)
    print("  请在浏览器打开: %s" % url, flush=True)
    print("  停止服务器: python3 scripts/stop_game.py", flush=True)
    print("=" * 46, flush=True)
    if open_browser:
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
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--pidfile", default=None, help="写入 pid/port 的 JSON 文件")
    args = parser.parse_args()
    run_server(port=args.port, open_browser=not args.no_browser, pidfile=args.pidfile)
