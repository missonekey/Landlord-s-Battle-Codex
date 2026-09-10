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
    for endpoint in ("api/health", "api/state"):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/%s" % (port, endpoint), timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
                if r.status != 200 or not isinstance(data, dict):
                    continue
                if endpoint == "api/health" and data.get("app") == "codex-doudizhu":
                    return True
                if endpoint == "api/state" and {"phase", "round_no", "hands", "hand_counts"} <= set(data):
                    return True
        except Exception:
            continue
    return False


def _port_base() -> int:
    return int(os.environ.get("DOUDIZHU_PORT_BASE", str(_PORT_BASE)))


def _pidfile() -> str:
    return os.environ.get("DOUDIZHU_PIDFILE",
                          os.path.join(tempfile.gettempdir(), "doudizhu_server.json"))


def _kill_pid(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


def _pid_owns_port(pid: int, port: int) -> bool:
    """确认 pid 本身正在监听该斗地主端口，避免陈旧 pidfile 误杀。"""
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", "-a", "-p", str(pid),
             "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL,
        )
        return str(pid) in out.decode().split()
    except (OSError, subprocess.CalledProcessError):
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
    # 调用方显式限定端口范围时，不允许共享/陈旧 pidfile 扩大停止范围。
    if "DOUDIZHU_PORT_BASE" in os.environ:
        base = _port_base()
        if not base <= port < base + _PORT_RANGE:
            return -1
    # 确认该进程还活着且端口确实是斗地主服务器（防止 pid 被系统复用误杀）
    try:
        os.kill(pid, 0)
    except OSError:
        return -1
    if not _ping(port) or not _pid_owns_port(pid, port):
        return -1
    return port if _kill_pid(pid) else -1


def _find_via_scan() -> int:
    """兜底：扫描端口并用 lsof 找进程。"""
    for p in range(_port_base(), _port_base() + _PORT_RANGE):
        if not _ping(p):
            continue
        try:
            out = subprocess.check_output(
                ["lsof", "-nP", "-tiTCP@127.0.0.1:%d" % p, "-sTCP:LISTEN"],
                stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            return -1
        for line in out.decode().split():
            if line.isdigit() and _pid_owns_port(int(line), p) and _kill_pid(int(line)):
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
        print("停止未完成：服务器仍在响应，请稍后重试。", flush=True)
        return 1
    else:
        print("斗地主游戏服务器已停止（端口 %d）。" % port, flush=True)
    path = _pidfile()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 只清理本次确实停止的实例记录，避免删掉另一端口的共享记录。
            if int(data.get("port", -1)) == port:
                os.remove(path)
        except (OSError, ValueError, AttributeError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
