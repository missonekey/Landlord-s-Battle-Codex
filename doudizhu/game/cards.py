# -*- coding: utf-8 -*-
"""牌定义：标准 54 张扑克牌（52 张普通牌 + 小王 + 大王）。

牌 id 规则:
  - 0..51: 普通牌, id = 花色 * 13 + (牌值 - 3)
        花色: 0=♠ 1=♥ 2=♣ 3=♦; 牌值: 3..10, J=11, Q=12, K=13, A=14, 2=15
  - 52: 小王, 53: 大王
"""
from __future__ import annotations

from typing import Dict, List, Optional

# 花色
SPADE, HEART, CLUB, DIAMOND = 0, 1, 2, 3
SUITS = (SPADE, HEART, CLUB, DIAMOND)
SUIT_SYMBOL: Dict[int, str] = {SPADE: "♠", HEART: "♥", CLUB: "♣", DIAMOND: "♦"}
SUIT_IS_RED: Dict[int, bool] = {SPADE: False, HEART: True, CLUB: False, DIAMOND: True}

# 牌值范围
RANK_MIN = 3
RANK_MAX = 15          # 3..10, J, Q, K, A, 2
RANK_JOKER_SMALL = 16  # 小王
RANK_JOKER_BIG = 17    # 大王

RANK_NAMES: Dict[int, str] = {
    3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A", 15: "2",
    RANK_JOKER_SMALL: "小王", RANK_JOKER_BIG: "大王",
}

JOKER_SMALL_ID = 52
JOKER_BIG_ID = 53


def rank_of(card: int) -> int:
    """返回牌的牌值（3..17）。"""
    if card < 52:
        return card % 13 + 3
    return RANK_JOKER_SMALL if card == JOKER_SMALL_ID else RANK_JOKER_BIG


def suit_of(card: int) -> Optional[int]:
    """返回牌的花色（普通牌），王牌返回 None。"""
    if card < 52:
        return card // 13
    return None


def make_card(rank: int, suit: int) -> int:
    """按牌值与花色构造牌 id。"""
    return suit * 13 + (rank - 3)


def card_name(card: int) -> str:
    """牌的显示名，如 '♠8'、'小王'。"""
    r = rank_of(card)
    if r >= RANK_JOKER_SMALL:
        return RANK_NAMES[r]
    return SUIT_SYMBOL[suit_of(card)] + RANK_NAMES[r]


def new_deck() -> List[int]:
    """一副 54 张的标准牌。"""
    return list(range(54))


def sort_hand(hand: List[int]) -> List[int]:
    """按牌值降序（大王 > 小王 > 2 > ... > 3），同牌值按花色。"""
    return sorted(hand, key=lambda c: (rank_of(c), suit_of(c) if suit_of(c) is not None else -1), reverse=True)
