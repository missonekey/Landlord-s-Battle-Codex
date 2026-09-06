# -*- coding: utf-8 -*-
"""engine.py 测试：流程、规则约束、结算计分与大规模模拟。"""
from __future__ import annotations

import os
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_GAME_DIR = os.path.normpath(os.path.join(_TEST_DIR, os.pardir, "doudizhu", "game"))
if _GAME_DIR not in sys.path:
    sys.path.insert(0, _GAME_DIR)

import ai  # noqa: E402
import rules  # noqa: E402
from cards import JOKER_BIG_ID, JOKER_SMALL_ID, make_card, rank_of  # noqa: E402
from engine import Game, PHASE_BIDDING, PHASE_OVER, PHASE_PLAYING  # noqa: E402


def mk(ranks_suits):
    """[(rank, suit)...] -> [id...]"""
    return [make_card(r, s) for r, s in ranks_suits]


def play_hand(g, player, ranks_suits):
    g.play(player, mk(ranks_suits))


class TestDeal(unittest.TestCase):
    def test_deal_counts(self):
        g = Game(seed=1)
        self.assertEqual(g.phase, PHASE_BIDDING)
        self.assertEqual([len(h) for h in g.hands], [17, 17, 17])
        self.assertEqual(len(g.bottom), 3)
        all_cards = g.hands[0] + g.hands[1] + g.hands[2] + g.bottom
        self.assertEqual(len(set(all_cards)), 54)

    def test_deterministic(self):
        g1 = Game(seed=123)
        g2 = Game(seed=123)
        self.assertEqual(g1.hands, g2.hands)
        self.assertEqual(g1.bottom, g2.bottom)


class TestBidding(unittest.TestCase):
    def test_bid_event(self):
        g = Game(seed=1)
        starter = g.starter
        g.bid(g.turn, 1)                       # 第一家叫 1 分
        self.assertEqual(g.bid_event, {"kind": "bid", "bid": 1, "player": starter})
        p = g.turn
        g.bid(p, 0)                            # 第二家不叫
        self.assertEqual(g.bid_event, {"kind": "pass", "player": p})
        p2 = g.turn
        g.bid(p2, 3)                           # 第三家叫 3 分
        self.assertEqual(g.bid_event, {"kind": "bid", "bid": 3, "player": p2})
        g.bid(g.turn, 0)
        g.bid(g.turn, 0)                       # 两家不叫 → 地主确定
        self.assertEqual(g.bid_event["kind"], "landlord")
        self.assertEqual(g.bid_event["player"], p2)
        self.assertEqual(g.bid_event["bid"], 3)

    def test_all_pass_redeals(self):
        g = Game(seed=2)
        deal0 = g.deal_no
        hands0 = [list(h) for h in g.hands]
        for _ in range(3):
            g.bid(g.turn, 0)
        self.assertEqual(g.deal_no, deal0 + 1)
        self.assertEqual(g.phase, PHASE_BIDDING)
        self.assertNotEqual(g.hands, hands0)  # 重新发牌（极小概率相同，seed 固定）

    def test_three_point_wins(self):
        g = Game(seed=3)
        # 找到三家都会叫的牌局：直接强制走流程
        g.bid(g.turn, 1)
        g.bid(g.turn, 2)
        g.bid(g.turn, 3)
        g.bid(g.turn, 0)  # 第一家不叫
        g.bid(g.turn, 0)  # 第二家不叫
        self.assertEqual(g.phase, PHASE_PLAYING)
        self.assertIsNotNone(g.landlord)
        self.assertEqual(g.bid_points, 3)
        self.assertEqual(len(g.hands[g.landlord]), 20)

    def test_one_point_wins_after_two_pass(self):
        g = Game(seed=4)
        g.bid(g.turn, 1)
        g.bid(g.turn, 0)
        g.bid(g.turn, 0)
        self.assertEqual(g.phase, PHASE_PLAYING)
        self.assertEqual(g.bid_points, 1)

    def test_landlord_takes_bottom(self):
        g = Game(seed=5)
        for _ in range(3):
            g.bid(g.turn, 0)
        # 重新发牌后叫 1 分
        g.bid(g.turn, 1)
        g.bid(g.turn, 0)
        g.bid(g.turn, 0)
        landlord = g.landlord
        for c in g.bottom:
            self.assertIn(c, g.hands[landlord])
        self.assertTrue(g.snapshot()["bottom_visible"])

    def test_invalid_bids(self):
        g = Game(seed=6)
        with self.assertRaises(ValueError):
            g.bid(g.turn, 5)
        g.bid(g.turn, 1)
        with self.assertRaises(ValueError):
            g.bid(g.turn, 1)  # 必须更高
        g.bid(g.turn, 0)      # 不叫是合法的
        g.bid(g.turn, 2)
        # 不是自己回合不能叫
        with self.assertRaises(ValueError):
            g.bid((g.turn + 1) % 3, 0)


