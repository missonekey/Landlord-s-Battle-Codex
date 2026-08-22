#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯标准库生成插件图标 PNG（icon.png / logo.png）——无任何第三方依赖。

用数学函数手绘：墨绿圆角底 + 白卡 + 红桃/黑桃/梅花 + 金色点缀。
用法: python3 make_icon.py [输出目录]
"""
from __future__ import annotations

import math
import os
import struct
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "assets")


# ---------------------------------------------------------------------------
# 最小 PNG 写入器
# ---------------------------------------------------------------------------

def write_png(path: str, w: int, h: int, pixels) -> None:
    """pixels: 每像素 (r, g, b, a) 的列表，行优先。"""
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter: None
        for x in range(w):
            r, g, b, a = (int(round(v)) for v in pixels[y * w + x])
            raw += bytes((max(0, min(255, r)), max(0, min(255, g)),
                          max(0, min(255, b)), max(0, min(255, a))))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------------------
# 形状函数（局部坐标，y 向上，范围约 [-1, 1]）
# ---------------------------------------------------------------------------

def inside_heart(x: float, y: float) -> bool:
    # 经典心形隐式曲线
    return (x * x + y * y - 1.0) ** 3 - x * x * y * y * y <= 0.0


def inside_spade(x: float, y: float) -> bool:
    # 黑桃 = 倒置的心 + 底部三角柄
    if (x * x + y * y - 1.0) ** 3 + x * x * y * y * y <= 0.0 and y <= 0.05:
        return True
    if 0.05 <= y <= 1.05:
        half = 0.30 * (1.0 - (y - 0.05) / 1.0) + 0.06
        if abs(x) <= half:
            return True
    return False


def inside_club(x: float, y: float) -> bool:
    # 梅花 = 三圆 + 柄
    for cx, cy, r in ((-0.34, 0.30, 0.34), (0.34, 0.30, 0.34), (0.0, 0.62, 0.34)):
        if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
            return True
    if -0.05 <= y <= 0.75:
        half = 0.14 * (1.0 - (y + 0.05) / 0.8) + 0.04
        if abs(x) <= half:
            return True
    return False


def inside_rounded_rect(x: float, y: float, w: float, h: float, r: float) -> bool:
    x, y = abs(x), abs(y)
    if x > w / 2 or y > h / 2:
        return False
    if x <= w / 2 - r or y <= h / 2 - r:
        return True
    return (x - (w / 2 - r)) ** 2 + (y - (h / 2 - r)) ** 2 <= r * r


def rot(x: float, y: float, ang: float):
    c, s = math.cos(ang), math.sin(ang)
    return x * c - y * s, x * s + y * c


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# 图标绘制
# ---------------------------------------------------------------------------

def draw_icon(size: int, fan: bool) -> list:
    """size: 边长；fan: 三张扇形（logo）或单张（icon）。"""
    px = []
    cx = cy = size / 2
    for y in range(size):
        for x in range(size):
            u = (x + 0.5 - cx) / (size / 2)   # [-1, 1]
            v = (cy - (y + 0.5)) / (size / 2)  # [-1, 1]，y 向上

            # 背景：墨绿圆角方
            if not inside_rounded_rect(u, v, 2.0, 2.0, 0.30):
                px.append((0, 0, 0, 0))
                continue
            bg = lerp(0x17, 0x0a, (v + 1) / 2)  # 上浅下深
            r, g, b = bg, lerp(0x7a, 0x49, (v + 1) / 2), lerp(0x45, 0x29, (v + 1) / 2)

            if fan:
                # 三张卡片：-22° / 0° / 22°，黑桃·红桃·黑桃
                cards = [(-0.30, -0.28, 0.58, 0.82, "S", 0.92),
                         (0.0, 0.06, 0.58, 0.82, "H", 1.0),
                         (0.30, -0.28, 0.58, 0.82, "S", 0.92)]
                color = None
                for ox, oy, cw, ch, shape, alpha in cards:
                    lx, ly = u - ox, v - oy
                    lx, ly = rot(lx, ly, 0.0)
                    if not inside_rounded_rect(lx, ly, cw, ch, 0.05):
                        continue
                    # 卡片面
                    if not inside_rounded_rect(lx, ly, cw - 0.06, ch - 0.06, 0.04):
                        continue
                    sx, sy = lx / (cw * 0.5 * 0.42), ly / (ch * 0.5 * 0.42)
                    if shape == "H" and inside_heart(sx, sy):
                        color = (0xD0, 0x34, 0x2C)
                    elif shape == "S" and inside_spade(sx, sy):
                        color = (0x20, 0x24, 0x2B)
                    if color:
                        break
                if color:
                    px.append(color + (255,))
                else:
                    px.append((0xFF, 0xFF, 0xFF, 255))
                continue

            # 单张卡片（icon）：白卡 + 红桃（卡面占画布约一半）
            cw, ch = 0.96, 1.34
            if inside_rounded_rect(u, v + 0.03, cw, ch, 0.07):
                if inside_rounded_rect(u, v + 0.03, cw - 0.05, ch - 0.05, 0.06):
                    sx = u / (cw * 0.5 * 0.42)
                    sy = (v + 0.03) / (ch * 0.5 * 0.42)
                    if inside_heart(sx, sy + 0.10):
                        px.append((0xD0, 0x34, 0x2C, 255))
                    else:
                        px.append((0xFF, 0xFF, 0xFF, 255))
                else:
                    px.append((0xC9, 0xCD, 0xD4, 255))
            else:
                # 金色小圆点装饰
                if (u + 0.58) ** 2 + (v - 0.62) ** 2 <= 0.05 ** 2:
                    px.append((0xFF, 0xD7, 0x6A, 255))
                else:
                    px.append((r, g, b, 255))
    return px


def main() -> None:
    out = os.path.abspath(OUT_DIR)
    os.makedirs(out, exist_ok=True)
    write_png(os.path.join(out, "icon.png"), 256, 256, draw_icon(256, fan=False))
    write_png(os.path.join(out, "logo.png"), 512, 512, draw_icon(512, fan=True))
    print("icons written to %s" % out)


if __name__ == "__main__":
    main()
