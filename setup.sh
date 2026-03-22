#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/kimbercurt/Open-Agentic-Memory.git"
INSTALL_DIR="open-agentic-memory"

BOLD='\033[1m'
DIM='\033[2m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

EMBED_OPTION_LABELS=()
EMBED_OPTION_PROVIDER=()
EMBED_OPTION_MODEL=()
EMBED_OPTION_DIMS=()
EMBED_OPTION_ENDPOINT=()
EMBED_OPTION_API_ENV=()
EMBED_OPTION_NOTE=()
EMBED_OPTION_OC_STRATEGY=()
EMBED_OPTION_OC_PROVIDER=()
EMBED_OPTION_OC_MODEL=()
EMBED_OPTION_OC_REMOTE_BASE=()
EMBED_OPTION_OC_LOCAL_MODEL=()

BRAIN_KEYS=()
BRAIN_NAMES=()

FRAMEWORK=""
PROVIDER=""
PRIMARY_MODEL=""
FAST_MODEL=""
PRIMARY_BASE_URL=""
API_KEY_ENV=""
PRIMARY_API_KEY_VALUE=""
PRIMARY_API_KEY_SOURCE=""

EMBED_PROVIDER=""
EMBED_MODEL=""
EMBED_DIMS="0"
EMBED_ENDPOINT=""
EMBED_KEY_ENV=""
EMBED_NOTE=""
EMBED_SELECTION_LABEL=""
EMBED_API_KEY_VALUE=""
EMBED_API_KEY_SOURCE=""

GATEWAY_ENABLED="false"
GATEWAY_BASE_URL=""
GATEWAY_PORT="0"
GATEWAY_TOKEN_ENV="OPENCLAW_GATEWAY_TOKEN"
GATEWAY_TOKEN=""
GATEWAY_PREFER_FOR_MODELS="false"

OPENCLAW_EMBED_STRATEGY="builtin"
OPENCLAW_MEMORYSEARCH_PROVIDER=""
OPENCLAW_MEMORYSEARCH_MODEL=""
OPENCLAW_MEMORYSEARCH_REMOTE_BASE=""
OPENCLAW_MEMORYSEARCH_LOCAL_MODEL=""

header() {
  echo
  echo -e "${BLUE}${BOLD}"
  echo "  =============================================="
  echo "      Open Agentic Memory - Setup"
  echo "      15 agents | 4 modes | 0ms recall"
  echo "  =============================================="
  echo -e "${NC}"
}

step() {
  echo -e "${GREEN}->${NC} $1"
}

info() {
  echo -e "  ${DIM}$1${NC}"
}

success() {
  echo -e "${GREEN}OK${NC} $1"
}

warn() {
  echo -e "${YELLOW}WARN${NC} $1"
}

divider() {
  echo -e "${DIM}  ------------------------------------------${NC}"
}

trim() {
  printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

wait_for_http_ready() {
  local url="$1"
  local tries="${2:-30}"
  local delay="${3:-0.5}"
  local count=0

  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi

  while [ "$count" -lt "$tries" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
    count=$((count + 1))
  done
  return 1
}

open_browser_url() {
  local url="$1"
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 &
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
    return 0
  fi
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$url" >/dev/null 2>&1
    return 0
  fi
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Start-Process '$url'" >/dev/null 2>&1
    return 0
  fi
  return 1
}

yaml_quote() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

json_quote() {
  python3 - "$1" <<'PY'
import json, sys
print(json.dumps(sys.argv[1]))
PY
}

slugify() {
  local raw
  raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
  if [ -z "$raw" ]; then
    raw="assistant"
  fi
  printf '%s' "$raw"
}

provider_api_key_env() {
  local provider
  provider="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$provider" in
    anthropic) printf '%s' "ANTHROPIC_API_KEY" ;;
    openai) printf '%s' "OPENAI_API_KEY" ;;
    openrouter) printf '%s' "OPENROUTER_API_KEY" ;;
    gemini|google) printf '%s' "GEMINI_API_KEY" ;;
    mistral) printf '%s' "MISTRAL_API_KEY" ;;
    voyage) printf '%s' "VOYAGE_API_KEY" ;;
    xai) printf '%s' "XAI_API_KEY" ;;
    ollama|openclaw-builtin|"") printf '%s' "" ;;
    *) printf '%s' "API_KEY" ;;
  esac
}

provider_display_name() {
  local provider
  provider="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$provider" in
    anthropic) printf '%s' "Anthropic" ;;
    openai) printf '%s' "OpenAI" ;;
    openrouter) printf '%s' "OpenRouter" ;;
    gemini|google) printf '%s' "Gemini" ;;
    mistral) printf '%s' "Mistral" ;;
    voyage) printf '%s' "Voyage" ;;
    ollama) printf '%s' "Ollama" ;;
    openclaw-builtin) printf '%s' "OpenClaw built-in" ;;
    *) printf '%s' "Provider" ;;
  esac
}

upsert_env_file() {
  local key="$1"
  local value="$2"
  local env_file="${3:-.env}"
  local temp_file=""
  local escaped=""

  [ -n "$key" ] || return 0
  touch "$env_file"
  temp_file="$(mktemp "${TMPDIR:-/tmp}/oam-env.XXXXXX")"
  grep -vE "^${key}=" "$env_file" > "$temp_file" 2>/dev/null || true
  escaped="$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf '%s="%s"\n' "$key" "$escaped" >> "$temp_file"
  mv "$temp_file" "$env_file"
}

detect_openclaw_provider_auth_source() {
  local provider="$1"
  local env_name="$2"

  python3 - "$provider" "$env_name" <<'PY'
import json
import sys
from pathlib import Path

provider = str(sys.argv[1] or "").strip().lower()
env_name = str(sys.argv[2] or "").strip()
if provider == "google":
    provider = "gemini"

aliases = {
    "anthropic": {"anthropic"},
    "openai": {"openai"},
    "openrouter": {"openrouter"},
    "gemini": {"gemini", "google"},
    "mistral": {"mistral"},
    "voyage": {"voyage"},
    "xai": {"xai"},
}.get(provider, {provider} if provider else set())

state_dir = Path.home() / ".openclaw"
config_path = state_dir / "openclaw.json"
auth_path = state_dir / "agents" / "main" / "agent" / "auth-profiles.json"

def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

cfg = load_json(config_path)
env_block = cfg.get("env", {}) if isinstance(cfg.get("env"), dict) else {}
if env_name and str(env_block.get(env_name, "") or "").strip():
    print(f"openclaw.env:{env_name}")
    raise SystemExit(0)

if not auth_path.exists():
    for candidate in (state_dir / "agents").glob("*/agent/auth-profiles.json"):
        auth_path = candidate
        break

auth_payload = load_json(auth_path)
profiles = auth_payload.get("profiles", {}) if isinstance(auth_payload.get("profiles"), dict) else {}
for profile_name, profile in profiles.items():
    if not isinstance(profile, dict):
        continue
    profile_provider = str(profile.get("provider", "") or "").strip().lower()
    if profile_provider == "google":
        profile_provider = "gemini"
    if profile_provider not in aliases:
        continue
    for field in ("token", "apiKey", "access", "password"):
        if str(profile.get(field, "") or "").strip():
            print(f"openclaw.auth:{profile_name}")
            raise SystemExit(0)
PY
}

