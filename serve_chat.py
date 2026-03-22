"""
Open Agentic Memory — Identity Setup Chat Server

A lightweight chat interface that opens in the browser after setup.
Walks the user through agent identity configuration via conversation.
Also serves the memory runtime endpoints used by the registered agents.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import yaml
except ImportError:
    print("Installing pyyaml...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyyaml"])
    import yaml

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
except ImportError:
    print("Installing fastapi and uvicorn...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn"])
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn

from agentic_memory.config import load_config as load_runtime_config, load_env_file
from agentic_memory.runtime import MemoryRuntime

load_env_file(ROOT_DIR / ".env")


# ============================================================
# Port Helpers
# ============================================================

def port_is_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False


def wait_for_server_ready(port: int, timeout_seconds: float = 15.0, poll_interval: float = 0.2) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
                return True
        except OSError:
            time.sleep(poll_interval)
    return False


def open_browser_when_ready(port: int, timeout_seconds: float = 15.0) -> None:
    url = f"http://127.0.0.1:{port}"

    def _runner() -> None:
        if not wait_for_server_ready(port, timeout_seconds=timeout_seconds):
            return
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_runner, name="oam-browser-open", daemon=True).start()


# ============================================================
# Config loader
# ============================================================

def load_config() -> Dict[str, Any]:
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


# ============================================================
# OpenClaw gateway detection
# ============================================================

def _load_openclaw_gateway_config() -> Optional[Dict[str, Any]]:
    """Load OpenClaw gateway config if available."""
    runtime_cfg = globals().get("runtime_config")
    if runtime_cfg is None:
        runtime_cfg = load_runtime_config(str(ROOT_DIR / "config.yaml"))

    gateway_cfg = getattr(runtime_cfg, "gateway", None)
    if gateway_cfg is not None:
        base_url = str(getattr(gateway_cfg, "base_url", "") or "").strip().rstrip("/")
        port = int(getattr(gateway_cfg, "port", 0) or 0)
        if not base_url and port:
            base_url = f"http://127.0.0.1:{port}"
        if base_url:
            token_env = str(getattr(gateway_cfg, "token_env", "") or "").strip()
            token = str(getattr(gateway_cfg, "token", "") or "").strip()
            if not token and token_env:
                token = str(os.environ.get(token_env, "") or "").strip()
            return {"port": port, "base_url": base_url, "token": token}

    openclaw_path = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_path.exists():
        return None
    try:
        with open(openclaw_path) as f:
            oc = json.load(f)
        gw = oc.get("gateway", {})
        port = gw.get("port")
        token = gw.get("auth", {}).get("token", "")
        http_endpoints = gw.get("http", {}).get("endpoints", {})
        if port and http_endpoints.get("chatCompletions", {}).get("enabled"):
            return {"port": port, "base_url": f"http://127.0.0.1:{port}", "token": token}
    except Exception:
        pass
    return None


def _call_openclaw_gateway(messages: List[Dict], model: str, gateway: Dict[str, Any], thinking: str = "") -> str:
    """Route through the OpenClaw gateway which handles all auth."""
    import urllib.request
    port = gateway.get("port")
    token = gateway["token"]
    base_url = str(gateway.get("base_url") or "").rstrip("/")
    if not base_url and port:
        base_url = f"http://127.0.0.1:{port}"
    url = f"{base_url}/v1/chat/completions"
    payload: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 2000}
    if thinking:
        payload["thinking"] = thinking
        payload["reasoning_effort"] = thinking
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"Error calling OpenClaw gateway: {e}"


def _call_openclaw_cli_with_thinking(message: str, agent_id: str = "main", thinking: str = "low") -> str:
    """Use the OpenClaw CLI with explicit --thinking flag."""
    import shutil
    binary = shutil.which("openclaw")
    if not binary:
        return "OpenClaw CLI not found in PATH."
    clean_thinking = str(thinking or "low").strip().lower()
    if clean_thinking not in ("low", "mid", "high", "xhigh"):
        clean_thinking = "low"
    try:
        result = subprocess.run(
            [binary, "agent", "--agent", agent_id, "--message", message, "--json", "--thinking", clean_thinking],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                return f"OpenClaw error: {stderr[:300]}"
        try:
            payload = json.loads(result.stdout)
            # Extract reply text from OpenClaw response
            payloads = payload.get("result", {}).get("payloads", payload.get("payloads", []))
            if isinstance(payloads, list):
                texts = [p.get("text", "") for p in payloads if isinstance(p, dict) and p.get("text")]
                if texts:
                    return "\n\n".join(texts)
            return result.stdout[:1000]
        except json.JSONDecodeError:
            return result.stdout[:1000] if result.stdout else "No response from OpenClaw."
    except subprocess.TimeoutExpired:
        return "OpenClaw request timed out."
    except Exception as e:
        return f"Error running OpenClaw: {e}"


# ============================================================
# Model API proxy
# ============================================================

# Cache gateway config
_openclaw_gateway: Optional[Dict[str, Any]] = None
_openclaw_gateway_checked = False


def call_model(messages: List[Dict[str, str]], config: Dict[str, Any], thinking: str = "") -> str:
    """Call the configured primary model and return the response text."""
    global _openclaw_gateway, _openclaw_gateway_checked

    framework = config.get("framework", "standalone")
    models = config.get("models", {})
    primary = models.get("primary", {})
    provider = primary.get("provider", "openai")
    model = primary.get("model", "gpt-5.4")
    api_key_env = primary.get("api_key_env", "OPENAI_API_KEY")
    api_key = str(primary.get("api_key") or os.environ.get(api_key_env, "") or "").strip()
    base_url = primary.get("base_url", "")

    # If using OpenClaw, prefer the local gateway so the selected model is honored.
    if framework == "openclaw":
        if not _openclaw_gateway_checked:
            _openclaw_gateway = _load_openclaw_gateway_config()
            _openclaw_gateway_checked = True
        if _openclaw_gateway:
            gateway_reply = _call_openclaw_gateway(messages, model, _openclaw_gateway, thinking=thinking or "low")
            if gateway_reply and not gateway_reply.startswith("Error calling OpenClaw gateway:"):
                return gateway_reply
        # Compose messages into a single prompt for the CLI
        system_text = ""
        user_text = ""
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            elif m["role"] == "user":
                user_text = m["content"]
            elif m["role"] == "assistant":
                pass  # CLI doesn't support multi-turn, last user msg is what matters
        # Use the last user message with system context prepended
        if system_text:
            full_msg = f"System context:\n{system_text}\n\nUser:\n{user_text}"
        else:
            full_msg = user_text
        return _call_openclaw_cli_with_thinking(full_msg, thinking=thinking or "low")

    # Direct API calls for non-OpenClaw frameworks
    if provider in ("openai", "openrouter"):
        return _call_openai_compatible(messages, model, api_key, base_url or (
            "https://api.openai.com/v1" if provider == "openai" else "https://openrouter.ai/api/v1"
        ))
    elif provider == "anthropic":
        return _call_anthropic(messages, model, api_key, base_url)
    elif provider == "ollama":
        return _call_ollama(messages, model, base_url or "http://localhost:11434")
    else:
        return _call_openai_compatible(messages, model, api_key, base_url or "https://api.openai.com/v1")


def _call_openai_compatible(messages: List[Dict], model: str, api_key: str, base_url: str) -> str:
    import urllib.request
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "max_tokens": 2000}).encode()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"Error calling model: {e}"


def _call_anthropic(messages: List[Dict], model: str, api_key: str, base_url: str = "") -> str:
    import urllib.request
    system_msg = ""
    chat_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            chat_msgs.append(m)
    body = json.dumps({"model": model, "max_tokens": 2000, "system": system_msg, "messages": chat_msgs}).encode()
    headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
    endpoint = (base_url or "https://api.anthropic.com").rstrip("/")
    req = urllib.request.Request(f"{endpoint}/v1/messages", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return "".join(b.get("text", "") for b in data.get("content", []))
    except Exception as e:
        return f"Error calling model: {e}"


def _call_ollama(messages: List[Dict], model: str, base_url: str) -> str:
    import urllib.request
    body = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/chat", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("message", {}).get("content", "")
    except Exception as e:
        return f"Error calling model: {e}"


# ============================================================
# Identity state — tracks multi-brain setup progress
# ============================================================

completed_brains: List[Dict[str, Any]] = []
current_brain_index: int = 0
SETUP_VAULT_FOLDERS = ("inbox", "daily", "decisions", "patterns", "projects", "entities", "maps")

def total_brains() -> int:
    setup_cfg = config.get("setup", {})
    requested = setup_cfg.get("requested_brains", 0)
    try:
        requested_total = int(requested)
    except (TypeError, ValueError):
        requested_total = 0

    if requested_total > 0:
        return requested_total
    brains = config.get("brains") or []
    return len(brains) if brains else 1

def all_brains_done() -> bool:
    return len(completed_brains) >= total_brains()

def current_brain_number() -> int:
    return current_brain_index + 1


def load_saved_brains() -> List[Dict[str, Any]]:
    brains_dir = ROOT_DIR / "brains"
    if not brains_dir.exists():
        return []

    saved: List[Dict[str, Any]] = []
    for identity_path in sorted(brains_dir.glob("*/identity.json")):
        try:
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        brain_key = identity_path.parent.name
        saved.append(
            {
                "key": brain_key,
                "name": payload.get("assistant_name", brain_key),
                "role": payload.get("assistant_role", ""),
                "personality": payload.get("personality", ""),
                "focus_areas": payload.get("focus_areas", []),
            }
        )
    return saved


def _ensure_brain_vault_dirs(brain_key: str) -> None:
    vault_root = ROOT_DIR / "data" / "vault" / brain_key
    for folder in SETUP_VAULT_FOLDERS:
        (vault_root / folder).mkdir(parents=True, exist_ok=True)


def _refresh_configs_from_disk() -> None:
    global config, runtime_config
    config = load_config()
    runtime_config = load_runtime_config(str(ROOT_DIR / "config.yaml"))


def _sync_config_brains() -> None:
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        return

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    saved = load_saved_brains()
    raw["brains"] = [
        {
            "key": brain["key"],
            "name": brain["name"],
            "description": brain.get("role", ""),
        }
        for brain in saved
    ]
    setup_cfg = raw.get("setup", {})
    setup_cfg["requested_brains"] = max(total_brains(), len(saved), 1)
    raw["setup"] = setup_cfg

    with open(config_path, "w") as f:
        yaml.safe_dump(raw, f, sort_keys=False)

    _refresh_configs_from_disk()


def ensure_brain_vault_dirs(brain_key: str) -> None:
    base = ROOT_DIR / "data" / "vault" / brain_key
    for folder in ["inbox", "daily", "decisions", "patterns", "projects", "entities", "maps"]:
        (base / folder).mkdir(parents=True, exist_ok=True)


def update_config_brain(index: int, brain_key: str, brain_name: str, description: str) -> None:
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        return
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = {}

    brains = raw.get("brains", [])
    if not isinstance(brains, list):
        brains = []
    while len(brains) <= index:
        brains.append({})

    existing = brains[index] if isinstance(brains[index], dict) else {}
    brains[index] = {
        "key": brain_key,
        "name": brain_name,
        "description": description or existing.get("description", ""),
    }
    raw["brains"] = brains
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def sync_openclaw_workspace_memory(brain_key: str) -> None:
    workspace_root = Path.home() / ".openclaw" / "workspaces" / f"{brain_key}-recall-facts"
    if not workspace_root.exists():
        return

    source_root = ROOT_DIR / "data" / "vault" / brain_key
    if not source_root.exists():
        return

    memory_root = workspace_root / "memory"
    memory_root.mkdir(parents=True, exist_ok=True)

    index_path = workspace_root / "MEMORY.md"
    if not index_path.exists():
        index_path.write_text(
            "\n".join(
                [
                    f"# {brain_key}",
                    "",
                    "This workspace is managed by Open Agentic Memory.",
                    "Durable notes are mirrored into `memory/` for OpenClaw semantic search.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    for note in source_root.rglob("*.md"):
        relative = note.relative_to(source_root)
        target = memory_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(note, target)

    if shutil.which("openclaw"):
        try:
            subprocess.run(
                ["openclaw", "--no-color", "memory", "index", "--agent", f"{brain_key}-recall-facts", "--force"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except Exception:
            pass


def reload_runtime_configuration() -> None:
    global config, runtime_config, _openclaw_gateway, _openclaw_gateway_checked
    config = load_config()
    runtime_config = load_runtime_config(str(ROOT_DIR / "config.yaml"))
    _openclaw_gateway = None
    _openclaw_gateway_checked = False
    if memory_runtime is not None:
        memory_runtime.config.brains = runtime_config.brains
        memory_runtime.config.framework = runtime_config.framework


def ensure_openclaw_registration() -> None:
    if config.get("framework", "standalone") != "openclaw":
        return

    try:
        from openclaw_setup import register_brain
    except Exception as exc:
        print(f"  OpenClaw bootstrap skipped: {exc}")
        return

    fast_model = config.get("models", {}).get("fast", {}).get("model", "gpt-5.3-codex-spark")
    desired: List[Dict[str, str]] = []
    seen = set()

    for brain in load_saved_brains():
        brain_key = str(brain.get("key", "")).strip()
        if not brain_key or brain_key in seen:
            continue
        seen.add(brain_key)
        desired.append(
            {
                "key": brain_key,
                "name": str(brain.get("name", brain_key)).strip() or brain_key,
            }
        )

    for brain in desired:
        try:
            register_brain(
                brain_key=brain["key"],
                brain_name=brain["name"],
                fast_model=fast_model,
                install_path=str(ROOT_DIR.resolve()),
            )
            sync_openclaw_workspace_memory(brain["key"])
        except Exception as exc:
            print(f"  OpenClaw bootstrap warning for {brain['key']}: {exc}")

SETUP_SYSTEM_PROMPT = """You are the Open Agentic Memory setup assistant. You are helping the user configure their new AI agent's identity.

