"""冒烟测试：不需要微信在跑，也不需要密钥。

覆盖：包能导入、配置解析、CLI 子命令齐、pipeline 模块存在。
只用标准库（unittest），所以 `python3 -m unittest` 就能跑，不需要装 pytest。

    PYTHONPATH=src python3 -m unittest discover -s tests -v
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import wxr  # noqa: E402
from wxr import config  # noqa: E402


class ConfigCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(config._CACHE.update, cfg=None, path=None)
        for k in ("WXR_CONFIG", "WXR_ACCOUNT", "WXR_DB_KEY", "WXR_STATE"):
            os.environ.pop(k, None)
        config._CACHE.update(cfg=None, path=None)

    def test_env_override(self):
        os.environ["WXR_CONFIG"] = os.path.join(self.tmp.name, "c.json")
        os.environ["WXR_ACCOUNT"] = "wxid_test"
        os.environ["WXR_DB_KEY"] = "ab" * 32
        config._CACHE.update(cfg=None, path=None)
        self.assertEqual(config.account(), "wxid_test")
        self.assertEqual(config.key(), "ab" * 32)
        self.assertEqual(config.dbdir().name, "db_storage")
        self.assertTrue(str(config.dbdir()).endswith("xwechat_files/wxid_test/db_storage"))

    def test_missing_config_gives_hint(self):
        os.environ["WXR_CONFIG"] = os.path.join(self.tmp.name, "none.json")
        config._CACHE.update(cfg=None, path=None)
        with self.assertRaises(SystemExit) as ctx:
            config.account()
        self.assertIn("wxr init", str(ctx.exception))


class LayoutCase(unittest.TestCase):
    def test_version(self):
        self.assertTrue(wxr.__version__)

    def test_import_every_module(self):
        for name in ("wx", "zstd", "core", "llm", "notify", "watcher", "daily",
                     "autoreply", "digest", "chatquery", "make_skill", "cli"):
            __import__(f"wxr.{name}")
        __import__("wxr.web.server")

    def test_pipelines_exist(self):
        for name in ("export", "build_export", "gen_html", "gen_moments",
                     "serve", "persona_build", "persona_gen", "viz"):
            self.assertTrue((SRC / "wxr/pipeline" / f"{name}.py").exists(), name)

    def test_assets(self):
        self.assertTrue((SRC / "wxr/web/ui.html").exists())
        self.assertTrue((SRC / "wxr/templates/skill.example.md").exists())


class CliCase(unittest.TestCase):
    def test_help_lists_commands(self):
        env = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}
        out = subprocess.run([sys.executable, "-m", "wxr.cli", "--help"],
                             capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        for cmd in ("init", "status", "chats", "messages", "search", "export",
                    "html", "persona", "ask", "digest", "skill", "web"):
            self.assertIn(cmd, out.stdout)

    def test_status_without_config(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["WXR_CONFIG"] = os.path.join(tmp.name, "none.json")
        for k in ("WXR_ACCOUNT", "WXR_DB_KEY"):
            os.environ.pop(k, None)
        config._CACHE.update(cfg=None, path=None)
        from wxr.cli import main
        self.assertEqual(main(["status"]), 0)
        config._CACHE.update(cfg=None, path=None)


if __name__ == "__main__":
    unittest.main()
