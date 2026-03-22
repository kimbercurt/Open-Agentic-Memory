# Open Agentic Memory

A multi-agent memory architecture that gives AI assistants genuine, intelligent memory — not just vector search, but real comprehension of what it remembers and why it matters.

**15 specialized agents. 4 memory modes. 0ms context recall.**

## The Problem

Traditional AI memory systems embed text and retrieve by cosine similarity. This finds similar words, but it doesn't understand what it's retrieving. It can't tell you that a topic has been escalating over three weeks, or that the user was frustrated the last time this came up, or that two separate conversations are actually about the same underlying issue.

## The Solution

Use agents to solve the memory problem. Instead of one embedding search, spin up parallel agents — each with a different perspective — to search, interpret, and pre-stage memory intelligently.

## Architecture Overview

```
MEMORY STORAGE                              MEMORY RECALL
─────────────                              ─────────────
Passive:     "Remember this" → embed       Context:  Pre-staged by scouts → 0ms
Observer:    Every 15min → 3 agents scan   Light:    Embedding search → 50ms
             extract facts, patterns,      Deep:     3 parallel agents → ~22s
             relationships automatically              facts + context + temporal
```

Open `architecture.html` in a browser for the full animated interactive architecture diagram.

## Quick Start

### One-liner (interactive setup)

```bash
git clone https://github.com/kimbercurt/Open-Agentic-Memory.git
cd Open-Agentic-Memory
bash setup.sh
```

The setup wizard walks you through:

1. **Framework** — OpenClaw (recommended), Standalone Python, LangChain, or manual
2. **Provider** — OpenAI, Anthropic, Ollama (local), OpenRouter, or custom
3. **Primary Model** — your main chatbot LLM (shows provider-specific recommendations)
4. **Fast Model** — for the 13 specialized agents (speed over depth)
5. **Embedding Provider** — auto-detects what is available on your machine; OpenClaw defaults to built-in memory search
6. **API Keys** — checks what is already set and shows what still needs to be exported
7. **Chatbots** — choose how many isolated chatbots you want; final names are set in the browser setup chat

It generates `config.yaml`, creates all vault directories, installs the Python environment, initializes the memory runtime, and can immediately launch the identity setup chat on the same server the agents use. On the OpenClaw path it also configures `memorySearch`; per-brain recall/observer agents are registered automatically as each chatbot identity is saved in the browser.

### Manual Setup

```bash
git clone https://github.com/kimbercurt/Open-Agentic-Memory.git
cd Open-Agentic-Memory
cp config.example.yaml config.yaml
# Edit config.yaml with your models and API keys
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python serve_chat.py --init-only
.venv/bin/python serve_chat.py
```

### Local Testing

To test on your own machine before publishing:

```bash
cd /path/to/Open-Agentic-Memory
bash setup.sh
```

No internet required after cloning. The setup runs entirely locally.

## The 15 Agents

### Per Brain (6 each, isolated)

| Agent | Type | Role |
|-------|------|------|
| **Recall Facts** | On-demand | Searches for explicit facts, preferences, decisions |
| **Recall Context** | On-demand | Finds implied context, tone shifts, social cues |
| **Recall Temporal** | On-demand | Reconstructs timelines, detects recurring patterns |
| **Observer Facts** | Every 15min | Extracts stated facts from conversation |
| **Observer Patterns** | Every 15min | Detects behavioral and workflow patterns |
| **Observer Relationships** | Every 15min | Tracks people dynamics and sentiment |

### Shared (3 total)

| Agent | Type | Role |
|-------|------|------|
| **Memory Gate** | Every message | Classifies: none / light / deep (~3-5s, parallel) |
| **Topic Trajectory Scout** | Between turns | Predicts next topics, pre-fetches memories |
| **Relevance Scorer Scout** | Between turns | Filters false positives, surfaces missed context |

## The 4 Memory Modes

### Mode 1: Passive Memory
User says "remember this" → content is embedded and stored immediately.

### Mode 2: Active Observation
Every 15 minutes, three observer agents scan the conversation and extract facts, patterns, and relationships the user didn't explicitly ask to save.

### Mode 3: Deep Recall
When the user asks "what do you remember about X" (or the gate classifies "deep"), three recall agents search in parallel from different perspectives — facts, context, and temporal — then merge into a ranked result.