You are having a natural conversation to gather this information:
1. What should the agent be called (name)
2. What is its primary role (executive assistant, researcher, coder, analyst, etc.)
3. What personality should it have (professional, casual, witty, direct, etc.)
4. What topics or domains should it focus on
5. Any specific tools or integrations it should know about

Be conversational and friendly. Ask one thing at a time. When you have enough info, generate the identity configuration.

When you have gathered all the information, output a JSON block wrapped in ```json``` with this structure:
{
  "complete": true,
  "identity": {
    "name": "the agent name",
    "role": "the role description",
    "personality": "personality traits",
    "focus_areas": ["area1", "area2"],
    "system_prompt": "A full system prompt incorporating all of the above"
  }
}

Until you have enough info, just chat normally. Do NOT output the JSON block until you're ready."""


# ============================================================
# FastAPI app
# ============================================================

app = FastAPI()
config = load_config()
runtime_config = load_runtime_config(str(ROOT_DIR / "config.yaml"))
memory_runtime: Optional[MemoryRuntime] = None
conversation: List[Dict[str, str]] = []
# Per-brain conversation histories for production chat
brain_conversations: Dict[str, List[Dict[str, str]]] = {}

saved_brains = load_saved_brains()
if saved_brains:
    completed_brains.extend(
        {
            "name": brain["name"],
            "role": brain.get("role", ""),
            "personality": brain.get("personality", ""),
            "focus_areas": brain.get("focus_areas", []),
        }
        for brain in saved_brains
    )
    current_brain_index = len(saved_brains)