class TestPlayRules(unittest.TestCase):
    def _playing_game(self):
        g = Game(seed=8)
        while g.phase == PHASE_BIDDING:
            g.bot_move(g.turn)
        return g

    def test_cannot_play_out_of_turn(self):
        g = self._playing_game()
        p = (g.turn + 1) % 3
        with self.assertRaises(ValueError):
            g.play(p, [g.hands[p][0]])

    def test_cannot_pass_when_leading(self):
        g = self._playing_game()
        with self.assertRaises(ValueError):
            g.pass_turn(g.turn)

    def test_pass_cycle_resets_trick(self):
        g = Game(seed=9)
        while g.phase == PHASE_BIDDING:
            g.bot_move(g.turn)
        # 地主先手出一张
        g.bot_move(g.turn)
        self.assertIsNotNone(g.last_combo)
        # 两家都不出 → 回合重置
        g.pass_turn(g.turn)
        g.pass_turn(g.turn)
        self.assertIsNone(g.last_combo)
        self.assertIsNone(g.last_player)
        self.assertEqual(g.last_plays, [None, None, None])

    def test_illegal_play_rejected(self):
        g = Game(seed=10)
        while g.phase == PHASE_BIDDING:
            g.bot_move(g.turn)
        p = g.turn
        hand = g.hands[p]
        # 先正常出一张
        g.play(p, [hand[0]])
        # 手牌外的牌
        outside = [c for c in range(54) if c not in g.hands[p] and c not in g.hands[(p + 1) % 3] and c not in g.hands[(p + 2) % 3] and c not in g.bottom][0]
        with self.assertRaises(ValueError):
            g.play(g.turn, [outside])

    def test_must_beat_or_pass(self):
        g = Game(seed=11)
        while g.phase == PHASE_BIDDING:
            g.bot_move(g.turn)
        p = g.turn
        # 出一张牌
        r0 = g.hands[p][0]
        g.play(p, [r0])
        nxt = g.turn
        # 下一家若出更小的单张则必须报错（压不住）
        smaller = [c for c in g.hands[nxt] if rank_of(c) < rank_of(r0)]
        if smaller:
            with self.assertRaises(ValueError):
                g.play(nxt, [smaller[0]])


class TestScoring(unittest.TestCase):
    def _setup(self, landlord, hand_specs, bottom=None, bid=1):
        """构造一个已进入出牌阶段的对局，指定三家手牌。"""
        g = Game(seed=0)
        # 直接设置状态
        g.phase = PHASE_PLAYING
        g.landlord = landlord
        g.bid_points = bid
        g.turn = landlord
        g.last_combo = None
        g.last_player = None
        g.trick_passes = 0
        g.last_plays = [None, None, None]
        g.plays_count = [0, 0, 0]
        g.bombs_used = 0
        g.rockets_used = 0
        g.played_ranks.clear()
        g.hands = [list(h) for h in hand_specs]
        g.bottom = list(bottom) if bottom else []
        g.winners = None
        g.round_result = None
        return g

    def test_spring_double(self):
        # 地主一手顺子直接走完（春天）
        g = self._setup(0, [
            mk([(3, 0), (4, 0), (5, 0), (6, 0), (7, 0)]),
            mk([(8, 0), (9, 0)]),
            mk([(10, 0), (11, 0)]),
        ], bid=2)
        g.play(0, mk([(3, 0), (4, 0), (5, 0), (6, 0), (7, 0)]))
        self.assertEqual(g.phase, PHASE_OVER)
        self.assertTrue(g.spring)
        self.assertFalse(g.anti_spring)
        # 春天 x2，炸弹 0 → mult=2, stake=2*2=4
        self.assertEqual(g.multiplier, 2)
        self.assertEqual(g.round_scores[0], 8)
        self.assertEqual(g.round_scores[1], -4)
        self.assertEqual(g.round_scores[2], -4)
        self.assertEqual(g.scores[0], 8)
        self.assertEqual(sum(g.round_scores), 0)

    def test_anti_spring(self):
        # 地主只出过一手（首出），随后农民一家走完（反春）
        g = self._setup(0, [
            mk([(3, 0), (4, 1)]),
            mk([(4, 0), (5, 0), (6, 0), (7, 0), (8, 0), (9, 0), (10, 0)]),
            mk([(11, 0), (12, 0)]),
        ], bid=1)
        g.play(0, mk([(3, 0)]))          # 地主首出
        g.play(1, mk([(4, 0)]))          # 下家压上
        g.pass_turn(2)
        g.pass_turn(0)
        for r in (5, 6, 7, 8, 9):
            g.play(1, mk([(r, 0)]))
            g.pass_turn(2)
            g.pass_turn(0)
        g.play(1, mk([(10, 0)]))         # 下家出完
        self.assertEqual(g.phase, PHASE_OVER)
        self.assertTrue(g.anti_spring)
        self.assertFalse(g.spring)
        # 反春 x2 → mult=2, stake=1*2=2
        self.assertEqual(g.multiplier, 2)
        self.assertEqual(g.round_scores[0], -4)
        self.assertEqual(g.round_scores[1], 2)
        self.assertEqual(g.round_scores[2], 2)

    def test_bomb_doubles(self):
        # 地主一手炸弹走完（炸弹 x2，无春天因为农民出过? 农民没出 → 春天 x2 → mult=4）
        g = self._setup(0, [
            mk([(3, 0), (3, 1), (3, 2), (3, 3)]),
            mk([(4, 0), (5, 0)]),
            mk([(6, 0), (7, 0)]),
        ], bid=1)
        g.play(0, mk([(3, 0), (3, 1), (3, 2), (3, 3)]))
        self.assertEqual(g.phase, PHASE_OVER)
        self.assertEqual(g.bombs_used, 1)
        self.assertEqual(g.multiplier, 4)  # 炸弹x2 * 春天x2
        self.assertEqual(g.round_scores[0], 8)

    def test_farmers_win_normal(self):
        # 农民一家直接走完、地主只出一手 → 反春 x2
        g = self._setup(0, [mk([(3, 0), (9, 0)]), mk([(4, 0)]), mk([(5, 0)])], bid=1)
        g.play(0, mk([(3, 0)]))
        g.play(1, mk([(4, 0)]))  # 下家出完即胜
        self.assertEqual(g.phase, PHASE_OVER)
        self.assertEqual(g.winners, [1])
        self.assertTrue(g.anti_spring)
        self.assertEqual(g.multiplier, 2)
        self.assertEqual(g.round_scores, [-4, 2, 2])