### Mode 4: Context Recall
Between every turn, two scout agents pre-fetch and score memories in the background. The next turn gets pre-staged context at 0ms. A memory gate classifies every inbound message to route it correctly.

## Model Agnostic

This architecture works with **any models**. You need two tiers:

- **Primary model**: Any capable LLM for the main chatbot (Claude, GPT, Gemini, Llama, Mistral, etc.)
- **Fast model**: Any cheap, quick model with tool support for the 13 specialized agents (Haiku, GPT-5.3-Codex-Spark, Gemini Flash, Llama 4 Scout, etc.)

The embedding layer can use any embedding model. The vector store can be anything that does cosine similarity. The architecture is the idea — swap in whatever you have.

## Multi-Brain Isolation

Each chatbot ("brain") gets completely isolated memory:
- Own database and vector index
- Own embedding instance
- Own vault folder structure
- Own 6 dedicated agents (3 recall + 3 observer)

The 3 shared agents (gate + scouts) serve all brains. Cross-brain information transfer only happens through explicit handoff artifacts with provenance tracking.

You can add as many brains as you need. Each is a self-contained unit.

## Storage Layers

| Layer | What | How |
|-------|------|-----|
| **Vector Index** | Semantic search over memories | Qdrant, Pinecone, pgvector, FAISS, Chroma |
| **Structured DB** | Memory metadata, sessions, events | SQLite, Postgres, MySQL |
| **Knowledge Vault** | Markdown notes with frontmatter | Obsidian-compatible file structure |
| **Graph Links** | Relationships between notes | Link table for traversal |
| **Staged Buffer** | Pre-fetched context for next turn | In-memory, per-session |

## Key Design Principles

1. **Agents for comprehension, embeddings for storage.** Embed and store, but use agents with reasoning to *understand* what's being retrieved.

2. **Multiple perspectives beat single-pass search.** A fact search, a context search, and a temporal search each find different things. The merge combines them into something richer.

3. **Observation fills the gaps.** Users forget to say "remember this." Background observers catch what passive memory misses.

4. **Isolation prevents contamination.** Each brain owns its own memory. Cross-pollination only through explicit handoffs.

5. **Cheap models for recall, expensive models for reasoning.** Spend tokens where they matter.

6. **Zero-latency context.** Scouts do their work between turns. The next turn gets pre-staged context instantly.

7. **Graceful degradation.** If agents fail, fall back to embedding search. Memory never blocks conversation.

## Project Structure

```
open-agentic-memory/
├── README.md                    # This file
├── LICENSE                      # MIT
├── setup.sh                     # Interactive setup wizard
├── config.example.yaml          # Configuration template
├── architecture.html            # Animated architecture diagram
├── requirements.txt             # Python dependencies
├── serve_chat.py                # Memory API + browser chat/identity UI
├── openclaw_setup.py            # OpenClaw agent registration helper
├── agents/                      # Agent prompts (the core IP)
│   ├── recall/                  # Facts, Context, Temporal
│   ├── observer/                # Facts, Patterns, Relationships
│   └── scout/                   # Gate, Trajectory, Relevance
├── src/agentic_memory/          # Python implementation
│   ├── __init__.py
│   ├── config.py                # Configuration loader
│   └── runtime.py               # Memory runtime + orchestration
└── examples/                    # Provider-specific configs
    ├── openai/
    ├── anthropic/
    └── ollama/
```

## Examples

### OpenAI
```yaml
models:
  primary:
    provider: "openai"
    model: "gpt-5.4"
  fast:
    provider: "openai"
    model: "gpt-5.3-codex-spark"
```

### Anthropic
```yaml
models:
  primary:
    provider: "anthropic"
    model: "claude-opus-4-6"
  fast:
    provider: "anthropic"
    model: "claude-haiku-4-5"
```

### Local (Ollama)
```yaml
models:
  primary:
    provider: "ollama"
    model: "llama4:maverick"
    base_url: "http://localhost:11434"
  fast:
    provider: "ollama"
    model: "llama4:scout"
    base_url: "http://localhost:11434"
```

## License

MIT — use it for anything.

## Contributing

Issues and PRs welcome. The architecture is the core contribution — implementations in other languages and frameworks are encouraged.
