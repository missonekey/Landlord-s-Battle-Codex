# -*- coding: utf-8 -*-
"""生成 JS 冒烟测试用的真实对局快照（bidding / playing / over 三阶段）。"""
from __future__ import annotations

import json
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_GAME_DIR = os.path.normpath(os.path.join(_TEST_DIR, os.pardir, "doudizhu", "game"))
if _GAME_DIR not in sys.path:
    sys.path.insert(0, _GAME_DIR)

from engine import Game  # noqa: E402


def make_snapshots(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    # 1) 叫分阶段（轮到人类）
    g = Game(seed=100)
    g.bot_move(g.turn)
    g.bot_move(g.turn)
    if g.turn == 0 and g.phase == "bidding":
        s = g.snapshot()
    else:
        # 强制：无论轮到谁，直接构造人类回合的叫分快照
        s = g.snapshot()
        s["turn"] = 0
        s["human_turn"] = True
        s["phase"] = "bidding"
    s["settings"] = {"bot_delay_ms": 900, "show_counter": True, "auto_pilot": False}
    with open(os.path.join(out_dir, "bidding.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)

    # 2) 出牌阶段：真实推进到「轮到人类跟牌」（can_pass=True）的状态
    import ai  # noqa: F401
    g2 = None
    for attempt in range(60):
        g2 = Game(seed=200 + attempt)
        guard = 0
        while g2.phase != "round_over" and guard < 3000:
            if g2.phase == "bidding":
                if g2.turn == 0:
                    g2.bid(0, 3 if g2.bid_highest < 3 else 0)
                else:
                    g2.bot_move(g2.turn)
            else:
                if g2.turn == 0 and g2.last_combo is not None and g2.last_player != 0:
                    break  # 轮到人类跟牌：可以出牌也可以不出
                if g2.turn == 0:
                    ctx = g2._ai_ctx(0)
                    cards = ai.suggest(g2.hands[0], g2.last_combo, ctx)
                    if cards is None:
                        g2.pass_turn(0)
                    else:
                        g2.play(0, cards)
                else:
                    g2.bot_move(g2.turn)
            guard += 1
        if (g2.phase == "playing" and g2.turn == 0
                and g2.last_combo is not None and g2.last_player != 0
                and len(g2.hands[0]) >= 8):
            break  # 手牌充足，供框选/多选测试使用
    assert g2 is not None and g2.phase == "playing" and g2.turn == 0, "无法构造跟牌状态"
    s2 = g2.snapshot()
    assert s2["can_pass"] is True, "playing 快照应允许不出"
    s2["settings"] = {"bot_delay_ms": 900, "show_counter": True, "auto_pilot": False}
    with open(os.path.join(out_dir, "playing.json"), "w", encoding="utf-8") as f:
        json.dump(s2, f, ensure_ascii=False)

    # 3) 结算阶段
    g3 = Game(seed=300)
    guard = 0
    while g3.phase != "round_over" and guard < 3000:
        g3.bot_move(g3.turn)
        guard += 1
    s3 = g3.snapshot()
    s3["settings"] = {"bot_delay_ms": 900, "show_counter": True, "auto_pilot": False}
    with open(os.path.join(out_dir, "over.json"), "w", encoding="utf-8") as f:
        json.dump(s3, f, ensure_ascii=False)
    print("snapshots written to", out_dir)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TEST_DIR, "snapshots")
    make_snapshots(out)
