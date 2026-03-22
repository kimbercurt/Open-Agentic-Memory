#!/usr/bin/env bash
set -euo pipefail

# Open Agentic Memory — Interactive Setup
# Usage: curl -sSL https://raw.githubusercontent.com/kimbercurt/Open-Agentic-Memory/main/setup.sh | bash

REPO_URL="https://github.com/kimbercurt/Open-Agentic-Memory.git"
INSTALL_DIR="open-agentic-memory"

# Colors
BOLD='\033[1m'
DIM='\033[2m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

header() {
  echo ""
  echo -e "${BLUE}${BOLD}"
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║       Open Agentic Memory — Setup            ║"
  echo "  ║       15 agents · 4 modes · 0ms recall       ║"
  echo "  ╚══════════════════════════════════════════════╝"
  echo -e "${NC}"
}

step() {
  echo -e "${GREEN}→${NC} $1"
}

prompt() {
  echo -e "${YELLOW}?${NC} $1"
}

info() {
  echo -e "  ${DIM}$1${NC}"
}

success() {
  echo -e "${GREEN}✓${NC} $1"
}

divider() {
  echo -e "${DIM}  ──────────────────────────────────────────${NC}"
}

# ============================================================
header

# Clone if needed
if [ ! -f "config.example.yaml" ]; then
  step "Cloning repository..."
  git clone "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
    echo "  Git clone failed. Make sure git is installed."
    exit 1
  }
  cd "$INSTALL_DIR"
  success "Repository cloned."
else
  step "Already in repo directory."
fi

# ============================================================
# Step 1: Agent Framework
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 1: Agent Framework${NC}"
echo ""
echo -e "  How do you want to run the agents?"
echo ""
echo -e "  ${GREEN}${BOLD}1)${NC} ${GREEN}OpenClaw${NC} ${DIM}(recommended — easiest setup if you have it)${NC}"
echo -e "  ${BLUE}${BOLD}2)${NC} ${BLUE}Standalone Python${NC} ${DIM}(no dependencies — uses raw API calls)${NC}"
echo -e "  ${PURPLE}${BOLD}3)${NC} ${PURPLE}LangChain / LangGraph${NC} ${DIM}(if you're already in that ecosystem)${NC}"
echo -e "  ${CYAN}${BOLD}4)${NC} ${CYAN}Skip${NC} ${DIM}(just give me the prompts and config, I'll wire it myself)${NC}"
echo ""
read -p "  Select [1-4]: " FRAMEWORK_CHOICE
FRAMEWORK_CHOICE=${FRAMEWORK_CHOICE:-1}

case "$FRAMEWORK_CHOICE" in
  1) FRAMEWORK="openclaw" ;;
  2) FRAMEWORK="standalone" ;;
  3) FRAMEWORK="langchain" ;;
  4) FRAMEWORK="manual" ;;
  *) FRAMEWORK="openclaw" ;;
esac

success "Framework: $FRAMEWORK"

# ============================================================
# Step 2: Model Provider
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 2: Model Provider${NC}"
echo ""
echo -e "  Which model provider are you using?"
echo ""
echo -e "  ${GREEN}${BOLD}1)${NC} OpenAI ${DIM}(GPT-5.4, GPT-5.3-Codex-Spark, etc.)${NC}"
echo -e "  ${BLUE}${BOLD}2)${NC} Anthropic ${DIM}(Claude Opus, Claude Haiku, etc.)${NC}"
echo -e "  ${PURPLE}${BOLD}3)${NC} Ollama ${DIM}(local models — Llama 4, Mistral, etc.)${NC}"
echo -e "  ${CYAN}${BOLD}4)${NC} OpenRouter ${DIM}(access multiple providers)${NC}"
echo -e "  ${YELLOW}${BOLD}5)${NC} Other ${DIM}(I'll configure manually)${NC}"
echo ""
read -p "  Select [1-5]: " PROVIDER_CHOICE
PROVIDER_CHOICE=${PROVIDER_CHOICE:-1}

