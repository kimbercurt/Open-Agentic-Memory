"""
Configuration loader for Open Agentic Memory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class ModelConfig:
    provider: str = "openai"
    model: str = "gpt-5.4"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = ""
    thinking: str = "high"

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


@dataclass
class EmbeddingConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    api_key_env: str = "OPENAI_API_KEY"
    endpoint: str = ""
    dimensions: int = 1536
    note: str = ""

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


@dataclass
class StorageConfig:
    vector_backend: str = "qdrant"
    vector_path: str = "./data/vector"
    db_backend: str = "sqlite"
    db_path: str = "./data/memory.db"
    vault_path: str = "./data/vault"


@dataclass
class BrainConfig:
    key: str = "assistant"
    name: str = "Assistant"
    description: str = "Primary AI assistant"


@dataclass
class AgentConfig:
    recall_enabled: bool = True
    recall_timeout: int = 90
    recall_merge_limit: int = 8
    observer_enabled: bool = True
    observer_interval: int = 900
    observer_min_messages: int = 3
    observer_max_per_cycle: int = 10
    gate_enabled: bool = True
    gate_timeout: int = 15
    scouts_enabled: bool = True
    scouts_timeout: int = 45


@dataclass
class Config:
    primary_model: ModelConfig = field(default_factory=ModelConfig)
    fast_model: ModelConfig = field(default_factory=lambda: ModelConfig(model="gpt-5.3-codex-spark"))
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    brains: List[BrainConfig] = field(default_factory=lambda: [BrainConfig()])
    agents: AgentConfig = field(default_factory=AgentConfig)
    framework: str = "standalone"
    server_host: str = "127.0.0.1"
    server_port: int = 8400


def load_config(path: str = "config.yaml") -> Config:
    """Load configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    models = raw.get("models", {})
    primary = models.get("primary", {})
    fast = models.get("fast", {})
    emb = raw.get("embedding", {})
    store = raw.get("storage", {})
    vector = store.get("vector", {})
    db = store.get("database", {})
    vault = store.get("vault", {})
    agent_cfg = raw.get("agents", {})
    recall = agent_cfg.get("recall", {})
    observer = agent_cfg.get("observer", {})
    gate = agent_cfg.get("gate", {})
    scouts = agent_cfg.get("scouts", {})
    server = raw.get("server", {})

    brains = []
    for b in raw.get("brains", [{"key": "assistant", "name": "Assistant"}]):
        brains.append(BrainConfig(
            key=b.get("key", "assistant"),
            name=b.get("name", "Assistant"),
            description=b.get("description", ""),
        ))

    return Config(
        primary_model=ModelConfig(
            provider=primary.get("provider", "openai"),
            model=primary.get("model", "gpt-5.4"),
            api_key_env=primary.get("api_key_env", "OPENAI_API_KEY"),
            base_url=primary.get("base_url", ""),
        ),
        fast_model=ModelConfig(
            provider=fast.get("provider", "openai"),
            model=fast.get("model", "gpt-5.3-codex-spark"),
            api_key_env=fast.get("api_key_env", "OPENAI_API_KEY"),
            base_url=fast.get("base_url", ""),
            thinking=fast.get("thinking", "high"),
        ),
        embedding=EmbeddingConfig(
            provider=emb.get("provider", "openai"),
            model=emb.get("model", "text-embedding-3-small"),
            api_key_env=emb.get("api_key_env", "OPENAI_API_KEY"),
            endpoint=emb.get("endpoint", ""),
            dimensions=emb.get("dimensions", 1536),
            note=emb.get("note", ""),
        ),
        storage=StorageConfig(
            vector_backend=vector.get("backend", "qdrant"),
            vector_path=vector.get("path", "./data/vector"),
            db_backend=db.get("backend", "sqlite"),
            db_path=db.get("path", "./data/memory.db"),
            vault_path=vault.get("path", "./data/vault"),
        ),
        brains=brains,
        agents=AgentConfig(
            recall_enabled=recall.get("enabled", True),
            recall_timeout=recall.get("timeout_seconds", 90),
            recall_merge_limit=recall.get("merge_limit", 8),
            observer_enabled=observer.get("enabled", True),
            observer_interval=observer.get("interval_seconds", 900),
            observer_min_messages=observer.get("min_messages", 3),
            observer_max_per_cycle=observer.get("max_observations_per_cycle", 10),
            gate_enabled=gate.get("enabled", True),
            gate_timeout=gate.get("timeout_seconds", 15),
            scouts_enabled=scouts.get("enabled", True),
            scouts_timeout=scouts.get("timeout_seconds", 45),
        ),
        framework=raw.get("framework", "standalone"),
        server_host=server.get("host", "127.0.0.1"),
        server_port=server.get("port", 8400),
    )
