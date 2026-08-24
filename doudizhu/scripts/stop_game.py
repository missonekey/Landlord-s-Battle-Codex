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
import sys
import tempfile
import time
import urllib.request

_PORT_BASE = 8765
_PORT_RANGE = 20


def _health(port: int, timeout: float = 0.4):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/health" % port, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            if r.status == 200 and data.get("service") == "doudizhu" \
                    and data.get("instance_id") and data.get("pid"):
                return data
    except Exception:
        pass
    return None


def _port_base() -> int:
    return int(os.environ.get("DOUDIZHU_PORT_BASE", str(_PORT_BASE)))


def _pidfile() -> str:
    uid = os.getuid() if hasattr(os, "getuid") else "user"
    return os.environ.get("DOUDIZHU_PIDFILE",
                          os.path.join(tempfile.gettempdir(),
                                       "doudizhu_server_%s.json" % uid))


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
        instance_id = str(data["instance_id"])
    except (OSError, ValueError, KeyError):
        return -1
    # 确认该进程还活着且端口确实是斗地主服务器（防止 pid 被系统复用误杀）
    try:
        os.kill(pid, 0)
    except OSError:
        return -1
    health = _health(port)
    if not health or int(health.get("pid", -1)) != pid \
            or health.get("instance_id") != instance_id:
        return -1
    _kill_pid(pid)
    return port


def main() -> int:
    port = _find_via_pidfile()
    if port < 0:
        print("没有检测到正在运行的斗地主服务器。", flush=True)
        return 0
    # 等待端口真正释放
    deadline = time.time() + 5
    while time.time() < deadline and _health(port, timeout=0.3):
        time.sleep(0.15)
    if _health(port, timeout=0.3):
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