detect_openclaw_gateway_port() {
  python3 - <<'PY'
import json
from pathlib import Path

path = Path.home() / ".openclaw" / "openclaw.json"
if not path.exists():
    raise SystemExit(0)
try:
    raw = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
gateway = raw.get("gateway", {}) if isinstance(raw.get("gateway"), dict) else {}
http = gateway.get("http", {}) if isinstance(gateway.get("http"), dict) else {}
endpoints = http.get("endpoints", {}) if isinstance(http.get("endpoints"), dict) else {}
chat = endpoints.get("chatCompletions", {}) if isinstance(endpoints.get("chatCompletions"), dict) else {}
port = gateway.get("port") or 0
if port and chat.get("enabled"):
    print(port)
PY
}

detect_openclaw_gateway_token() {
  python3 - <<'PY'
import json
import os
from pathlib import Path

token = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or os.environ.get("OPENCLAW_GATEWAY_PASSWORD") or ""
if token:
    print(token)
    raise SystemExit(0)

path = Path.home() / ".openclaw" / "openclaw.json"
if not path.exists():
    raise SystemExit(0)
try:
    raw = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
gateway = raw.get("gateway", {}) if isinstance(raw.get("gateway"), dict) else {}
auth = gateway.get("auth", {}) if isinstance(gateway.get("auth"), dict) else {}
token = str(auth.get("token", "") or auth.get("password", "") or "").strip()
if token:
    print(token)
PY
}

configure_openclaw_gateway() {
  if [ "$FRAMEWORK" != "openclaw" ]; then
    GATEWAY_ENABLED="false"
    GATEWAY_BASE_URL=""
    GATEWAY_PORT="0"
    GATEWAY_TOKEN=""
    GATEWAY_PREFER_FOR_MODELS="false"
    return 0
  fi

  GATEWAY_ENABLED="true"
  GATEWAY_PREFER_FOR_MODELS="true"
  GATEWAY_PORT="$(detect_openclaw_gateway_port || true)"
  GATEWAY_PORT="${GATEWAY_PORT:-0}"
  if [ "$GATEWAY_PORT" != "0" ]; then
    GATEWAY_BASE_URL="http://127.0.0.1:${GATEWAY_PORT}"
  else
    GATEWAY_BASE_URL=""
  fi
  GATEWAY_TOKEN="$(detect_openclaw_gateway_token || true)"
}

resolve_provider_auth_setup() {
  local provider="$1"
  local env_name="$2"
  local prompt_name="$3"
  local allow_gateway="${4:-false}"
  local openclaw_source=""

  RESOLVED_AUTH_SOURCE=""
  RESOLVED_AUTH_VALUE=""

  if [ -z "$env_name" ]; then
    RESOLVED_AUTH_SOURCE="not-needed"
    return 0
  fi

  if [ -n "${!env_name:-}" ]; then
    RESOLVED_AUTH_SOURCE="env:${env_name}"
    return 0
  fi

  if [ "$FRAMEWORK" = "openclaw" ]; then
    openclaw_source="$(detect_openclaw_provider_auth_source "$provider" "$env_name" || true)"
    if [ -n "$openclaw_source" ]; then
      RESOLVED_AUTH_SOURCE="$openclaw_source"
      return 0
    fi
  fi

  if [ "$allow_gateway" = "true" ]; then
    read -r -s -p "  Enter your ${prompt_name} API key (or press Enter to use OpenClaw's gateway for all model calls): " RESOLVED_AUTH_VALUE
  else
    read -r -s -p "  Enter your ${prompt_name} API key (optional - save it to .env for direct calls): " RESOLVED_AUTH_VALUE
  fi
  echo
  RESOLVED_AUTH_VALUE="$(trim "$RESOLVED_AUTH_VALUE")"

  if [ -n "$RESOLVED_AUTH_VALUE" ]; then
    upsert_env_file "$env_name" "$RESOLVED_AUTH_VALUE" ".env"
    export "${env_name}=${RESOLVED_AUTH_VALUE}"
    RESOLVED_AUTH_SOURCE="dotenv:${env_name}"
    return 0
  fi

  if [ "$allow_gateway" = "true" ]; then
    RESOLVED_AUTH_SOURCE="gateway"
  else
    RESOLVED_AUTH_SOURCE="missing"
  fi
}

brain_key_exists() {
  local candidate="$1"
  local existing
  for existing in "${BRAIN_KEYS[@]-}"; do
    if [ "$existing" = "$candidate" ]; then
      return 0
    fi
  done
  return 1
}

unique_brain_key() {
  local base="$1"
  local candidate="$base"
  local suffix=2
  while brain_key_exists "$candidate"; do
    candidate="${base}-${suffix}"
    suffix=$((suffix + 1))
  done
  printf '%s' "$candidate"
}

normalize_remote_base() {
  local raw
  raw="$(trim "${1:-}")"
  raw="${raw%/}"
  case "$raw" in
    */api/embed) raw="${raw%/api/embed}" ;;
    */v1/embeddings) raw="${raw%/embeddings}" ;;
    */embeddings) raw="${raw%/embeddings}" ;;
    */v1/chat/completions) raw="${raw%/chat/completions}" ;;
    */api/chat) raw="${raw%/api/chat}" ;;
  esac
  printf '%s' "$raw"
}

normalize_embedding_endpoint() {
  local provider="$1"
  local raw
  raw="$(trim "${2:-}")"
  if [ -z "$raw" ]; then
    printf '%s' ""
    return
  fi
  raw="${raw%/}"
  case "$provider" in
    ollama)
      raw="$(normalize_remote_base "$raw")"
      printf '%s/api/embed' "$raw"
      ;;
    openai|openrouter|mistral|custom)
      printf '%s' "$(normalize_remote_base "$raw")"
      ;;
    *)
      printf '%s' "$raw"
      ;;
  esac
}

