import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agentic_memory import config as config_module


class ConfigLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        config_module._LOADED_ENV_FILES.clear()

    def tearDown(self) -> None:
        config_module._LOADED_ENV_FILES.clear()

    def test_load_env_file_parses_values_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                textwrap.dedent(
                    """
                    # comment
                    OPENAI_API_KEY="test-openai-key"
                    FEATURE_FLAG=yes
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertTrue(config_module.load_env_file(env_path))
                self.assertEqual(os.environ["OPENAI_API_KEY"], "test-openai-key")
                self.assertEqual(os.environ["FEATURE_FLAG"], "yes")
                self.assertFalse(config_module.load_env_file(env_path))

    def test_load_config_reads_dotenv_and_openclaw_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
            (root / "config.yaml").write_text(
                textwrap.dedent(
                    """
                    framework: "openclaw"
                    models:
                      primary:
                        provider: "openai"
                        model: "gpt-5.4"
                    brains:
                      - key: "ship"
                        name: "Ship"
                        description: "Release brain"
                    agents:
                      observer:
                        enabled: false
                    server:
                      port: 9901
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = config_module.load_config(str(root / "config.yaml"))
                self.assertEqual(os.environ["OPENAI_API_KEY"], "from-dotenv")

            self.assertEqual(loaded.framework, "openclaw")
            self.assertTrue(loaded.gateway.enabled)
            self.assertEqual(loaded.server_port, 9901)
            self.assertEqual(len(loaded.brains), 1)
            self.assertEqual(loaded.brains[0].key, "ship")
            self.assertFalse(loaded.agents.observer_enabled)


if __name__ == "__main__":
    unittest.main()
