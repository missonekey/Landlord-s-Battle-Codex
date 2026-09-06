#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""斗地主游戏停止脚本：结束正在运行的斗地主服务器。

用法:
    python3 scripts/stop_game.py
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

_PORT_BASE = 8765
_PORT_RANGE = 20


def _ping(port: int, timeout: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/state" % port, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _port_base() -> int:
    return int(os.environ.get("DOUDIZHU_PORT_BASE", str(_PORT_BASE)))


def _pidfile() -> str:
    return os.environ.get("DOUDIZHU_PIDFILE",
                          os.path.join(tempfile.gettempdir(), "doudizhu_server.json"))


def _kill_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


def _find_via_pidfile() -> int:
    """通过 pidfile 找到并结束服务器。"""
    path = _pidfile()
    if not os.path.isfile(path):
        return -1
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid, port = int(data["pid"]), int(data["port"])
    except (OSError, ValueError, KeyError):
        return -1
    # 确认该进程还活着且端口确实是斗地主服务器（防止 pid 被系统复用误杀）
    try:
        os.kill(pid, 0)
    except OSError:
        return -1
    if not _ping(port):
        return -1
    _kill_pid(pid)
    return port


def _find_via_scan() -> int:
    """兜底：扫描端口并用 lsof 找进程。"""
    for p in range(_port_base(), _port_base() + _PORT_RANGE):
        if not _ping(p):
            continue
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", "tcp:%d" % p], stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            return -1
        for line in out.decode().split():
            _kill_pid(int(line))
        return p
    return -1


def main() -> int:
    port = _find_via_pidfile()
    if port < 0:
        port = _find_via_scan()
    if port < 0:
        print("没有检测到正在运行的斗地主服务器。", flush=True)
        return 0
    # 等待端口真正释放
    deadline = time.time() + 5
    while time.time() < deadline and _ping(port, timeout=0.3):
        time.sleep(0.15)
    if _ping(port, timeout=0.3):
        print("提示：服务器进程已结束但端口尚未释放（数秒内自动恢复）。", flush=True)
    else:
        print("斗地主游戏服务器已停止（端口 %d）。" % port, flush=True)
    path = _pidfile()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