case "$PROVIDER_CHOICE" in
  1) PROVIDER="openai" ;;
  2) PROVIDER="anthropic" ;;
  3) PROVIDER="ollama" ;;
  4) PROVIDER="openrouter" ;;
  5) PROVIDER="other" ;;
  *) PROVIDER="openai" ;;
esac

success "Provider: $PROVIDER"

# ============================================================
# Step 3: Primary Model (strong reasoning)
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 3: Primary Model${NC} ${DIM}(your main chatbot — needs strong reasoning)${NC}"
echo ""

case "$PROVIDER" in
  openai)
    echo -e "  ${BOLD}1)${NC} gpt-5.4 ${DIM}(recommended — flagship)${NC}"
    echo -e "  ${BOLD}2)${NC} gpt-5.4-pro ${DIM}(max performance)${NC}"
    echo -e "  ${BOLD}3)${NC} gpt-5.3-codex ${DIM}(agentic coding)${NC}"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="gpt-5.4" ;;
      2) PRIMARY_MODEL="gpt-5.4-pro" ;;
      3) PRIMARY_MODEL="gpt-5.3-codex" ;;
      4) read -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="gpt-5.4" ;;
    esac
    ;;
  anthropic)
    echo -e "  ${BOLD}1)${NC} claude-opus-4-6 ${DIM}(recommended — maximum reasoning)${NC}"
    echo -e "  ${BOLD}2)${NC} claude-sonnet-4-6"
    echo -e "  ${BOLD}3)${NC} claude-haiku-4-5"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="claude-opus-4-6" ;;
      2) PRIMARY_MODEL="claude-sonnet-4-6" ;;
      3) PRIMARY_MODEL="claude-haiku-4-5" ;;
      4) read -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="claude-opus-4-6" ;;
    esac
    ;;
  ollama)
    echo -e "  ${BOLD}1)${NC} llama4:maverick ${DIM}(recommended — 17B active, 128 experts)${NC}"
    echo -e "  ${BOLD}2)${NC} llama4:scout ${DIM}(17B active, 16 experts, fits single H100)${NC}"
    echo -e "  ${BOLD}3)${NC} llama4:behemoth ${DIM}(288B, most powerful)${NC}"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="llama4:maverick" ;;
      2) PRIMARY_MODEL="llama4:scout" ;;
      3) PRIMARY_MODEL="llama4:behemoth" ;;
      4) read -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="llama4:maverick" ;;
    esac
    ;;
  openrouter)
    echo -e "  ${BOLD}1)${NC} openai/gpt-5.4 ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} anthropic/claude-opus-4-6"
    echo -e "  ${BOLD}3)${NC} google/gemini-3.1-pro"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="openai/gpt-5.4" ;;
      2) PRIMARY_MODEL="anthropic/claude-opus-4-6" ;;
      3) PRIMARY_MODEL="google/gemini-3.1-pro" ;;
      4) read -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="openai/gpt-5.4" ;;
    esac
    ;;
  *)
    read -p "  Enter primary model name: " PRIMARY_MODEL
    PRIMARY_MODEL=${PRIMARY_MODEL:-"gpt-5.4"}
    ;;
esac

success "Primary model: $PRIMARY_MODEL"

# ============================================================
# Step 4: Fast Model (for the 13 specialized agents)
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 4: Fast Model${NC} ${DIM}(for recall, observer, gate, scout agents — speed matters)${NC}"
echo ""

