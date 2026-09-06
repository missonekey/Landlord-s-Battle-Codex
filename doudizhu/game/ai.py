# -*- coding: utf-8 -*-
"""斗地主 AI 策略引擎（确定性规则机器人）。

包含:
    bid_value / decide_bid     叫分决策
    suggest_lead               主动出牌
    suggest_follow             跟牌/压牌/过牌
    suggest                    统一入口（供机器人出牌与玩家「提示」使用）
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Tuple

import rules
from cards import (JOKER_BIG_ID, JOKER_SMALL_ID, RANK_JOKER_BIG,
                   RANK_JOKER_SMALL, rank_of)

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _hand_counts(hand) -> Counter:
    return Counter(rank_of(c) for c in hand)


def _ids_by_rank(hand) -> Dict[int, List[int]]:
    ids: Dict[int, List[int]] = {}
    for c in sorted(hand):
        ids.setdefault(rank_of(c), []).append(c)
    return ids


def _runs(ranks: List[int]) -> List[Tuple[int, int]]:
    """升序 rank 列表中的最大连续段 [(start, end), ...]。"""
    if not ranks:
        return []
    out = []
    s = p = ranks[0]
    for r in ranks[1:]:
        if r == p + 1:
            p = r
        else:
            out.append((s, p))
            s = p = r
    out.append((s, p))
    return out


def _safe_single(rank: int, remaining: dict) -> bool:
    """该单张是否"安全"：所有比它大的牌都已打出（外面没有更大的单牌）。"""
    return all(remaining.get(r, 0) == 0 for r in range(rank + 1, 18))



def _break_penalty(rank: int, count: int) -> float:
    """拆牌代价：拆对 +1.1，拆三张 +2.2，拆炸弹 +8。"""
    if count >= 4:
        return 8.0
    if count == 3:
        return 2.2
    if count == 2:
        return 1.1
    return 0.0


# ---------------------------------------------------------------------------
# 叫分
# ---------------------------------------------------------------------------


def bid_value(hand) -> float:
    """手牌实力评分（越高越强）。"""
    counts = _hand_counts(hand)
    score = 0.0
    # 大牌
    score += 3.0 * counts.get(15, 0)          # 每张 2
    score += 1.6 * counts.get(14, 0)          # 每张 A
    score += 1.0 * counts.get(13, 0)          # 每张 K
    # 炸弹与王炸
    score += 3.0 * sum(1 for r, n in counts.items() if n == 4)
    if counts.get(RANK_JOKER_SMALL) and counts.get(RANK_JOKER_BIG):
        score += 5.0
    # 三张
    score += 1.3 * sum(1 for r, n in counts.items() if n == 3 and r <= 15)
    # 孤张多则减分（2 与王不算孤张）
    score -= 0.35 * sum(1 for r, n in counts.items() if n == 1 and r <= 15)
    return score


def decide_bid(hand, current_highest: int) -> int:
    """返回 0（不叫）或 1/2/3（叫分，必须高于 current_highest）。"""
    s = bid_value(hand)
    for threshold, level in ((11.5, 3), (9.0, 2), (6.5, 1)):
        if s >= threshold and level > current_highest:
            return level
    return 0


# ---------------------------------------------------------------------------
# 主动出牌
# ---------------------------------------------------------------------------


def _smallest_single(hand, counts, ids) -> Optional[List[int]]:
    """最小的孤张单牌（不拆牌）；没有孤张时返回最小的单张（含拆牌）。"""
    for r in sorted(counts):
        if counts[r] == 1:
            return [ids[r][0]]
    for r in sorted(counts):
        if counts[r] >= 1:
            return [ids[r][0]]
    return None


def _smallest_pair(hand, counts, ids) -> Optional[List[int]]:
    for r in sorted(counts):
        if counts[r] >= 2 and counts[r] != 4:
            return ids[r][:2]
    return None


def _pure_straights(counts) -> List[Tuple[int, int]]:
    """只用孤张组成的顺子 (start, length)，长度 >= 5。"""
    ranks = [r for r in range(3, 15) if counts.get(r) == 1]
    out = []
    for s, e in _runs(ranks):
        for length in range(5, e - s + 2):
            for start in range(s, e - length + 2):
                out.append((start, length))
    return out


def _pure_chains(counts) -> List[Tuple[int, int]]:
    """只用完整对子组成的连对 (start, 对数)，>= 3 对。"""
    ranks = [r for r in range(3, 15) if counts.get(r) == 2]
    out = []
    for s, e in _runs(ranks):
        for k in range(3, e - s + 2):
            for start in range(s, e - k + 2):
                out.append((start, k))
    return out


def _pure_airplanes(counts) -> List[Tuple[int, int]]:
    """只用完整三张组成的飞机 (start, 组数)，>= 2 组。"""
    ranks = [r for r in range(3, 15) if counts.get(r) == 3]
    out = []
    for s, e in _runs(ranks):
        for k in range(2, e - s + 2):
            for start in range(s, e - k + 2):
                out.append((start, k))
    return out


def _pick_lead_airplane(start: int, k: int, hand, counts, ids) -> List[int]:
    """组一个飞机出牌：优先带单，其次带对，最后裸飞。"""
    cards = []
    for r in range(start, start + k):
        cards.extend(ids[r][:3])
    triple_ranks = set(range(start, start + k))
    spare_singles = [r for r in sorted(counts) if counts[r] == 1 and r not in triple_ranks]
    if len(spare_singles) >= k:
        for r in spare_singles[:k]:
            cards.append(ids[r][0])
        return cards
    spare_pairs = [r for r in sorted(counts) if counts[r] == 2 and r not in triple_ranks]
    if len(spare_pairs) >= k:
        for r in spare_pairs[:k]:
            cards.extend(ids[r][:2])
        return cards
    return cards


def suggest_lead(hand, ctx: Optional[dict] = None) -> List[int]:
    """主动出牌：返回要打出的牌。"""
    ctx = ctx or {}
    if not hand:
        return []
    counts = _hand_counts(hand)
    ids = _ids_by_rank(hand)

    # 1) 一手走完直接赢
    whole = rules.classify(hand)
    if whole is not None:
        return list(hand)

    # 2) 队友快走完了，喂牌
    teammate_left = ctx.get("teammate_left")
    if ctx.get("role") == "farmer" and teammate_left is not None and teammate_left <= 3:
        s = _smallest_single(hand, counts, ids)
        if s:
            return s
        p = _smallest_pair(hand, counts, ids)
        if p:
            return p

    # 3) 孤张单牌（优先非 2、非王的小牌；再优先"安全牌"——外面没有更大的牌）
    singles = [r for r in sorted(counts) if counts[r] == 1]
    if singles:
        prefer = [r for r in singles if r <= 14]
        pool = prefer or singles
        rem = ctx.get("remaining") or {}
        safe = [r for r in pool if _safe_single(r, rem)]
        r = (safe or pool)[0]
        return [ids[r][0]]

    # 4) 对子
    pairs = [r for r in sorted(counts) if 2 <= counts[r] < 4]
    if pairs:
        return ids[pairs[0]][:2]

    # 5) 三张（有孤张就三带一）
    triples = [r for r in sorted(counts) if 3 <= counts[r] < 4]
    if triples:
        r = triples[0]
        wing = [x for x in sorted(counts) if counts[x] == 1 and x != r]
        if wing:
            return ids[r][:3] + [ids[wing[0]][0]]
        return ids[r][:3]

    # 6) 顺子（孤张组成，选最长、起点最小）
    straights = _pure_straights(counts)
    if straights:
        start, length = max(straights, key=lambda t: (t[1], -t[0]))
        return [ids[r][0] for r in range(start, start + length)]

    # 7) 连对
    chains = _pure_chains(counts)
    if chains:
        start, k = max(chains, key=lambda t: (t[1], -t[0]))
        out = []
        for r in range(start, start + k):
            out.extend(ids[r][:2])
        return out

    # 8) 飞机
    planes = _pure_airplanes(counts)
    if planes:
        start, k = max(planes, key=lambda t: (t[1], -t[0]))
        return _pick_lead_airplane(start, k, hand, counts, ids)

    # 9) 只剩炸弹/王炸
    if all(n == 4 for n in counts.values()) or set(hand) == {JOKER_SMALL_ID, JOKER_BIG_ID}:
        r = min(counts)
        return ids[r][:4]

    # 10) 兜底：拆最小的牌
    r = min(counts)
    if counts[r] >= 2:
        return ids[r][:2]
    return [ids[r][0]]


# ---------------------------------------------------------------------------
# 跟牌
# ---------------------------------------------------------------------------


def _gen_beats(hand, target: rules.Combo, ctx: dict):
    """生成所有能压过 target 的出法 [(代价, 牌列表), ...]。"""
    counts = _hand_counts(hand)
    ids = _ids_by_rank(hand)
    my_left = len(hand)
    opp_min = ctx.get("opp_min", 99)
    desperate = ctx.get("desperate", False) or my_left <= 6 or opp_min <= 7
    t = target.type
    t_main = target.main_rank
    out = []

    def add(combo_type, main_rank, card_ids, penalty=0.0, bomb_use=0.0):
        combo = rules.Combo(combo_type, main_rank, len(card_ids), tuple(card_ids))
        if not rules.beats(combo, target):
            return
        big = 0.0
        if main_rank >= RANK_JOKER_SMALL:
            big = 4.0
        elif main_rank == 15:
            big = 2.6
        elif main_rank == 14:
            big = 1.4
        elif main_rank == 13:
            big = 0.6
        cost = penalty + big + bomb_use + 0.1 * len(card_ids)
        out.append((cost, card_ids))

    sorted_ranks = sorted(counts)

    # --- 同类型候选 ---
    if t == rules.COMBO_SINGLE:
        for r in sorted_ranks:
            if r > t_main:
                add(rules.COMBO_SINGLE, r, [ids[r][0]], _break_penalty(r, counts[r]))
    elif t == rules.COMBO_PAIR:
        for r in sorted_ranks:
            if r > t_main and counts[r] >= 2:
                add(rules.COMBO_PAIR, r, ids[r][:2], _break_penalty(r, counts[r]))
    elif t == rules.COMBO_TRIPLE:
        for r in sorted_ranks:
            if r > t_main and counts[r] >= 3:
                add(rules.COMBO_TRIPLE, r, ids[r][:3], _break_penalty(r, counts[r]))
    elif t == rules.COMBO_TRIPLE_SINGLE:
        for r in sorted_ranks:
            if r > t_main and counts[r] >= 3:
                wings = [x for x in sorted_ranks if counts[x] >= 1 and x != r]
                wings.sort(key=lambda w: (_break_penalty(w, counts[w]), w))
                for w in wings:
                    if {r, w} == {RANK_JOKER_SMALL, RANK_JOKER_BIG}:
                        continue
                    penalty = _break_penalty(r, counts[r]) + _break_penalty(w, counts[w])
                    add(rules.COMBO_TRIPLE_SINGLE, r, ids[r][:3] + [ids[w][0]], penalty)
                    break  # 每张三带一配代价最小的翅膀即可
    elif t == rules.COMBO_TRIPLE_PAIR:
        for r in sorted_ranks:
            if r > t_main and counts[r] >= 3:
                pairs = [x for x in sorted_ranks if counts[x] >= 2 and x != r]
                pairs.sort(key=lambda w: (_break_penalty(w, counts[w]), w))
                if pairs:
                    w = pairs[0]
                    penalty = _break_penalty(r, counts[r]) + _break_penalty(w, counts[w])
                    add(rules.COMBO_TRIPLE_PAIR, r, ids[r][:3] + ids[w][:2], penalty)
    elif t == rules.COMBO_STRAIGHT:
        length = target.length
        ranks = [r for r in range(3, 15) if counts.get(r, 0) >= 1]
        for s, e in _runs(ranks):
            for start in range(s, e - length + 2):
                top = start + length - 1
                if top > t_main:
                    card_ids = []
                    penalty = 0.0
                    for r in range(start, start + length):
                        card_ids.append(ids[r][0])
                        penalty += _break_penalty(r, counts[r])
                    add(rules.COMBO_STRAIGHT, top, card_ids, penalty)
    elif t == rules.COMBO_PAIR_CHAIN:
        k = target.length // 2
        ranks = [r for r in range(3, 15) if counts.get(r, 0) >= 2]
        for s, e in _runs(ranks):
            for start in range(s, e - k + 2):
                top = start + k - 1
                if top > t_main:
                    card_ids = []
                    penalty = 0.0
                    for r in range(start, start + k):
                        card_ids.extend(ids[r][:2])
                        penalty += _break_penalty(r, counts[r])
                    add(rules.COMBO_PAIR_CHAIN, top, card_ids, penalty)
    elif t in (rules.COMBO_AIRPLANE, rules.COMBO_AIRPLANE_SINGLE, rules.COMBO_AIRPLANE_PAIR):
        if t == rules.COMBO_AIRPLANE:
            k = target.length // 3
            wing = 0
        elif t == rules.COMBO_AIRPLANE_SINGLE:
            k = target.length // 4
            wing = 1
        else:
            k = target.length // 5
            wing = 2
        triple_ranks_all = [r for r in range(3, 15) if counts.get(r, 0) >= 3]
        for s, e in _runs(triple_ranks_all):
            for start in range(s, e - k + 2):
                top = start + k - 1
                if top <= t_main:
                    continue
                run_ranks = set(range(start, start + k))
                card_ids = []
                penalty = 0.0
                for r in range(start, start + k):
                    card_ids.extend(ids[r][:3])
                    penalty += _break_penalty(r, counts[r])
                if wing == 0:
                    add(rules.COMBO_AIRPLANE, top, card_ids, penalty)
                    continue
                if wing == 1:
                    wings = [x for x in sorted_ranks if counts[x] == 1 and x not in run_ranks]
                    if len(wings) >= k:
                        for w in wings[:k]:
                            card_ids.append(ids[w][0])
                        add(rules.COMBO_AIRPLANE_SINGLE, top, card_ids, penalty)
                else:
                    wings = [x for x in sorted_ranks if counts[x] == 2 and x not in run_ranks]
                    if len(wings) >= k:
                        for w in wings[:k]:
                            card_ids.extend(ids[w][:2])
                        add(rules.COMBO_AIRPLANE_PAIR, top, card_ids, penalty)
    elif t == rules.COMBO_FOUR_TWO_SINGLE:
        for r in sorted_ranks:
            if r > t_main and counts[r] == 4:
                wings = [x for x in sorted_ranks if x != r]
                chosen = []
                for w in wings:
                    chosen.append(ids[w][0])
                    if len(chosen) == 2:
                        break
                # 不允许把王炸拆开带出去
                chosen_ranks = {rank_of(c) for c in chosen}
                if len(chosen) == 2 and chosen_ranks != {RANK_JOKER_SMALL, RANK_JOKER_BIG}:
                    penalty = _break_penalty(r, counts[r]) + sum(
                        _break_penalty(w, counts[w]) for w in chosen_ranks)
                    add(rules.COMBO_FOUR_TWO_SINGLE, r, ids[r][:4] + chosen, penalty)
    elif t == rules.COMBO_FOUR_TWO_PAIR:
        for r in sorted_ranks:
            if r > t_main and counts[r] == 4:
                pairs = [x for x in sorted_ranks if counts[x] >= 2 and x != r]
                if len(pairs) >= 2:
                    chosen = pairs[:2]
                    card_ids = ids[r][:4]
                    penalty = _break_penalty(r, counts[r])
                    for w in chosen:
                        card_ids.extend(ids[w][:2])
                        penalty += _break_penalty(w, counts[w])
                    add(rules.COMBO_FOUR_TWO_PAIR, r, card_ids, penalty)
    elif t == rules.COMBO_BOMB:
        for r in sorted_ranks:
            if r > t_main and counts[r] == 4:
                add(rules.COMBO_BOMB, r, ids[r][:4], 0.0, bomb_use=0.0)

    # --- 拆牌候选（单张/对子/三张） ---
    if t == rules.COMBO_SINGLE:
        for r in sorted_ranks:
            if r > t_main and 2 <= counts[r] <= 3:
                add(rules.COMBO_SINGLE, r, [ids[r][0]], _break_penalty(r, counts[r]))
            if r > t_main and counts[r] == 4 and desperate:
                add(rules.COMBO_SINGLE, r, [ids[r][0]], 8.0)
    elif t == rules.COMBO_PAIR:
        for r in sorted_ranks:
            if r > t_main and counts[r] == 3:
                add(rules.COMBO_PAIR, r, ids[r][:2], 2.2)
            if r > t_main and counts[r] == 4 and desperate:
                add(rules.COMBO_PAIR, r, ids[r][:2], 8.0)
    elif t == rules.COMBO_TRIPLE:
        for r in sorted_ranks:
            if r > t_main and counts[r] == 4 and desperate:
                add(rules.COMBO_TRIPLE, r, ids[r][:3], 8.0)

    # --- 炸弹 / 王炸（只在必要时使用） ---
    bomb_allowed = t == rules.COMBO_BOMB or desperate
    if bomb_allowed:
        for r in sorted_ranks:
            if counts[r] == 4:
                add(rules.COMBO_BOMB, r, ids[r][:4], 0.0, bomb_use=5.0)
    if counts.get(RANK_JOKER_SMALL) and counts.get(RANK_JOKER_BIG) and t != rules.COMBO_ROCKET:
        if t == rules.COMBO_BOMB or desperate:
            add(rules.COMBO_ROCKET, RANK_JOKER_BIG, [JOKER_SMALL_ID, JOKER_BIG_ID],
                0.0, bomb_use=7.0)

    return out


def suggest_follow(hand, target: rules.Combo, ctx: Optional[dict] = None) -> Optional[List[int]]:
    """跟牌：返回要出的牌，或 None 表示过牌。"""
    ctx = ctx or {}
    if ctx.get("role") == "farmer" and ctx.get("target_owner") == ctx.get("teammate"):
        return None  # 不压队友
    # 大师级：整手牌能一把压过就走（残局直接获胜）
    whole = rules.classify(hand)
    if whole is not None and rules.beats(whole, target):
        return list(hand)
    cands = _gen_beats(hand, target, ctx)
    if not cands:
        return None
    best_cost, best_cards = min(cands, key=lambda x: x[0])
    landlord_left = ctx.get("landlord_left", 99)
    opp_min = ctx.get("opp_min", 99)
    if ctx.get("role") == "farmer":
        if landlord_left <= 6:
            return best_cards
        if best_cost <= 6.0:
            return best_cards
        return None
    # 地主
    if opp_min <= 4:
        return best_cards
    if best_cost <= 6.0:
        return best_cards
    return None


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def suggest(hand, target, ctx: Optional[dict] = None) -> Optional[List[int]]:
    """按 target（None 表示新回合先手）给出建议出牌；None 表示建议过牌。"""
    if target is None:
        return suggest_lead(hand, ctx)
    return suggest_follow(hand, target, ctx)
