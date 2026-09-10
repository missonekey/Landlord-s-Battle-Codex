# -*- coding: utf-8 -*-
"""启动/停止脚本测试：守护进程模式端到端验证。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import importlib.util
import urllib.request

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_TEST_DIR, os.pardir))
_START = os.path.join(_REPO, "doudizhu", "scripts", "start_game.py")
_STOP = os.path.join(_REPO, "doudizhu", "scripts", "stop_game.py")
PORT_BASE = 9100

_stop_spec = importlib.util.spec_from_file_location('ddz_stop_test', _STOP)
stop_module = importlib.util.module_from_spec(_stop_spec)
_stop_spec.loader.exec_module(stop_module)


def _env():
    env = dict(os.environ)
    env["DOUDIZHU_PORT_BASE"] = str(PORT_BASE)
    env["DOUDIZHU_PIDFILE"] = os.path.join(tempfile.gettempdir(),
                                           "doudizhu_test_server.json")
    return env


def _ping(port, timeout=0.5):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/health" % port, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return r.status == 200 and data.get("app") == "codex-doudizhu"
    except Exception:
        return False


class TestLauncher(unittest.TestCase):
    def setUp(self):
        # 确保测试端口干净
        subprocess.run([sys.executable, _STOP], env=_env(),
                       capture_output=True, timeout=30)
        time.sleep(0.3)

    def tearDown(self):
        subprocess.run([sys.executable, _STOP], env=_env(),
                       capture_output=True, timeout=30)
        time.sleep(0.3)

    def test_start_reuse_stop(self):
        # 1) 首次启动：命令应立即返回（守护进程模式），服务器可用
        t0 = time.time()
        r = subprocess.run([sys.executable, _START, "--no-browser"], env=_env(),
                           capture_output=True, timeout=30)
        elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        out = r.stdout.decode()
        self.assertIn("斗地主游戏服务器已启动", out)
        # 端口可能自动回退（起始端口被占时），以实际输出为准
        m = re.search(r"http://127\.0\.0\.1:(\d+)/", out)
        self.assertIsNotNone(m, out)
        port = int(m.group(1))
        self.assertTrue(PORT_BASE <= port < PORT_BASE + 20, "端口应在回退范围内: %d" % port)
        self.assertLess(elapsed, 15, "启动命令应快速返回")
        self.assertTrue(_ping(port), "服务器应已就绪 (port %d)" % port)

        # 2) 再次启动：复用已运行实例
        r2 = subprocess.run([sys.executable, _START, "--no-browser"], env=_env(),
                            capture_output=True, timeout=30)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("已在运行", r2.stdout.decode())

        # 3) 服务器仍正常工作
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/state" % port, timeout=5) as resp:
            s = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(s["hand_counts"], [17, 17, 17])

        # 4) 停止：端口释放、pidfile 清理
        r3 = subprocess.run([sys.executable, _STOP], env=_env(),
                            capture_output=True, timeout=30)
        self.assertEqual(r3.returncode, 0)
        deadline = time.time() + 8
        while time.time() < deadline and _ping(port):
            time.sleep(0.2)
        self.assertFalse(_ping(port), "服务器应已停止")
        self.assertFalse(os.path.exists(_env()["DOUDIZHU_PIDFILE"]),
                         "pidfile 应被清理")

        # 5) 再次停止：应提示没有运行中的服务器
        r4 = subprocess.run([sys.executable, _STOP], env=_env(),
                            capture_output=True, timeout=30)
        self.assertEqual(r4.returncode, 0)
        self.assertIn("没有检测到", r4.stdout.decode())


class TestStopSafety(unittest.TestCase):
    def test_explicit_port_scope_ignores_other_pidfile(self):
        with mock.patch.dict(stop_module.os.environ,
                             {"DOUDIZHU_PORT_BASE": "9325"}), \
                mock.patch.object(stop_module.os.path, 'isfile', return_value=True), \
                mock.patch('builtins.open', mock.mock_open(
                    read_data='{"pid":12345,"port":8765}')), \
                mock.patch.object(stop_module.os, 'kill') as kill, \
                mock.patch.object(stop_module, '_ping') as ping:
            self.assertEqual(stop_module._find_via_pidfile(), -1)
            kill.assert_not_called()
            ping.assert_not_called()

    def test_stale_pidfile_does_not_signal_unrelated_process(self):
        with mock.patch.object(stop_module.os.path, 'isfile', return_value=True), \
                mock.patch('builtins.open', mock.mock_open(read_data='{"pid":12345,"port":8765}')), \
                mock.patch.object(stop_module.os, 'kill') as kill, \
                mock.patch.object(stop_module, '_ping', return_value=True), \
                mock.patch.object(stop_module, '_pid_owns_port', return_value=False):
            self.assertEqual(stop_module._find_via_pidfile(), -1)
            kill.assert_called_once_with(12345, 0)

    def test_health_must_identify_game(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'{"app":"unrelated-service"}'
        with mock.patch.object(stop_module.urllib.request, 'urlopen', return_value=response):
            self.assertFalse(stop_module._ping(8765))

    def test_old_game_state_is_still_recognized(self):
        health = mock.MagicMock()
        health.__enter__.side_effect = urllib.error.HTTPError('', 404, '', {}, None)
        state = mock.MagicMock()
        state.__enter__.return_value.status = 200
        state.__enter__.return_value.read.return_value = (
            b'{"phase":"playing","round_no":1,"hands":{"0":[]},"hand_counts":[0,1,1]}')
        with mock.patch.object(stop_module.urllib.request, 'urlopen', side_effect=[health, state]):
            self.assertTrue(stop_module._ping(8765))

    def test_never_signals_process_group(self):
        with mock.patch.object(stop_module.os, 'kill') as kill:
            for pid in [-1, 0, 1]:
                self.assertFalse(stop_module._kill_pid(pid))
            kill.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