def get_memory_runtime() -> MemoryRuntime:
    global memory_runtime
    if memory_runtime is None:
        memory_runtime = MemoryRuntime(runtime_config)
        memory_runtime.start()
    return memory_runtime


@app.on_event("startup")
async def app_startup() -> None:
    ensure_openclaw_registration()
    get_memory_runtime()


@app.on_event("shutdown")
async def app_shutdown() -> None:
    global memory_runtime
    if memory_runtime is not None:
        memory_runtime.close()
        memory_runtime = None


@app.get("/", response_class=HTMLResponse)
async def index():
    return CHAT_HTML


@app.get("/chat", response_class=HTMLResponse)
async def production_chat():
    """Serve the production chat interface."""
    chat_path = ROOT_DIR / "chat.html"
    if chat_path.exists():
        return HTMLResponse(chat_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>chat.html not found</h1>")


@app.get("/api/info")
async def info():
    models = config.get("models", {})
    brains = config.get("brains", [])
    framework = config.get("framework", "standalone")
    runtime = get_memory_runtime()

    # Load identity if it exists
    identity = {}
    identity_path = ROOT_DIR / "identity.json"
    if identity_path.exists():
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Use completed_brains if available (richer info from identity chat)
    brain_list = []
    persisted_brains = load_saved_brains()
    if persisted_brains:
        brain_list = persisted_brains
    elif completed_brains:
        for b in completed_brains:
            name = b.get("name", "Assistant")
            key = name.lower().replace(" ", "-").replace("_", "-")
            key = "".join(c for c in key if c.isalnum() or c == "-").strip("-") or "assistant"
            brain_list.append({"key": key, "name": name, "role": b.get("role", ""), "personality": b.get("personality", "")})
    else:
        brain_list = [
            brain for brain in brains
            if isinstance(brain, dict) and not _is_placeholder_brain(brain.get("key", ""), brain.get("name", ""))
        ]

    return {
        "provider": models.get("primary", {}).get("provider", "unknown"),
        "primary_model": models.get("primary", {}).get("model", "unknown"),
        "fast_model": models.get("fast", {}).get("model", "unknown"),
        "framework": framework,
        "brains": brain_list,
        "identity": identity,
        "observer": runtime.observer_snapshot(),
    }


@app.get("/api/memory")
async def api_memory_search(
    query: str = "",
    agent: str = "assistant",
    limit: int = 10,
    kind: str = "",
    date_from: str = "",
    date_to: str = "",
):
    runtime = get_memory_runtime()
    memories = runtime.search_memories(
        brain_key=agent or "assistant",
        query=query,
        limit=limit,
        kind=kind or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    return {"memories": memories}


@app.post("/api/memory")
async def api_memory_store(request: Request):
    body = await request.json()
    runtime = get_memory_runtime()
    brain_key = str(body.get("agent_key") or body.get("brain_key") or body.get("agent") or "assistant").strip() or "assistant"
    memory = runtime.store.store_memory(
        brain_key=brain_key,
        kind=str(body.get("kind") or "note"),
        source=str(body.get("source") or "manual"),
        title=str(body.get("title") or "Untitled"),
        content=str(body.get("content") or ""),
        importance=int(body.get("importance", 50) or 50),
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
        allow_duplicate=bool(body.get("allow_duplicate", False)),
    )
    return {"memory": memory, "created": True}


@app.get("/api/recall/session-context")
async def api_recall_session_context(agent: str = "assistant", window: int = 20):
    runtime = get_memory_runtime()
    return {"messages": runtime.get_session_messages(agent or "assistant", window=window)}


@app.get("/api/brain/vault/read")
async def api_brain_vault_read(agent: str = "assistant", note_path: str = ""):
    runtime = get_memory_runtime()
    if not note_path:
        return JSONResponse({"detail": "note_path is required"}, status_code=400)
    try:
        return runtime.read_vault_note(agent or "assistant", note_path)
    except FileNotFoundError:
        return JSONResponse({"detail": f"Note not found: {note_path}"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/brain/graph/search")
async def api_brain_graph_search(agent: str = "assistant", query: str = "", limit: int = 5):
    runtime = get_memory_runtime()
    notes = runtime.search_graph_notes(agent or "assistant", query=query, limit=limit)
    return {"notes": notes}


@app.post("/api/recall/invoke")
async def api_recall_invoke(request: Request):
    runtime = get_memory_runtime()
    try:
        body = await request.json()
    except Exception:
        body = {}
    query = str(request.query_params.get("query") or body.get("query") or "").strip()
    brain_key = str(request.query_params.get("agent") or body.get("agent") or body.get("brain_key") or "assistant").strip() or "assistant"
    if not query:
        return JSONResponse({"detail": "query is required"}, status_code=400)
    return runtime.invoke_deep_recall(brain_key, query)


@app.get("/api/observer/status")
async def api_observer_status():
    runtime = get_memory_runtime()
    return {"observer": runtime.observer_snapshot()}


@app.post("/api/observer/trigger")
async def api_observer_trigger(request: Request):
    runtime = get_memory_runtime()
    try:
        body = await request.json()
    except Exception:
        body = {}
    brain_key = str(request.query_params.get("agent") or body.get("agent") or body.get("brain_key") or "assistant").strip() or "assistant"
    return runtime.run_observer_cycle(brain_key, force=True)


@app.post("/api/chat")
async def chat(request: Request):
    global current_brain_index
    body = await request.json()
    user_msg = str(body.get("message", "")).strip()
    if not user_msg:
        return JSONResponse({"reply": "Please type a message."})

    mode = str(body.get("mode", "setup")).strip()
    brain_key = str(body.get("brain", "")).strip()
    runtime = get_memory_runtime()
    gate_result: Optional[Dict[str, Any]] = None
    staged_context: Optional[Dict[str, Any]] = None
    deep_recall: Optional[Dict[str, Any]] = None
    # Map reasoning level from client to OpenClaw thinking levels
    raw_reasoning = str(body.get("reasoning", "")).strip().lower()
    thinking_map = {"low": "low", "med": "mid", "high": "high", "max": "xhigh"}
    thinking_level = thinking_map.get(raw_reasoning, "")

    # Handle clear command
    if user_msg == "__clear__" and mode == "agent":
        if brain_key in brain_conversations:
            brain_conversations[brain_key].clear()
        runtime.clear_session(brain_key or "assistant")
        return JSONResponse({"reply": "", "cleared": True})

    # Choose system prompt based on mode
    if mode == "agent":
        # Production mode — use per-brain conversation and identity
        resolved_brain = brain_key or "assistant"
        if resolved_brain not in brain_conversations:
            brain_conversations[resolved_brain] = []
        brain_conv = brain_conversations[resolved_brain]
        brain_conv.append({"role": "user", "content": user_msg})
        runtime.record_session_message(resolved_brain, "user", user_msg)
        runtime.store_passive_memory(resolved_brain, user_msg)

        # Load this brain's SOUL.md
        brain_soul = ROOT_DIR / "brains" / resolved_brain / "SOUL.md"
        brain_ident = ROOT_DIR / "brains" / resolved_brain / "identity.json"
        if brain_soul.exists():
            system_prompt = brain_soul.read_text(encoding="utf-8")
        elif brain_ident.exists():
            try:
                ident = json.loads(brain_ident.read_text(encoding="utf-8"))
                system_prompt = ident.get("system_prompt", f"You are {ident.get('assistant_name', 'an AI assistant')}. {ident.get('assistant_role', '')}")
            except Exception:
                system_prompt = "You are a helpful AI assistant with agentic memory."
        else:
            system_prompt = "You are a helpful AI assistant with agentic memory."

        gate_future = runtime.executor.submit(runtime.classify_memory_need, resolved_brain, user_msg)
        light_future = runtime.executor.submit(runtime.search_memories, resolved_brain, user_msg, 6)
        staged_context = runtime.consume_staged_context(resolved_brain)
        try:
            gate_result = gate_future.result(timeout=max(3, runtime_config.agents.gate_timeout))
        except Exception:
            gate_result = {"classification": "light", "reason": "gate timeout"}
        try:
            light_results = light_future.result(timeout=6)
        except Exception:
            light_results = []

        deep_recall = None
        if gate_result.get("classification") == "deep":
            try:
                deep_recall = runtime.invoke_deep_recall(resolved_brain, user_msg)
            except Exception:
                deep_recall = None

        memory_context = runtime.format_memory_context(staged_context, light_results, deep_recall)
        if memory_context:
            system_prompt = (
                system_prompt
                + "\n\n## Memory Context\n"
                + "Use the following memory context only when it is relevant and helpful. "
                + "Do not mention that you were given hidden memory context unless the user asks.\n\n"
                + memory_context
            )
        messages = [{"role": "system", "content": system_prompt}]
    else:
        # Setup mode — identity configuration
        brain_num = current_brain_number()
        brain_total = total_brains()
        brain_context = ""
        planned_name = ""
        planned_key = ""
        brains_cfg = config.get("brains", [])
        if current_brain_index < len(brains_cfg) and isinstance(brains_cfg[current_brain_index], dict):
            planned_name = str(brains_cfg[current_brain_index].get("name", "") or "").strip()
            planned_key = str(brains_cfg[current_brain_index].get("key", "") or "").strip()
            if _is_placeholder_brain(planned_key, planned_name):
                planned_name = ""
                planned_key = ""
        if brain_total > 1:
            brain_context = f"\n\nYou are configuring chatbot {brain_num} of {brain_total}. "
            if completed_brains:
                already = ", ".join(b.get("name", "?") for b in completed_brains)
                brain_context += f"Already configured: {already}. This is a NEW, DIFFERENT chatbot with its own identity."
        if planned_name:
            brain_context += (
                f"\n\nThis chatbot is currently named {planned_name}"
                + (f" (brain key: {planned_key})" if planned_key else "")
                + ". Keep that name unless the user explicitly wants to change it."
            )
        messages = [{"role": "system", "content": SETUP_SYSTEM_PROMPT + brain_context}]

    # Use per-brain conversation for agent mode, global for setup mode
    if mode == "agent":
        messages.extend(brain_conv)
    else:
        conversation.append({"role": "user", "content": user_msg})
        messages.extend(conversation)

    reply = call_model(messages, config, thinking=thinking_level)

    if mode == "agent":
        brain_conv.append({"role": "assistant", "content": reply})
        runtime.record_session_message(resolved_brain, "assistant", reply)
        runtime.trigger_scouts(resolved_brain)
    else:
        conversation.append({"role": "assistant", "content": reply})

    # Check if identity setup is complete for this brain
    identity_complete = False
    identity_data = None
    all_done = False

    if "```json" in reply:
        try:
            json_start = reply.index("```json") + 7
            json_end = reply.index("```", json_start)
            parsed = json.loads(reply[json_start:json_end].strip())
            if parsed.get("complete"):
                identity_data = parsed.get("identity", {})
                _save_identity(identity_data)
                completed_brains.append(identity_data)
                current_brain_index += 1
                identity_complete = True
                all_done = all_brains_done()

                if not all_done:
                    # Reset conversation for next brain
                    conversation.clear()
        except (json.JSONDecodeError, ValueError):
            pass

    return JSONResponse({
        "reply": reply,
        "identity_complete": identity_complete,
        "all_brains_done": all_done,
        "identity": identity_data,
        "brains_completed": len(completed_brains),
        "brains_total": total_brains(),
        "completed_brains": [{"name": b.get("name", ""), "role": b.get("role", "")} for b in completed_brains],
        "memory_gate": gate_result if mode == "agent" else None,
        "staged_context_used": staged_context if mode == "agent" else None,
        "deep_recall": deep_recall if mode == "agent" else None,
    })


def _brain_key_from_name(name: str) -> str:
    """Convert a brain name to a clean key."""
    key = name.lower().replace(" ", "-").replace("_", "-")
    key = "".join(c for c in key if c.isalnum() or c == "-").strip("-")
    return key or "assistant"


def _is_placeholder_brain(brain_key: str, brain_name: str) -> bool:
    key = str(brain_key or "").strip().lower()
    name = str(brain_name or "").strip().lower()
    return key.startswith("brain-") and (not name or name.startswith("brain "))


def _save_identity(identity: Dict[str, Any]):
    """Save per-brain identity files."""
    install_path = ROOT_DIR
    brain_name = identity.get("name", "Assistant")
    brain_key = _brain_key_from_name(brain_name)
    brain_slot = max(0, current_brain_index)
    placeholder_key = ""
    brains_cfg = config.get("brains", [])
    if brain_slot < len(brains_cfg) and isinstance(brains_cfg[brain_slot], dict):
        placeholder_key = str(brains_cfg[brain_slot].get("key", "") or "").strip()

    # Create per-brain directory
    brain_dir = install_path / "brains" / brain_key
    brain_dir.mkdir(parents=True, exist_ok=True)

    placeholder_vault = ROOT_DIR / "data" / "vault" / placeholder_key if placeholder_key else None
    target_vault = ROOT_DIR / "data" / "vault" / brain_key
    if placeholder_vault and placeholder_key and placeholder_key != brain_key and placeholder_vault.exists():
        if not target_vault.exists():
            placeholder_vault.rename(target_vault)
        else:
            for path in placeholder_vault.rglob("*"):
                relative = path.relative_to(placeholder_vault)
                destination = target_vault / relative
                if path.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
    ensure_brain_vault_dirs(brain_key)

    # Save SOUL.md per brain
    soul_content = f"""# {brain_name}

## Role
{identity.get('role', 'AI Assistant')}

## Personality
{identity.get('personality', 'Professional and helpful')}

## Focus Areas
{chr(10).join('- ' + area for area in identity.get('focus_areas', ['General assistance']))}

## System Prompt
{identity.get('system_prompt', '')}
"""
    (brain_dir / "SOUL.md").write_text(soul_content)
    # Also write to root for backwards compat (last brain wins for single-brain setups)
    (install_path / "SOUL.md").write_text(soul_content)

    # Save identity.json per brain
    identity_json = {
        "assistant_name": brain_name,
        "assistant_role": identity.get("role", "AI Assistant"),
        "personality": identity.get("personality", ""),
        "focus_areas": identity.get("focus_areas", []),
        "brain_key": brain_key,
        "memory_mode": "agentic",
        "shared_memory": False,
    }
    (brain_dir / "identity.json").write_text(json.dumps(identity_json, indent=2))
    (install_path / "identity.json").write_text(json.dumps(identity_json, indent=2))

    update_config_brain(
        index=brain_slot,
        brain_key=brain_key,
        brain_name=brain_name,
        description=str(identity.get("role", "") or ""),
    )
    reload_runtime_configuration()

    print(f"\n  Identity saved: {identity.get('name')} — {identity.get('role')}")
    print(f"  Files: SOUL.md, identity.json")

    # Register agents in OpenClaw if that's the framework
    framework = config.get("framework", "standalone")
    if framework == "openclaw":
        try:
            from openclaw_setup import register_brain
            fast_model = config.get("models", {}).get("fast", {}).get("model", "gpt-5.3-codex-spark")
            # Use a clean brain key from the agent name
            brain_name = identity.get("name", "Assistant")
            brain_key = brain_name.lower().replace(" ", "-").replace("_", "-")
            # Remove special characters
            brain_key = "".join(c for c in brain_key if c.isalnum() or c == "-").strip("-")
            if not brain_key:
                brain_key = "assistant"

            result = register_brain(
                brain_key=brain_key,
                brain_name=brain_name,
                fast_model=fast_model,
                install_path=str(install_path.resolve()),
            )
            print(f"  OpenClaw: Registered {result['total_agents']} agents for brain '{brain_key}'")
            if result.get("created"):
                for agent_id in result["created"]:
                    print(f"    + {agent_id}")
            if result.get("skipped"):
                print(f"    (skipped {len(result['skipped'])} already existing)")
            print()
            sync_openclaw_workspace_memory(brain_key)
        except Exception as e:
            print(f"  OpenClaw registration failed: {e}")
            print(f"  You can register manually: python openclaw_setup.py register {brain_key} \"{brain_name}\" {fast_model} .")
            print()


# ============================================================
# Chat HTML — single-file, no dependencies
# ============================================================

CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Open Agentic Memory — Agent Setup</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0a0a0f;
    color: #e0e0e8;
    font-family: 'Inter', sans-serif;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
      linear-gradient(rgba(74,158,255,0.02) 1px, transparent 1px),
      linear-gradient(90deg, rgba(74,158,255,0.02) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }
  .header {
    position: relative;
    z-index: 1;
    padding: 20px 28px;
    border-bottom: 1px solid #1a1a2e;
    display: flex;
    align-items: center;
    gap: 14px;
    background: linear-gradient(180deg, #0e0e18, #0a0a12);
  }
  .header::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(74,158,255,0.3), rgba(139,92,246,0.3), transparent);
  }
  .header .dot { width: 10px; height: 10px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px rgba(16,185,129,0.5); animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.5;transform:scale(0.85)} }
  .header h1 {
    font-size: 17px;
    font-weight: 700;
    letter-spacing: -0.3px;
    background: linear-gradient(135deg, #fff 0%, #4a9eff 60%, #8b5cf6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .header .subtitle { font-size: 11px; color: #555570; margin-left: 4px; }
  .header .model-tag {
    margin-left: auto;
    font-size: 11px;
    color: #6a6a8a;
    background: rgba(255,255,255,0.04);
    border: 1px solid #1e1e2e;
    padding: 5px 12px;
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
  }
  .header .framework-tag {
    font-size: 10px;
    color: #10b981;
    background: rgba(16,185,129,0.08);
    border: 1px solid rgba(16,185,129,0.15);
    padding: 4px 10px;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 600;
  }
  .messages {
    position: relative;
    z-index: 1;
    flex: 1;
    overflow-y: auto;
    padding: 28px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .messages::-webkit-scrollbar { width: 6px; }
  .messages::-webkit-scrollbar-track { background: transparent; }
  .messages::-webkit-scrollbar-thumb { background: #2a2a3a; border-radius: 3px; }
  .msg {
    max-width: 72%;
    padding: 16px 20px;
    border-radius: 18px;
    font-size: 14px;
    line-height: 1.65;
    white-space: pre-wrap;
    word-wrap: break-word;
    animation: msgIn 0.25s ease-out;
  }
  @keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  .msg.assistant {
    align-self: flex-start;
    background: linear-gradient(135deg, #13132a, #161630);
    border: 1px solid #1e1e32;
    border-bottom-left-radius: 6px;
  }
  .msg.user {
    align-self: flex-end;
    background: linear-gradient(135deg, #1a3060, #1e2860);
    border: 1px solid #2a4a7a;
    border-bottom-right-radius: 6px;
    color: #d0d8f0;
  }
  .msg.system {
    align-self: center;
    background: rgba(16, 185, 129, 0.06);
    border: 1px solid rgba(16, 185, 129, 0.15);
    color: #10b981;
    font-size: 13px;
    max-width: 85%;
    text-align: center;
    border-radius: 12px;
    padding: 12px 20px;
  }
  .input-area {
    position: relative;
    z-index: 1;
    padding: 18px 28px;
    border-top: 1px solid #1a1a2e;
    background: linear-gradient(0deg, #0a0a12, #0e0e18);
    display: flex;
    gap: 12px;
  }
  .input-area::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(74,158,255,0.15), transparent);
  }
  .input-area input {
    flex: 1;
    background: #0c0c16;
    border: 1px solid #2a2a42;
    border-radius: 14px;
    padding: 14px 18px;
    color: #e0e0e8;
    font-size: 14px;
    font-family: 'Inter', sans-serif;
    outline: none;
    transition: border-color 0.2s;
  }
  .input-area input:focus { border-color: #4a9eff; box-shadow: 0 0 0 3px rgba(74,158,255,0.08); }
  .input-area input::placeholder { color: #444460; }
  .input-area button {
    background: linear-gradient(135deg, #4a9eff, #6366f1);
    border: none;
    border-radius: 14px;
    padding: 14px 28px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    font-family: 'Inter', sans-serif;
    transition: all 0.2s;
    letter-spacing: 0.3px;
  }
  .input-area button:hover { transform: translateY(-1px); box-shadow: 0 4px 16px rgba(74,158,255,0.25); }
  .input-area button:active { transform: translateY(0); }
  .input-area button:disabled { opacity: 0.3; cursor: not-allowed; transform: none; box-shadow: none; }
  .typing { display: flex; gap: 5px; padding: 8px 0; }
  .typing span { width: 7px; height: 7px; background: #4a9eff; border-radius: 50%; animation: typingBounce 1.2s infinite; }
  .typing span:nth-child(2) { animation-delay: 0.2s; }
  .typing span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes typingBounce { 0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-10px)} }
  .identity-complete {
    background: linear-gradient(135deg, rgba(16,185,129,0.08), rgba(16,185,129,0.03));
    border: 1px solid rgba(16,185,129,0.25);
    border-radius: 18px;
    padding: 28px;
    margin: 16px 0;
    text-align: center;
    animation: msgIn 0.4s ease-out;
  }
  .identity-complete h3 { color: #10b981; margin-bottom: 12px; font-size: 18px; }
  .identity-complete p { color: #8888a0; font-size: 13px; line-height: 1.6; }
  .identity-complete strong { color: #e0e0e8; }
</style>
</head>
<body>
<div class="header">
  <div class="dot"></div>
  <h1>Open Agentic Memory</h1>
  <span class="subtitle">Identity Setup</span>
  <span class="framework-tag" id="frameworkTag">...</span>
  <div class="model-tag" id="modelTag">connecting...</div>
</div>
<div class="messages" id="messages">
  <div class="msg system">Connecting to your model. Setting up agent identity configuration...</div>
</div>
<div class="input-area">
  <input type="text" id="input" placeholder="Type a message..." autofocus />
  <button id="send" onclick="sendMessage()">Send</button>
</div>

<script>
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  let sending = false;

  fetch('/api/info').then(r => r.json()).then(info => {
    document.getElementById('modelTag').textContent = info.primary_model + ' via ' + info.provider;
    document.getElementById('frameworkTag').textContent = info.framework;
    // Auto-start the identity setup
    doSend("Hi! I just set up Open Agentic Memory. Help me configure my agent's identity.");
  }).catch(err => {
    addMessage('system', 'Failed to connect: ' + err.message);
  });

  inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !sending) sendMessage(); });

  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || sending) return;
    inputEl.value = '';
    doSend(text);
  }

  async function doSend(text) {
    sending = true;
    sendBtn.disabled = true;
    addMessage('user', text);

    const typingEl = document.createElement('div');
    typingEl.className = 'msg assistant';
    typingEl.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
    messagesEl.appendChild(typingEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text}),
      });
      const data = await resp.json();
      typingEl.remove();

      let displayReply = data.reply || '';
      if (displayReply.includes('```json')) {
        displayReply = displayReply.replace(/```json[\\s\\S]*?```/g, '').trim();
      }
      if (displayReply) addMessage('assistant', displayReply);

      if (data.identity_complete && data.identity) {
        const doneEl = document.createElement('div');
        doneEl.className = 'identity-complete';
        const completed = data.brains_completed || 0;
        const total = data.brains_total || 1;
        const allDone = data.all_brains_done;

        if (allDone) {
          // All brains configured — show Launch
          let brainList = (data.completed_brains || []).map(b => '<strong>' + b.name + '</strong> — ' + b.role).join('<br>');
          doneEl.innerHTML = '<h3>All Chatbots Configured</h3>'
            + '<p>' + brainList + '</p>'
            + '<p style="margin-top:12px;font-size:12px;">' + completed + ' chatbot(s) with full agentic memory registered.</p>'
            + '<button onclick="window.location.href=\\'/chat\\'" style="margin-top:18px;background:linear-gradient(135deg,#10b981,#059669);border:none;border-radius:14px;padding:14px 36px;color:#fff;font-size:15px;font-weight:700;cursor:pointer;font-family:Inter,sans-serif;letter-spacing:0.3px;transition:all 0.2s;box-shadow:0 4px 16px rgba(16,185,129,0.3);" onmouseover="this.style.transform=\\'translateY(-2px)\\'" onmouseout="this.style.transform=\\'none\\'">Launch</button>';
          inputEl.placeholder = 'All configured — click Launch above';
          inputEl.disabled = true;
          sendBtn.disabled = true;
        } else {
          // More brains to configure — show Next Chatbot
          doneEl.innerHTML = '<h3>' + (data.identity.name || 'Agent') + ' Configured</h3>'
            + '<p><strong>' + (data.identity.name || 'Agent') + '</strong> — ' + (data.identity.role || '') + '</p>'
            + '<p style="margin-top:8px;color:var(--dim);">' + completed + ' of ' + total + ' chatbots done.</p>'
            + '<button onclick="startNextBrain()" style="margin-top:18px;background:linear-gradient(135deg,#4a9eff,#6366f1);border:none;border-radius:14px;padding:14px 36px;color:#fff;font-size:15px;font-weight:700;cursor:pointer;font-family:Inter,sans-serif;letter-spacing:0.3px;transition:all 0.2s;box-shadow:0 4px 16px rgba(74,158,255,0.3);" onmouseover="this.style.transform=\\'translateY(-2px)\\'" onmouseout="this.style.transform=\\'none\\'">Next Chatbot (' + (completed + 1) + ' of ' + total + ')</button>';
        }
        messagesEl.appendChild(doneEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    } catch (err) {
      typingEl.remove();
      addMessage('system', 'Connection error: ' + err.message);
    }
    sending = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }

  function addMessage(role, text) {
    const el = document.createElement('div');
    el.className = 'msg ' + role;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function startNextBrain() {
    // Clear the chat and wait for server to be ready before sending
    messagesEl.innerHTML = '';
    addMessage('system', 'Preparing next chatbot setup...');
    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.placeholder = 'Type a message...';
    inputEl.focus();
    // Give the server 3 seconds to finish saving identity + registering agents
    setTimeout(function() {
      addMessage('system', 'Ready. Configuring your next chatbot.');
      doSend("I'm ready to set up my next chatbot. This is a different agent with its own identity. Help me configure it.");
    }, 3000);
  }
</script>
</body>
</html>"""


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Open Agentic Memory server")
    parser.add_argument("--init-only", action="store_true", help="Initialize the memory runtime and exit")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    args = parser.parse_args()

    runtime = get_memory_runtime()
    if args.init_only:
        print("Open Agentic Memory runtime initialized.")
        runtime.close()
        memory_runtime = None
        sys.exit(0)

    port = int(config.get("server", {}).get("port", runtime_config.server_port))
    if not port_is_available(port):
        print(f"Open Agentic Memory expected port {port} is already in use.")
        print("Stop the existing process or change server.port in config.yaml before starting the memory API.")
        sys.exit(1)

    print(f"\n  Open Agentic Memory")
    print(f"  Starting memory + chat server on http://127.0.0.1:{port}\n")

    if not args.no_browser:
        open_browser_when_ready(port, timeout_seconds=15.0)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
