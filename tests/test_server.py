# -*- coding: utf-8 -*-
"""server.py 测试：API 行为、机器人调度与端到端流程。"""
from __future__ import annotations

import json
import os
import sys
import threading
import tempfile
import time
import unittest
import urllib.request

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_GAME_DIR = os.path.normpath(os.path.join(_TEST_DIR, os.pardir, "doudizhu", "game"))
if _GAME_DIR not in sys.path:
    sys.path.insert(0, _GAME_DIR)

from server import GameServer, create_server  # noqa: E402


class GameServerStateTest(unittest.TestCase):
    def test_state_survives_server_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "state.json")
            first = GameServer(seed=31, state_path=path)
            first.act({"action": "start"})
            first.act({"action": "bid", "bid": 3})
            before = first.snapshot()

            restored = GameServer(state_path=path)
            after = restored.snapshot()
            for key in ("phase", "round_no", "landlord", "bid", "hands",
                        "hand_counts", "bottom", "scores", "version"):
                self.assertEqual(after[key], before[key], key)
            self.assertFalse(after["settings"]["started"],
                             "重启后应等待玩家重新点击开始，不能后台自动走牌")

    def test_disabling_auto_cancels_pending_human_move(self):
        dsh = GameServer(seed=32)
        dsh.act({"action": "start"})
        dsh.bot_delay_ms = 40
        dsh.act({"action": "set_auto", "on": True})
        dsh.act({"action": "set_auto", "on": False})
        version = dsh.game.version
        time.sleep(0.1)
        self.assertEqual(dsh.game.version, version)

    def test_state_save_does_not_follow_temporary_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "state.json")
            victim = os.path.join(td, "keep.txt")
            with open(victim, "w", encoding="utf-8") as f:
                f.write("KEEP")
            tmp = "%s.tmp.%d" % (path, os.getpid())
            os.symlink(victim, tmp)
            dsh = GameServer(seed=33, state_path=path)
            dsh.act({"action": "start"})
            with open(victim, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "KEEP")
            self.assertFalse(os.path.exists(tmp))


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.httpd = create_server(port=0, bot_delay_ms=15)
        # 生产环境最低 500ms；测试直接缩短内部计时，避免拖慢套件。
        self.httpd.dsh.bot_delay_ms = 15
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.httpd.server_close)
        self.token = None

    def get_state(self, timeout=5.0):
        url = self.base + "/api/state"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            self.token = r.headers.get("X-Doudizhu-Token") or self.token
            return json.loads(r.read().decode("utf-8"))

    def post(self, payload, expect_ok=True):
        if not self.token:
            self.get_state()
        req = urllib.request.Request(
            self.base + "/api/action",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-Doudizhu-Token": self.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as r:
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
        self.assertEqual(s["bottom"], [])
        self.assertEqual(s["bottom_count"], 3)
        self.assertFalse(s["settings"]["started"])

    def test_health_and_security_headers(self):
        with urllib.request.urlopen(self.base + "/api/health", timeout=5) as r:
            body = json.loads(r.read().decode("utf-8"))
            self.assertEqual(body["service"], "doudizhu")
            self.assertEqual(body["version"], "1.2.0")
            self.assertTrue(r.headers.get("Content-Security-Policy"))
            self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")

    def test_action_requires_json_token_and_same_origin(self):
        self.get_state()
        cases = [
            ({"Content-Type": "text/plain", "X-Doudizhu-Token": self.token}, 415),
            ({"Content-Type": "application/json"}, 403),
            ({"Content-Type": "application/json", "X-Doudizhu-Token": self.token,
              "Origin": "https://attacker.example"}, 403),
        ]
        for headers, expected in cases:
            req = urllib.request.Request(
                self.base + "/api/action", data=b'{"action":"hint"}',
                headers=headers, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, expected)

    def test_static_cache_revalidation(self):
        with urllib.request.urlopen(self.base + "/js/main.js", timeout=5) as r:
            etag = r.headers.get("ETag")
            self.assertTrue(etag)
            self.assertIn("max-age=3600", r.headers.get("Cache-Control", ""))
        req = urllib.request.Request(self.base + "/js/main.js",
                                     headers={"If-None-Match": etag})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 304)

    def test_static_files(self):
        for path in ("/", "/index.html", "/css/style.css", "/js/render.js", "/js/main.js"):
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                self.assertEqual(r.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/nope.js", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_invalid_action(self):
        self.post({"action": "dance"}, expect_ok=False)

    def test_stale_tab_action_is_rejected(self):
        s = self.get_state()
        self.post({"action": "start", "expected_version": s["version"]})
        body, code = self.post(
            {"action": "new_round", "expected_version": s["version"]},
            expect_ok=False,
        )
        self.assertEqual(code, 409)
        self.assertTrue(body.get("conflict"))

    def _pass_bidding_if_human(self):
        """叫分阶段若轮到人类则替人类叫 3 分。"""
        self.post({"action": "start"})
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
        self.assertEqual(s["settings"]["bot_delay_ms"], 500)
        self.assertTrue(s["settings"]["auto_pilot"])

    def test_full_game_autopilot(self):
        """托管模式跑到一局结束，验证结算数据。"""
        self.post({"action": "set_auto", "on": True})
        self.post({"action": "set_delay", "ms": 5})
        self.httpd.dsh.bot_delay_ms = 5
        self.post({"action": "start"})
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