append_embedding_option() {
  EMBED_OPTION_LABELS+=("$1")
  EMBED_OPTION_PROVIDER+=("$2")
  EMBED_OPTION_MODEL+=("$3")
  EMBED_OPTION_DIMS+=("$4")
  EMBED_OPTION_ENDPOINT+=("$5")
  EMBED_OPTION_API_ENV+=("$6")
  EMBED_OPTION_NOTE+=("$7")
  EMBED_OPTION_OC_STRATEGY+=("$8")
  EMBED_OPTION_OC_PROVIDER+=("$9")
  EMBED_OPTION_OC_MODEL+=("${10}")
  EMBED_OPTION_OC_REMOTE_BASE+=("${11}")
  EMBED_OPTION_OC_LOCAL_MODEL+=("${12}")
}

set_embedding_selection() {
  EMBED_PROVIDER="$1"
  EMBED_MODEL="$2"
  EMBED_DIMS="$3"
  EMBED_ENDPOINT="$4"
  EMBED_KEY_ENV="$5"
  EMBED_NOTE="$6"
  OPENCLAW_EMBED_STRATEGY="$7"
  OPENCLAW_MEMORYSEARCH_PROVIDER="$8"
  OPENCLAW_MEMORYSEARCH_MODEL="$9"
  OPENCLAW_MEMORYSEARCH_REMOTE_BASE="${10}"
  OPENCLAW_MEMORYSEARCH_LOCAL_MODEL="${11}"
  EMBED_SELECTION_LABEL="${12}"
}

scan_local_gguf_options() {
  local scan_root
  local path
  local count=0
  for scan_root in \
    "$HOME/.cache/lm-studio" \
    "$HOME/.ollama" \
    "$HOME/Library/Application Support/LM Studio" \
    "$HOME/Library/Application Support/lm-studio"
  do
    [ -d "$scan_root" ] || continue
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      count=$((count + 1))
      append_embedding_option \
        "Local GGUF - $(basename "$path") (OpenClaw local model)" \
        "openclaw-builtin" \
        "$(basename "$path")" \
        "0" \
        "" \
        "" \
        "Using OpenClaw local GGUF embeddings through native memory_search." \
        "custom" \
        "local" \
        "" \
        "" \
        "$path"
      [ "$count" -ge 5 ] && return
    done < <(find "$scan_root" -maxdepth 6 -type f \( -iname '*embed*.gguf' -o -iname 'embedding*.gguf' \) 2>/dev/null)
  done
}

