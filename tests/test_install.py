# -*- coding: utf-8 -*-
"""个人市场安装脚本回归测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import install_plugin


class InstallPluginTest(unittest.TestCase):
    def test_registers_marketplace_and_calls_current_cli_command(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(install_plugin, "home", return_value=td), \
                    mock.patch.object(install_plugin.shutil, "which",
                                      return_value="/usr/local/bin/codex"), \
                    mock.patch.object(install_plugin.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="{}", stderr="")
                install_plugin.upsert_marketplace()
                self.assertTrue(install_plugin.install_with_codex())

            with open(os.path.join(td, ".agents", "plugins", "marketplace.json"),
                      "r", encoding="utf-8") as f:
                marketplace = json.load(f)
            self.assertEqual(marketplace["plugins"][0]["name"], "doudizhu")
            run.assert_called_once_with(
                ["/usr/local/bin/codex", "plugin", "add", "doudizhu@personal", "--json"],
                capture_output=True, text=True,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