case "$PROVIDER" in
  openai)
    echo -e "  ${BOLD}1)${NC} gpt-5.3-codex-spark ${DIM}(recommended — real-time, 128k context, 1000+ tok/s)${NC}"
    echo -e "  ${BOLD}2)${NC} gpt-5.4-mini ${DIM}(fast variant)${NC}"
    echo -e "  ${BOLD}3)${NC} gpt-5.4-nano ${DIM}(cheapest)${NC}"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -p "  Select [1-4]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="gpt-5.3-codex-spark" ;;
      2) FAST_MODEL="gpt-5.4-mini" ;;
      3) FAST_MODEL="gpt-5.4-nano" ;;
      4) read -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="gpt-5.3-codex-spark" ;;
    esac
    ;;
  anthropic)
    echo -e "  ${BOLD}1)${NC} claude-haiku-4-5 ${DIM}(recommended — fastest Claude)${NC}"
    echo -e "  ${BOLD}2)${NC} claude-sonnet-4-6"
    echo -e "  ${BOLD}3)${NC} Custom"
    read -p "  Select [1-3]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="claude-haiku-4-5" ;;
      2) FAST_MODEL="claude-sonnet-4-6" ;;
      3) read -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="claude-haiku-4-5" ;;
    esac
    ;;
  ollama)
    echo -e "  ${BOLD}1)${NC} llama4:scout ${DIM}(recommended — fast, 10M context)${NC}"
    echo -e "  ${BOLD}2)${NC} mistral-small"
    echo -e "  ${BOLD}3)${NC} Custom"
    read -p "  Select [1-3]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="llama4:scout" ;;
      2) FAST_MODEL="mistral-small" ;;
      3) read -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="llama4:scout" ;;
    esac
    ;;
  openrouter)
    echo -e "  ${BOLD}1)${NC} openai/gpt-5.3-codex-spark ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} anthropic/claude-haiku-4-5"
    echo -e "  ${BOLD}3)${NC} google/gemini-3-flash"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -p "  Select [1-4]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="openai/gpt-5.3-codex-spark" ;;
      2) FAST_MODEL="anthropic/claude-haiku-4-5" ;;
      3) FAST_MODEL="google/gemini-3-flash" ;;
      4) read -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="openai/gpt-5.3-codex-spark" ;;
    esac
    ;;
  *)
    read -p "  Enter fast model name: " FAST_MODEL
    FAST_MODEL=${FAST_MODEL:-"gpt-5.3-codex-spark"}
    ;;
esac

success "Fast model: $FAST_MODEL"

# ============================================================
# Step 5: Embedding Model
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 5: Embedding Model${NC} ${DIM}(for semantic memory search)${NC}"
echo ""

case "$PROVIDER" in
  openai|openrouter)
    echo -e "  ${BOLD}1)${NC} text-embedding-3-small ${DIM}(recommended — fast, cheap, 1536 dims)${NC}"
    echo -e "  ${BOLD}2)${NC} text-embedding-3-large ${DIM}(3072 dims, more accurate)${NC}"
    echo -e "  ${BOLD}3)${NC} Custom"
    read -p "  Select [1-3]: " EM_CHOICE
    case "$EM_CHOICE" in
      1) EMBED_MODEL="text-embedding-3-small"; EMBED_DIMS=1536; EMBED_PROVIDER="openai" ;;
      2) EMBED_MODEL="text-embedding-3-large"; EMBED_DIMS=3072; EMBED_PROVIDER="openai" ;;
      3) read -p "  Model name: " EMBED_MODEL; read -p "  Dimensions: " EMBED_DIMS; EMBED_PROVIDER="openai" ;;
      *) EMBED_MODEL="text-embedding-3-small"; EMBED_DIMS=1536; EMBED_PROVIDER="openai" ;;
    esac
    ;;
  anthropic)
    echo -e "  ${DIM}Anthropic doesn't offer embeddings. Using OpenAI for embeddings.${NC}"
    echo -e "  ${BOLD}1)${NC} text-embedding-3-small ${DIM}(needs OPENAI_API_KEY)${NC}"
    echo -e "  ${BOLD}2)${NC} Use Ollama locally instead ${DIM}(no extra API key)${NC}"
    read -p "  Select [1-2]: " EM_CHOICE
    case "$EM_CHOICE" in
      1) EMBED_MODEL="text-embedding-3-small"; EMBED_DIMS=1536; EMBED_PROVIDER="openai" ;;
      2) EMBED_MODEL="nomic-embed-text"; EMBED_DIMS=768; EMBED_PROVIDER="ollama" ;;
      *) EMBED_MODEL="text-embedding-3-small"; EMBED_DIMS=1536; EMBED_PROVIDER="openai" ;;
    esac
    ;;
  ollama)
    echo -e "  ${BOLD}1)${NC} nomic-embed-text ${DIM}(recommended — 768 dims, runs locally)${NC}"
    echo -e "  ${BOLD}2)${NC} mxbai-embed-large ${DIM}(1024 dims)${NC}"
    echo -e "  ${BOLD}3)${NC} Custom"
    read -p "  Select [1-3]: " EM_CHOICE
    case "$EM_CHOICE" in
      1) EMBED_MODEL="nomic-embed-text"; EMBED_DIMS=768; EMBED_PROVIDER="ollama" ;;
      2) EMBED_MODEL="mxbai-embed-large"; EMBED_DIMS=1024; EMBED_PROVIDER="ollama" ;;
      3) read -p "  Model name: " EMBED_MODEL; read -p "  Dimensions: " EMBED_DIMS; EMBED_PROVIDER="ollama" ;;
      *) EMBED_MODEL="nomic-embed-text"; EMBED_DIMS=768; EMBED_PROVIDER="ollama" ;;
    esac
    ;;
  *)
    read -p "  Embedding model name: " EMBED_MODEL
    read -p "  Dimensions: " EMBED_DIMS
    EMBED_PROVIDER="openai"
    ;;
