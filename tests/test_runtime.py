import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agentic_memory import config as config_module
from agentic_memory import runtime


class FakeEmbeddings:
    KEYWORDS = ("launch", "project", "memory", "anthropic")

    def embed_text(self, text: str):
        lower = str(text or "").lower()
        vector = [float(lower.count(keyword)) for keyword in self.KEYWORDS]
        if not any(vector):
            vector[0] = 1.0
        return vector


class RuntimeHelperTests(unittest.TestCase):
    def test_resolve_configured_api_key_precedence(self) -> None:
        with mock.patch.object(runtime, "_resolve_openclaw_env_value", return_value=("openclaw-env-key", "openclaw.env:OPENAI_API_KEY")) as openclaw_env:
            with mock.patch.object(runtime, "_resolve_openclaw_profile_api_key", return_value=("profile-key", "openclaw.auth:main")) as openclaw_profile:
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
                    value, source = runtime._resolve_configured_api_key("config-key", "OPENAI_API_KEY", "openai")
                    self.assertEqual((value, source), ("config-key", "config.api_key"))

                    value, source = runtime._resolve_configured_api_key("", "OPENAI_API_KEY", "openai")
                    self.assertEqual((value, source), ("env-key", "env:OPENAI_API_KEY"))

                with mock.patch.dict(os.environ, {}, clear=True):
                    value, source = runtime._resolve_configured_api_key("", "OPENAI_API_KEY", "openai")
                    self.assertEqual((value, source), ("openclaw-env-key", "openclaw.env:OPENAI_API_KEY"))

                openclaw_env.return_value = ("", "")
                with mock.patch.dict(os.environ, {}, clear=True):
                    value, source = runtime._resolve_configured_api_key("", "OPENAI_API_KEY", "openai")
                    self.assertEqual((value, source), ("profile-key", "openclaw.auth:main"))

                self.assertTrue(openclaw_profile.called)

    def test_resolve_gateway_config_uses_detected_gateway_token(self) -> None:
        app_config = config_module.Config(
            gateway=config_module.GatewayConfig(enabled=True, port=8400, token_env="OPENCLAW_GATEWAY_TOKEN", token="")
        )
        with mock.patch.object(runtime, "_detect_openclaw_gateway", return_value={"base_url": "http://127.0.0.1:18789", "token": "detected-token"}):
            with mock.patch.dict(os.environ, {}, clear=True):
                resolved = runtime._resolve_gateway_config(app_config)

        self.assertEqual(
            resolved,
            {"base_url": "http://127.0.0.1:8400", "token": "detected-token"},
        )


class MemoryStoreSmokeTests(unittest.TestCase):
    def _make_config(self, root: Path) -> config_module.Config:
        return config_module.Config(
            embedding=config_module.EmbeddingConfig(
                provider="openai",
                model="text-embedding-3-small",
                dimensions=4,
            ),
            storage=config_module.StorageConfig(
                vector_path=str(root / "vector"),
                db_path=str(root / "memory.db"),
                vault_path=str(root / "vault"),
            ),
        )

    def test_store_search_and_read_memory_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._make_config(Path(tmpdir))
            with mock.patch.object(runtime, "QdrantClient", None):
                store = runtime.MemoryStore(config, FakeEmbeddings())
                self.addCleanup(store.close)

                first = store.store_memory(
                    brain_key="assistant",
                    kind="note",
                    source="test",
                    title="Launch Plan",
                    content="The launch project needs a final memory test pass.",
                    importance=80,
                )
                duplicate = store.store_memory(
                    brain_key="assistant",
                    kind="note",
                    source="test",
                    title="Launch Plan",
                    content="The launch project needs a final memory test pass.",
                    importance=80,
                )

                self.assertEqual(first["id"], duplicate["id"])

                results = store.search_memories("assistant", "launch project", limit=5)
                self.assertGreaterEqual(len(results), 1)
                self.assertEqual(results[0]["id"], first["id"])

                note = store.read_vault_note("assistant", first["note_path"])
                self.assertIn("launch project", note["content"].lower())

                recent = store.recent_memories("assistant", limit=1)
                self.assertEqual(recent[0]["id"], first["id"])

    def test_read_vault_note_blocks_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._make_config(Path(tmpdir))
            with mock.patch.object(runtime, "QdrantClient", None):
                store = runtime.MemoryStore(config, FakeEmbeddings())
                self.addCleanup(store.close)

                with self.assertRaises(ValueError):
                    store.read_vault_note("assistant", "../outside.md")


if __name__ == "__main__":
    unittest.main()