scan_embedding_providers() {
  local mode="${1:-runtime}"
  local ollama_json=""
  local model_name=""
  local dims=""

  EMBED_OPTION_LABELS=()
  EMBED_OPTION_PROVIDER=()
  EMBED_OPTION_MODEL=()
  EMBED_OPTION_DIMS=()
  EMBED_OPTION_ENDPOINT=()
  EMBED_OPTION_API_ENV=()
  EMBED_OPTION_NOTE=()
  EMBED_OPTION_OC_STRATEGY=()
  EMBED_OPTION_OC_PROVIDER=()
  EMBED_OPTION_OC_MODEL=()
  EMBED_OPTION_OC_REMOTE_BASE=()
  EMBED_OPTION_OC_LOCAL_MODEL=()

  if [ "$mode" = "openclaw" ]; then
    append_embedding_option \
      "OpenClaw built-in (recommended - zero config, auto-detects available providers)" \
      "openclaw-builtin" \
      "" \
      "0" \
      "" \
      "" \
      "Using OpenClaw's native memory_search. No separate embedding config needed." \
      "builtin" \
      "" \
      "" \
      "" \
      ""
  fi

  if command -v curl >/dev/null 2>&1; then
    ollama_json="$(curl -fsS --connect-timeout 1 --max-time 2 http://localhost:11434/api/tags 2>/dev/null || true)"
  fi
  if [ -n "$ollama_json" ]; then
    while IFS='|' read -r model_name dims; do
      [ -n "$model_name" ] || continue
      dims="${dims:-0}"
      append_embedding_option \
        "Ollama - $model_name (local, running on localhost:11434)" \
        "ollama" \
        "$model_name" \
        "$dims" \
        "http://localhost:11434/api/embed" \
        "" \
        "" \
        "custom" \
        "ollama" \
        "$model_name" \
        "http://localhost:11434" \
        ""
    done < <(OLLAMA_TAGS_JSON="$ollama_json" python3 - <<'PY'
import json, os

raw = os.environ.get("OLLAMA_TAGS_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}

seen = set()
for item in payload.get("models", []):
    if not isinstance(item, dict):
        continue
    name = str(item.get("name", "")).strip()
    lower = name.lower()
    if not name or "embed" not in lower:
        continue
    if name in seen:
        continue
    seen.add(name)
    dims = "0"
    if "nomic-embed-text" in lower:
        dims = "768"
    elif "mxbai-embed-large" in lower:
        dims = "1024"
    elif "embeddinggemma" in lower:
        dims = "768"
    print(f"{name}|{dims}")
PY
)
  fi

  if [ -n "${OPENAI_API_KEY:-}" ]; then
    append_embedding_option \
      "OpenAI - text-embedding-3-small (API key found in environment)" \
      "openai" \
      "text-embedding-3-small" \
      "1536" \
      "" \
      "OPENAI_API_KEY" \
      "" \
      "custom" \
      "openai" \
      "text-embedding-3-small" \
      "https://api.openai.com/v1" \
      ""
  fi

  if [ -n "${GEMINI_API_KEY:-}" ]; then
    append_embedding_option \
      "Gemini - gemini-embedding-001 (API key found in environment)" \
      "gemini" \
      "gemini-embedding-001" \
      "768" \
      "" \
      "GEMINI_API_KEY" \
      "" \
      "custom" \
      "gemini" \
      "gemini-embedding-001" \
      "" \
      ""
  fi

  if [ -n "${VOYAGE_API_KEY:-}" ]; then
    append_embedding_option \
      "Voyage - voyage-4-lite (API key found in environment)" \
      "voyage" \
      "voyage-4-lite" \
      "1024" \
      "https://api.voyageai.com/v1/embeddings" \
      "VOYAGE_API_KEY" \
      "" \
      "custom" \
      "voyage" \
      "voyage-4-lite" \
      "https://api.voyageai.com/v1" \
      ""
  fi

  if [ -n "${MISTRAL_API_KEY:-}" ]; then
    append_embedding_option \
      "Mistral - mistral-embed (API key found in environment)" \
      "mistral" \
      "mistral-embed" \
      "0" \
      "https://api.mistral.ai/v1" \
      "MISTRAL_API_KEY" \
      "" \
      "custom" \
      "mistral" \
      "mistral-embed" \
      "https://api.mistral.ai/v1" \
      ""
  fi

  if [ "$mode" = "openclaw" ]; then
    scan_local_gguf_options
  fi

  append_embedding_option \
    "Enter custom provider manually" \
    "__manual__" \
    "" \
    "0" \
    "" \
    "" \
    "" \
    "custom" \
    "" \
    "" \
    "" \
    ""
}

prompt_custom_embedding() {
  local mode="${1:-runtime}"
  local family=""
  local model=""
  local dims=""
  local endpoint=""
  local key_env=""
  local runtime_provider=""
  local note=""
  local oc_strategy="custom"
  local oc_provider=""
  local oc_model=""
  local oc_remote=""
  local oc_local=""
  local label=""

  echo
  info "Supported families: openai, openai-compatible, openrouter, ollama, gemini, voyage, mistral"
  if [ "$mode" = "openclaw" ]; then
    info "OpenClaw-only option: local (GGUF model path)"
  fi
  read -r -p "  Provider family [openai-compatible]: " family
  family="$(trim "$family")"
  family="${family:-openai-compatible}"

  case "$family" in
    openai)
      read -r -p "  Model name [text-embedding-3-small]: " model
      model="${model:-text-embedding-3-small}"
      read -r -p "  API key env var [OPENAI_API_KEY]: " key_env
      key_env="${key_env:-OPENAI_API_KEY}"
      read -r -p "  Dimensions [1536]: " dims
      dims="${dims:-1536}"
      runtime_provider="openai"
      endpoint=""
      oc_provider="openai"
      oc_model="$model"
      oc_remote="https://api.openai.com/v1"
      label="OpenAI - $model"
      ;;
    openai-compatible|custom)
      read -r -p "  Embedding API base URL [https://api.openai.com/v1]: " endpoint
      endpoint="${endpoint:-https://api.openai.com/v1}"
      endpoint="$(normalize_embedding_endpoint "custom" "$endpoint")"
      read -r -p "  Model name [text-embedding-3-small]: " model
      model="${model:-text-embedding-3-small}"
      read -r -p "  API key env var [OPENAI_API_KEY]: " key_env
      key_env="${key_env:-OPENAI_API_KEY}"
      read -r -p "  Dimensions [1536]: " dims
      dims="${dims:-1536}"
      runtime_provider="custom"
      oc_provider="openai"
      oc_model="$model"
      oc_remote="$endpoint"
      label="Custom endpoint - $model ($endpoint)"
      ;;
    openrouter)
      read -r -p "  Model name [text-embedding-3-small]: " model
      model="${model:-text-embedding-3-small}"
      read -r -p "  API key env var [OPENROUTER_API_KEY]: " key_env
      key_env="${key_env:-OPENROUTER_API_KEY}"
      read -r -p "  Base URL [https://openrouter.ai/api/v1]: " endpoint
      endpoint="${endpoint:-https://openrouter.ai/api/v1}"
      endpoint="$(normalize_embedding_endpoint "openrouter" "$endpoint")"
      read -r -p "  Dimensions [1536]: " dims
      dims="${dims:-1536}"
      runtime_provider="openrouter"
      oc_provider="openrouter"
      oc_model="$model"
      oc_remote="$endpoint"
      label="OpenRouter - $model"
      ;;
    ollama)
      read -r -p "  Ollama base URL [http://localhost:11434]: " endpoint
      endpoint="${endpoint:-http://localhost:11434}"
      endpoint="$(normalize_remote_base "$endpoint")"
      read -r -p "  Model name [nomic-embed-text]: " model
      model="${model:-nomic-embed-text}"
      read -r -p "  Dimensions [768]: " dims
      dims="${dims:-768}"
      runtime_provider="ollama"
      key_env=""
      oc_provider="ollama"
      oc_model="$model"
      oc_remote="$endpoint"
      endpoint="${endpoint}/api/embed"
      label="Ollama - $model"
      ;;
    gemini)
      read -r -p "  Model name [gemini-embedding-001]: " model
      model="${model:-gemini-embedding-001}"
      read -r -p "  API key env var [GEMINI_API_KEY]: " key_env
      key_env="${key_env:-GEMINI_API_KEY}"
      read -r -p "  Dimensions [768]: " dims
      dims="${dims:-768}"
      read -r -p "  Custom endpoint (optional): " endpoint
      endpoint="$(trim "$endpoint")"
      runtime_provider="gemini"
      oc_provider="gemini"
      oc_model="$model"
      oc_remote=""
      label="Gemini - $model"
      ;;
    voyage)
      read -r -p "  Model name [voyage-4-lite]: " model
      model="${model:-voyage-4-lite}"
      read -r -p "  API key env var [VOYAGE_API_KEY]: " key_env
      key_env="${key_env:-VOYAGE_API_KEY}"
      read -r -p "  Dimensions [1024]: " dims
      dims="${dims:-1024}"
      read -r -p "  Endpoint [https://api.voyageai.com/v1/embeddings]: " endpoint
      endpoint="${endpoint:-https://api.voyageai.com/v1/embeddings}"
      runtime_provider="voyage"
      oc_provider="voyage"
      oc_model="$model"
      oc_remote="https://api.voyageai.com/v1"
      label="Voyage - $model"
      ;;
    mistral)
      read -r -p "  Model name [mistral-embed]: " model
      model="${model:-mistral-embed}"
      read -r -p "  API key env var [MISTRAL_API_KEY]: " key_env
      key_env="${key_env:-MISTRAL_API_KEY}"
      read -r -p "  Base URL [https://api.mistral.ai/v1]: " endpoint
      endpoint="${endpoint:-https://api.mistral.ai/v1}"
      endpoint="$(normalize_embedding_endpoint "mistral" "$endpoint")"
      read -r -p "  Dimensions [0]: " dims
      dims="${dims:-0}"
      runtime_provider="mistral"
      oc_provider="mistral"
      oc_model="$model"
      oc_remote="$endpoint"
      label="Mistral - $model"
      ;;
    local)
      if [ "$mode" != "openclaw" ]; then
        warn "Local GGUF embeddings are only supported when framework = OpenClaw."
        prompt_custom_embedding "$mode"
        return
      fi
      read -r -p "  GGUF model path: " oc_local
      oc_local="$(trim "$oc_local")"
      if [ -z "$oc_local" ]; then
        warn "A GGUF model path is required."
        prompt_custom_embedding "$mode"
        return
      fi
      runtime_provider="openclaw-builtin"
      model="$(basename "$oc_local")"
      dims="0"
      key_env=""
      endpoint=""
      note="Using OpenClaw local GGUF embeddings through native memory_search."
      oc_provider="local"
      oc_model="$oc_local"
      label="Local GGUF - $(basename "$oc_local")"
      ;;
    *)
      warn "Unknown provider family: $family"
      prompt_custom_embedding "$mode"
      return
      ;;
  esac

  set_embedding_selection \
    "$runtime_provider" \
    "$model" \
    "$dims" \
    "$endpoint" \
    "$key_env" \
    "$note" \
    "$oc_strategy" \
    "$oc_provider" \
    "$oc_model" \
    "$oc_remote" \
    "$oc_local" \
    "$label"
}