esac

success "Embedding: $EMBED_MODEL ($EMBED_DIMS dims via $EMBED_PROVIDER)"

# ============================================================
# Step 6: API Key
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 6: API Key${NC}"
echo ""

API_KEY_ENV=""
case "$PROVIDER" in
  openai)     API_KEY_ENV="OPENAI_API_KEY" ;;
  anthropic)  API_KEY_ENV="ANTHROPIC_API_KEY" ;;
  openrouter) API_KEY_ENV="OPENROUTER_API_KEY" ;;
  ollama)     API_KEY_ENV="" ;;
  *)          API_KEY_ENV="API_KEY" ;;
esac

if [ -n "$API_KEY_ENV" ]; then
  EXISTING_KEY="${!API_KEY_ENV:-}"
  if [ -n "$EXISTING_KEY" ]; then
    success "$API_KEY_ENV is already set in your environment."
  else
    echo -e "  ${DIM}Set your API key before running:${NC}"
    echo -e "  ${WHITE}export $API_KEY_ENV=your-key-here${NC}"
    echo ""
  fi
else
  info "Ollama runs locally — no API key needed."
fi

# Handle embedding API key if different provider
EMBED_KEY_ENV=""
if [ "$EMBED_PROVIDER" = "openai" ] && [ "$PROVIDER" != "openai" ]; then
  EMBED_KEY_ENV="OPENAI_API_KEY"
  EXISTING_EMBED_KEY="${!EMBED_KEY_ENV:-}"
  if [ -z "$EXISTING_EMBED_KEY" ]; then
    echo -e "  ${DIM}Embeddings use OpenAI — also set:${NC}"
    echo -e "  ${WHITE}export OPENAI_API_KEY=your-key-here${NC}"
    echo ""
  fi
fi

# ============================================================
# Step 7: Number of Brains
# ============================================================
divider
echo ""
echo -e "${WHITE}${BOLD}  Step 7: How many chatbots?${NC}"
echo ""
echo -e "  ${DIM}Each chatbot gets its own isolated memory. You'll name them in the next step.${NC}"
echo ""
read -p "  Number of chatbots [1]: " NUM_BRAINS
NUM_BRAINS=${NUM_BRAINS:-1}

# Generate placeholder brain configs — names will be set during identity chat
BRAIN_CONFIGS=""
for i in $(seq 1 "$NUM_BRAINS"); do
  BRAIN_CONFIGS="$BRAIN_CONFIGS
  - key: \"brain-$i\"
    name: \"Brain $i\"
    description: \"\""
done

success "$NUM_BRAINS chatbot(s). You'll name and configure them in the identity chat."

# ============================================================
# Generate config.yaml
# ============================================================
divider
echo ""
step "Generating config.yaml..."

BASE_URL=""
EMBED_ENDPOINT=""
case "$PROVIDER" in
  ollama) BASE_URL="http://localhost:11434" ;;
esac
case "$EMBED_PROVIDER" in
  ollama) EMBED_ENDPOINT="http://localhost:11434/api/embed" ;;
esac

