"""
Runtime services for Open Agentic Memory.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import warnings
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from .config import Config, EmbeddingConfig, ModelConfig

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        Range,
        VectorParams,
    )
except ImportError:  # pragma: no cover - setup installs dependency
    QdrantClient = None  # type: ignore[assignment]
    Distance = FieldCondition = Filter = MatchValue = PointStruct = Range = VectorParams = None  # type: ignore[assignment]


PROMPT_DIR = Path(__file__).resolve().parents[2] / "agents"
DEFAULT_COLLECTION = "oam_memories"
OPENCLAW_STATE_DIR = Path.home() / ".openclaw"
OPENCLAW_CONFIG_PATH = OPENCLAW_STATE_DIR / "openclaw.json"
OPENCLAW_MAIN_AUTH_PROFILES_PATH = OPENCLAW_STATE_DIR / "agents" / "main" / "agent" / "auth-profiles.json"
OPENCLAW_WORKSPACES_DIR = OPENCLAW_STATE_DIR / "workspaces"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def truncate(text: str, limit: int = 80) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None

    candidates = [raw]
    fence = re.findall(r"```json\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    candidates.extend(fence)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            parsed = json.loads(raw[first : last + 1])
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def hash_embedding(text: str, dimensions: int) -> List[float]:
    if dimensions <= 0:
        return []
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9_]+", str(text or "").lower())
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[idx] += sign * weight

    magnitude = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / magnitude, 8) for v in vector]


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    vec_a = list(a)
    vec_b = list(b)
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(x * x for x in vec_a)) or 1.0
    mag_b = math.sqrt(sum(y * y for y in vec_b)) or 1.0
    return dot / (mag_a * mag_b)


def parse_iso_date(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:19]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "memory"


def _urlopen_json(url: str, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 60) -> Dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST" if payload is not None else "GET")
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    if not data:
        return {}
    parsed = json.loads(data.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _normalize_provider(provider: str) -> str:
    clean = str(provider or "").strip().lower()
    if clean == "google":
        return "gemini"
    return clean or "openai"


def _provider_api_key_env(provider: str) -> str:
    normalized = _normalize_provider(provider)
    mapping = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "voyage": "VOYAGE_API_KEY",
        "xai": "XAI_API_KEY",
        "openai-compatible": "OPENAI_API_KEY",
        "custom": "OPENAI_API_KEY",
    }
    env_name = mapping.get(normalized, "")
    if not env_name:
        warnings.warn(f"Unknown provider '{provider}' has no default API key environment mapping.")
        return "API_KEY"
    return env_name


def _provider_api_key_env_candidates(provider: str, api_key_env: str = "") -> List[str]:
    names: List[str] = []
    explicit = str(api_key_env or "").strip()
    if explicit:
        names.append(explicit)

    default_env = _provider_api_key_env(provider)
    if default_env and default_env not in names:
        names.append(default_env)

    if _normalize_provider(provider) == "gemini":
        for extra in ("GOOGLE_API_KEY",):
            if extra not in names:
                names.append(extra)

    return names


def _normalize_reasoning_level(level: str) -> str:
    clean = str(level or "").strip().lower()
    mapping = {
        "low": "low",
        "med": "medium",
        "mid": "medium",
        "medium": "medium",
        "high": "high",
        "max": "max",
        "xhigh": "max",
    }
    return mapping.get(clean, "")


def _openai_reasoning_effort(level: str) -> str:
    normalized = _normalize_reasoning_level(level)
    if normalized == "medium":
        return "medium"
    if normalized == "high":
        return "high"
    if normalized == "max":
        return "high"
    if normalized == "low":
        return "low"
    return ""


def _anthropic_thinking_budget(level: str) -> int:
    normalized = _normalize_reasoning_level(level)
    mapping = {
        "low": 4000,
        "medium": 8000,
        "high": 12000,
        "max": 16000,
    }
    return mapping.get(normalized, 0)


def _openclaw_provider_aliases(provider: str) -> List[str]:
    normalized = _normalize_provider(provider)
    aliases = {
        "anthropic": ["anthropic"],
        "openai": ["openai"],
        "openrouter": ["openrouter"],
        "gemini": ["gemini", "google"],
        "mistral": ["mistral"],
        "voyage": ["voyage"],
        "xai": ["xai"],
    }
    return aliases.get(normalized, [normalized] if normalized else [])


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_openclaw_config_json() -> Dict[str, Any]:
    return _load_json_file(OPENCLAW_CONFIG_PATH)


def _find_openclaw_auth_profiles_path() -> Optional[Path]:
    if OPENCLAW_MAIN_AUTH_PROFILES_PATH.exists():
        return OPENCLAW_MAIN_AUTH_PROFILES_PATH

    agents_root = OPENCLAW_STATE_DIR / "agents"
    if not agents_root.exists():
        return None
    for path in agents_root.glob("*/agent/auth-profiles.json"):
        if path.exists():
            return path
    return None


def _load_openclaw_auth_profiles() -> Dict[str, Any]:
    path = _find_openclaw_auth_profiles_path()
    if path is None:
        return {}
    return _load_json_file(path)


def _resolve_openclaw_env_value(env_name: str) -> Tuple[str, str]:
    clean_name = str(env_name or "").strip()
    if not clean_name:
        return "", ""
    cfg = _load_openclaw_config_json()
    env_block = cfg.get("env", {}) if isinstance(cfg.get("env"), dict) else {}
    value = str(env_block.get(clean_name, "") or "").strip()
    if value:
        return value, f"openclaw.env:{clean_name}"
    return "", ""


def _extract_openclaw_profile_secret(profile: Dict[str, Any]) -> str:
    for field in ("token", "apiKey", "access", "password"):
        value = str(profile.get(field, "") or "").strip()
        if value:
            return value
    return ""


def _resolve_openclaw_profile_api_key(provider: str) -> Tuple[str, str]:
    aliases = set(_openclaw_provider_aliases(provider))
    if not aliases:
        return "", ""

    auth_payload = _load_openclaw_auth_profiles()
    profiles = auth_payload.get("profiles", {}) if isinstance(auth_payload.get("profiles"), dict) else {}
    if not profiles:
        return "", ""

    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        profile_provider = _normalize_provider(profile.get("provider", ""))
        if profile_provider not in aliases:
            continue
        secret = _extract_openclaw_profile_secret(profile)
        if secret:
            return secret, f"openclaw.auth:{profile_name}"
    return "", ""


def _resolve_configured_api_key(explicit_key: str, api_key_env: str, provider: str) -> Tuple[str, str]:
    clean_key = str(explicit_key or "").strip()
    if clean_key:
        return clean_key, "config.api_key"

    for env_name in _provider_api_key_env_candidates(provider, api_key_env):
        env_value = str(os.environ.get(env_name, "") or "").strip()
        if env_value:
            return env_value, f"env:{env_name}"

        openclaw_env_value, openclaw_env_source = _resolve_openclaw_env_value(env_name)
        if openclaw_env_value:
            return openclaw_env_value, openclaw_env_source

    profile_value, profile_source = _resolve_openclaw_profile_api_key(provider)
    if profile_value:
        return profile_value, profile_source

    return "", ""


def _resolve_gateway_config(app_config: Optional[Config] = None) -> Optional[Dict[str, str]]:
    if app_config is not None and getattr(app_config, "gateway", None) is not None:
        gateway_cfg = app_config.gateway
        if not bool(getattr(gateway_cfg, "enabled", False)):
            return None
        base_url = str(gateway_cfg.base_url or "").strip().rstrip("/")
        port = int(getattr(gateway_cfg, "port", 0) or 0)
        if not base_url and port > 0:
            base_url = f"http://127.0.0.1:{port}"
        token = str(gateway_cfg.token or "").strip()
        token_env = str(gateway_cfg.token_env or "").strip()
        if not token and token_env:
            token = str(os.environ.get(token_env, "") or "").strip()
        if base_url:
            return {"base_url": base_url, "token": token}

    cfg = _load_openclaw_config_json()
    gateway = cfg.get("gateway", {}) if isinstance(cfg.get("gateway"), dict) else {}
    auth = gateway.get("auth", {}) if isinstance(gateway.get("auth"), dict) else {}
    http_endpoints = gateway.get("http", {}).get("endpoints", {}) if isinstance(gateway.get("http"), dict) else {}
    port = gateway.get("port") or 0
    if not port or not http_endpoints.get("chatCompletions", {}).get("enabled"):
        return None

    token = (
        os.environ.get("OPENCLAW_GATEWAY_TOKEN")
        or os.environ.get("OPENCLAW_GATEWAY_PASSWORD")
        or str(auth.get("token", "") or "")
        or str(auth.get("password", "") or "")
    ).strip()
    return {
        "base_url": f"http://127.0.0.1:{port}",
        "token": token,
    }


def _call_openclaw_gateway_model(messages: List[Dict[str, str]], model: str, gateway: Dict[str, str], thinking: str = "") -> str:
    base_url = str(gateway.get("base_url", "") or "").rstrip("/")
    token = str(gateway.get("token", "") or "").strip()
    payload: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 2000}
    if thinking:
        payload["thinking"] = thinking
        payload["reasoning_effort"] = thinking
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = _urlopen_json(
        f"{base_url}/v1/chat/completions",
        body=payload,
        headers=headers,
        timeout=90,
    )
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", "") or "")


def _prefer_gateway_transport(app_config: Optional[Config]) -> bool:
    if app_config is None or getattr(app_config, "gateway", None) is None:
        return False
    if str(getattr(app_config, "framework", "") or "").strip().lower() == "openclaw":
        return False
    return bool(getattr(app_config.gateway, "prefer_for_models", False))


def call_model_text(
    model_cfg: ModelConfig,
    messages: List[Dict[str, str]],
    thinking: str = "",
    app_config: Optional[Config] = None,
) -> str:
    provider = _normalize_provider(model_cfg.provider or "openai")
    model = str(model_cfg.model or "gpt-5.4").strip()
    base_url = str(model_cfg.base_url or "").strip()
    gateway = _resolve_gateway_config(app_config)
    gateway_preferred = bool(gateway and _prefer_gateway_transport(app_config))
    reasoning_level = _normalize_reasoning_level(thinking)

    if gateway_preferred:
        try:
            gateway_reply = _call_openclaw_gateway_model(messages, model, gateway, thinking=thinking)
            if gateway_reply:
                return gateway_reply
        except Exception:
            pass

    api_key, api_source = _resolve_configured_api_key(model_cfg.api_key, model_cfg.api_key_env, provider)

    try:
        if provider in ("openai", "openrouter", "mistral", "openai-compatible", "custom"):
            endpoint = base_url or (
                "https://api.openai.com/v1" if provider == "openai"
                else "https://openrouter.ai/api/v1" if provider == "openrouter"
                else "https://api.mistral.ai/v1" if provider == "mistral"
                else "https://api.openai.com/v1"
            )
            if not api_key:
                return f"Error calling model: missing API key for provider {provider}."
            payload: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 2000}
            reasoning_effort = _openai_reasoning_effort(reasoning_level)
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
            data = _urlopen_json(
                f"{endpoint.rstrip('/')}/chat/completions",
                body=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=90,
            )
            return str(data.get("choices", [{}])[0].get("message", {}).get("content", "") or "")

        if provider == "anthropic":
            if not api_key:
                return "Error calling model: missing API key for provider anthropic."
            endpoint = (base_url or "https://api.anthropic.com").rstrip("/")
            system_text = ""
            chat_messages: List[Dict[str, str]] = []
            for message in messages:
                if message.get("role") == "system":
                    system_text = str(message.get("content", ""))
                else:
                    chat_messages.append({
                        "role": str(message.get("role", "user")),
                        "content": str(message.get("content", "")),
                    })
            payload: Dict[str, Any] = {
                "model": model,
                "max_tokens": 2000,
                "system": system_text,
                "messages": chat_messages,
            }
            thinking_budget = _anthropic_thinking_budget(reasoning_level)
            if thinking_budget > 0:
                payload["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
                payload["max_tokens"] = max(4096, thinking_budget + 2000)
            data = _urlopen_json(
                f"{endpoint}/v1/messages",
                body=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=90,
            )
            chunks = data.get("content", [])
            if isinstance(chunks, list):
                return "".join(str(chunk.get("text", "")) for chunk in chunks if isinstance(chunk, dict))
            return ""

        if provider == "ollama":
            endpoint = base_url or "http://localhost:11434"
            data = _urlopen_json(
                f"{endpoint.rstrip('/')}/api/chat",
                body={"model": model, "messages": messages, "stream": False},
                timeout=120,
            )
            return str(data.get("message", {}).get("content", "") or "")

        return f"Error calling model: unsupported provider '{provider}'."
    except Exception as exc:  # pragma: no cover - network dependent
        if gateway_preferred:
            try:
                gateway_reply = _call_openclaw_gateway_model(messages, model, gateway, thinking=thinking)
                if gateway_reply:
                    return gateway_reply
            except Exception:
                pass
        if api_source:
            return f"Error calling model: {exc} (auth source: {api_source})"
        return f"Error calling model: {exc}"


class OpenClawMemoryBridge:
    def __init__(self, config: Config):
        self.config = config
        self.last_error: str = ""

    def canonical_agent_id(self, brain_key: str) -> str:
        return f"{brain_key}-recall-facts"

    def _load_openclaw_config(self) -> Dict[str, Any]:
        if not OPENCLAW_CONFIG_PATH.exists():
            return {}
        try:
            raw = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _gateway_settings(self) -> Tuple[Optional[str], Optional[str]]:
        if getattr(self.config, "gateway", None) is not None:
            gateway_cfg = self.config.gateway
            if not bool(getattr(gateway_cfg, "enabled", False)):
                return None, None
            port = int(getattr(gateway_cfg, "port", 0) or 0)
            token = str(getattr(gateway_cfg, "token", "") or "").strip()
            token_env = str(getattr(gateway_cfg, "token_env", "") or "").strip()
            if not token and token_env:
                token = str(os.environ.get(token_env, "") or "").strip()
            if port:
                return str(port), token or None

        cfg = self._load_openclaw_config()
        gateway = cfg.get("gateway", {}) if isinstance(cfg.get("gateway"), dict) else {}
        auth = gateway.get("auth", {}) if isinstance(gateway.get("auth"), dict) else {}
        port = gateway.get("port") or 18789
        token = (
            os.environ.get("OPENCLAW_GATEWAY_TOKEN")
            or os.environ.get("OPENCLAW_GATEWAY_PASSWORD")
            or auth.get("token")
            or auth.get("password")
            or ""
        )
        return str(port), str(token)

    def _agent_workspace(self, agent_id: str) -> Path:
        cfg = self._load_openclaw_config()
        agents = cfg.get("agents", {}) if isinstance(cfg.get("agents"), dict) else {}
        agent_list = agents.get("list", []) if isinstance(agents.get("list"), list) else []
        for entry in agent_list:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("id", "")).strip() != agent_id:
                continue
            workspace = str(entry.get("workspace", "")).strip()
            if workspace:
                return Path(workspace).expanduser()
        return OPENCLAW_WORKSPACES_DIR / agent_id

    def mirror_memory_file(
        self,
        brain_key: str,
        kind: str,
        source: str,
        title: str,
        content: str,
        importance: int,
        created_at: str,
        fingerprint: str,
    ) -> Optional[str]:
        agent_id = self.canonical_agent_id(brain_key)
        workspace = self._agent_workspace(agent_id)
        folder_map = {
            "observed_fact": "facts",
            "observed_pattern": "patterns",
            "observed_relationship": "relationships",
            "chat_turn": "daily",
            "note": "notes",
            "decision": "decisions",
            "project_context": "projects",
        }
        folder = folder_map.get(kind, "notes")
        path = workspace / "memory" / folder / f"{slugify(title)}-{fingerprint[:8]}.md"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(
                    "\n".join(
                        [
                            "---",
                            f'title: "{title.replace(chr(34), chr(39))}"',
                            f"kind: {kind}",
                            f"source: {source}",
                            f"importance: {importance}",
                            f"created_at: {created_at}",
                            "---",
                            "",
                            f"# {title}",
                            "",
                            str(content or "").strip(),
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
            return str(path.relative_to(workspace))
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def _invoke_tool(self, tool: str, args: Dict[str, Any], brain_key: str) -> Dict[str, Any]:
        port, token = self._gateway_settings()
        if not port:
            raise RuntimeError("OpenClaw gateway port is not configured")

        payload = {
            "tool": tool,
            "args": args,
            "sessionKey": f"agent:{self.canonical_agent_id(brain_key)}:main",
        }
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = _urlopen_json(
            f"http://127.0.0.1:{port}/tools/invoke",
            body=payload,
            headers=headers,
            timeout=30,
        )
        if not data.get("ok", True):
            error = data.get("error", {})
            raise RuntimeError(str(error.get("message") or error or "OpenClaw tool invoke failed"))
        result = data.get("result", {})
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"items": result}
        return {}

    def search_memories(self, brain_key: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        self.last_error = ""
        try:
            result = self._invoke_tool(
                "memory_search",
                {
                    "query": str(query or "").strip(),
                    "maxResults": max(1, int(limit)),
                },
                brain_key=brain_key,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return []

        raw_items = []
        for key in ("items", "results", "hits", "matches", "memories"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                raw_items = candidate
                break
        if not raw_items and isinstance(result.get("data"), list):
            raw_items = result["data"]

        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("file") or item.get("note_path") or "").strip()
            snippet = str(item.get("snippet") or item.get("text") or item.get("content") or "").strip()
            title = Path(path).stem.replace("-", " ").title() if path else f"Memory {idx}"
            line_start = int(item.get("line") or item.get("startLine") or item.get("lineStart") or 1)
            line_end = int(item.get("endLine") or item.get("lineEnd") or line_start)
            score = float(item.get("score") or item.get("similarity") or 0.0)
            normalized.append(
                {
                    "id": f"openclaw:{brain_key}:{path or idx}",
                    "brain_key": brain_key,
                    "kind": "note",
                    "source": "openclaw-memory",
                    "title": title,
                    "content": snippet,
                    "content_hash": hashlib.sha256(f"{path}\n{snippet}".encode("utf-8")).hexdigest(),
                    "importance": 50,
                    "created_at": "",
                    "updated_at": "",
                    "metadata": {
                        "provider": item.get("provider"),
                        "model": item.get("model"),
                        "line_start": line_start,
                        "line_end": line_end,
                    },
                    "note_path": path,
                    "score": round(score, 4),
                }
            )
        return normalized[: max(1, int(limit))]

    def read_memory_file(self, brain_key: str, note_path: str) -> Dict[str, Any]:
        clean_path = str(note_path or "").strip()
        if not clean_path:
            raise FileNotFoundError("note_path is required")
        if clean_path != "MEMORY.md" and not clean_path.startswith("memory/"):
            raise ValueError("note_path must stay inside MEMORY.md or memory/")

        try:
            result = self._invoke_tool(
                "memory_get",
                {
                    "path": clean_path,
                    "startLine": 1,
                    "maxLines": 400,
                },
                brain_key=brain_key,
            )
            content = str(
                result.get("content")
                or result.get("text")
                or result.get("body")
                or ""
            )
            if content:
                return {
                    "title": Path(clean_path).stem or "Memory",
                    "content": content,
                    "note_path": clean_path,
                }
        except Exception as exc:
            self.last_error = str(exc)

        workspace = self._agent_workspace(self.canonical_agent_id(brain_key))
        target = (workspace / clean_path).resolve()
        root = workspace.resolve()
        if root not in target.parents and target != root:
            raise ValueError("note_path must stay inside the OpenClaw memory workspace")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(clean_path)
        content = target.read_text(encoding="utf-8")
        return {
            "title": Path(clean_path).stem or "Memory",
            "content": content,
            "note_path": clean_path,
        }


class EmbeddingService:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.last_error: str = ""

    def embed_text(self, text: str) -> List[float]:
        normalized = normalize_text(text)
        dimensions = int(self.config.dimensions or 0)
        if dimensions <= 0:
            dimensions = 768
        if not normalized:
            return [0.0] * dimensions

        try:
            provider = _normalize_provider(self.config.provider or "openai")
            if provider == "openclaw-builtin":
                return self._embed_openclaw_builtin(normalized)
            if provider == "ollama":
                return self._embed_ollama(normalized)
            if provider in ("openai", "openrouter", "mistral", "openai-compatible", "custom"):
                return self._embed_openai_compatible(normalized, provider)
            if provider == "gemini":
                return self._embed_gemini(normalized)
            if provider == "voyage":
                return self._embed_voyage(normalized)
        except Exception as exc:  # pragma: no cover - network dependent
            self.last_error = str(exc)

        return hash_embedding(normalized, dimensions)

    def _embed_openclaw_builtin(self, text: str) -> List[float]:
        resolved = self._resolve_openclaw_builtin()
        provider = str(resolved.get("provider", "") or "").strip().lower()
        model = str(resolved.get("model", "") or self.config.model or "").strip()
        endpoint = str(resolved.get("endpoint", "") or "").strip()
        dimensions = int(resolved.get("dimensions") or self.config.dimensions or 768)

        if provider == "ollama":
            temp = EmbeddingConfig(
                provider="ollama",
                model=model or "nomic-embed-text",
                endpoint=endpoint or "http://localhost:11434/api/embed",
                dimensions=dimensions,
            )
            return EmbeddingService(temp).embed_text(text)
        if provider in ("openai", "openrouter", "mistral", "openai-compatible", "custom"):
            temp = EmbeddingConfig(
                provider=provider,
                model=model or self.config.model or "text-embedding-3-small",
                api_key_env=_provider_api_key_env(provider),
                endpoint=endpoint,
                dimensions=dimensions,
            )
            return EmbeddingService(temp).embed_text(text)
        if provider == "gemini":
            temp = EmbeddingConfig(
                provider="gemini",
                model=model or "gemini-embedding-001",
                api_key_env=_provider_api_key_env("gemini"),
                endpoint=endpoint,
                dimensions=dimensions,
            )
            return EmbeddingService(temp).embed_text(text)
        if provider == "voyage":
            temp = EmbeddingConfig(
                provider="voyage",
                model=model or "voyage-4-lite",
                api_key_env=_provider_api_key_env("voyage"),
                endpoint=endpoint,
                dimensions=dimensions,
            )
            return EmbeddingService(temp).embed_text(text)

        raise RuntimeError("OpenClaw builtin embeddings are unavailable")

    def _resolve_openclaw_builtin(self) -> Dict[str, Any]:
        if not OPENCLAW_CONFIG_PATH.exists():
            return {}
        try:
            raw = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        agents = raw.get("agents", {}) if isinstance(raw.get("agents"), dict) else {}
        defaults = agents.get("defaults", {}) if isinstance(agents.get("defaults"), dict) else {}
        memory_search = defaults.get("memorySearch", {}) if isinstance(defaults.get("memorySearch"), dict) else {}
        provider = str(memory_search.get("provider", "") or "").strip().lower()
        model = str(memory_search.get("model", "") or "").strip()
        endpoint = ""
        dimensions = self.config.dimensions

        if provider == "ollama":
            remote = memory_search.get("remote", {}) if isinstance(memory_search.get("remote"), dict) else {}
            endpoint = str(remote.get("baseUrl", "") or "").strip()
            endpoint = f"{endpoint.rstrip('/')}/api/embed" if endpoint else ""
            if not model:
                model = "nomic-embed-text"
        elif provider in ("openai", "openrouter"):
            remote = memory_search.get("remote", {}) if isinstance(memory_search.get("remote"), dict) else {}
            endpoint = str(remote.get("baseUrl", "") or "").strip()
            if provider == "openai" and not endpoint:
                endpoint = "https://api.openai.com/v1"
            if provider == "openrouter" and not endpoint:
                endpoint = "https://openrouter.ai/api/v1"
            if not model:
                model = "text-embedding-3-small"
        elif provider == "gemini":
            if not model:
                model = "gemini-embedding-001"
        elif provider == "voyage":
            if not model:
                model = "voyage-4-lite"
        elif provider == "mistral":
            endpoint = "https://api.mistral.ai/v1"
            if not model:
                model = "mistral-embed"
        elif not provider:
            if _resolve_configured_api_key("", "OPENAI_API_KEY", "openai")[0]:
                provider = "openai"
                model = model or "text-embedding-3-small"
                endpoint = "https://api.openai.com/v1"
            elif _resolve_configured_api_key("", "GEMINI_API_KEY", "gemini")[0]:
                provider = "gemini"
                model = model or "gemini-embedding-001"
            elif _resolve_configured_api_key("", "VOYAGE_API_KEY", "voyage")[0]:
                provider = "voyage"
                model = model or "voyage-4-lite"
            elif _resolve_configured_api_key("", "MISTRAL_API_KEY", "mistral")[0]:
                provider = "mistral"
                model = model or "mistral-embed"
                endpoint = "https://api.mistral.ai/v1"
            elif os.environ.get("OLLAMA_HOST") or Path("/tmp/ollama.sock").exists():
                provider = "ollama"
                model = model or "nomic-embed-text"
                endpoint = "http://localhost:11434/api/embed"

        return {
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "dimensions": dimensions,
        }

    def _provider_api_key_env(self, provider: str) -> str:
        return _provider_api_key_env(provider)

    def _resolve_api_key(self, provider: str) -> Tuple[str, str]:
        return _resolve_configured_api_key(
            explicit_key=self.config.api_key,
            api_key_env=self.config.api_key_env,
            provider=provider,
        )

    def _embed_ollama(self, text: str) -> List[float]:
        endpoint = str(self.config.endpoint or "http://localhost:11434/api/embed").rstrip("/")
        payload = {"model": self.config.model, "input": text}
        data = _urlopen_json(endpoint, body=payload, timeout=60)

        if isinstance(data.get("embedding"), list):
            return [float(v) for v in data["embedding"]]
        if isinstance(data.get("embeddings"), list) and data["embeddings"]:
            first = data["embeddings"][0]
            if isinstance(first, list):
                return [float(v) for v in first]
        raise RuntimeError("Unexpected Ollama embedding response")

    def _embed_openai_compatible(self, text: str, provider: str) -> List[float]:
        base_url = str(self.config.endpoint or "").strip()
        if not base_url:
            if provider == "openai":
                base_url = "https://api.openai.com/v1"
            elif provider == "openrouter":
                base_url = "https://openrouter.ai/api/v1"
            elif provider == "mistral":
                base_url = "https://api.mistral.ai/v1"
            else:
                base_url = "https://api.openai.com/v1"
        api_key, _ = self._resolve_api_key(provider)
        if not api_key:
            raise RuntimeError(f"Missing API key for embedding provider {provider}")
        headers = {"Authorization": f"Bearer {api_key}"}
        data = _urlopen_json(
            f"{base_url.rstrip('/')}/embeddings",
            body={"model": self.config.model, "input": text},
            headers=headers,
            timeout=60,
        )
        item = data.get("data", [{}])[0]
        vector = item.get("embedding", [])
        if isinstance(vector, list):
            return [float(v) for v in vector]
        raise RuntimeError("Unexpected embeddings response")

    def _embed_gemini(self, text: str) -> List[float]:
        endpoint = str(self.config.endpoint or "").strip()
        api_key, _ = self._resolve_api_key("gemini")
        if not api_key:
            raise RuntimeError("Missing API key for embedding provider gemini")
        if not endpoint:
            model = self.config.model or "gemini-embedding-001"
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
        data = _urlopen_json(
            endpoint,
            body={
                "model": self.config.model or "models/gemini-embedding-001",
                "content": {"parts": [{"text": text}]},
                "output_dimensionality": int(self.config.dimensions or 768),
            },
            headers={"x-goog-api-key": api_key} if api_key else {},
            timeout=60,
        )
        embedding = data.get("embedding", {})
        values = embedding.get("values", []) if isinstance(embedding, dict) else []
        if isinstance(values, list):
            return [float(v) for v in values]
        raise RuntimeError("Unexpected Gemini embeddings response")

    def _embed_voyage(self, text: str) -> List[float]:
        endpoint = str(self.config.endpoint or "https://api.voyageai.com/v1/embeddings").strip()
        api_key, _ = self._resolve_api_key("voyage")
        if not api_key:
            raise RuntimeError("Missing API key for embedding provider voyage")
        headers = {"Authorization": f"Bearer {api_key}"}
        body: Dict[str, Any] = {
            "model": self.config.model or "voyage-4-lite",
            "input": [text],
        }
        if int(self.config.dimensions or 0) > 0:
            body["output_dimension"] = int(self.config.dimensions)
        data = _urlopen_json(
            endpoint,
            body=body,
            headers=headers,
            timeout=60,
        )
        item = data.get("data", [{}])[0]
        vector = item.get("embedding", [])
        if isinstance(vector, list):
            return [float(v) for v in vector]
        raise RuntimeError("Unexpected Voyage embeddings response")


class MemoryStore:
    def __init__(self, config: Config, embeddings: EmbeddingService, openclaw_bridge: Optional[OpenClawMemoryBridge] = None):
        self.config = config
        self.embeddings = embeddings
        self.openclaw_bridge = openclaw_bridge
        self.db_path = Path(config.storage.db_path)
        self.vector_path = Path(config.storage.vector_path)
        self.vault_root = Path(config.storage.vault_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._qdrant_collection_ready = False
        self._init_db()
        self._qdrant = self._init_qdrant()

    def _use_openclaw_memory_proxy(self) -> bool:
        provider = str(getattr(self.config.embedding, "provider", "") or "").strip().lower()
        return provider == "openclaw-builtin" and self.openclaw_bridge is not None

    def _openclaw_workspace_root(self, brain_key: str) -> Path:
        if self.openclaw_bridge is None:
            return OPENCLAW_WORKSPACES_DIR / f"{brain_key}-recall-facts"
        return self.openclaw_bridge._agent_workspace(self.openclaw_bridge.canonical_agent_id(brain_key))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brain_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding_json TEXT NOT NULL DEFAULT '[]',
                    importance INTEGER NOT NULL DEFAULT 50,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_brain_key ON memories(brain_key);
                CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
                CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(content_hash);
                CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
                """
            )
            self._conn.commit()

    def _init_qdrant(self) -> Optional[Any]:
        if QdrantClient is None or VectorParams is None or Distance is None:
            return None

        try:
            client = QdrantClient(path=str(self.vector_path))
            try:
                self._qdrant_collection_ready = bool(client.collection_exists(DEFAULT_COLLECTION))
            except Exception:
                try:
                    client.get_collection(DEFAULT_COLLECTION)
                    self._qdrant_collection_ready = True
                except Exception:
                    self._qdrant_collection_ready = False

            initial_dimensions = int(self.config.embedding.dimensions or 0)
            if not self._qdrant_collection_ready and initial_dimensions > 0:
                client.create_collection(
                    collection_name=DEFAULT_COLLECTION,
                    vectors_config=VectorParams(
                        size=initial_dimensions,
                        distance=Distance.COSINE,
                    ),
                )
                self._qdrant_collection_ready = True
            return client
        except Exception:
            return None

    def _ensure_qdrant_collection(self, dimensions: int) -> None:
        if self._qdrant is None or VectorParams is None or Distance is None:
            return
        if self._qdrant_collection_ready or dimensions <= 0:
            return
        try:
            self._qdrant.create_collection(
                collection_name=DEFAULT_COLLECTION,
                vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
            )
            self._qdrant_collection_ready = True
        except Exception:
            try:
                self._qdrant.get_collection(DEFAULT_COLLECTION)
                self._qdrant_collection_ready = True
            except Exception:
                pass

    def _row_to_memory(self, row: sqlite3.Row, score: float = 0.0) -> Dict[str, Any]:
        metadata = {}
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return {
            "id": row["id"],
            "brain_key": row["brain_key"],
            "kind": row["kind"],
            "source": row["source"],
            "title": row["title"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "importance": row["importance"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": metadata,
            "note_path": metadata.get("note_path"),
            "score": round(float(score), 4),
        }

    def get_by_id(self, memory_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row_to_memory(row) if row else None

    def has_content_hash(self, brain_key: str, content_hash: str, kind: Optional[str] = None) -> bool:
        sql = "SELECT 1 FROM memories WHERE brain_key = ? AND content_hash = ?"
        params: List[Any] = [brain_key, content_hash]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return row is not None

    def store_memory(
        self,
        brain_key: str,
        kind: str,
        source: str,
        title: str,
        content: str,
        importance: int = 50,
        metadata: Optional[Dict[str, Any]] = None,
        allow_duplicate: bool = False,
    ) -> Dict[str, Any]:
        clean_title = normalize_text(title) or "Untitled"
        clean_content = str(content or "").strip()
        metadata = metadata or {}
        fingerprint = hashlib.sha256(f"{brain_key}\n{kind}\n{clean_title}\n{clean_content}".encode("utf-8")).hexdigest()

        if not allow_duplicate and self.has_content_hash(brain_key, fingerprint, kind):
            existing = self._find_existing_by_hash(brain_key, fingerprint, kind)
            if existing:
                return existing

        created_at = utc_now()
        local_note_path = self._write_memory_note(
            brain_key=brain_key,
            kind=kind,
            source=source,
            title=clean_title,
            content=clean_content,
            importance=int(max(1, min(int(importance or 50), 100))),
            created_at=created_at,
            fingerprint=fingerprint,
        )
        mirrored_note_path = None
        if self._use_openclaw_memory_proxy() and self.openclaw_bridge is not None:
            mirrored_note_path = self.openclaw_bridge.mirror_memory_file(
                brain_key=brain_key,
                kind=kind,
                source=source,
                title=clean_title,
                content=clean_content,
                importance=int(max(1, min(int(importance or 50), 100))),
                created_at=created_at,
                fingerprint=fingerprint,
            )
        note_path = metadata.get("note_path") or mirrored_note_path or local_note_path
        metadata = {
            **metadata,
            "note_path": note_path,
            "vault_note_path": local_note_path,
        }
        embedding = self.embeddings.embed_text(f"{clean_title}\n\n{clean_content}")
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO memories (
                    brain_key, kind, source, title, content, content_hash,
                    embedding_json, importance, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brain_key,
                    kind,
                    source,
                    clean_title,
                    clean_content,
                    fingerprint,
                    json.dumps(embedding),
                    int(max(1, min(int(importance or 50), 100))),
                    json.dumps(metadata),
                    created_at,
                    created_at,
                ),
            )
            memory_id = int(cursor.lastrowid)
            self._conn.commit()

        if self._qdrant is not None and PointStruct is not None:
            payload = {
                "memory_id": memory_id,
                "brain_key": brain_key,
                "kind": kind,
                "source": source,
                "title": clean_title,
                "content": clean_content,
                "importance": int(max(1, min(int(importance or 50), 100))),
                "created_at": created_at,
            }
            try:
                self._ensure_qdrant_collection(len(embedding))
                self._qdrant.upsert(
                    collection_name=DEFAULT_COLLECTION,
                    points=[
                        PointStruct(
                            id=memory_id,
                            vector=embedding,
                            payload=payload,
                        )
                    ],
                )
            except Exception:
                pass

        stored = self.get_by_id(memory_id)
        return stored or {
            "id": memory_id,
            "brain_key": brain_key,
            "kind": kind,
            "source": source,
            "title": clean_title,
            "content": clean_content,
            "content_hash": fingerprint,
            "importance": importance,
            "created_at": created_at,
            "updated_at": created_at,
            "metadata": metadata,
            "note_path": note_path,
            "score": 1.0,
        }

    def _write_memory_note(
        self,
        brain_key: str,
        kind: str,
        source: str,
        title: str,
        content: str,
        importance: int,
        created_at: str,
        fingerprint: str,
    ) -> str:
        folder_map = {
            "observed_fact": "inbox",
            "observed_pattern": "patterns",
            "observed_relationship": "entities",
            "chat_turn": "daily",
            "note": "inbox",
            "decision": "decisions",
            "project_context": "projects",
        }
        folder = folder_map.get(kind, "inbox")
        brain_root = self.vault_root / brain_key / folder
        brain_root.mkdir(parents=True, exist_ok=True)
        filename = f"{slugify(title)}-{fingerprint[:8]}.md"
        path = brain_root / filename
        if not path.exists():
            path.write_text(
                "\n".join(
                    [
                        "---",
                        f'title: "{title.replace(chr(34), chr(39))}"',
                        f"kind: {kind}",
                        f"source: {source}",
                        f"importance: {importance}",
                        f"created_at: {created_at}",
                        "---",
                        "",
                        content,
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return str(path.relative_to(self.vault_root / brain_key))

    def _find_existing_by_hash(self, brain_key: str, content_hash: str, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM memories WHERE brain_key = ? AND content_hash = ?"
        params: List[Any] = [brain_key, content_hash]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return self._row_to_memory(row, score=1.0) if row else None

    def _sql_filters(self, brain_key: str, kind: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> Tuple[str, List[Any]]:
        clauses = ["brain_key = ?"]
        params: List[Any] = [brain_key]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to)
        return " AND ".join(clauses), params

    def recent_memories(
        self,
        brain_key: str,
        limit: int = 10,
        kind: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        where_sql, params = self._sql_filters(brain_key, kind, parse_iso_date(date_from), parse_iso_date(date_to))
        params.append(int(max(1, limit)))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE {where_sql} ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._row_to_memory(row, score=0.0) for row in rows]

    def search_memories(
        self,
        brain_key: str,
        query: str,
        limit: int = 10,
        kind: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clean_query = normalize_text(query)
        if not clean_query:
            return self.recent_memories(brain_key, limit=limit, kind=kind, date_from=date_from, date_to=date_to)

        if self._use_openclaw_memory_proxy():
            if kind and kind not in {"memory", "note"}:
                return []
            proxied = self.openclaw_bridge.search_memories(brain_key, clean_query, max(1, int(limit))) if self.openclaw_bridge else []
            if proxied or not (self.openclaw_bridge and self.openclaw_bridge.last_error):
                return proxied[: max(1, int(limit))]

        requested = max(1, int(limit))
        results: Dict[str, Dict[str, Any]] = {}
        where_sql, params = self._sql_filters(brain_key, kind, parse_iso_date(date_from), parse_iso_date(date_to))
        vector_matches = self._vector_search(
            brain_key=brain_key,
            query=clean_query,
            limit=max(requested * 3, 8),
            kind=kind,
            date_from=parse_iso_date(date_from),
            date_to=parse_iso_date(date_to),
        )
        for memory, score in vector_matches:
            item = dict(memory)
            item["score"] = round(max(float(item.get("score", 0.0)), score), 4)
            results[str(item["id"])] = item

        tokens = [token for token in re.findall(r"[a-z0-9_]+", clean_query.lower()) if token]
        if tokens:
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT * FROM memories WHERE {where_sql} ORDER BY updated_at DESC LIMIT 100",
                    tuple(params),
                ).fetchall()
            for row in rows:
                haystack = f"{row['title']} {row['content']}".lower()
                hits = sum(haystack.count(token) for token in tokens)
                if hits <= 0:
                    continue
                score = min(0.75, 0.15 + (hits / max(len(tokens), 1)) * 0.25 + float(row["importance"]) / 400.0)
                item = self._row_to_memory(row, score=score)
                existing = results.get(str(item["id"]))
                if existing:
                    existing["score"] = round(max(float(existing.get("score", 0.0)), score), 4)
                else:
                    results[str(item["id"])] = item

        ranked = sorted(
            results.values(),
            key=lambda item: (
                float(item.get("score", 0.0)),
                float(item.get("importance", 0.0)),
                item.get("updated_at", ""),
            ),
            reverse=True,
        )
        return ranked[:requested]

    def _vector_search(
        self,
        brain_key: str,
        query: str,
        limit: int,
        kind: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> List[Tuple[Dict[str, Any], float]]:
        embedding = self.embeddings.embed_text(query)
        if not embedding:
            return []

        if self._qdrant is not None and Filter is not None and FieldCondition is not None and MatchValue is not None:
            self._ensure_qdrant_collection(len(embedding))
            must = [FieldCondition(key="brain_key", match=MatchValue(value=brain_key))]
            if kind:
                must.append(FieldCondition(key="kind", match=MatchValue(value=kind)))
            if (date_from or date_to) and Range is not None:
                must.append(FieldCondition(key="created_at", range=Range(gte=date_from, lte=date_to)))
            query_filter = Filter(must=must)
            try:
                if hasattr(self._qdrant, "query_points"):
                    response = self._qdrant.query_points(
                        collection_name=DEFAULT_COLLECTION,
                        query=embedding,
                        query_filter=query_filter,
                        limit=limit,
                        with_payload=True,
                    )
                    points = getattr(response, "points", response)
                else:
                    points = self._qdrant.search(
                        collection_name=DEFAULT_COLLECTION,
                        query_vector=embedding,
                        query_filter=query_filter,
                        limit=limit,
                        with_payload=True,
                    )
                results: List[Tuple[Dict[str, Any], float]] = []
                for point in points:
                    memory_id = getattr(point, "id", None)
                    if memory_id is None and isinstance(getattr(point, "payload", None), dict):
                        memory_id = point.payload.get("memory_id")
                    if memory_id is None:
                        continue
                    memory = self.get_by_id(int(memory_id))
                    if memory:
                        results.append((memory, float(getattr(point, "score", 0.0) or 0.0)))
                if results:
                    return results
            except Exception:
                pass

        # Fallback vector search from SQLite if qdrant is unavailable.
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE brain_key = ? ORDER BY updated_at DESC LIMIT 200",
                (brain_key,),
            ).fetchall()
        results = []
        for row in rows:
            if kind and row["kind"] != kind:
                continue
            if date_from and str(row["created_at"]) < date_from:
                continue
            if date_to and str(row["created_at"]) > date_to:
                continue
            try:
                stored_embedding = json.loads(row["embedding_json"] or "[]")
            except json.JSONDecodeError:
                stored_embedding = []
            if not isinstance(stored_embedding, list):
                continue
            score = cosine_similarity(embedding, [float(v) for v in stored_embedding])
            if score <= 0.0:
                continue
            results.append((self._row_to_memory(row, score=score), score))
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:limit]

    def read_vault_note(self, brain_key: str, note_path: str) -> Dict[str, Any]:
        if self._use_openclaw_memory_proxy():
            clean_path = str(note_path or "").strip()
            if clean_path == "MEMORY.md" or clean_path.startswith("memory/"):
                return self.openclaw_bridge.read_memory_file(brain_key, clean_path)

        root = (self.vault_root / brain_key).resolve()
        target = (root / note_path).resolve()
        if root not in target.parents and target != root:
            raise ValueError("note_path must stay inside the brain vault")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(note_path)
        content = target.read_text(encoding="utf-8")
        title = target.stem
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip() or title
                break
        return {
            "title": title,
            "content": content,
            "note_path": str(target.relative_to(root)),
        }

    def search_graph_notes(self, brain_key: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        openclaw_root = self._openclaw_workspace_root(brain_key)
        use_openclaw_root = self._use_openclaw_memory_proxy() and openclaw_root.exists()
        root = openclaw_root if use_openclaw_root else (self.vault_root / brain_key)
        if not root.exists():
            return []

        terms = [token for token in re.findall(r"[a-z0-9_]+", query.lower()) if token]
        scored: List[Tuple[float, Dict[str, Any]]] = []
        paths: List[Path] = []
        if use_openclaw_root:
            memory_index = root / "MEMORY.md"
            if memory_index.exists():
                paths.append(memory_index)
            memory_root = root / "memory"
            if memory_root.exists():
                paths.extend(sorted(memory_root.rglob("*.md")))
        else:
            paths.extend(sorted(root.rglob("*.md")))

        for path in paths:
            try:
                body = path.read_text(encoding="utf-8")
            except Exception:
                continue
            title = path.stem
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    title = stripped.lstrip("#").strip() or title
                    break
            haystack = f"{title}\n{body}".lower()
            hits = sum(haystack.count(term) for term in terms) if terms else 0
            if terms and hits == 0:
                continue
            score = float(hits) + (1.5 if any(term in title.lower() for term in terms) else 0.0)
            preview = normalize_text(body)[:240]
            scored.append(
                (
                    score,
                    {
                        "title": title,
                        "note_type": "memory" if use_openclaw_root and path.name == "MEMORY.md" else path.parent.name,
                        "note_path": str(path.relative_to(root)),
                        "body_preview": preview,
                    },
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: max(1, int(limit))]]


@dataclass
class ObserverStatus:
    running: bool = False
    last_run: str = ""
    last_error: str = ""
    last_result: Dict[str, Any] = None  # type: ignore[assignment]


class MemoryRuntime:
    def __init__(self, config: Config):
        self.config = config
        self.embeddings = EmbeddingService(config.embedding)
        provider = str(config.embedding.provider or "").strip().lower()
        self.openclaw_bridge = OpenClawMemoryBridge(config) if provider == "openclaw-builtin" else None
        self.store = MemoryStore(config, self.embeddings, openclaw_bridge=self.openclaw_bridge)
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="oam")
        self.session_buffers: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=200))
        self.staged_buffers: Dict[str, Dict[str, Any]] = {}
        self.observer_status: Dict[str, ObserverStatus] = defaultdict(ObserverStatus)
        self.scout_status: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._observer_event = threading.Event()
        self._observer_thread: Optional[threading.Thread] = None
        self._session_lock = threading.RLock()
        self._observer_offsets: Dict[str, int] = defaultdict(int)
        self._prompt_cache: Dict[str, str] = {}

    def close(self) -> None:
        self._observer_event.set()
        if self._observer_thread and self._observer_thread.is_alive():
            self._observer_thread.join(timeout=2)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.store.close()

    def start(self) -> None:
        if self._observer_thread is not None:
            return
        self._observer_thread = threading.Thread(target=self._observer_loop, name="oam-observer", daemon=True)
        self._observer_thread.start()

    def _observer_loop(self) -> None:
        interval = max(30, int(self.config.agents.observer_interval))
        while not self._observer_event.wait(interval):
            for brain_key in self.known_brains():
                try:
                    self.run_observer_cycle(brain_key, force=False)
                except Exception as exc:  # pragma: no cover - background safety
                    status = self.observer_status[brain_key]
                    status.last_error = str(exc)
                    status.running = False

    def known_brains(self) -> List[str]:
        keys = {brain.key for brain in self.config.brains}
        keys.update(self.session_buffers.keys())
        keys.update(self.staged_buffers.keys())
        for brain_dir in self.store.vault_root.iterdir() if self.store.vault_root.exists() else []:
            if brain_dir.is_dir():
                keys.add(brain_dir.name)
        return sorted(key for key in keys if key)

    def record_session_message(self, brain_key: str, role: str, text: str) -> Dict[str, Any]:
        message = {"role": role, "text": str(text or ""), "created_at": utc_now()}
        with self._session_lock:
            self.session_buffers[brain_key].append(message)
        return message

    def clear_session(self, brain_key: str) -> None:
        with self._session_lock:
            self.session_buffers[brain_key].clear()
        self.staged_buffers.pop(brain_key, None)
        self._observer_offsets[brain_key] = 0

    def get_session_messages(self, brain_key: str, window: int = 20) -> List[Dict[str, Any]]:
        with self._session_lock:
            buffer = list(self.session_buffers.get(brain_key, deque()))
        return buffer[-max(1, int(window)) :]

    def consume_staged_context(self, brain_key: str) -> Optional[Dict[str, Any]]:
        return self.staged_buffers.pop(brain_key, None)

    def store_passive_memory(self, brain_key: str, user_text: str) -> Optional[Dict[str, Any]]:
        if not user_text.strip():
            return None
        content = user_text.strip()
        lowered = content.lower()
        importance = 25
        kind = "chat_turn"
        title = truncate(content, 72)
        source = "chat-user"
        metadata = {"role": "user", "captured_at": utc_now()}

        if any(phrase in lowered for phrase in ["remember this", "note this", "save this", "keep this in mind"]):
            kind = "note"
            importance = 90
            source = "passive-memory"

        return self.store.store_memory(
            brain_key=brain_key,
            kind=kind,
            source=source,
            title=title,
            content=content,
            importance=importance,
            metadata=metadata,
            allow_duplicate=(kind == "chat_turn"),
        )

    def search_memories(self, brain_key: str, query: str, limit: int = 10, kind: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.search_memories(brain_key, query, limit=limit, kind=kind, date_from=date_from, date_to=date_to)

    def read_vault_note(self, brain_key: str, note_path: str) -> Dict[str, Any]:
        return self.store.read_vault_note(brain_key, note_path)

    def search_graph_notes(self, brain_key: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self.store.search_graph_notes(brain_key, query, limit=limit)

    def classify_memory_need(self, brain_key: str, message: str) -> Dict[str, Any]:
        prompt = self._load_prompt("scout/gate.md")
        recent = self.get_session_messages(brain_key, window=6)
        user_prompt = (
            "Classify whether memory is needed for this inbound user message.\n\n"
            f"Recent session messages:\n{json.dumps(recent, indent=2)}\n\n"
            f"Inbound message:\n{message}\n"
        )
        response = call_model_text(
            self.config.fast_model,
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_prompt},
            ],
            thinking=self.config.fast_model.thinking,
            app_config=self.config,
        )
        parsed = extract_json_object(response)
        if parsed and parsed.get("classification") in {"none", "light", "deep"}:
            return {
                "classification": parsed["classification"],
                "reason": str(parsed.get("reason", "")),
                "raw": response,
            }

        lowered = message.lower()
        if any(term in lowered for term in ["what do you remember", "last time", "previously", "history", "before", "remember about"]):
            classification = "deep"
        elif any(term in lowered for term in ["thanks", "hello", "hi", "ok", "okay"]):
            classification = "none"
        else:
            classification = "light"
        return {"classification": classification, "reason": "fallback heuristic", "raw": response}

    def invoke_deep_recall(self, brain_key: str, query: str) -> Dict[str, Any]:
        jobs = {
            "facts": self.executor.submit(self._run_recall_agent, "facts", brain_key, query),
            "context": self.executor.submit(self._run_recall_agent, "context", brain_key, query),
            "temporal": self.executor.submit(self._run_recall_agent, "temporal", brain_key, query),
        }

        raw_agents: Dict[str, Dict[str, Any]] = {}
        merged: List[Dict[str, Any]] = []
        for agent_type, future in jobs.items():
            try:
                payload = future.result(timeout=max(10, self.config.agents.recall_timeout))
            except Exception as exc:
                payload = {"findings": [], "search_summary": f"Error: {exc}", "agent_type": agent_type}
            raw_agents[agent_type] = payload
            merged.extend(self._normalize_recall_findings(agent_type, payload))

        deduped: Dict[str, Dict[str, Any]] = {}
        for item in sorted(merged, key=lambda result: result["score"], reverse=True):
            key = normalize_text(item["summary"]).lower()
            if not key:
                continue
            if key not in deduped:
                deduped[key] = item

        top_results = list(deduped.values())[: max(1, int(self.config.agents.recall_merge_limit))]
        return {
            "query": query,
            "brain_key": brain_key,
            "results": top_results,
            "agents": raw_agents,
        }

    def _normalize_recall_findings(self, agent_type: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        findings = payload.get("findings", [])
        if not isinstance(findings, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if agent_type == "facts":
                summary = str(finding.get("fact") or finding.get("summary") or "")
            elif agent_type == "context":
                summary = str(finding.get("context_summary") or finding.get("inferred_intent") or "")
            else:
                summary = str(finding.get("timeline_entry") or finding.get("recurring_pattern") or "")
            summary = normalize_text(summary)
            if not summary:
                continue
            relevance = float(finding.get("relevance", 0.5) or 0.5)
            confidence = float(finding.get("confidence", 0.5) or 0.5)
            normalized.append(
                {
                    "agent_type": agent_type,
                    "summary": summary,
                    "score": round(relevance * 0.7 + confidence * 0.3, 4),
                    "details": finding,
                }
            )
        return normalized

    def _run_recall_agent(self, agent_type: str, brain_key: str, query: str) -> Dict[str, Any]:
        prompt_map = {
            "facts": "recall/facts.md",
            "context": "recall/context.md",
            "temporal": "recall/temporal.md",
        }
        prompt = self._load_prompt(prompt_map[agent_type])
        memory_results = self.search_memories(brain_key, query, limit=10)
        graph_notes = self.search_graph_notes(brain_key, query, limit=6)
        session_messages = self.get_session_messages(brain_key, window=20)

        user_payload = {
            "brain_key": brain_key,
            "query": query,
            "memory_results": memory_results,
            "session_messages": session_messages if agent_type == "context" else [],
            "graph_notes": graph_notes if agent_type in {"context", "temporal"} else [],
        }
        augmented_prompt = (
            prompt
            + "\n\nYou are being given pre-fetched tool results instead of live tool access. "
            "Use only the provided data. Return ONLY valid JSON that matches the documented format."
        )
        response = call_model_text(
            self.config.fast_model,
            [
                {"role": "system", "content": augmented_prompt},
                {"role": "user", "content": json.dumps(user_payload, indent=2)},
            ],
            thinking=self.config.fast_model.thinking,
            app_config=self.config,
        )
        parsed = extract_json_object(response)
        if parsed and isinstance(parsed.get("findings"), list):
            return parsed

        # Conservative fallback if the model does not return valid JSON.
        fallback_findings = []
        for item in memory_results[: min(6, len(memory_results))]:
            if agent_type == "facts":
                fallback_findings.append(
                    {
                        "fact": item["content"],
                        "source_id": item["id"],
                        "source_kind": item["kind"],
                        "confidence": 0.55,
                        "relevance": max(0.45, float(item.get("score", 0.45))),
                    }
                )
            elif agent_type == "context":
                fallback_findings.append(
                    {
                        "context_summary": item["content"],
                        "inferred_intent": None,
                        "surrounding_evidence": item["title"],
                        "social_dynamics": None,
                        "confidence": 0.45,
                        "relevance": max(0.4, float(item.get("score", 0.4))),
                    }
                )
            else:
                fallback_findings.append(
                    {
                        "timeline_entry": item["title"],
                        "recurring_pattern": truncate(item["content"], 120),
                        "frequency": "unknown",
                        "escalation_status": "unknown",
                        "date_range": f"{item['created_at'][:10]} to {item['updated_at'][:10]}",
                        "confidence": 0.45,
                        "relevance": max(0.4, float(item.get("score", 0.4))),
                    }
                )
        return {
            "findings": fallback_findings,
            "search_summary": f"Fallback recall from {len(memory_results)} stored memories",
            "agent_type": agent_type,
        }

    def run_observer_cycle(self, brain_key: str, force: bool = False) -> Dict[str, Any]:
        status = self.observer_status[brain_key]
        if status.running:
            return {"brain_key": brain_key, "status": "already-running"}

        messages = self.get_session_messages(brain_key, window=80)
        new_count = max(0, len(messages) - self._observer_offsets[brain_key])
        if not force and (len(messages) < self.config.agents.observer_min_messages or new_count < self.config.agents.observer_min_messages):
            return {"brain_key": brain_key, "status": "skipped", "reason": "not enough new messages"}

        status.running = True
        status.last_error = ""
        try:
            jobs = {
                "facts": self.executor.submit(self._run_observer_agent, "facts", brain_key, messages),
                "patterns": self.executor.submit(self._run_observer_agent, "patterns", brain_key, messages),
                "relationships": self.executor.submit(self._run_observer_agent, "relationships", brain_key, messages),
            }
            results: Dict[str, Any] = {}
            for key, future in jobs.items():
                try:
                    results[key] = future.result(timeout=60)
                except Exception as exc:
                    results[key] = {"agent_type": key, "observed": 0, "stored": 0, "error": str(exc)}
            self._observer_offsets[brain_key] = len(messages)
            status.last_run = utc_now()
            status.last_result = results
            return {"brain_key": brain_key, "status": "completed", "results": results}
        except Exception as exc:
            status.last_error = str(exc)
            raise
        finally:
            status.running = False

    def _run_observer_agent(self, role: str, brain_key: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt_map = {
            "facts": "observer/facts.md",
            "patterns": "observer/patterns.md",
            "relationships": "observer/relationships.md",
        }
        kind_map = {
            "facts": "observed_fact",
            "patterns": "observed_pattern",
            "relationships": "observed_relationship",
        }
        source_map = {
            "facts": "observer-facts",
            "patterns": "observer-patterns",
            "relationships": "observer-relationships",
        }

        prompt = self._load_prompt(prompt_map[role])
        user_payload = {
            "brain_key": brain_key,
            "messages": messages[-40:],
            "max_items": self.config.agents.observer_max_per_cycle,
        }
        schema_instruction = (
            prompt
            + "\n\nReturn ONLY valid JSON with this shape:\n"
            + '{"items":[{"title":"Short title","content":"Useful standalone memory text","importance":70}],"agent_type":"observer"}'
        )
        response = call_model_text(
            self.config.fast_model,
            [
                {"role": "system", "content": schema_instruction},
                {"role": "user", "content": json.dumps(user_payload, indent=2)},
            ],
            thinking=self.config.fast_model.thinking,
            app_config=self.config,
        )
        parsed = extract_json_object(response) or {}
        raw_items = parsed.get("items", [])
        items = raw_items if isinstance(raw_items, list) else []

        observed = 0
        stored = 0
        skipped_duplicate = 0
        result_items: List[Dict[str, Any]] = []
        for candidate in items[: self.config.agents.observer_max_per_cycle]:
            if not isinstance(candidate, dict):
                continue
            title = normalize_text(str(candidate.get("title", "")))
            content = str(candidate.get("content", "")).strip()
            if not title or not content:
                continue
            observed += 1
            content_hash = hashlib.sha256(f"{brain_key}\n{kind_map[role]}\n{title}\n{content}".encode("utf-8")).hexdigest()
            if self.store.has_content_hash(brain_key, content_hash, kind_map[role]):
                skipped_duplicate += 1
                result_items.append({"title": title, "stored": False, "reason": "duplicate hash"})
                continue

            nearby = self.search_memories(brain_key, title, limit=3)
            if nearby and float(nearby[0].get("score", 0.0)) >= 0.92:
                skipped_duplicate += 1
                result_items.append({"title": title, "stored": False, "reason": "similar memory exists"})
                continue

            importance = int(candidate.get("importance", 65) or 65)
            self.store.store_memory(
                brain_key=brain_key,
                kind=kind_map[role],
                source=source_map[role],
                title=title,
                content=content,
                importance=importance,
                metadata={"observer_role": role, "observed_at": utc_now()},
                allow_duplicate=False,
            )
            stored += 1
            result_items.append({"title": title, "stored": True, "reason": "stored"})

        return {
            "observed": observed,
            "stored": stored,
            "skipped_duplicate": skipped_duplicate,
            "items": result_items,
            "agent_type": f"observer_{role}",
        }

    def trigger_scouts(self, brain_key: str) -> None:
        self.executor.submit(self._run_scouts, brain_key)

    def _run_scouts(self, brain_key: str) -> None:
        recent_messages = self.get_session_messages(brain_key, window=8)
        if not recent_messages:
            return

        trajectory_prompt = self._load_prompt("scout/trajectory.md")
        recent_payload = {"brain_key": brain_key, "messages": recent_messages}
        trajectory_response = call_model_text(
            self.config.fast_model,
            [
                {
                    "role": "system",
                    "content": trajectory_prompt
                    + "\n\nReturn ONLY valid JSON with this shape: "
                    + '{"current_topic":"...","predicted_topics":["topic"],"agent_type":"scout_trajectory"}',
                },
                {"role": "user", "content": json.dumps(recent_payload, indent=2)},
            ],
            thinking=self.config.fast_model.thinking,
            app_config=self.config,
        )
        trajectory = extract_json_object(trajectory_response) or {}

        current_topic = normalize_text(str(trajectory.get("current_topic", ""))) or normalize_text(str(recent_messages[-1]["text"]))
        predicted_topics = [
            normalize_text(str(topic))
            for topic in (trajectory.get("predicted_topics", []) if isinstance(trajectory.get("predicted_topics"), list) else [])
            if normalize_text(str(topic))
        ][:3]
        if not predicted_topics and current_topic:
            predicted_topics = [current_topic]

        candidate_memories: List[Dict[str, Any]] = []
        seen_ids = set()
        for topic in [current_topic] + predicted_topics:
            if not topic:
                continue
            for memory in self.search_memories(brain_key, topic, limit=4):
                if memory["id"] in seen_ids:
                    continue
                seen_ids.add(memory["id"])
                candidate_memories.append(memory)

        relevance_prompt = self._load_prompt("scout/relevance.md")
        relevance_response = call_model_text(
            self.config.fast_model,
            [
                {
                    "role": "system",
                    "content": relevance_prompt
                    + "\n\nReturn ONLY valid JSON. Candidate memories are pre-fetched for you."
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "brain_key": brain_key,
                            "current_topic": current_topic,
                            "candidate_memories": candidate_memories,
                        },
                        indent=2,
                    ),
                },
            ],
            thinking=self.config.fast_model.thinking,
            app_config=self.config,
        )
        relevance = extract_json_object(relevance_response) or {}
        scored = relevance.get("scored_memories", [])
        scored_items = scored if isinstance(scored, list) else []
        boosted_ids = {int(item["id"]) for item in scored_items if isinstance(item, dict) and str(item.get("id", "")).isdigit() and float(item.get("adjusted_score", 0.0) or 0.0) >= 0.55}
        surfaced_items = relevance.get("surfaced", [])
        if isinstance(surfaced_items, list):
            boosted_ids.update(
                int(item["id"])
                for item in surfaced_items
                if isinstance(item, dict) and str(item.get("id", "")).isdigit()
            )

        staged = [memory for memory in candidate_memories if memory["id"] in boosted_ids] or candidate_memories[:4]
        self.staged_buffers[brain_key] = {
            "generated_at": utc_now(),
            "current_topic": current_topic,
            "predicted_topics": predicted_topics,
            "memories": staged[:6],
        }
        self.scout_status[brain_key] = {
            "generated_at": utc_now(),
            "current_topic": current_topic,
            "count": len(staged[:6]),
        }

    def format_memory_context(
        self,
        staged_context: Optional[Dict[str, Any]],
        light_results: List[Dict[str, Any]],
        deep_recall: Optional[Dict[str, Any]],
    ) -> str:
        sections: List[str] = []
        if staged_context and staged_context.get("memories"):
            topic = staged_context.get("current_topic", "current conversation")
            sections.append(
                "Pre-staged context for "
                + str(topic)
                + ":\n"
                + self._format_memories(staged_context.get("memories", []), max_items=4)
            )
        if light_results:
            sections.append("Relevant memory search results:\n" + self._format_memories(light_results, max_items=5))
        if deep_recall and deep_recall.get("results"):
            recall_lines = []
            for idx, item in enumerate(deep_recall["results"][:6], start=1):
                recall_lines.append(
                    f"{idx}. [{item['agent_type']}] {item['summary']} (score={item['score']:.2f})"
                )
            sections.append("Deep recall findings:\n" + "\n".join(recall_lines))
        return "\n\n".join(section for section in sections if section).strip()

    def _format_memories(self, memories: List[Dict[str, Any]], max_items: int = 5) -> str:
        lines = []
        for idx, memory in enumerate(memories[:max_items], start=1):
            lines.append(
                f"{idx}. [{memory.get('kind', 'note')} score={float(memory.get('score', 0.0)):.2f}] "
                f"{memory.get('title', 'Untitled')}\n   {truncate(memory.get('content', ''), 220)}"
            )
        return "\n".join(lines)

    def observer_snapshot(self) -> Dict[str, Any]:
        return {
            brain_key: {
                "running": status.running,
                "last_run": status.last_run,
                "last_error": status.last_error,
                "last_result": status.last_result or {},
            }
            for brain_key, status in self.observer_status.items()
        }

    def _load_prompt(self, relative_path: str) -> str:
        if relative_path not in self._prompt_cache:
            self._prompt_cache[relative_path] = (PROMPT_DIR / relative_path).read_text(encoding="utf-8")
        return self._prompt_cache[relative_path]
