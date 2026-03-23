"""
Open Agentic Memory — OpenClaw Agent Registration

Registers all memory system agents into OpenClaw for a given brain.
Creates agent dirs, workspaces, copies auth, and updates openclaw.json.
"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


OPENCLAW_HOME = Path.home() / ".openclaw"
OPENCLAW_CONFIG = OPENCLAW_HOME / "openclaw.json"
MODEL_RUNNER_ID = "oam-model-runner"

# Agent templates per brain
BRAIN_AGENTS = [
    {"suffix": "recall-facts",    "name": "Facts Recall",         "theme": "Fast literal fact retrieval for memory recall.",         "tools": ["recall_search_memories", "recall_read_vault"]},
    {"suffix": "recall-context",  "name": "Context Recall",       "theme": "Implied context, tone, and social dynamics retrieval.",  "tools": ["recall_search_memories", "recall_scan_sessions", "recall_search_graph"]},
    {"suffix": "recall-temporal", "name": "Temporal Recall",      "theme": "Timeline reconstruction and pattern tracking.",         "tools": ["recall_search_memories", "recall_search_graph"]},
    {"suffix": "observer-facts",  "name": "Fact Observer",        "theme": "Background agent extracting explicit facts.",            "tools": ["observer_read_session", "observer_store_memory", "observer_check_existing"]},
    {"suffix": "observer-patterns","name": "Pattern Observer",    "theme": "Background agent detecting behavioral patterns.",       "tools": ["observer_read_session", "observer_store_memory", "observer_check_existing"]},
    {"suffix": "observer-relationships","name": "Relationship Observer","theme": "Background agent tracking relationship dynamics.","tools": ["observer_read_session", "observer_store_memory", "observer_check_existing"]},
]

# Shared agents (created once, not per-brain)
SHARED_AGENTS = [
    {"id": "oam-memory-gate",      "name": "Memory Gate",           "theme": "Fast classifier — none/light/deep for every message.", "tools": []},
    {"id": "oam-scout-trajectory", "name": "Topic Trajectory Scout","theme": "Predicts upcoming topics and pre-fetches memories.",   "tools": ["recall_search_memories", "recall_scan_sessions"]},
    {"id": "oam-scout-relevance",  "name": "Relevance Scorer",     "theme": "Scores and filters memory results for relevance.",     "tools": ["recall_search_memories", "recall_search_graph"]},
]


def _load_openclaw_config() -> Dict[str, Any]:
    if not OPENCLAW_CONFIG.exists():
        return {"agents": {"list": []}, "plugins": {"allow": [], "load": {"paths": []}, "entries": {}}}
    with open(OPENCLAW_CONFIG) as f:
        return json.load(f)


def _save_openclaw_config(config: Dict[str, Any]):
    with open(OPENCLAW_CONFIG, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _find_auth_profile() -> Optional[Path]:
    """Find an existing agent's auth-profiles.json to copy."""
    agents_dir = OPENCLAW_HOME / "agents"
    if not agents_dir.exists():
        return None
    for agent_dir in agents_dir.iterdir():
        auth_file = agent_dir / "agent" / "auth-profiles.json"
        if auth_file.exists():
            return auth_file
    return None