cat > config.yaml << CONFIGEOF
# Open Agentic Memory — Generated Configuration
# Framework: $FRAMEWORK
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

models:
  primary:
    provider: "$PROVIDER"
    model: "$PRIMARY_MODEL"
    api_key_env: "${API_KEY_ENV:-none}"
    base_url: "$BASE_URL"
  fast:
    provider: "$PROVIDER"
    model: "$FAST_MODEL"
    api_key_env: "${API_KEY_ENV:-none}"
    base_url: "$BASE_URL"
    thinking: "high"

embedding:
  provider: "$EMBED_PROVIDER"
  model: "$EMBED_MODEL"
  api_key_env: "${EMBED_KEY_ENV:-$API_KEY_ENV}"
  endpoint: "$EMBED_ENDPOINT"
  dimensions: $EMBED_DIMS

storage:
  vector:
    backend: "qdrant"
    path: "./data/vector"
  database:
    backend: "sqlite"
    path: "./data/memory.db"
  vault:
    path: "./data/vault"

brains:
$BRAIN_CONFIGS

agents:
  recall:
    enabled: true
    timeout_seconds: 90
    merge_limit: 8
  observer:
    enabled: true
    interval_seconds: 900
    min_messages: 3
    max_observations_per_cycle: 10
  gate:
    enabled: true
    timeout_seconds: 15
  scouts:
    enabled: true
    timeout_seconds: 45

framework: "$FRAMEWORK"

server:
  host: "127.0.0.1"
  port: 8400
CONFIGEOF

success "config.yaml generated."

# ============================================================
# Create data directories
# ============================================================
step "Creating data directories..."
mkdir -p data/vector

for brain_line in $(echo "$BRAIN_CONFIGS" | grep 'key:' | sed 's/.*key: "\(.*\)"/\1/'); do
  mkdir -p "data/vault/$brain_line/inbox"
  mkdir -p "data/vault/$brain_line/daily"
  mkdir -p "data/vault/$brain_line/decisions"
  mkdir -p "data/vault/$brain_line/patterns"
  mkdir -p "data/vault/$brain_line/projects"
  mkdir -p "data/vault/$brain_line/entities"
  mkdir -p "data/vault/$brain_line/maps"
done
success "Data directories created."

# ============================================================
# Python environment
# ============================================================
step "Setting up Python environment..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv 2>/dev/null || {
    echo "  Python 3 venv creation failed. Make sure python3 is installed."
    exit 1
  }
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt 2>/dev/null
success "Python environment ready."

# ============================================================
# Framework-specific setup
# ============================================================
if [ "$FRAMEWORK" = "openclaw" ]; then
  divider
  step "Setting up OpenClaw agents..."

  if command -v openclaw &>/dev/null; then
    success "OpenClaw found: $(which openclaw)"
    info "Run 'openclaw agent --list' to verify agents are registered."
  else
    echo -e "  ${YELLOW}OpenClaw not found in PATH.${NC}"
    info "Install OpenClaw first, then re-run setup."
    info "Docs: https://openclaw.dev"
  fi
fi

# ============================================================
# Generate the implementation prompt for the user's coding agent
# ============================================================
INSTALL_PATH="$(pwd)"

cat > NEXT_STEPS.md << NEXTEOF
# Open Agentic Memory — Implementation Guide

## Your Configuration
- **Framework:** $FRAMEWORK
- **Provider:** $PROVIDER
- **Primary Model:** $PRIMARY_MODEL
- **Fast Model:** $FAST_MODEL
- **Embedding:** $EMBED_MODEL ($EMBED_DIMS dims)
- **Brains:** $NUM_BRAINS
- **Install Path:** $INSTALL_PATH

