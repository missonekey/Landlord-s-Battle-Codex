#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""斗地主游戏启动脚本（守护进程模式）。

行为:
  1. 若已有斗地主服务器在运行 → 直接打开浏览器并退出（可重复调用）。
  2. 否则在后台启动一个脱离终端的服务器进程（不会随本命令结束而退出），
     等待其就绪后自动打开浏览器，然后本命令立即返回。

用法:
    python3 start_game.py            # 启动（或复用）并打开浏览器
    python3 start_game.py --no-browser  # 只启动不打开浏览器（测试用）
停止:
    python3 scripts/stop_game.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser

_GAME_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "game")
)
_SERVER_PY = os.path.join(_GAME_DIR, "server.py")
DEFAULT_PORT_BASE = 8765
PORT_RANGE = 20


def _ping(port: int, timeout: float = 0.4) -> bool:
    """探测指定端口是否在运行斗地主服务器。"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/state" % port, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _port_base() -> int:
    return int(os.environ.get("DOUDIZHU_PORT_BASE", str(DEFAULT_PORT_BASE)))


def _pidfile_path() -> str:
    return os.environ.get("DOUDIZHU_PIDFILE",
                          os.path.join(tempfile.gettempdir(), "doudizhu_server.json"))


def _find_running() -> int:
    base = _port_base()
    for p in range(base, base + PORT_RANGE):
        if _ping(p):
            return p
    return -1


def _free_port() -> int:
    base = _port_base()
    for p in range(base, base + PORT_RANGE):
        if _ping(p, timeout=0.25):
            continue
        # 确认端口本身可绑定（避免被其它程序占用但未响应 /api/state）
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # 允许复用 TIME_WAIT 端口（服务器本身也设置了 SO_REUSEADDR）
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            pass
        finally:
            s.close()
    return -1


def main() -> int:
    no_browser = "--no-browser" in sys.argv

    # 1) 已有实例 → 直接复用
    running = _find_running()
    if running >= 0:
        url = "http://127.0.0.1:%d/" % running
        print("斗地主游戏已在运行：%s" % url, flush=True)
        print("（停止服务器：python3 scripts/stop_game.py）", flush=True)
        if not no_browser:
            webbrowser.open(url)
        return 0

    # 2) 启动新的守护进程
    port = _free_port()
    if port < 0:
        print("错误：端口 %d-%d 均不可用，无法启动游戏服务器。"
              % (_port_base(), _port_base() + PORT_RANGE - 1), flush=True)
        return 1

    pidfile = _pidfile_path()
    logfile = os.path.join(tempfile.gettempdir(), "doudizhu_server.log")
    try:
        log = open(logfile, "a", encoding="utf-8")
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", _SERVER_PY,
             "--port", str(port), "--pidfile", pidfile, "--no-browser"],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,  # 脱离终端/进程组，命令退出后继续运行
        )
    except OSError as e:
        print("错误：无法启动游戏服务器进程：%s" % e, flush=True)
        return 1

    # 3) 等待服务器就绪
    deadline = time.time() + 10
    while time.time() < deadline:
        if _ping(port, timeout=0.3):
            url = "http://127.0.0.1:%d/" % port
            print("=" * 46, flush=True)
            print("  斗地主游戏服务器已启动", flush=True)
            print("  请在浏览器打开: %s" % url, flush=True)
            print("  停止服务器: python3 scripts/stop_game.py", flush=True)
            print("=" * 46, flush=True)
            if not no_browser:
                webbrowser.open(url)
            return 0
        if proc.poll() is not None:
            print("错误：游戏服务器启动失败，日志：%s" % logfile, flush=True)
            return 1
        time.sleep(0.15)

    print("错误：游戏服务器启动超时，日志：%s" % logfile, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
