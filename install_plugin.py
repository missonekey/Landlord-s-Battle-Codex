#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""斗地主 Codex 插件安装脚本（个人市场）。

1. 将插件目录复制到 ~/plugins/doudizhu
2. 在 ~/.agents/plugins/marketplace.json 中注册（或更新）doudizhu 条目
3. 打印使用说明

用法: python3 install_plugin.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PLUGIN_SRC = os.path.join(REPO_ROOT, "doudizhu")
PLUGIN_NAME = "doudizhu"


def home() -> str:
    return os.path.expanduser("~")


def plugin_dst() -> str:
    return os.path.join(home(), "plugins", PLUGIN_NAME)


def marketplace_path() -> str:
    return os.path.join(home(), ".agents", "plugins", "marketplace.json")


def copy_plugin() -> str:
    dst = plugin_dst()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(PLUGIN_SRC, dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def upsert_marketplace() -> None:
    path = marketplace_path()
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    else:
        data = {"name": "personal",
                "interface": {"displayName": "Personal"}}
    data.setdefault("name", "personal")
    data.setdefault("interface", {"displayName": "Personal"})
    plugins = data.setdefault("plugins", [])
    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": "./plugins/%s" % PLUGIN_NAME},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Games",
    }
    for i, p in enumerate(plugins):
        if isinstance(p, dict) and p.get("name") == PLUGIN_NAME:
            plugins[i] = entry
            break
    else:
        plugins.append(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def install_with_codex() -> bool:
    """让当前 Codex CLI 真正登记为已安装，而不只是在市场中可见。"""
    codex = shutil.which("codex")
    if not codex:
        print("提示：未找到 codex CLI。插件文件与个人市场已准备好，")
        print("请在 Codex 的 Plugins Directory 中选择 Personal 后点击安装。")
        return False
    result = subprocess.run(
        [codex, "plugin", "add", "%s@personal" % PLUGIN_NAME, "--json"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    combined = (result.stdout + "\n" + result.stderr).lower()
    if "already installed" in combined or "已安装" in combined:
        return True
    print("提示：Codex CLI 安装登记未完成：%s" %
          (result.stderr.strip() or result.stdout.strip() or "未知错误"))
    print("请在 Codex 的 Plugins Directory 中选择 Personal 后点击安装。")
    return False


def main() -> None:
    if not os.path.isdir(PLUGIN_SRC):
        print("错误：找不到插件源码目录 %s" % PLUGIN_SRC)
        sys.exit(1)
    dst = copy_plugin()
    upsert_marketplace()
    registered = install_with_codex()
    print("=" * 52)
    print(" 斗地主插件文件已安装%s！" % ("并已登记到 Codex" if registered else ""))
    print(" 插件位置: %s" % dst)
    print(" 市场条目: %s" % marketplace_path())
    print("=" * 52)
    print("")
    print("使用方式：")
    print("  1. 打开 Codex，输入：玩斗地主 / 启动斗地主游戏")
    print("     （或直接说“我想打斗地主”）")
    print("  2. Codex 会运行 python3 scripts/start_game.py 并在内置浏览器打开")
    print("     （命令立即返回；服务器在后台运行）")
    print("")
    print("停止服务器：")
    print("  python3 %s/scripts/stop_game.py" % dst)
    print("")
    print("发布给他人使用：")
    print("  本仓库根目录自带 .agents/plugins/marketplace.json（仓库级市场），")
    print("  推送到 GitHub 后，他人执行：")
    print("    codex plugin marketplace add <仓库地址>")
    print("    codex plugin add doudizhu@doudizhu-marketplace")
    print("")
    print("验证安装：")
    print("  codex plugin list        # 应能看到 doudizhu")
    print("  ls ~/plugins/doudizhu    # 插件文件")
    print("")
    print("手动启动（不经过 Codex）：")
    print("  python3 ~/plugins/doudizhu/scripts/start_game.py")


if __name__ == "__main__":
    main()