## What Was Created
- \`config.yaml\` — your full configuration
- \`data/vault/\` — knowledge graph vault with folder structure per brain
- \`data/vector/\` — vector index directory
- \`agents/\` — all 9 agent prompt files (recall, observer, scout)
- \`.venv/\` — Python environment

## Next Step: Hand This to Your Coding Agent

Copy the prompt below and paste it into your coding agent (Claude Code, Codex, Cursor, etc.).
It will read your config file, the agent prompts, and the architecture, then wire everything
into your existing project.

---

### The Prompt

\`\`\`
I have set up the Open Agentic Memory system at $INSTALL_PATH.

Read these files to understand the architecture:
- $INSTALL_PATH/config.yaml (my configuration)
- $INSTALL_PATH/README.md (full architecture overview)
- $INSTALL_PATH/agents/recall/facts.md (recall facts agent prompt)
- $INSTALL_PATH/agents/recall/context.md (recall context agent prompt)
- $INSTALL_PATH/agents/recall/temporal.md (recall temporal agent prompt)
- $INSTALL_PATH/agents/observer/facts.md (observer facts agent prompt)
- $INSTALL_PATH/agents/observer/patterns.md (observer patterns agent prompt)
- $INSTALL_PATH/agents/observer/relationships.md (observer relationships agent prompt)
- $INSTALL_PATH/agents/scout/gate.md (memory gate agent prompt)
- $INSTALL_PATH/agents/scout/trajectory.md (topic trajectory scout prompt)
- $INSTALL_PATH/agents/scout/relevance.md (relevance scorer scout prompt)

Here is what I need you to implement:

1. MEMORY STORE: Set up a SQLite database at $INSTALL_PATH/data/memory.db with a memories table (id, brain_key, kind, source, title, content, content_hash, embedding_json, importance, created_at, updated_at). Set up a vector index at $INSTALL_PATH/data/vector/ using Qdrant for $EMBED_DIMS-dimensional vectors from $EMBED_MODEL via $EMBED_PROVIDER.

2. MEMORY API: Create a FastAPI server (host 127.0.0.1, port 8400) with these endpoints:
   - GET /api/memory?query=&agent=&limit= (search memories by embedding similarity + text match)
   - POST /api/memory (store a new memory with embedding)
   - GET /api/recall/session-context?agent=&window= (return last N messages from session state)
   - GET /api/brain/vault/read?agent=&note_path= (read a vault markdown note)
   - GET /api/brain/graph/search?agent=&query= (search graph notes)
   - POST /api/recall/invoke?query=&agent= (trigger deep recall manually)
   - GET /api/observer/status (observer worker status)
   - POST /api/observer/trigger?agent= (trigger observer manually)

3. RECALL ORCHESTRATION: When deep recall is triggered, spawn 3 parallel agents using $FAST_MODEL with these prompts from the agents/recall/ directory. Each agent gets tool access to the memory API. Run them in parallel via ThreadPoolExecutor, parse their JSON responses, merge and deduplicate findings, return top 8 ranked results.

4. OBSERVER WORKER: Run 3 parallel observer agents every 15 minutes using $FAST_MODEL with prompts from agents/observer/. They read session messages, check for duplicate memories, and store new observations. Run as a background thread.

5. MEMORY GATE: On every inbound message, run the gate agent (agents/scout/gate.md) using $FAST_MODEL with no tools — just classify the message as none/light/deep. Run in parallel with the response, don't block.

6. CONTEXT SCOUTS: After every response is sent, spawn 2 scout agents in background using $FAST_MODEL with prompts from agents/scout/. They pre-fetch and score memories, writing results to a staged buffer. The next turn consumes the staged buffer at 0ms.

7. CHAT INTEGRATION: Wire the memory system into the chat handler:
   - On message received: consume staged context from scouts, run gate in parallel, do embedding search
   - If gate says "deep": trigger full 3-agent recall
   - After response sent: spawn scouts in background for next turn

My primary chatbot model is $PRIMARY_MODEL via $PROVIDER.
The fast model for all 13 specialized agents is $FAST_MODEL via $PROVIDER.

The vault is at $INSTALL_PATH/data/vault/ with folders: inbox, daily, decisions, patterns, projects, entities, maps.
\`\`\`
NEXTEOF

success "Implementation guide saved to NEXT_STEPS.md"

# ============================================================
# Summary
# ============================================================
divider
echo ""
echo -e "${GREEN}${BOLD}  ╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}  ║           Setup complete!                    ║${NC}"
echo -e "${GREEN}${BOLD}  ╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${WHITE}Your Configuration:${NC}"
echo -e "    Framework:    ${CYAN}$FRAMEWORK${NC}"
echo -e "    Provider:     ${CYAN}$PROVIDER${NC}"
echo -e "    Primary:      ${CYAN}$PRIMARY_MODEL${NC}"
echo -e "    Fast:         ${CYAN}$FAST_MODEL${NC}"
echo -e "    Embedding:    ${CYAN}$EMBED_MODEL ($EMBED_DIMS dims)${NC}"
echo -e "    Brains:       ${CYAN}$NUM_BRAINS${NC}"
echo -e "    Install:      ${CYAN}$INSTALL_PATH${NC}"
echo ""
divider
echo ""
echo -e "  ${WHITE}${BOLD}What to do next:${NC}"
echo ""

if [ -n "$API_KEY_ENV" ]; then
  EXISTING_KEY="${!API_KEY_ENV:-}"
  if [ -z "$EXISTING_KEY" ]; then
    echo -e "  ${YELLOW}1.${NC} Set your API key:"
    echo -e "     ${CYAN}export $API_KEY_ENV=your-key-here${NC}"
    echo ""
  fi
fi

echo -e "  ${YELLOW}${BOLD}Open your coding agent${NC} (Claude Code, Codex, Cursor, etc.) and either:"
echo ""
echo -e "  ${GREEN}Option A:${NC} Point it at the implementation guide:"
echo -e "     ${CYAN}\"Read $INSTALL_PATH/NEXT_STEPS.md and implement everything it describes.\"${NC}"
echo ""
echo -e "  ${GREEN}Option B:${NC} Copy the full prompt from NEXT_STEPS.md and paste it directly."
echo ""
echo -e "  The guide contains the exact prompt with your config, file paths, model"
echo -e "  names, and step-by-step instructions for your coding agent to wire up"
echo -e "  the entire 15-agent memory system into your project."
echo ""
divider
echo ""
echo -e "  ${WHITE}Files created:${NC}"
echo -e "    ${DIM}config.yaml${NC}          Your configuration"
echo -e "    ${DIM}NEXT_STEPS.md${NC}        Implementation prompt for your coding agent"
echo -e "    ${DIM}data/vault/*/${NC}        Knowledge graph vault directories"
echo -e "    ${DIM}agents/*/${NC}            All 9 agent prompt files"
echo -e "    ${DIM}architecture.html${NC}    Interactive architecture diagram"
echo ""
echo -e "  ${DIM}View the full architecture: ${CYAN}open architecture.html${NC}"
echo ""

# ============================================================
# Step 8: Launch Identity Setup Chat
# ============================================================
divider
echo ""
echo -e "  ${WHITE}${BOLD}Step 8: Agent Identity Setup${NC}"
echo ""
echo -e "  Would you like to open the identity setup chat?"
echo -e "  ${DIM}This opens a browser window where you can configure your agent's${NC}"
echo -e "  ${DIM}name, personality, role, and focus areas through conversation.${NC}"
echo ""
echo -e "  ${BOLD}1)${NC} Yes, open the chat ${DIM}(recommended)${NC}"
echo -e "  ${BOLD}2)${NC} No, I'll set up identity later"
echo ""
read -p "  Select [1-2]: " CHAT_CHOICE
CHAT_CHOICE=${CHAT_CHOICE:-1}

if [ "$CHAT_CHOICE" = "1" ]; then
  # Install chat server dependencies
  step "Installing chat server dependencies..."
  .venv/bin/pip install -q fastapi uvicorn 2>/dev/null
  success "Dependencies installed."

  echo ""
  echo -e "  ${GREEN}${BOLD}Launching identity setup chat...${NC}"
  echo -e "  ${DIM}A browser window will open. Chat with your agent to set up its identity.${NC}"
  echo -e "  ${DIM}Press Ctrl+C in this terminal when you're done.${NC}"
  echo ""

  .venv/bin/python serve_chat.py
else
  echo ""
  echo -e "  ${DIM}To launch identity setup later, run:${NC}"
  echo -e "  ${CYAN}.venv/bin/python serve_chat.py${NC}"
  echo ""
fi