apply_scanned_embedding_choice() {
  local index="$1"
  local mode="${2:-runtime}"

  if [ "${EMBED_OPTION_PROVIDER[$index]}" = "__manual__" ]; then
    prompt_custom_embedding "$mode"
    return
  fi

  set_embedding_selection \
    "${EMBED_OPTION_PROVIDER[$index]}" \
    "${EMBED_OPTION_MODEL[$index]}" \
    "${EMBED_OPTION_DIMS[$index]}" \
    "${EMBED_OPTION_ENDPOINT[$index]}" \
    "${EMBED_OPTION_API_ENV[$index]}" \
    "${EMBED_OPTION_NOTE[$index]}" \
    "${EMBED_OPTION_OC_STRATEGY[$index]}" \
    "${EMBED_OPTION_OC_PROVIDER[$index]}" \
    "${EMBED_OPTION_OC_MODEL[$index]}" \
    "${EMBED_OPTION_OC_REMOTE_BASE[$index]}" \
    "${EMBED_OPTION_OC_LOCAL_MODEL[$index]}" \
    "${EMBED_OPTION_LABELS[$index]}"
}

choose_scanned_embedding_option() {
  local mode="${1:-runtime}"
  local total=0
  local i=0
  local choice=""

  scan_embedding_providers "$mode"
  total="${#EMBED_OPTION_LABELS[@]}"

  echo
  echo -e "  ${WHITE}Detected embedding options on this machine:${NC}"
  while [ "$i" -lt "$total" ]; do
    echo -e "    ${BOLD}$((i + 1)))${NC} ${EMBED_OPTION_LABELS[$i]}"
    i=$((i + 1))
  done
  echo
  read -r -p "  Select [1]: " choice
  choice="${choice:-1}"
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$total" ]; then
    choice=1
  fi

  apply_scanned_embedding_choice "$((choice - 1))" "$mode"
}

openclaw_config_set() {
  local path="$1"
  local value="$2"
  openclaw config set --strict-json "$path" "$value" >/dev/null
}

openclaw_config_unset() {
  local path="$1"
  openclaw config unset "$path" >/dev/null 2>&1 || true
}

apply_openclaw_memorysearch_config() {
  [ "$FRAMEWORK" = "openclaw" ] || return

  if ! command -v openclaw >/dev/null 2>&1; then
    warn "OpenClaw is not in PATH, so memorySearch could not be configured."
    return
  fi

  step "Configuring OpenClaw memory search..."
  openclaw_config_set "agents.defaults.memorySearch.enabled" "true"
  openclaw_config_set "agents.defaults.memorySearch.sources" '["memory"]'

  if [ "$OPENCLAW_EMBED_STRATEGY" = "builtin" ]; then
    openclaw_config_unset "agents.defaults.memorySearch.provider"
    openclaw_config_unset "agents.defaults.memorySearch.model"
    openclaw_config_unset "agents.defaults.memorySearch.remote"
    openclaw_config_unset "agents.defaults.memorySearch.local"
    success "OpenClaw memorySearch left in auto-detect mode."
  else
    openclaw_config_set "agents.defaults.memorySearch.provider" "$(json_quote "$OPENCLAW_MEMORYSEARCH_PROVIDER")"
    if [ -n "$OPENCLAW_MEMORYSEARCH_MODEL" ]; then
      openclaw_config_set "agents.defaults.memorySearch.model" "$(json_quote "$OPENCLAW_MEMORYSEARCH_MODEL")"
    else
      openclaw_config_unset "agents.defaults.memorySearch.model"
    fi

    if [ "$OPENCLAW_MEMORYSEARCH_PROVIDER" = "local" ]; then
      openclaw_config_unset "agents.defaults.memorySearch.model"
      openclaw_config_unset "agents.defaults.memorySearch.remote"
      openclaw_config_set "agents.defaults.memorySearch.local.modelPath" "$(json_quote "$OPENCLAW_MEMORYSEARCH_LOCAL_MODEL")"
    else
      openclaw_config_unset "agents.defaults.memorySearch.local"
      if [ -n "$OPENCLAW_MEMORYSEARCH_REMOTE_BASE" ]; then
        openclaw_config_set "agents.defaults.memorySearch.remote.baseUrl" "$(json_quote "$OPENCLAW_MEMORYSEARCH_REMOTE_BASE")"
      else
        openclaw_config_unset "agents.defaults.memorySearch.remote"
      fi
    fi
    success "OpenClaw memorySearch set to ${OPENCLAW_MEMORYSEARCH_PROVIDER}."
  fi

  if ! openclaw config validate >/dev/null 2>&1; then
    warn "OpenClaw config validation reported an issue. Review 'openclaw config validate' if search does not behave as expected."
  fi
}

header

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

divider
echo
echo -e "${WHITE}${BOLD}  Step 1: Agent Framework${NC}"
echo
echo -e "  How do you want to run the agents?"
echo
echo -e "  ${GREEN}${BOLD}1)${NC} ${GREEN}OpenClaw${NC} ${DIM}(recommended - easiest setup if you already use OpenClaw)${NC}"
echo -e "  ${BLUE}${BOLD}2)${NC} ${BLUE}Standalone Python${NC} ${DIM}(memory service runs directly from this repo)${NC}"
echo -e "  ${PURPLE}${BOLD}3)${NC} ${PURPLE}LangChain / LangGraph${NC} ${DIM}(use this repo's memory API with your existing app)${NC}"
echo -e "  ${CYAN}${BOLD}4)${NC} ${CYAN}Manual${NC} ${DIM}(generate config and service, wire it in yourself)${NC}"
echo
read -r -p "  Select [1-4]: " FRAMEWORK_CHOICE
FRAMEWORK_CHOICE="${FRAMEWORK_CHOICE:-1}"

case "$FRAMEWORK_CHOICE" in
  1) FRAMEWORK="openclaw" ;;
  2) FRAMEWORK="standalone" ;;
  3) FRAMEWORK="langchain" ;;
  4) FRAMEWORK="manual" ;;
  *) FRAMEWORK="openclaw" ;;
esac

