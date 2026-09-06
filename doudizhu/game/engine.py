# -*- coding: utf-8 -*-
"""斗地主对局引擎：发牌、叫地主、出牌、过牌、结算与计分。

三位玩家: 0 = 人类（主玩家，坐在下方）, 1 = 下家（电脑）, 2 = 上家（电脑）
出牌顺序: 0 -> 1 -> 2 -> 0 ...
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Dict, List, Optional, Tuple

import ai
import rules
from cards import (JOKER_BIG_ID, JOKER_SMALL_ID, RANK_JOKER_BIG,
                   RANK_JOKER_SMALL, card_name, new_deck, rank_of, sort_hand)

PLAYER_NAMES = ("你", "下家", "上家")

PHASE_BIDDING = "bidding"
PHASE_PLAYING = "playing"
PHASE_OVER = "round_over"

MAX_DEALS_PER_ROUND = 200  # 防止极端情况下无限重新发牌（正常远达不到）


class Game:
    def __init__(self, human: int = 0, seed: Optional[int] = None):
        self.human = human
        self.rng = random.Random(seed)
        self.scores: List[int] = [0, 0, 0]
        self.round_no = 0
        self.version = 0
        self.log: List[str] = []
        self._new_round()

    # ------------------------------------------------------------------
    # 回合初始化
    # ------------------------------------------------------------------

    def _new_round(self) -> None:
        self.round_no += 1
        self.deal_no = 0
        self._deal()

    def _deal(self) -> None:
        self.deal_no += 1
        deck = new_deck()
        self.rng.shuffle(deck)
        self.hands: List[List[int]] = [deck[:17], deck[17:34], deck[34:51]]
        self.bottom: List[int] = deck[51:]
        for i in range(3):
            self.hands[i] = sort_hand(self.hands[i])

        self.phase = PHASE_BIDDING
        self.starter = (self.round_no - 1 + self.deal_no - 1) % 3
        self.turn = self.starter
        self.bid_highest = 0
        self.bidder: Optional[int] = None
        self.pass_count = 0
        self.bid_points = 0
        self.landlord: Optional[int] = None
        self.bid_event: Optional[dict] = None   # 最近一次叫分事件（供前端语音播报）

        self.last_combo: Optional[rules.Combo] = None
        self.last_player: Optional[int] = None
        self.trick_passes = 0
        self.last_plays: List[Optional[dict]] = [None, None, None]
        self.plays_count = [0, 0, 0]
        self.bombs_used = 0
        self.rockets_used = 0
        self.played_ranks: Counter = Counter()

        self.winners: Optional[List[int]] = None
        self.round_result: Optional[str] = None
        self.spring = False
        self.anti_spring = False
        self.multiplier = 1

        self._log("第 %d 局发牌完毕，%s 先叫地主。" % (self.round_no, PLAYER_NAMES[self.starter]))
        self.version += 1

    def _log(self, msg: str) -> None:
        self.log.append(msg)
        if len(self.log) > 40:
            del self.log[:-40]

    # ------------------------------------------------------------------
    # 叫地主
    # ------------------------------------------------------------------

    def bid(self, player: int, value: int) -> None:
        """叫分：value=0 不叫，1/2/3 叫分（必须高于当前最高分）。"""
        if self.phase != PHASE_BIDDING:
            raise ValueError("当前不是叫地主阶段")
        if player != self.turn:
            raise ValueError("还没轮到%s叫分" % PLAYER_NAMES[player])
        if value not in (0, 1, 2, 3):
            raise ValueError("叫分只能是 0(不叫)、1、2、3")
        if value != 0 and value <= self.bid_highest:
            raise ValueError("叫分必须高于当前最高分 %d 分" % self.bid_highest)

        if value == 0:
            self.pass_count += 1
            self.bid_event = {"kind": "pass", "player": player}
            self._log("%s 不叫。" % PLAYER_NAMES[player])
        else:
            self.bid_highest = value
            self.bidder = player
            self.pass_count = 0
            self.bid_event = {"kind": "bid", "bid": value, "player": player}
            self._log("%s 叫 %d 分。" % (PLAYER_NAMES[player], value))

        if self.pass_count == 3:
            self._log("三家都不叫，重新发牌。")
            if self.deal_no >= MAX_DEALS_PER_ROUND:
                raise RuntimeError("重新发牌次数过多")
            self.bid_event = {"kind": "redeal"}
            self._deal()
            return

        if self.bidder is not None and self.pass_count == 2:
            self.landlord = self.bidder
            self.bid_points = self.bid_highest
            self.hands[self.landlord] = sort_hand(self.hands[self.landlord] + self.bottom)
            self.phase = PHASE_PLAYING
            self.turn = self.landlord
            self.bid_event = {"kind": "landlord", "bid": self.bid_points, "player": self.landlord}
            self._log("%s 成为地主（%d 分），底牌：%s。"
                      % (PLAYER_NAMES[self.landlord], self.bid_points,
                         " ".join(card_name(c) for c in self.bottom)))
        else:
            self.turn = (self.turn + 1) % 3
        self.version += 1

    # ------------------------------------------------------------------
    # 出牌 / 过牌
    # ------------------------------------------------------------------

    def play(self, player: int, cards) -> None:
        """打出一组牌。非法时抛出 ValueError（中文提示）。"""
        cards = list(cards)
        if self.phase != PHASE_PLAYING:
            raise ValueError("当前不是出牌阶段")
        if player != self.turn:
            raise ValueError("还没轮到%s出牌" % PLAYER_NAMES[player])
        if not cards:
            raise ValueError("请选择要出的牌")
        if len(set(cards)) != len(cards):
            raise ValueError("出牌不能重复")
        if not all(c in self.hands[player] for c in cards):
            raise ValueError("手牌中没有这些牌")
        combo = rules.classify(cards)
        if combo is None:
            raise ValueError("所选牌型不合法")
        if self.last_combo is not None and not rules.beats(combo, self.last_combo):
            raise ValueError("压不住上家的牌（%s）" % self.last_combo.describe())

        for c in cards:
            self.hands[player].remove(c)
            self.played_ranks[rank_of(c)] += 1
        self.plays_count[player] += 1
        if combo.type == rules.COMBO_BOMB:
            self.bombs_used += 1
        elif combo.type == rules.COMBO_ROCKET:
            self.rockets_used += 1

        self.last_combo = combo
        self.last_player = player
        self.trick_passes = 0
        self.last_plays[player] = {
            "player": player, "passed": False,
            "cards": cards, "type": combo.type,
            "main_rank": combo.main_rank, "label": combo.describe(),
        }
        self._log("%s 出牌：%s" % (PLAYER_NAMES[player], combo.describe()))

        if not self.hands[player]:
            self._finish(player)
            return
        self.turn = (player + 1) % 3
        self.version += 1

    def pass_turn(self, player: int) -> None:
        if self.phase != PHASE_PLAYING:
            raise ValueError("当前不是出牌阶段")
        if player != self.turn:
            raise ValueError("还没轮到%s出牌" % PLAYER_NAMES[player])
        if self.last_combo is None or self.last_player == player:
            raise ValueError("必须出牌，不能过牌")

        self.trick_passes += 1
        self.last_plays[player] = {"player": player, "passed": True,
                                   "cards": [], "type": None,
                                   "main_rank": None, "label": "不出"}
        self._log("%s 不出。" % PLAYER_NAMES[player])
        if self.trick_passes == 2:
            # 两家都不出，上家重新出牌
            self.last_combo = None
            self.last_player = None
            self.trick_passes = 0
            self.last_plays = [None, None, None]
        self.turn = (player + 1) % 3
        self.version += 1

    # ------------------------------------------------------------------
    # 结算
    # ------------------------------------------------------------------

    def _finish(self, winner: int) -> None:
        self.winners = [winner]
        farmers = [p for p in range(3) if p != self.landlord]
        landlord_plays = self.plays_count[self.landlord]
        farmers_plays = sum(self.plays_count[p] for p in farmers)

        self.spring = winner == self.landlord and farmers_plays == 0
        self.anti_spring = winner != self.landlord and landlord_plays == 1

        mult = 2 ** (self.bombs_used + self.rockets_used)
        if self.spring or self.anti_spring:
            mult *= 2
        self.multiplier = mult

        stake = self.bid_points * mult
        round_scores = [0, 0, 0]
        if winner == self.landlord:
            round_scores[self.landlord] = 2 * stake
            for p in farmers:
                round_scores[p] = -stake
            self.round_result = "地主胜"
        else:
            round_scores[self.landlord] = -2 * stake
            for p in farmers:
                round_scores[p] = stake
            self.round_result = "农民胜"
        for p in range(3):
            self.scores[p] += round_scores[p]
        self.round_scores = round_scores

        notes = []
        if self.bombs_used:
            notes.append("炸弹x%d" % self.bombs_used)
        if self.rockets_used:
            notes.append("王炸x%d" % self.rockets_used)
        if self.spring:
            notes.append("春天")
        if self.anti_spring:
            notes.append("反春")
        note = ("，".join(notes) + "，" if notes else "")
        self._log("%s获胜（%s，%s倍数 x%d）。" % (PLAYER_NAMES[winner], self.round_result, note, mult))
        self.phase = PHASE_OVER
        self.version += 1

    # ------------------------------------------------------------------
    # 机器人
    # ------------------------------------------------------------------

    def _ai_ctx(self, player: int) -> dict:
        ctx = {
            "role": "landlord" if player == self.landlord else "farmer",
            "my_left": len(self.hands[player]),
            "target_owner": self.last_player,
        }
        if ctx["role"] == "farmer":
            ctx["teammate"] = 3 - player - self.landlord
            ctx["teammate_left"] = len(self.hands[ctx["teammate"]])
            ctx["landlord_left"] = len(self.hands[self.landlord])
            ctx["opp_min"] = ctx["landlord_left"]
        else:
            farmers = [p for p in range(3) if p != self.landlord]
            ctx["opp_min"] = min(len(self.hands[p]) for p in farmers)
        # 记牌：每张牌值还剩多少在外面（大师级 AI 用）
        ctx["remaining"] = {r: (1 if r >= RANK_JOKER_SMALL else 4) - self.played_ranks[r]
                            for r in range(3, RANK_JOKER_BIG + 1)}
        return ctx

    def bot_move(self, player: int) -> None:
        """机器人走一步（叫分或出牌）。"""
        if self.phase == PHASE_BIDDING:
            self.bid(player, ai.decide_bid(self.hands[player], self.bid_highest))
            return
        if self.phase == PHASE_PLAYING:
            ctx = self._ai_ctx(player)
            cards = ai.suggest(self.hands[player], self.last_combo, ctx)
            if cards is None:
                self.pass_turn(player)
            else:
                self.play(player, cards)
            return
        raise ValueError("对局已结束")

    def hint(self) -> dict:
        """给人类玩家的提示。"""
        if self.phase == PHASE_BIDDING:
            if self.turn != self.human:
                return {"kind": "wait"}
            return {"kind": "bid", "value": ai.decide_bid(self.hands[self.human], self.bid_highest)}
        if self.phase == PHASE_PLAYING:
            if self.turn != self.human:
                return {"kind": "wait"}
            ctx = self._ai_ctx(self.human)
            cards = ai.suggest(self.hands[self.human], self.last_combo, ctx)
            return {"kind": "play", "cards": cards or [], "pass": cards is None}
        return {"kind": "none"}

    # ------------------------------------------------------------------
    # 快照
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        d: dict = {
            "version": self.version,
            "phase": self.phase,
            "round_no": self.round_no,
            "deal_no": self.deal_no,
            "landlord": self.landlord,
            "bid": self.bid_points,
            "bid_highest": self.bid_highest,
            "bidder": self.bidder,
            "bid_event": self.bid_event,
            "starter": self.starter,
            "turn": self.turn,
            "human": self.human,
            "human_turn": self.phase in (PHASE_BIDDING, PHASE_PLAYING) and self.turn == self.human,
            "can_pass": (self.phase == PHASE_PLAYING and self.turn == self.human
                         and self.last_combo is not None and self.last_player != self.human),
            "must_beat": None if self.last_combo is None else {
                "type": self.last_combo.type,
                "main_rank": self.last_combo.main_rank,
                "length": self.last_combo.length,
                "label": self.last_combo.describe(),
            },
            "hands": {
                "0": [{"id": c, "rank": rank_of(c),
                       "suit": (c // 13) if c < 52 else None} for c in self.hands[0]],
            },
            "hand_counts": [len(h) for h in self.hands],
            "bottom_visible": self.landlord is not None,
            "bottom": [{"id": c, "rank": rank_of(c), "suit": (c // 13) if c < 52 else None}
                       for c in self.bottom],
            "last_plays": self.last_plays,
            "bombs_used": self.bombs_used,
            "rockets_used": self.rockets_used,
            "multiplier": 2 ** (self.bombs_used + self.rockets_used),
            "spring": self.spring,
            "anti_spring": self.anti_spring,
            "scores": list(self.scores),
            "round_scores": getattr(self, "round_scores", None),
            "winners": self.winners,
            "round_result": self.round_result,
            "plays_count": list(self.plays_count),
            "log": list(self.log[-8:]),
        }
        return d
