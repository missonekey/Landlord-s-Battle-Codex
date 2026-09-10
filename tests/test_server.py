# -*- coding: utf-8 -*-
"""server.py 测试：API 行为、机器人调度与端到端流程。"""
from __future__ import annotations

import json
import http.cookiejar
import os
import sys
import threading
import time
import unittest
import urllib.request

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_GAME_DIR = os.path.normpath(os.path.join(_TEST_DIR, os.pardir, "doudizhu", "game"))
if _GAME_DIR not in sys.path:
    sys.path.insert(0, _GAME_DIR)

from server import create_server  # noqa: E402
from unittest import mock


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.httpd = create_server(port=0, bot_delay_ms=15)
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies))
        # 访问页面建立受 SameSite 保护的本地游戏会话。
        with self.opener.open(self.base + "/", timeout=5):
            pass

    def get_state(self, timeout=5.0):
        url = self.base + "/api/state"
        with self.opener.open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, payload, expect_ok=True):
        req = urllib.request.Request(
            self.base + "/api/action",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(req, timeout=5.0) as r:
                body = json.loads(r.read().decode("utf-8"))
                code = r.status
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8"))
            code = e.code
        if expect_ok:
            self.assertTrue(body.get("ok"), "动作应成功: %s -> %r" % (payload, body))
        else:
            self.assertFalse(body.get("ok"), "动作应失败: %s" % (payload,))
            self.assertTrue(body.get("error"))
        return body, code

    def wait_until(self, cond, timeout=8.0):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.get_state()
            if cond(last):
                return last
            time.sleep(0.05)
        self.fail("等待条件超时, 最后状态: %s" % json.dumps(last, ensure_ascii=False)[:500])

    # ------------------------------------------------------------------

    def test_state_shape(self):
        s = self.get_state()
        for key in ("version", "phase", "hands", "hand_counts", "scores",
                    "bottom", "turn", "human_turn", "last_plays", "settings",
                    "log"):
            self.assertIn(key, s)
        self.assertEqual(s["hand_counts"], [17, 17, 17])
        self.assertEqual(len(s["hands"]["0"]), 17)
        self.assertEqual(len(s["bottom"]), 3)

    def test_static_files(self):
        for path in ("/", "/index.html", "/css/style.css", "/js/render.js", "/js/main.js"):
            with self.opener.open(self.base + path, timeout=5) as r:
                self.assertEqual(r.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(self.base + "/nope.js", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_health_security_headers_and_private_files(self):
        with urllib.request.urlopen(self.base + "/api/health", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            self.assertEqual(data["app"], "codex-doudizhu")
        with self.opener.open(self.base + "/", timeout=5) as r:
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
            self.assertIn("SameSite=Strict", r.headers["Set-Cookie"])
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(self.base + "/server.py", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_state_etag(self):
        with self.opener.open(self.base + "/api/state", timeout=5) as r:
            etag = r.headers["ETag"]
            self.assertTrue(etag)
        req = urllib.request.Request(self.base + "/api/state",
                                     headers={"If-None-Match": etag})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(req, timeout=5)
        self.assertEqual(ctx.exception.code, 304)

    def test_action_requires_session_and_same_origin(self):
        body = json.dumps({"action": "set_delay", "ms": 250}).encode("utf-8")
        no_cookie = urllib.request.Request(
            self.base + "/api/action", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(no_cookie, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

        bad_origin = urllib.request.Request(
            self.base + "/api/action", data=body,
            headers={"Content-Type": "application/json",
                     "Origin": "https://evil.example"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(bad_origin, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_action_rejects_wrong_type_and_large_body(self):
        wrong_type = urllib.request.Request(
            self.base + "/api/action", data=b'{"action":"hint"}',
            headers={"Content-Type": "text/plain"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(wrong_type, timeout=5)
        self.assertEqual(ctx.exception.code, 415)

        large = urllib.request.Request(
            self.base + "/api/action", data=b"x" * (16 * 1024 + 1),
            headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(large, timeout=5)
        self.assertEqual(ctx.exception.code, 413)

    def test_invalid_action(self):
        self.post({"action": "dance"}, expect_ok=False)

    def test_untrusted_host_rejected(self):
        req = urllib.request.Request(self.base + '/api/state', headers={'Host': 'evil.example'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.opener.open(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_disabling_auto_cancels_queued_human_move(self):
        dsh = self.httpd.dsh
        with dsh.lock:
            version = dsh.game.version
            dsh.auto_pilot = False
            dsh._scheduled = (dsh.game.human, version)
        with mock.patch.object(dsh.game, 'bot_move') as move:
            dsh._bot_tick()
        move.assert_not_called()
        self.assertEqual(dsh.game.version, version)

    def test_bot_failure_is_rescheduled(self):
        dsh = self.httpd.dsh
        with dsh.lock:
            dsh._scheduled = (dsh.game.turn, dsh.game.version)
        with mock.patch.object(dsh.game, 'bot_move', side_effect=RuntimeError('retry')), \
                mock.patch.object(dsh, '_schedule') as schedule, \
                mock.patch('traceback.print_exc'):
            dsh._bot_tick()
        schedule.assert_called_once_with()

    def _pass_bidding_if_human(self):
        """叫分阶段若轮到人类则替人类叫 3 分。"""
        s = self.get_state()
        if s["phase"] == "bidding" and s["human_turn"]:
            self.post({"action": "bid", "bid": 3})
            return self.get_state()
        return s

    def test_bid_flow_with_bots(self):
        # 机器人会自动叫分；轮到人类则替人类叫分，等待进入出牌阶段
        s = self._pass_bidding_if_human()
        if s["phase"] == "bidding":
            s = self.wait_until(lambda x: x["phase"] == "playing")
        self.assertIsNotNone(s["landlord"])
        self.assertEqual(len(s["hands"]["0"]), 17 if s["landlord"] != 0 else 20)
        self.assertTrue(s["bottom_visible"])

    def test_human_bid_and_play(self):
        # 若轮到人类叫分则直接叫 3 分，否则等待机器人叫分
        s = self._pass_bidding_if_human()
        if s["phase"] == "bidding":
            s = self.wait_until(lambda x: x["phase"] == "playing")
        s = self.wait_until(lambda x: x["human_turn"])
        # 出两张不同牌值、且不构成王炸的牌 → 必然非法，服务端应拒绝且不崩溃
        hand = s["hands"]["0"]
        first = next(c for c in hand if c["rank"] < 16)   # 避开王牌
        second = next(c for c in hand if c["rank"] != first["rank"])
        bad = [first["id"], second["id"]]
        body, code = self.post({"action": "play", "cards": bad}, expect_ok=False)
        self.assertEqual(code, 422)
        # 提示接口返回出牌建议
        body, _ = self.post({"action": "hint"})
        hint = body["hint"]
        self.assertEqual(hint["kind"], "play")
        if hint["pass"]:
            # 建议过牌 → 过牌合法
            self.post({"action": "pass"})
        else:
            # 建议的出牌必须能通过服务端校验
            cards = hint["cards"]
            self.assertTrue(cards)
            body, _ = self.post({"action": "play", "cards": cards})
            self.assertTrue(body["ok"])

    def test_new_round_anytime(self):
        s = self.get_state()
        v = s["version"]
        self.post({"action": "new_round"})
        s2 = self.get_state()
        self.assertGreater(s2["version"], v)
        self.assertEqual(s2["phase"], "bidding")
        self.assertEqual(s2["hand_counts"], [17, 17, 17])

    def test_settings(self):
        self.post({"action": "set_delay", "ms": 250})
        self.post({"action": "set_auto", "on": True})
        s = self.get_state()
        self.assertEqual(s["settings"]["bot_delay_ms"], 250)
        self.assertTrue(s["settings"]["auto_pilot"])

    def test_full_game_autopilot(self):
        """托管模式跑到一局结束，验证结算数据。"""
        self.post({"action": "set_auto", "on": True})
        self.post({"action": "set_delay", "ms": 5})
        s = self.wait_until(lambda x: x["phase"] == "round_over", timeout=30)
        self.assertIsNotNone(s["winners"])
        self.assertIsNotNone(s["round_scores"])
        self.assertEqual(sum(s["round_scores"]), 0)
        self.assertGreaterEqual(s["multiplier"], 1)
        # 再来一局
        self.post({"action": "new_round"})
        s = self.get_state()
        self.assertEqual(s["phase"], "bidding")


if __name__ == "__main__":
    unittest.main(verbosity=2)