if [ "$FRAMEWORK" = "openclaw" ] && ! command -v openclaw >/dev/null 2>&1; then
  warn "OpenClaw was selected, but the 'openclaw' CLI is not available in PATH."
  info "Install OpenClaw first, or re-run setup and choose Standalone Python."
  exit 1
fi

success "Framework: $FRAMEWORK"

divider
echo
echo -e "${WHITE}${BOLD}  Step 2: Model Provider${NC}"
echo
echo -e "  Which provider should the main chat model and fast agents use?"
echo
echo -e "  ${GREEN}${BOLD}1)${NC} OpenAI ${DIM}(GPT family)${NC}"
echo -e "  ${BLUE}${BOLD}2)${NC} Anthropic ${DIM}(Claude family)${NC}"
echo -e "  ${PURPLE}${BOLD}3)${NC} Ollama ${DIM}(local models)${NC}"
echo -e "  ${CYAN}${BOLD}4)${NC} OpenRouter ${DIM}(multi-provider routing)${NC}"
echo -e "  ${YELLOW}${BOLD}5)${NC} Other ${DIM}(manual model config)${NC}"
echo
read -r -p "  Select [1-5]: " PROVIDER_CHOICE
PROVIDER_CHOICE="${PROVIDER_CHOICE:-1}"

case "$PROVIDER_CHOICE" in
  1) PROVIDER="openai" ;;
  2) PROVIDER="anthropic" ;;
  3) PROVIDER="ollama" ;;
  4) PROVIDER="openrouter" ;;
  5) PROVIDER="other" ;;
  *) PROVIDER="openai" ;;
esac

case "$PROVIDER" in
  openai) API_KEY_ENV="OPENAI_API_KEY"; PRIMARY_BASE_URL="" ;;
  anthropic) API_KEY_ENV="ANTHROPIC_API_KEY"; PRIMARY_BASE_URL="" ;;
  ollama) API_KEY_ENV=""; PRIMARY_BASE_URL="http://localhost:11434" ;;
  openrouter) API_KEY_ENV="OPENROUTER_API_KEY"; PRIMARY_BASE_URL="https://openrouter.ai/api/v1" ;;
  other)
    read -r -p "  API key env var [API_KEY]: " API_KEY_ENV
    API_KEY_ENV="${API_KEY_ENV:-API_KEY}"
    read -r -p "  Base URL (optional): " PRIMARY_BASE_URL
    PRIMARY_BASE_URL="$(trim "$PRIMARY_BASE_URL")"
    ;;
esac

success "Provider: $PROVIDER"

divider
echo
echo -e "${WHITE}${BOLD}  Step 3: Primary Model${NC} ${DIM}(your main chatbot)${NC}"
echo

case "$PROVIDER" in
  openai)
    echo -e "  ${BOLD}1)${NC} gpt-5.4 ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} gpt-5.4-pro"
    echo -e "  ${BOLD}3)${NC} gpt-5.3-codex"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -r -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="gpt-5.4" ;;
      2) PRIMARY_MODEL="gpt-5.4-pro" ;;
      3) PRIMARY_MODEL="gpt-5.3-codex" ;;
      4) read -r -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="gpt-5.4" ;;
    esac
    ;;
  anthropic)
    echo -e "  ${BOLD}1)${NC} claude-opus-4-6 ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} claude-sonnet-4-6"
    echo -e "  ${BOLD}3)${NC} claude-haiku-4-5"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -r -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="claude-opus-4-6" ;;
      2) PRIMARY_MODEL="claude-sonnet-4-6" ;;
      3) PRIMARY_MODEL="claude-haiku-4-5" ;;
      4) read -r -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="claude-opus-4-6" ;;
    esac
    ;;
  ollama)
    echo -e "  ${BOLD}1)${NC} llama4:maverick ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} llama4:scout"
    echo -e "  ${BOLD}3)${NC} mistral-small"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -r -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="llama4:maverick" ;;
      2) PRIMARY_MODEL="llama4:scout" ;;
      3) PRIMARY_MODEL="mistral-small" ;;
      4) read -r -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="llama4:maverick" ;;
    esac
    ;;
  openrouter)
    echo -e "  ${BOLD}1)${NC} openai/gpt-5.4 ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} anthropic/claude-opus-4-6"
    echo -e "  ${BOLD}3)${NC} google/gemini-2.5-pro"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -r -p "  Select [1-4]: " PM_CHOICE
    case "$PM_CHOICE" in
      1) PRIMARY_MODEL="openai/gpt-5.4" ;;
      2) PRIMARY_MODEL="anthropic/claude-opus-4-6" ;;
      3) PRIMARY_MODEL="google/gemini-2.5-pro" ;;
      4) read -r -p "  Enter model name: " PRIMARY_MODEL ;;
      *) PRIMARY_MODEL="openai/gpt-5.4" ;;
    esac
    ;;
  *)
    read -r -p "  Enter primary model name: " PRIMARY_MODEL
    PRIMARY_MODEL="${PRIMARY_MODEL:-gpt-5.4}"
    ;;
esac

success "Primary model: $PRIMARY_MODEL"

divider
echo
echo -e "${WHITE}${BOLD}  Step 4: Fast Model${NC} ${DIM}(recall, observer, gate, scouts)${NC}"
echo

case "$PROVIDER" in
  openai)
    echo -e "  ${BOLD}1)${NC} gpt-5.3-codex-spark ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} gpt-5.4-mini"
    echo -e "  ${BOLD}3)${NC} gpt-5.4-nano"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -r -p "  Select [1-4]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="gpt-5.3-codex-spark" ;;
      2) FAST_MODEL="gpt-5.4-mini" ;;
      3) FAST_MODEL="gpt-5.4-nano" ;;
      4) read -r -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="gpt-5.3-codex-spark" ;;
    esac
    ;;
  anthropic)
    echo -e "  ${BOLD}1)${NC} claude-sonnet-4-6 ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} claude-haiku-4-5"
    echo -e "  ${BOLD}3)${NC} Custom"
    read -r -p "  Select [1-3]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="claude-sonnet-4-6" ;;
      2) FAST_MODEL="claude-haiku-4-5" ;;
      3) read -r -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="claude-sonnet-4-6" ;;
    esac
    ;;
  ollama)
    echo -e "  ${BOLD}1)${NC} llama4:scout ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} mistral-small"
    echo -e "  ${BOLD}3)${NC} Custom"
    read -r -p "  Select [1-3]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="llama4:scout" ;;
      2) FAST_MODEL="mistral-small" ;;
      3) read -r -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="llama4:scout" ;;
    esac
    ;;
  openrouter)
    echo -e "  ${BOLD}1)${NC} anthropic/claude-sonnet-4-6 ${DIM}(recommended)${NC}"
    echo -e "  ${BOLD}2)${NC} openai/gpt-5.4-mini"
    echo -e "  ${BOLD}3)${NC} google/gemini-2.5-flash"
    echo -e "  ${BOLD}4)${NC} Custom"
    read -r -p "  Select [1-4]: " FM_CHOICE
    case "$FM_CHOICE" in
      1) FAST_MODEL="anthropic/claude-sonnet-4-6" ;;
      2) FAST_MODEL="openai/gpt-5.4-mini" ;;
      3) FAST_MODEL="google/gemini-2.5-flash" ;;
      4) read -r -p "  Enter model name: " FAST_MODEL ;;
      *) FAST_MODEL="anthropic/claude-sonnet-4-6" ;;
    esac
    ;;
  *)
    read -r -p "  Enter fast model name: " FAST_MODEL
    FAST_MODEL="${FAST_MODEL:-gpt-5.3-codex-spark}"
    ;;
