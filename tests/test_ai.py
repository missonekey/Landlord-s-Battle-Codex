# -*- coding: utf-8 -*-
"""ai.py 测试：叫分合理性 + 出牌合法性（大量随机手牌验证）。"""
from __future__ import annotations

import os
import random
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_GAME_DIR = os.path.normpath(os.path.join(_TEST_DIR, os.pardir, "doudizhu", "game"))
if _GAME_DIR not in sys.path:
    sys.path.insert(0, _GAME_DIR)

import ai  # noqa: E402
import rules  # noqa: E402
from cards import new_deck  # noqa: E402


def random_hand(rng, size=17):
    deck = new_deck()
    rng.shuffle(deck)
    return deck[:size]


def random_combo(rng):
    """随机生成一个合法牌型（用于当靶子）。"""
    deck = new_deck()
    rng.shuffle(deck)
    n = rng.choice([1, 1, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 6, 8])
    return rules.classify(deck[:n])


class TestBid(unittest.TestCase):
    def test_bid_levels(self):
        rng = random.Random(42)
        for _ in range(500):
            hand = random_hand(rng)
            for cur in (0, 1, 2, 3):
                v = ai.decide_bid(hand, cur)
                self.assertIn(v, (0, 1, 2, 3))
                if v != 0:
                    self.assertGreater(v, cur)

    def test_strong_hand_bids_high(self):
        # 双王 + 2 个2 + A + K → 必叫
        hand = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 52, 53]
        self.assertGreater(ai.decide_bid(hand, 0), 0)

    def test_weak_hand_passes(self):
        # 一堆小牌无大牌
        hand = list(range(0, 13)) + [26, 27, 28, 29]  # 3..9 双份左右的小牌
        self.assertEqual(ai.decide_bid(hand, 1), 0)


class TestSuggestLead(unittest.TestCase):
    def test_always_legal(self):
        rng = random.Random(7)
        for _ in range(800):
            hand = random_hand(rng, rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 17]))
            cards = ai.suggest_lead(hand)
            self.assertTrue(cards)
            self.assertTrue(all(c in hand for c in cards))
            self.assertIsNotNone(rules.classify(cards),
                                 "主动出牌必须合法: %r -> %r" % (hand, cards))
            self.assertEqual(len(set(cards)), len(cards))

    def test_whole_hand_win(self):
        # 一手顺子 3,4,5,6,7 → 直接全出
        straight = [0, 1, 2, 3, 4]  # 3♠ 4♠ 5♠ 6♠ 7♠
        cards = ai.suggest_lead(straight)
        self.assertEqual(sorted(cards), sorted(straight))
        # 三带二 → 全出
        tdp = [0, 13, 26, 1, 14]  # 3,3,3,4,4
        cards = ai.suggest_lead(tdp)
        self.assertEqual(sorted(cards), sorted(tdp))
        # 王炸 → 全出
        cards = ai.suggest_lead([52, 53])
        self.assertEqual(sorted(cards), [52, 53])

    def test_preserves_and_leads_structures(self):
        straight_hand = [0, 1, 2, 3, 4, 12]  # 3-7 顺子 + 2
        self.assertEqual(rules.classify(ai.suggest_lead(straight_hand)).type,
                         rules.COMBO_STRAIGHT)

        chain_hand = [0, 13, 1, 14, 2, 15, 6]  # 33 44 55 + 9
        self.assertEqual(rules.classify(ai.suggest_lead(chain_hand)).type,
                         rules.COMBO_PAIR_CHAIN)

        plane_hand = [0, 13, 26, 1, 14, 27, 6, 7, 12]  # 333444 + 9/10/2
        self.assertIn(rules.classify(ai.suggest_lead(plane_hand)).type,
                      (rules.COMBO_AIRPLANE, rules.COMBO_AIRPLANE_SINGLE))


class TestSuggestFollow(unittest.TestCase):
    def test_follow_legality(self):
        rng = random.Random(99)
        checked = 0
        for _ in range(8000):
            hand = random_hand(rng)
            target = random_combo(rng)
            if target is None:
                continue
            if any(c in hand for c in target.cards):
                continue  # 靶子的牌不能和手牌冲突
            ctx = {"role": "farmer", "teammate": 1, "target_owner": 2,
                   "landlord_left": 10, "opp_min": 10}
            cards = ai.suggest_follow(hand, target, ctx)
            if cards is not None:
                self.assertTrue(all(c in hand for c in cards))
                combo = rules.classify(cards)
                self.assertIsNotNone(combo, "跟牌必须合法: %r vs %r -> %r"
                                     % (hand, target, cards))
                self.assertTrue(rules.beats(combo, target),
                                "跟牌必须压过: %r vs %r -> %r" % (target, cards, combo))
                checked += 1
        # 确保真的验证过不少有效跟牌
        self.assertGreater(checked, 300)

    def test_never_beats_teammate(self):
        rng = random.Random(5)
        for _ in range(500):
            hand = random_hand(rng)
            target = random_combo(rng)
            if target is None or any(c in hand for c in target.cards):
                continue
            ctx = {"role": "farmer", "teammate": 2, "target_owner": 2,
                   "landlord_left": 10, "opp_min": 10}
            self.assertIsNone(ai.suggest_follow(hand, target, ctx))

    def test_defends_when_landlord_has_one_card(self):
        target = rules.classify([0])  # 队友出了 3
        hand = [1, 2, 3]              # 4/5/6 均可压
        ctx = {"role": "farmer", "teammate": 2, "target_owner": 2,
               "landlord_left": 1, "opp_min": 1}
        cards = ai.suggest_follow(hand, target, ctx)
        self.assertIsNotNone(cards)
        self.assertTrue(rules.beats(rules.classify(cards), target))

    def test_no_target_means_lead(self):
        hand = random_hand(random.Random(3))
        cards = ai.suggest(hand, None, {})
        self.assertTrue(cards)
        self.assertIsNotNone(rules.classify(cards))


if __name__ == "__main__":
    unittest.main(verbosity=2)
