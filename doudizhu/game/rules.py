# -*- coding: utf-8 -*-
"""斗地主牌型规则：组合识别与大小比较（完整标准规则）。

牌型:
    single          单张
    pair            对子
    triple          三张
    triple_single   三带一
    triple_pair     三带二
    straight        顺子（>=5 张连续单牌，不含 2 与王）
    pair_chain      连对（>=3 对连续对子，不含 2）
    airplane        飞机不带（>=2 组连续三张，不含 2）
    airplane_single 飞机带单（每组三张带一张单牌）
    airplane_pair   飞机带对（每组三张带一对）
    four_two_single 四带二（四张 + 任意两张，允许成对，不允许带王炸）
    four_two_pair   四带两对（四张 + 两对）
    bomb            炸弹（四张相同）
    rocket          王炸（大小王）
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from cards import (RANK_JOKER_BIG, RANK_JOKER_SMALL, RANK_MAX, RANK_MIN,
                   rank_of)

COMBO_SINGLE = "single"
COMBO_PAIR = "pair"
COMBO_TRIPLE = "triple"
COMBO_TRIPLE_SINGLE = "triple_single"
COMBO_TRIPLE_PAIR = "triple_pair"
COMBO_STRAIGHT = "straight"
COMBO_PAIR_CHAIN = "pair_chain"
COMBO_AIRPLANE = "airplane"
COMBO_AIRPLANE_SINGLE = "airplane_single"
COMBO_AIRPLANE_PAIR = "airplane_pair"
COMBO_FOUR_TWO_SINGLE = "four_two_single"
COMBO_FOUR_TWO_PAIR = "four_two_pair"
COMBO_BOMB = "bomb"
COMBO_ROCKET = "rocket"

# 普通组合（非炸弹/王炸）集合
NORMAL_COMBOS = {
    COMBO_SINGLE, COMBO_PAIR, COMBO_TRIPLE, COMBO_TRIPLE_SINGLE,
    COMBO_TRIPLE_PAIR, COMBO_STRAIGHT, COMBO_PAIR_CHAIN, COMBO_AIRPLANE,
    COMBO_AIRPLANE_SINGLE, COMBO_AIRPLANE_PAIR, COMBO_FOUR_TWO_SINGLE,
    COMBO_FOUR_TWO_PAIR,
}

COMBO_LABEL_ZH: Dict[str, str] = {
    COMBO_SINGLE: "单张",
    COMBO_PAIR: "对子",
    COMBO_TRIPLE: "三张",
    COMBO_TRIPLE_SINGLE: "三带一",
    COMBO_TRIPLE_PAIR: "三带二",
    COMBO_STRAIGHT: "顺子",
    COMBO_PAIR_CHAIN: "连对",
    COMBO_AIRPLANE: "飞机",
    COMBO_AIRPLANE_SINGLE: "飞机带单",
    COMBO_AIRPLANE_PAIR: "飞机带对",
    COMBO_FOUR_TWO_SINGLE: "四带二",
    COMBO_FOUR_TWO_PAIR: "四带两对",
    COMBO_BOMB: "炸弹",
    COMBO_ROCKET: "王炸",
}


@dataclass(frozen=True)
class Combo:
    """一个合法的出牌组合。"""
    type: str
    main_rank: int          # 比较大小的关键牌值
    length: int             # 总张数
    cards: Tuple[int, ...] = field(default=(), repr=False)  # 组成该组合的牌 id

    @property
    def label(self) -> str:
        return COMBO_LABEL_ZH.get(self.type, self.type)

    def describe(self) -> str:
        """用于日志的中文描述，如 '对子 KK'、'顺子 3-7'。"""
        from cards import RANK_NAMES
        name = self.label
        if self.type == COMBO_STRAIGHT:
            low = self.main_rank - self.length + 1
            return "%s %s-%s" % (name, RANK_NAMES[low], RANK_NAMES[self.main_rank])
        if self.type == COMBO_PAIR_CHAIN or self.type == COMBO_AIRPLANE:
            low = self.main_rank - (self.length // (2 if self.type == COMBO_PAIR_CHAIN else 3)) + 1
            return "%s %s-%s" % (name, RANK_NAMES[low], RANK_NAMES[self.main_rank])
        if self.type == COMBO_AIRPLANE_SINGLE:
            k = self.length // 4
            low = self.main_rank - k + 1
            return "%s %s-%s" % (name, RANK_NAMES[low], RANK_NAMES[self.main_rank])
        if self.type == COMBO_AIRPLANE_PAIR:
            k = self.length // 5
            low = self.main_rank - k + 1
            return "%s %s-%s" % (name, RANK_NAMES[low], RANK_NAMES[self.main_rank])
        if self.type == COMBO_ROCKET:
            return name
        return "%s %s" % (name, RANK_NAMES[self.main_rank])


def _consecutive(ranks: List[int]) -> bool:
    """ranks 升序排列且连续。"""
    return all(ranks[i + 1] == ranks[i] + 1 for i in range(len(ranks) - 1))


def classify(cards) -> Optional[Combo]:
    """判断一组牌是否构成合法牌型，合法返回 Combo，否则返回 None。"""
    cards = tuple(cards)
    n = len(cards)
    if n == 0:
        return None
    ranks = [rank_of(c) for c in cards]
    counts: Counter = Counter(ranks)

    # ---- 1 张 / 2 张 ----
    if n == 1:
        return Combo(COMBO_SINGLE, ranks[0], 1, cards)
    if n == 2:
        r0, r1 = ranks
        if r0 == r1:
            return Combo(COMBO_PAIR, r0, 2, cards)
        if {r0, r1} == {RANK_JOKER_SMALL, RANK_JOKER_BIG}:
            return Combo(COMBO_ROCKET, RANK_JOKER_BIG, 2, cards)
        return None

    # ---- 3 张 / 4 张 ----
    if n == 3:
        if len(set(ranks)) == 1:
            return Combo(COMBO_TRIPLE, ranks[0], 3, cards)
        return None
    if n == 4:
        if len(set(ranks)) == 1:
            return Combo(COMBO_BOMB, ranks[0], 4, cards)
        triples = [r for r, c in counts.items() if c == 3]
        if len(triples) == 1 and len(counts) == 2:
            return Combo(COMBO_TRIPLE_SINGLE, triples[0], 4, cards)
        return None

    # ---- 四带二 / 四带两对（先于其它判断，避免误判） ----
    quads = [r for r, c in counts.items() if c == 4]
    if len(quads) == 1:
        main = quads[0]
        rest_ranks = [r for r, c in counts.items() if r != main]
        rest_cards = n - 4
        if rest_cards == 2 and len(rest_ranks) in (1, 2):
            # 不允许把王炸拆开作为两张单牌带出
            if not ({RANK_JOKER_SMALL, RANK_JOKER_BIG} <= set(rest_ranks)):
                return Combo(COMBO_FOUR_TWO_SINGLE, main, n, cards)
            return None
        if rest_cards == 4 and len(rest_ranks) == 2 and all(counts[r] == 2 for r in rest_ranks):
            return Combo(COMBO_FOUR_TWO_PAIR, main, n, cards)
        return None

    # ---- 顺子 ----
    if all(c == 1 for c in counts.values()):
        lo, hi = min(ranks), max(ranks)
        if n >= 5 and lo >= RANK_MIN and hi <= 14 and hi - lo + 1 == n:
            return Combo(COMBO_STRAIGHT, hi, n, cards)

    # ---- 连对 ----
    if n >= 6 and n % 2 == 0:
        pair_ranks = [r for r, c in counts.items() if c == 2]
        if len(pair_ranks) == n // 2 and len(counts) == n // 2:
            lo, hi = min(pair_ranks), max(pair_ranks)
            if hi <= 14 and hi - lo + 1 == n // 2:
                return Combo(COMBO_PAIR_CHAIN, hi, n, cards)

    # ---- 飞机 / 三带一 / 三带二 ----
    triple_ranks = sorted(r for r, c in counts.items() if c == 3)
    if triple_ranks:
        k = len(triple_ranks)
        if k >= 2 and _consecutive(triple_ranks) and triple_ranks[-1] <= 14:
            base = k * 3
            triple_set = set(triple_ranks)
            if n == base:
                return Combo(COMBO_AIRPLANE, triple_ranks[-1], n, cards)
            if n == base + k:
                # 带 k 张单牌：必须互不相同且不是飞机本身的牌
                wing_ranks = [r for r, c in counts.items() if c == 1]
                if (len(wing_ranks) == k and len(counts) == k + k
                        and not (set(wing_ranks) & triple_set)):
                    return Combo(COMBO_AIRPLANE_SINGLE, triple_ranks[-1], n, cards)
            if n == base + 2 * k:
                wing_pairs = [r for r, c in counts.items() if c == 2]
                if len(wing_pairs) == k and not (set(wing_pairs) & triple_set):
                    return Combo(COMBO_AIRPLANE_PAIR, triple_ranks[-1], n, cards)
        # 三带一 / 三带二（仅一组三张时）
        if k == 1:
            main = triple_ranks[0]
            if n == 4 and len(counts) == 2:
                return Combo(COMBO_TRIPLE_SINGLE, main, n, cards)
            if n == 5 and len(counts) == 2:
                pair_ranks = [r for r, c in counts.items() if c == 2]
                if pair_ranks:
                    return Combo(COMBO_TRIPLE_PAIR, main, n, cards)
    return None


def beats(a: Combo, b: Combo) -> bool:
    """a 是否能压过 b。"""
    if a.type == b.type:
        if a.type == COMBO_ROCKET:
            return False  # 王炸只有一副，不存在互压
        return a.length == b.length and a.main_rank > b.main_rank
    if a.type == COMBO_ROCKET:
        return True
    if b.type == COMBO_ROCKET:
        return False
    if a.type == COMBO_BOMB:
        return True
    return False