esac

success "Fast model: $FAST_MODEL"

divider
echo
echo -e "${WHITE}${BOLD}  Step 5: Embedding Provider${NC}"
echo

if [ "$FRAMEWORK" = "openclaw" ]; then
  echo -e "  ${BOLD}1)${NC} Use OpenClaw's built-in memory search ${DIM}(recommended - zero config, auto-detects providers)${NC}"
  echo -e "  ${BOLD}2)${NC} Use a custom embedding provider"
  echo
  read -r -p "  Select [1-2]: " EMBED_CHOICE
  EMBED_CHOICE="${EMBED_CHOICE:-1}"
  if [ "$EMBED_CHOICE" = "2" ]; then
    choose_scanned_embedding_option "openclaw-custom"
  else
    set_embedding_selection \
      "openclaw-builtin" \
      "" \
      "0" \
      "" \
      "" \
      "Using OpenClaw's native memory_search. No separate embedding config needed." \
      "builtin" \
      "" \
      "" \
      "" \
      "" \
      "OpenClaw built-in memory search"
  fi
else
  choose_scanned_embedding_option "runtime"
fi

success "Embedding: $EMBED_SELECTION_LABEL"

divider
echo
echo -e "${WHITE}${BOLD}  Step 6: API Keys${NC}"
echo

configure_openclaw_gateway

if [ "$FRAMEWORK" = "openclaw" ]; then
  info "OpenClaw will be the preferred path for all model calls when its local gateway is available."
  if [ "$GATEWAY_PORT" != "0" ]; then
    success "OpenClaw gateway detected at $GATEWAY_BASE_URL."
  else
    warn "OpenClaw gateway metadata was not detected. The runtime will still fall back to provider auth or auto-discovery."
  fi
fi

resolve_provider_auth_setup "$PROVIDER" "$API_KEY_ENV" "$(provider_display_name "$PROVIDER")" "$([ "$FRAMEWORK" = "openclaw" ] && printf '%s' "true" || printf '%s' "false")"
PRIMARY_API_KEY_VALUE="$RESOLVED_AUTH_VALUE"
PRIMARY_API_KEY_SOURCE="$RESOLVED_AUTH_SOURCE"

case "$PRIMARY_API_KEY_SOURCE" in
  env:*)
    success "$API_KEY_ENV is already set in the current environment."
    ;;
  openclaw.env:*|openclaw.auth:*)
    success "$(provider_display_name "$PROVIDER") credentials found in OpenClaw (${PRIMARY_API_KEY_SOURCE})."
    ;;
  dotenv:*)
    success "$(provider_display_name "$PROVIDER") API key saved to .env."
    ;;
  gateway)
    info "No separate $(provider_display_name "$PROVIDER") key was provided. Sub-agents will use the OpenClaw gateway."
    ;;
  not-needed)
    info "No primary provider API key is needed for this selection."
    ;;
  *)
    warn "$(provider_display_name "$PROVIDER") credentials were not detected automatically."
    if [ -n "$API_KEY_ENV" ]; then
      info "You can add one later in .env or export ${API_KEY_ENV} before starting the service."
    fi
    ;;
esac

if [ -n "$EMBED_KEY_ENV" ]; then
  if [ "$EMBED_KEY_ENV" = "$API_KEY_ENV" ] && [ "$PRIMARY_API_KEY_SOURCE" != "gateway" ] && [ "$PRIMARY_API_KEY_SOURCE" != "missing" ] && [ "$PRIMARY_API_KEY_SOURCE" != "not-needed" ]; then
    EMBED_API_KEY_VALUE="$PRIMARY_API_KEY_VALUE"
    EMBED_API_KEY_SOURCE="$PRIMARY_API_KEY_SOURCE"
  else
    resolve_provider_auth_setup "$EMBED_PROVIDER" "$EMBED_KEY_ENV" "$(provider_display_name "$EMBED_PROVIDER")" "false"
    EMBED_API_KEY_VALUE="$RESOLVED_AUTH_VALUE"
    EMBED_API_KEY_SOURCE="$RESOLVED_AUTH_SOURCE"
  fi

  case "$EMBED_API_KEY_SOURCE" in
    env:*)
      success "$EMBED_KEY_ENV is already set for embeddings."
      ;;
    openclaw.env:*|openclaw.auth:*)
      success "$(provider_display_name "$EMBED_PROVIDER") embedding credentials found in OpenClaw (${EMBED_API_KEY_SOURCE})."
      ;;
    dotenv:*)
      success "$(provider_display_name "$EMBED_PROVIDER") embedding key saved to .env."
      ;;
    not-needed)
      info "No embedding API key is needed for this selection."
      ;;
    *)
      warn "Embedding credentials were not detected automatically."
      info "Memory search will need ${EMBED_KEY_ENV} in .env or your shell if this provider requires direct API access."
      ;;
  esac
else
  EMBED_API_KEY_SOURCE="not-needed"
  info "No embedding API key is needed for this selection."
fi

if [ "$FRAMEWORK" = "openclaw" ] && [ "$PRIMARY_API_KEY_SOURCE" = "gateway" ] && [ "$GATEWAY_PORT" = "0" ]; then
  warn "You chose gateway-only model auth, but no local OpenClaw gateway port was detected yet."
  info "If sub-agents fail later, start OpenClaw's gateway or add ${API_KEY_ENV} to .env."
fi

divider
echo
echo -e "${WHITE}${BOLD}  Step 7: Chatbots${NC}"
echo
echo -e "  ${DIM}Each chatbot gets isolated memory and vault folders. You will name them in the browser chat.${NC}"
echo
read -r -p "  Number of chatbots [1]: " NUM_BRAINS
NUM_BRAINS="${NUM_BRAINS:-1}"

