# -*- coding: utf-8 -*-
"""斗地主本地游戏服务器。

- 静态文件服务（游戏页面 / css / js）
- JSON API（状态查询 / 人类动作 / 设置）
- 机器人异步调度（按设置的延迟自动出牌）

只监听 127.0.0.1，完全本地运行。
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import unquote, urlparse

from engine import PHASE_BIDDING, PHASE_PLAYING, Game

GAME_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8765


class GameServer:
    """持有对局实例并负责机器人调度。"""

    def __init__(self, bot_delay_ms: int = 900, show_counter: bool = True,
                 auto_pilot: bool = False, seed: Optional[int] = None):
        self.lock = threading.RLock()
        self.game = Game(seed=seed)
        self.bot_delay_ms = max(0, min(5000, int(bot_delay_ms)))
        self.show_counter = bool(show_counter)
        self.auto_pilot = bool(auto_pilot)
        self._tick_lock = threading.Lock()
        self._scheduled: Optional[int] = None  # (actor, version)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            d = self.game.snapshot()
            d["settings"] = {
                "bot_delay_ms": self.bot_delay_ms,
                "show_counter": self.show_counter,
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
                elif action == "set_counter":
                    self.show_counter = bool(payload.get("show", True))
                elif action == "set_auto":
                    self.auto_pilot = bool(payload.get("on", False))
                else:
                    return {"ok": False, "error": "未知动作：%s" % action,
                            "state": self.snapshot()}
            except (ValueError, TypeError) as e:
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
                        and g.turn == actor and g.version == version:
                    g.bot_move(actor)
        except Exception:
            import traceback
            traceback.print_exc()
        self._schedule()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "Doudizhu/1.0"
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _static(self, path: str) -> None:
        rel = path.lstrip("/")
        if not rel:
            rel = "index.html"
        full = os.path.normpath(os.path.join(GAME_DIR, rel))
        if not full.startswith(GAME_DIR) or not os.path.isfile(full):
            self._json(404, {"error": "资源不存在"})
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/api/state":
            self._json(200, self.server.dsh.snapshot())
            return
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "接口不存在"})
            return
        self._static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path != "/api/action":
            self._json(404, {"error": "接口不存在"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
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


def create_server(port: int = DEFAULT_PORT, bot_delay_ms: int = 900,
                   auto_pilot: bool = False, seed: Optional[int] = None):
    """创建（未启动）服务器；port=0 时自动分配端口。"""
    dsh = GameServer(bot_delay_ms=bot_delay_ms, auto_pilot=auto_pilot, seed=seed)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
            with open(pidfile, "w", encoding="utf-8") as f:
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
