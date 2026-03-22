"""
Open Agentic Memory — Identity Setup Chat Server

A lightweight chat interface that opens in the browser after setup.
Walks the user through agent identity configuration via conversation.
Scans for an available port automatically.
"""

import json
import os
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ============================================================
# Port Scanner — find an available port
# ============================================================

def find_available_port(start: int = 8400, end: int = 8500) -> int:
    """Scan for an available port in the given range."""
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available port found between {start} and {end}")


# ============================================================
# Config loader
# ============================================================

def load_config() -> Dict[str, Any]:
    config_path = Path("config.yaml")
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


# ============================================================
# OpenClaw gateway detection
# ============================================================

def _load_openclaw_gateway_config() -> Optional[Dict[str, Any]]:
    """Load OpenClaw gateway config if available."""
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
            return {"port": port, "token": token}
    except Exception:
        pass
    return None


def _call_openclaw_gateway(messages: List[Dict], model: str, gateway: Dict[str, Any], thinking: str = "") -> str:
    """Route through the OpenClaw gateway which handles all auth."""
    import urllib.request
    port = gateway["port"]
    token = gateway["token"]
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
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
    api_key = os.environ.get(api_key_env, "")
    base_url = primary.get("base_url", "")

    # If using OpenClaw, use the CLI which properly supports --thinking
    if framework == "openclaw":
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
        return _call_anthropic(messages, model, api_key)
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


def _call_anthropic(messages: List[Dict], model: str, api_key: str) -> str:
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
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers=headers, method="POST")
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

def total_brains() -> int:
    return len(config.get("brains", [{"key": "brain-1"}]))

def all_brains_done() -> bool:
    return len(completed_brains) >= total_brains()

def current_brain_number() -> int:
    return current_brain_index + 1

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
conversation: List[Dict[str, str]] = []
# Per-brain conversation histories for production chat
brain_conversations: Dict[str, List[Dict[str, str]]] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return CHAT_HTML


@app.get("/chat", response_class=HTMLResponse)
async def production_chat():
    """Serve the production chat interface."""
    chat_path = Path("chat.html")
    if chat_path.exists():
        return HTMLResponse(chat_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>chat.html not found</h1>")


@app.get("/api/info")
async def info():
    models = config.get("models", {})
    brains = config.get("brains", [])
    framework = config.get("framework", "standalone")

    # Load identity if it exists
    identity = {}
    identity_path = Path("identity.json")
    if identity_path.exists():
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Use completed_brains if available (richer info from identity chat)
    brain_list = []
    if completed_brains:
        for b in completed_brains:
            name = b.get("name", "Assistant")
            key = name.lower().replace(" ", "-").replace("_", "-")
            key = "".join(c for c in key if c.isalnum() or c == "-").strip("-") or "assistant"
            brain_list.append({"key": key, "name": name, "role": b.get("role", ""), "personality": b.get("personality", "")})
    else:
        brain_list = brains

    return {
        "provider": models.get("primary", {}).get("provider", "unknown"),
        "primary_model": models.get("primary", {}).get("model", "unknown"),
        "fast_model": models.get("fast", {}).get("model", "unknown"),
        "framework": framework,
        "brains": brain_list,
        "identity": identity,
    }


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    user_msg = str(body.get("message", "")).strip()
    if not user_msg:
        return JSONResponse({"reply": "Please type a message."})

    mode = str(body.get("mode", "setup")).strip()
    brain_key = str(body.get("brain", "")).strip()
    # Map reasoning level from client to OpenClaw thinking levels
    raw_reasoning = str(body.get("reasoning", "")).strip().lower()
    thinking_map = {"low": "low", "med": "mid", "high": "high", "max": "xhigh"}
    thinking_level = thinking_map.get(raw_reasoning, "")

    # Handle clear command
    if user_msg == "__clear__" and mode == "agent":
        if brain_key in brain_conversations:
            brain_conversations[brain_key].clear()
        return JSONResponse({"reply": "", "cleared": True})

    # Choose system prompt based on mode
    if mode == "agent":
        # Production mode — use per-brain conversation and identity
        if brain_key not in brain_conversations:
            brain_conversations[brain_key] = []
        brain_conv = brain_conversations[brain_key]
        brain_conv.append({"role": "user", "content": user_msg})

        # Load this brain's SOUL.md
        brain_soul = Path("brains") / brain_key / "SOUL.md"
        brain_ident = Path("brains") / brain_key / "identity.json"
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
        messages = [{"role": "system", "content": system_prompt}]
    else:
        # Setup mode — identity configuration
        brain_num = current_brain_number()
        brain_total = total_brains()
        brain_context = ""
        if brain_total > 1:
            brain_context = f"\n\nYou are configuring chatbot {brain_num} of {brain_total}. "
            if completed_brains:
                already = ", ".join(b.get("name", "?") for b in completed_brains)
                brain_context += f"Already configured: {already}. This is a NEW, DIFFERENT chatbot with its own identity."
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
    else:
        conversation.append({"role": "assistant", "content": reply})

    # Check if identity setup is complete for this brain
    global current_brain_index
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
    })


def _brain_key_from_name(name: str) -> str:
    """Convert a brain name to a clean key."""
    key = name.lower().replace(" ", "-").replace("_", "-")
    key = "".join(c for c in key if c.isalnum() or c == "-").strip("-")
    return key or "assistant"


def _save_identity(identity: Dict[str, Any]):
    """Save per-brain identity files."""
    install_path = Path(".")
    brain_name = identity.get("name", "Assistant")
    brain_key = _brain_key_from_name(brain_name)

    # Create per-brain directory
    brain_dir = install_path / "brains" / brain_key
    brain_dir.mkdir(parents=True, exist_ok=True)

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
    port = find_available_port(8400, 8500)
    print(f"\n  Open Agentic Memory — Identity Setup")
    print(f"  Port {port} is available.")
    print(f"  Opening http://127.0.0.1:{port} in your browser...\n")

    # Open browser after a short delay
    import threading
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