if ! [[ "$NUM_BRAINS" =~ ^[0-9]+$ ]] || [ "$NUM_BRAINS" -lt 1 ]; then
  NUM_BRAINS=1
fi

i=1
while [ "$i" -le "$NUM_BRAINS" ]; do
  brain_key="brain-$i"
  brain_name="Brain $i"
  BRAIN_NAMES+=("$brain_name")
  BRAIN_KEYS+=("$brain_key")
  i=$((i + 1))
done

success "$NUM_BRAINS chatbot(s). Final names will be set in the browser setup chat."

divider
echo
step "Generating config.yaml..."

BRAIN_CONFIGS=""
i=0
while [ "$i" -lt "${#BRAIN_KEYS[@]}" ]; do
  BRAIN_CONFIGS="${BRAIN_CONFIGS}
  - key: \"$(yaml_quote "${BRAIN_KEYS[$i]}")\"
    name: \"$(yaml_quote "${BRAIN_NAMES[$i]}")\"
    description: \"\""
  i=$((i + 1))
done

cat > config.yaml <<CONFIGEOF
# Open Agentic Memory - Generated Configuration
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

framework: "$(yaml_quote "$FRAMEWORK")"

models:
  primary:
    provider: "$(yaml_quote "$PROVIDER")"
    model: "$(yaml_quote "$PRIMARY_MODEL")"
    api_key_env: "$(yaml_quote "$API_KEY_ENV")"
    api_key: "$(yaml_quote "$PRIMARY_API_KEY_VALUE")"
    base_url: "$(yaml_quote "$PRIMARY_BASE_URL")"
  fast:
    provider: "$(yaml_quote "$PROVIDER")"
    model: "$(yaml_quote "$FAST_MODEL")"
    api_key_env: "$(yaml_quote "$API_KEY_ENV")"
    api_key: "$(yaml_quote "$PRIMARY_API_KEY_VALUE")"
    base_url: "$(yaml_quote "$PRIMARY_BASE_URL")"
    thinking: "high"

embedding:
  provider: "$(yaml_quote "$EMBED_PROVIDER")"
  model: "$(yaml_quote "$EMBED_MODEL")"
  api_key_env: "$(yaml_quote "$EMBED_KEY_ENV")"
  api_key: "$(yaml_quote "$EMBED_API_KEY_VALUE")"
  endpoint: "$(yaml_quote "$EMBED_ENDPOINT")"
  dimensions: $EMBED_DIMS
  note: "$(yaml_quote "$EMBED_NOTE")"

gateway:
  enabled: $GATEWAY_ENABLED
  base_url: "$(yaml_quote "$GATEWAY_BASE_URL")"
  port: $GATEWAY_PORT
  token_env: "$(yaml_quote "$GATEWAY_TOKEN_ENV")"
  token: "$(yaml_quote "$GATEWAY_TOKEN")"
  prefer_for_models: $GATEWAY_PREFER_FOR_MODELS

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

setup:
  requested_brains: $NUM_BRAINS

server:
  host: "127.0.0.1"
  port: 8400
CONFIGEOF

success "config.yaml generated."

step "Creating data directories..."
mkdir -p data/vector
i=0
while [ "$i" -lt "${#BRAIN_KEYS[@]}" ]; do
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/inbox"
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/daily"
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/decisions"
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/patterns"
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/projects"
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/entities"
  mkdir -p "data/vault/${BRAIN_KEYS[$i]}/maps"
  mkdir -p "brains/${BRAIN_KEYS[$i]}"
  i=$((i + 1))
done
success "Brain vault folders created."

step "Setting up Python environment..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
success "Python environment ready."

if [ "$FRAMEWORK" = "openclaw" ]; then
  apply_openclaw_memorysearch_config
fi

step "Initializing memory runtime..."
.venv/bin/python serve_chat.py --init-only >/dev/null
success "Memory database, vector store, and API runtime initialized."

divider
echo
echo -e "${GREEN}${BOLD}  Setup complete.${NC}"
echo
echo -e "  ${WHITE}Configuration summary:${NC}"
echo -e "    Framework:  ${CYAN}$FRAMEWORK${NC}"
echo -e "    Provider:   ${CYAN}$PROVIDER${NC}"
echo -e "    Primary:    ${CYAN}$PRIMARY_MODEL${NC}"
echo -e "    Fast:       ${CYAN}$FAST_MODEL${NC}"
echo -e "    Embedding:  ${CYAN}$EMBED_SELECTION_LABEL${NC}"
echo -e "    Chatbots:   ${CYAN}$NUM_BRAINS${NC}"
echo
info "config.yaml, data/memory.db, data/vector/, and per-brain vault folders are ready."
if [ -f ".env" ]; then
  info "Any keys entered during setup were saved to .env for future launches."
fi
if [ "$FRAMEWORK" = "openclaw" ]; then
  info "OpenClaw memorySearch is configured, and gateway routing will be preferred when the local gateway is running."
  info "Per-brain agents will be registered automatically as each chatbot identity is saved in the browser."
fi

divider
echo
echo -e "${WHITE}${BOLD}  Step 8: Launch the memory server and identity chat?${NC}"
echo
echo -e "  ${BOLD}1)${NC} Yes ${DIM}(recommended)${NC}"
echo -e "  ${BOLD}2)${NC} No, I will start it later"
echo
read -r -p "  Select [1-2]: " CHAT_CHOICE
CHAT_CHOICE="${CHAT_CHOICE:-1}"

if [ "$CHAT_CHOICE" = "1" ]; then
  echo
  info "Starting the memory API and opening the browser UI. Keep this terminal running while you use it."
  SERVER_URL="http://127.0.0.1:8400"
  .venv/bin/python serve_chat.py --no-browser &
  SERVER_PID=$!

  cleanup_server() {
    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
      kill "$SERVER_PID" >/dev/null 2>&1 || true
    fi
  }

  trap cleanup_server INT TERM

  READY=0
  TRIES=0
  while [ "$TRIES" -lt 30 ]; do
    if curl -fsS "${SERVER_URL}/api/info" >/dev/null 2>&1; then
      READY=1
      break
    fi
    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
    TRIES=$((TRIES + 1))
  done

  if [ "$READY" = "1" ]; then
    if ! open_browser_url "$SERVER_URL"; then
      warn "Could not open the browser automatically. Open ${SERVER_URL} manually."
    fi
  else
    warn "Server took too long to start. Open ${SERVER_URL} manually."
  fi

  wait "$SERVER_PID"
  SERVER_STATUS=$?
  trap - INT TERM
  exit "$SERVER_STATUS"
else
  echo
  info "Start it later with:"
  echo -e "  ${CYAN}.venv/bin/python serve_chat.py${NC}"
  echo
fi
