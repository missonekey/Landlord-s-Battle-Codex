# -*- coding: utf-8 -*-
"""rules.py 单元测试：牌型识别与大小比较。"""
from __future__ import annotations

import os
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_GAME_DIR = os.path.normpath(os.path.join(_TEST_DIR, os.pardir, "doudizhu", "game"))
if _GAME_DIR not in sys.path:
    sys.path.insert(0, _GAME_DIR)

import rules  # noqa: E402
from cards import (JOKER_BIG_ID, JOKER_SMALL_ID, make_card, rank_of)  # noqa: E402

# 便捷构造: (牌值, 花色) -> id
S = 0  # ♠
H = 1  # ♥
C = 2  # ♣
D = 3  # ♦


def c(rank, suit=0):
    return make_card(rank, suit)


def cards_of(*ranks):
    """按牌值序列构造牌 id（自动补不同花色）。"""
    out = []
    used = {}
    for r in ranks:
        s = used.get(r, 0)
        out.append(make_card(r, s))
        used[r] = s + 1
    return out


class TestClassify(unittest.TestCase):
    def _ok(self, cards, ctype, main_rank=None, length=None):
        combo = rules.classify(cards)
        self.assertIsNotNone(combo, "应识别为合法牌型: %s" % (cards,))
        self.assertEqual(combo.type, ctype)
        if main_rank is not None:
            self.assertEqual(combo.main_rank, main_rank)
        if length is not None:
            self.assertEqual(combo.length, length)
        return combo

    def _bad(self, cards):
        self.assertIsNone(rules.classify(cards), "不应识别为合法牌型: %s" % (cards,))

    def test_single(self):
        self._ok([c(3)], rules.COMBO_SINGLE, 3, 1)
        self._ok([JOKER_SMALL_ID], rules.COMBO_SINGLE, 16, 1)
        self._ok([JOKER_BIG_ID], rules.COMBO_SINGLE, 17, 1)

    def test_pair(self):
        self._ok(cards_of(3, 3), rules.COMBO_PAIR, 3, 2)
        self._ok(cards_of(15, 15), rules.COMBO_PAIR, 15, 2)

    def test_rocket(self):
        self._ok([JOKER_SMALL_ID, JOKER_BIG_ID], rules.COMBO_ROCKET, 17, 2)

    def test_triple(self):
        self._ok(cards_of(8, 8, 8), rules.COMBO_TRIPLE, 8, 3)

    def test_bomb(self):
        self._ok(cards_of(9, 9, 9, 9), rules.COMBO_BOMB, 9, 4)
        self._ok(cards_of(15, 15, 15, 15), rules.COMBO_BOMB, 15, 4)

    def test_triple_single(self):
        self._ok(cards_of(7, 7, 7, 5), rules.COMBO_TRIPLE_SINGLE, 7, 4)
        self._ok(cards_of(7, 7, 7, JOKER_SMALL_ID), rules.COMBO_TRIPLE_SINGLE, 7, 4)
        # 带两张王不行（那不是三带一）
        self._bad(cards_of(7, 7, 7, JOKER_SMALL_ID, JOKER_BIG_ID))

    def test_triple_pair(self):
        self._ok(cards_of(7, 7, 7, 15, 15), rules.COMBO_TRIPLE_PAIR, 7, 5)
        self._bad(cards_of(7, 7, 7, 5, 6))  # 三带二必须是带对子

    def test_straight(self):
        self._ok(cards_of(3, 4, 5, 6, 7), rules.COMBO_STRAIGHT, 7, 5)
        self._ok(cards_of(10, 11, 12, 13, 14), rules.COMBO_STRAIGHT, 14, 5)  # 10JQKA
        self._ok(cards_of(3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
                 rules.COMBO_STRAIGHT, 14, 12)  # 最长顺子
        self._bad(cards_of(3, 4, 5, 6))              # 少于 5 张
        self._bad(cards_of(3, 4, 5, 6, 8))           # 不连续
        self._bad(cards_of(11, 12, 13, 14, 15))      # 含 2
        self._bad([JOKER_SMALL_ID, 3, 4, 5, 6])      # 含王
        self._bad(cards_of(3, 3, 4, 5, 6))           # 有对子

    def test_pair_chain(self):
        self._ok(cards_of(3, 3, 4, 4, 5, 5), rules.COMBO_PAIR_CHAIN, 5, 6)
        self._ok(cards_of(3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10,
                          11, 11, 12, 12, 13, 13, 14, 14),
                 rules.COMBO_PAIR_CHAIN, 14, 24)     # 最长连对 3-A
        self._bad(cards_of(3, 3, 4, 4))              # 只有两对
        self._bad(cards_of(3, 3, 4, 4, 15, 15))      # 含 2
        self._bad(cards_of(3, 3, 4, 4, 6, 6))        # 不连续

    def test_airplane(self):
        self._ok(cards_of(3, 3, 3, 4, 4, 4), rules.COMBO_AIRPLANE, 4, 6)
        self._ok(cards_of(3, 3, 3, 4, 4, 4, 5, 5, 5), rules.COMBO_AIRPLANE, 5, 9)
        self._bad(cards_of(3, 3, 3, 5, 5, 5))        # 不连续
        self._bad(cards_of(14, 14, 14, 15, 15, 15))  # 含 2

    def test_airplane_single(self):
        self._ok(cards_of(3, 3, 3, 4, 4, 4, 5, 6), rules.COMBO_AIRPLANE_SINGLE, 4, 8)
        self._ok(cards_of(3, 3, 3, 4, 4, 4, JOKER_SMALL_ID, 5),
                 rules.COMBO_AIRPLANE_SINGLE, 4, 8)  # 翅膀可带王
        # 翅膀重复（相当于一对）不行
        self._bad(cards_of(3, 3, 3, 4, 4, 4, 5, 5))
        # 翅膀与飞机本身重复不行
        self._bad(cards_of(3, 3, 3, 4, 4, 4, 4, 5))

    def test_airplane_pair(self):
        self._ok(cards_of(3, 3, 3, 4, 4, 4, 5, 5, 6, 6),
                 rules.COMBO_AIRPLANE_PAIR, 4, 10)
        # 三组三张 3,4,5 + 三对 6,7,8 = 15 张
        self._ok(cards_of(3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 7, 7, 8, 8),
                 rules.COMBO_AIRPLANE_PAIR, 5, 15)
        self._bad(cards_of(3, 3, 3, 4, 4, 4, 5, 5, 6, 7))  # 混带

    def test_four_two_single(self):
        self._ok(cards_of(9, 9, 9, 9, 5, 6), rules.COMBO_FOUR_TWO_SINGLE, 9, 6)
        self._ok(cards_of(9, 9, 9, 9, 5, 5), rules.COMBO_FOUR_TWO_SINGLE, 9, 6)   # 可带一对
        self._ok(cards_of(9, 9, 9, 9, JOKER_SMALL_ID, 5), rules.COMBO_FOUR_TWO_SINGLE, 9, 6)
        # 不能带王炸
        self._bad([make_card(9, s) for s in range(4)] + [JOKER_SMALL_ID, JOKER_BIG_ID])
        self._bad(cards_of(9, 9, 9, 9, 5))           # 四带一不存在

    def test_four_two_pair(self):
        self._ok(cards_of(9, 9, 9, 9, 5, 5, 6, 6), rules.COMBO_FOUR_TWO_PAIR, 9, 8)
        self._bad(cards_of(9, 9, 9, 9, 5, 5, 6, 7))  # 必须两对
        self._bad(cards_of(9, 9, 9, 9, 5, 5, 15, 15, 3))  # 张数不对

    def test_empty(self):
        self._bad([])

    def test_two_different(self):
        self._bad(cards_of(3, 4))


class TestBeats(unittest.TestCase):
    def _combo(self, cards):
        combo = rules.classify(cards)
        self.assertIsNotNone(combo)
        return combo

    def test_same_type(self):
        a = self._combo(cards_of(3, 4, 5, 6, 7))
        b = self._combo(cards_of(4, 5, 6, 7, 8))
        self.assertTrue(rules.beats(b, a))
        self.assertFalse(rules.beats(a, b))

    def test_length_must_match(self):
        a = self._combo(cards_of(3, 4, 5, 6, 7))
        b = self._combo(cards_of(4, 5, 6, 7, 8, 9))
        self.assertFalse(rules.beats(b, a))

    def test_pair_vs_single(self):
        a = self._combo(cards_of(3, 3))
        b = self._combo(cards_of(14))
        self.assertFalse(rules.beats(b, a))  # 类型不同不可互压

    def test_bomb_beats_anything(self):
        bomb = self._combo(cards_of(9, 9, 9, 9))
        straight = self._combo(cards_of(10, 11, 12, 13, 14))
        rocket = self._combo([JOKER_SMALL_ID, JOKER_BIG_ID])
        self.assertTrue(rules.beats(bomb, straight))
        self.assertTrue(rules.beats(bomb, self._combo(cards_of(15, 15))))
        self.assertFalse(rules.beats(straight, bomb))
        self.assertTrue(rules.beats(rocket, bomb))

    def test_bomb_compare(self):
        low = self._combo(cards_of(5, 5, 5, 5))
        high = self._combo(cards_of(6, 6, 6, 6))
        self.assertTrue(rules.beats(high, low))
        self.assertFalse(rules.beats(low, high))

    def test_rocket_beats_all(self):
        rocket = self._combo([JOKER_SMALL_ID, JOKER_BIG_ID])
        bomb = self._combo(cards_of(15, 15, 15, 15))
        self.assertTrue(rules.beats(rocket, bomb))
        self.assertFalse(rules.beats(bomb, rocket))

    def test_single_rank_order(self):
        # 3 < ... < 2 < 小王 < 大王
        self.assertTrue(rules.beats(self._combo([c(15)]), self._combo([c(14)])))
        self.assertTrue(rules.beats(self._combo([JOKER_SMALL_ID]), self._combo([c(15)])))
        self.assertTrue(rules.beats(self._combo([JOKER_BIG_ID]), self._combo([JOKER_SMALL_ID])))

    def test_airplane_main_rank(self):
        low = self._combo(cards_of(3, 3, 3, 4, 4, 4, 5, 6))
        high = self._combo(cards_of(4, 4, 4, 5, 5, 5, 6, 7))
        self.assertTrue(rules.beats(high, low))
        # 张数不同不可压
        longer = self._combo(cards_of(3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6))
        self.assertFalse(rules.beats(longer, low))

    def test_four_two_compare(self):
        low = self._combo(cards_of(9, 9, 9, 9, 5, 6))
        high = self._combo(cards_of(10, 10, 10, 10, 5, 6))
        self.assertTrue(rules.beats(high, low))
        pair = self._combo(cards_of(10, 10, 10, 10, 5, 5, 6, 6))
        self.assertFalse(rules.beats(pair, low))  # 类型不同


if __name__ == "__main__":
    unittest.main(verbosity=2)