def _create_agent_dir(agent_id: str, fast_model: str, auth_source: Optional[Path]):
    """Create the agent directory with auth and models files."""
    agent_dir = OPENCLAW_HOME / "agents" / agent_id / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Copy auth from existing agent
    if auth_source and auth_source.exists():
        shutil.copy2(auth_source, agent_dir / "auth-profiles.json")

    # Write models.json for the fast model
    provider, model_id = "openai-codex", fast_model
    if "/" in fast_model:
        parts = fast_model.split("/", 1)
        provider, model_id = parts[0], parts[1]

    models = {
        "providers": {
            provider: {
                "baseUrl": "https://chatgpt.com/backend-api" if "codex" in provider else "https://api.openai.com/v1",
                "api": "openai-codex-responses" if "codex" in provider else "openai-completions",
                "models": [{
                    "id": model_id,
                    "name": model_id,
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 72000,
                    "maxTokens": 16000,
                }]
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(models, indent=2))

    # Create workspace
    workspace_dir = OPENCLAW_HOME / "workspaces" / agent_id
    workspace_dir.mkdir(parents=True, exist_ok=True)


def _agent_entry(agent_id: str, name: str, theme: str, fast_model: str, tools: List[str], emoji: str = "\u26a1") -> Dict[str, Any]:
    """Build an openclaw.json agent entry."""
    entry: Dict[str, Any] = {
        "id": agent_id,
        "name": agent_id,
        "workspace": str(OPENCLAW_HOME / "workspaces" / agent_id),
        "agentDir": str(OPENCLAW_HOME / "agents" / agent_id / "agent"),
        "model": fast_model,
        "identity": {
            "name": name,
            "theme": theme,
            "emoji": emoji,
        },
    }
    if tools:
        entry["tools"] = {"allow": tools}
    return entry


def _write_model_runner_workspace(agent_id: str) -> None:
    workspace_dir = OPENCLAW_HOME / "workspaces" / agent_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "AGENTS.md").write_text(
        "# AGENTS.md\n\n"
        "1. Read IDENTITY.md\n"
        "2. Read SOUL.md\n"
        "3. Treat the incoming request messages as the full source of truth for this turn.\n",
        encoding="utf-8",
    )
    (workspace_dir / "IDENTITY.md").write_text(
        "# IDENTITY.md\n\n"
        "- Name: Open Agentic Memory Model Runner\n"
        "- Role: Neutral OpenClaw gateway runner for Open Agentic Memory\n",
        encoding="utf-8",
    )
    (workspace_dir / "SOUL.md").write_text(
        "# SOUL.md\n\n"
        "You are the neutral model runner for Open Agentic Memory.\n\n"
        "Rules:\n"
        "- Follow the incoming system message exactly when one is present.\n"
        "- Do not impose your own standing persona, memory, or agenda.\n"
        "- Keep replies inside the requested format.\n"
        "- Do not mention this runner identity unless the user explicitly asks.\n",
        encoding="utf-8",
    )


def ensure_model_runner(model_name: str, install_path: str) -> Dict[str, Any]:
    config = _load_openclaw_config()
    agents_list = config.setdefault("agents", {}).setdefault("list", [])
    existing_ids = {a["id"] for a in agents_list if isinstance(a, dict) and a.get("id")}
    auth_source = _find_auth_profile()
    created = False

    if MODEL_RUNNER_ID not in existing_ids:
        _create_agent_dir(MODEL_RUNNER_ID, model_name, auth_source)
        agents_list.append(
            _agent_entry(
                agent_id=MODEL_RUNNER_ID,
                name="Model Runner",
                theme="Neutral gateway runner that obeys incoming system messages.",
                fast_model=model_name,
                tools=[],
                emoji="\U0001F3C3",
            )
        )
        created = True

    _write_model_runner_workspace(MODEL_RUNNER_ID)
    _save_openclaw_config(config)
    return {"agent_id": MODEL_RUNNER_ID, "created": created, "model": model_name, "install_path": install_path}


def register_brain(
    brain_key: str,
    brain_name: str,
    fast_model: str,
    install_path: str,
) -> Dict[str, Any]:
    """
    Register all memory agents for a brain in OpenClaw.
    Returns a summary of what was created.
    """
    runner_result = ensure_model_runner(fast_model, install_path)
    config = _load_openclaw_config()
    agents_list = config.setdefault("agents", {}).setdefault("list", [])
    existing_ids = {a["id"] for a in agents_list}
    auth_source = _find_auth_profile()

    created = []
    skipped = []
    if runner_result.get("created"):
        created.append(MODEL_RUNNER_ID)
    else:
        skipped.append(MODEL_RUNNER_ID)

    # Per-brain agents
    for tmpl in BRAIN_AGENTS:
        agent_id = f"{brain_key}-{tmpl['suffix']}"
        if agent_id in existing_ids:
            skipped.append(agent_id)
            continue

        _create_agent_dir(agent_id, fast_model, auth_source)

        emoji_map = {
            "recall-facts": "\U0001F50D", "recall-context": "\U0001F4AC", "recall-temporal": "\u23F3",
            "observer-facts": "\U0001F441\uFE0F", "observer-patterns": "\U0001F504", "observer-relationships": "\U0001F91D",
        }
        agents_list.append(_agent_entry(
            agent_id=agent_id,
            name=f"{brain_name} {tmpl['name']}",
            theme=tmpl["theme"],
            fast_model=fast_model,
            tools=tmpl["tools"],
            emoji=emoji_map.get(tmpl["suffix"], "\u26a1"),
        ))
        created.append(agent_id)

    # Shared agents (only create once)
    for tmpl in SHARED_AGENTS:
        agent_id = tmpl["id"]
        if agent_id in existing_ids:
            skipped.append(agent_id)
            continue

        _create_agent_dir(agent_id, fast_model, auth_source)
        agents_list.append(_agent_entry(
            agent_id=agent_id,
            name=tmpl["name"],
            theme=tmpl["theme"],
            fast_model=fast_model,
            tools=tmpl["tools"],
            emoji="\u26A1" if "gate" in agent_id else "\U0001F52E" if "trajectory" in agent_id else "\U0001F3AF",
        ))
        created.append(agent_id)

    # Register plugins
    plugins = config.setdefault("plugins", {})
    allow_list = plugins.setdefault("allow", [])
    load_paths = plugins.setdefault("load", {}).setdefault("paths", [])
    entries = plugins.setdefault("entries", {})

    recall_tools_path = str(Path(install_path) / "plugins" / "recall-tools")
    observer_tools_path = str(Path(install_path) / "plugins" / "observer-tools")

    # Recall tools plugin
    if "oam-recall-tools" not in allow_list:
        allow_list.append("oam-recall-tools")
    if recall_tools_path not in load_paths:
        load_paths.append(recall_tools_path)

    # Build allowed agents list for recall tools
    recall_allowed = [f"{brain_key}-recall-facts", f"{brain_key}-recall-context", f"{brain_key}-recall-temporal",
                      "oam-scout-trajectory", "oam-scout-relevance"]
    existing_recall = entries.get("oam-recall-tools", {}).get("config", {}).get("allowedAgents", [])
    merged_recall = list(set(existing_recall + recall_allowed))
    entries["oam-recall-tools"] = {
        "enabled": True,
        "config": {"baseUrl": "http://127.0.0.1:8400", "allowedAgents": merged_recall}
    }

    # Observer tools plugin
    if "oam-observer-tools" not in allow_list:
        allow_list.append("oam-observer-tools")
    if observer_tools_path not in load_paths:
        load_paths.append(observer_tools_path)

    observer_allowed = [f"{brain_key}-observer-facts", f"{brain_key}-observer-patterns", f"{brain_key}-observer-relationships"]
    existing_observer = entries.get("oam-observer-tools", {}).get("config", {}).get("allowedAgents", [])
    merged_observer = list(set(existing_observer + observer_allowed))
    entries["oam-observer-tools"] = {
        "enabled": True,
        "config": {"baseUrl": "http://127.0.0.1:8400", "allowedAgents": merged_observer}
    }

    _save_openclaw_config(config)

    return {
        "brain_key": brain_key,
        "brain_name": brain_name,
        "created": created,
        "skipped": skipped,
        "total_agents": len(created),
        "fast_model": fast_model,
    }


def unregister_brain(brain_key: str) -> Dict[str, Any]:
    """
    Remove all memory agents for a brain from OpenClaw.
    Also removes shared agents if no other OAM brains exist.
    """
    config = _load_openclaw_config()
    agents_list = config.get("agents", {}).get("list", [])

    # Find agents belonging to this brain
    brain_prefix = f"{brain_key}-"
    to_remove = [a["id"] for a in agents_list if a["id"].startswith(brain_prefix)]

    # Check if any other OAM brains exist
    shared_ids = [s["id"] for s in SHARED_AGENTS] + [MODEL_RUNNER_ID]
    other_oam = [a["id"] for a in agents_list
                 if (a["id"].startswith("oam-") or any(s in a["id"] for s in ["-recall-", "-observer-"]))
                 and not a["id"].startswith(brain_prefix)
                 and a["id"] not in shared_ids]

    # Remove shared agents too if this is the last brain
    if not other_oam:
        to_remove.extend(shared_ids)

    # Remove from agents list
    config["agents"]["list"] = [a for a in agents_list if a["id"] not in to_remove]

    # Clean up plugin entries
    plugins = config.get("plugins", {})
    entries = plugins.get("entries", {})
    for plugin_key in ["oam-recall-tools", "oam-observer-tools"]:
        if plugin_key in entries:
            allowed = entries[plugin_key].get("config", {}).get("allowedAgents", [])
            entries[plugin_key]["config"]["allowedAgents"] = [
                a for a in allowed if not a.startswith(brain_prefix)
            ]
            # Remove plugin entirely if no agents left
            if not entries[plugin_key]["config"]["allowedAgents"]:
                del entries[plugin_key]
                if plugin_key in plugins.get("allow", []):
                    plugins["allow"].remove(plugin_key)

    _save_openclaw_config(config)

    # Remove agent directories and workspaces
    removed_dirs = []
    for agent_id in to_remove:
        agent_dir = OPENCLAW_HOME / "agents" / agent_id
        workspace_dir = OPENCLAW_HOME / "workspaces" / agent_id
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
            removed_dirs.append(str(agent_dir))
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
            removed_dirs.append(str(workspace_dir))

    return {
        "brain_key": brain_key,
        "removed_agents": to_remove,
        "removed_dirs": removed_dirs,
        "shared_removed": not bool(other_oam),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python openclaw_setup.py register <brain_key> <brain_name> <fast_model> <install_path>")
        print("       python openclaw_setup.py ensure-runner <model_name> <install_path>")
        print("       python openclaw_setup.py unregister <brain_key>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "register" and len(sys.argv) >= 6:
        result = register_brain(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
        print(json.dumps(result, indent=2))
    elif cmd == "ensure-runner" and len(sys.argv) >= 4:
        result = ensure_model_runner(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))
    elif cmd == "unregister" and len(sys.argv) >= 3:
        result = unregister_brain(sys.argv[2])
        print(json.dumps(result, indent=2))
    else:
        print("Unknown command or missing arguments.")
        sys.exit(1)