class TestSimulation(unittest.TestCase):
    """数百局 AI vs AI 全自动模拟：每一步都校验合法性，最终校验结算守恒。"""

    def _run_game(self, seed):
        g = Game(seed=seed)
        plays = []

        orig_play = g.play
        orig_pass = g.pass_turn
        orig_bid = g.bid

        def spy_play(player, cards):
            cards = list(cards)
            self.assertTrue(cards)
            self.assertEqual(g.turn, player)
            combo = rules.classify(cards)
            self.assertIsNotNone(combo, "机器人出牌非法: %r" % (cards,))
            if g.last_combo is not None:
                self.assertTrue(rules.beats(combo, g.last_combo),
                                "机器人未压过上家: %r vs %r" % (combo, g.last_combo))
            self.assertTrue(all(c in g.hands[player] for c in cards))
            self.assertEqual(len(set(cards)), len(cards))
            orig_play(player, cards)

        def spy_pass(player):
            self.assertIsNotNone(g.last_combo)
            self.assertNotEqual(g.last_player, player)
            orig_pass(player)

        def spy_bid(player, value):
            self.assertIn(value, (0, 1, 2, 3))
            if value:
                self.assertGreater(value, g.bid_highest)
            orig_bid(player, value)

        g.play = spy_play
        g.pass_turn = spy_pass
        g.bid = spy_bid

        steps = 0
        max_steps = 30000
        while g.phase != PHASE_OVER and steps < max_steps:
            g.bot_move(g.turn)
            steps += 1
            # 不变量：54 张牌 = 手牌 + 未并入地主手牌的底牌 + 已打出的牌
            hidden_bottom = 3 if g.landlord is None else 0
            accounted = (sum(len(h) for h in g.hands) + hidden_bottom
                         + sum(g.played_ranks.values()))
            self.assertEqual(accounted, 54, "牌数不守恒 (seed=%s, phase=%s)"
                             % (seed, g.phase))
            if g.phase == PHASE_PLAYING:
                self.assertLessEqual(g.deal_no, 50, "重新发牌次数异常")

        self.assertLess(steps, max_steps, "对局未在步数上限内结束 seed=%s" % seed)
        self.assertEqual(g.phase, PHASE_OVER)
        winner = g.winners[0]
        self.assertEqual(len(g.hands[winner]), 0, "胜者手牌应为空")
        self.assertEqual(sum(g.round_scores), 0, "本局得分应守恒")
        self.assertGreaterEqual(g.multiplier, 1)
        # 地主必存在
        self.assertIsNotNone(g.landlord)
        return g

    def test_sim_many_games(self):
        for seed in range(120):
            g = self._run_game(seed)
            # 每 40 局换一个新 Game（累计分继续累加无妨）
        # 再跑几局长会话（同一实例连续多局）
        g = Game(seed=999)
        for _ in range(10):
            while g.phase != PHASE_OVER:
                g.bot_move(g.turn)
            g._new_round()
        self.assertEqual(g.round_no, 11)


if __name__ == "__main__":
    unittest.main(verbosity=2)
