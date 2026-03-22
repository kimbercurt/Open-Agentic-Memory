const DEFAULT_BASE_URL = "http://127.0.0.1:4195";
const DEFAULT_TIMEOUT_MS = 12000;
const DEFAULT_ALLOWED_AGENTS = [
  
  
  
  
  
  
  "scout-trajectory",
  "scout-relevance",
];

function resolveConfig(api) {
  const pluginConfig = api && typeof api.pluginConfig === "object" ? api.pluginConfig : {};
  const baseUrl =
    typeof pluginConfig.baseUrl === "string" && pluginConfig.baseUrl.trim()
      ? pluginConfig.baseUrl.trim().replace(/\/+$/, "")
      : DEFAULT_BASE_URL;
  const allowedAgents = Array.isArray(pluginConfig.allowedAgents)
    ? pluginConfig.allowedAgents.map((v) => String(v || "").trim()).filter(Boolean)
    : DEFAULT_ALLOWED_AGENTS;
  const timeoutMs =
    typeof pluginConfig.timeoutMs === "number" && pluginConfig.timeoutMs > 0
      ? pluginConfig.timeoutMs
      : DEFAULT_TIMEOUT_MS;
  return { baseUrl, allowedAgents, timeoutMs };
}

function isAllowedAgent(ctx, config) {
  const agentId = String((ctx && ctx.agentId) || "").trim();
  return agentId ? config.allowedAgents.includes(agentId) : false;
}

function parentAgentKey(ctx) {
  const agentId = String((ctx && ctx.agentId) || "").trim();
  // Extract brain key from agent ID prefix
  const parts = agentId.split(/-(recall|observer|scout)-/); return parts.length > 1 ? parts[0] : "assistant";
  // Scouts are shared — the agent_key is passed in the message, default to assistant
  return "assistant";
}

function agentRole(ctx) {
  const agentId = String((ctx && ctx.agentId) || "").trim();
  if (agentId.includes("-recall-facts")) return "facts";
  if (agentId.includes("-recall-context")) return "context";
  if (agentId.includes("-recall-temporal")) return "temporal";
  if (agentId === "scout-trajectory") return "scout_trajectory";
  if (agentId === "scout-relevance") return "scout_relevance";
  return "facts";
}

async function requestJson(config, path, init) {
  const url = `${config.baseUrl}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init && init.headers ? init.headers : {}),
    },
    signal: AbortSignal.timeout(config.timeoutMs),
  });
  const text = await response.text();
  let parsed = {};
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    parsed = { raw: text };
  }
  if (!response.ok) {
    const detail =
      (parsed && typeof parsed === "object" && (parsed.detail || parsed.reply || parsed.raw)) ||
      text ||
      response.statusText;
    throw new Error(String(detail || `Memory recall API request failed (${response.status})`));
  }
  return parsed;
}

function summarizeMemories(memories) {
  if (!memories.length) return "(no results)";
  return memories
    .map((m, i) => {
      const title = String(m.title || "").trim() || "Untitled";
      const kind = String(m.kind || "note");
      const score = typeof m.score === "number" ? m.score.toFixed(2) : "n/a";
      const content = String(m.content || "").trim().slice(0, 300);
      const created = String(m.created_at || "").slice(0, 10);
      const updated = String(m.updated_at || "").slice(0, 10);
      return `${i + 1}. [${kind} score=${score}] ${title}\n   created=${created} updated=${updated}\n   ${content}`;
    })
    .join("\n");
}

// --- Tool: recall_search_memories ---
function createRecallSearchMemoriesTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  return {
    name: "recall_search_memories",
    label: "Search Memory Store",
    description:
      "Search the durable embedded memory store for stored information. Supports keyword queries, kind filtering, date range filtering, and importance thresholds.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        query: {
          type: "string",
          description: "Natural language search query. Describe the topic, fact, or context.",
        },
        limit: {
          type: "number",
          description: "Maximum results to return (default 10).",
        },
        kind: {
          type: "string",
          description:
            "Filter by memory kind: note, preference, project_context, observed_fact, observed_pattern, observed_relationship, chat_turn, etc.",
        },
        date_from: {
          type: "string",
          description: "Only return memories created after this date (YYYY-MM-DD).",
        },
        date_to: {
          type: "string",
          description: "Only return memories created before this date (YYYY-MM-DD).",
        },
      },
    },
    async execute(_id, params) {
      const query = typeof params.query === "string" ? params.query.trim() : "";
      const limit =
        typeof params.limit === "number" && params.limit > 0 ? Math.floor(params.limit) : 10;
      const parts = [`limit=${limit}`, `agent=${agent}`];
      if (query) parts.push(`query=${encodeURIComponent(query)}`);
      if (params.kind) parts.push(`kind=${encodeURIComponent(params.kind)}`);
      if (params.date_from) parts.push(`date_from=${encodeURIComponent(params.date_from)}`);
      if (params.date_to) parts.push(`date_to=${encodeURIComponent(params.date_to)}`);
      const qs = parts.join("&");
      const data = await requestJson(config, `/api/memory?${qs}`, { method: "GET" });
      const memories = Array.isArray(data.memories) ? data.memories : [];
      const text = query
        ? `Memory search for "${query}" (${memories.length} results):\n${summarizeMemories(memories)}`
        : `Recent memories (${memories.length} results):\n${summarizeMemories(memories)}`;
      return { content: [{ type: "text", text }], details: data };
    },
  };
}

// --- Tool: recall_read_vault ---
function createRecallReadVaultTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  return {
    name: "recall_read_vault",
    label: "Read Vault Note",
    description:
      "Read a specific vault markdown note from the brain's knowledge graph. Use this when a memory search result references a graph note that needs deeper reading.",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["note_path"],
      properties: {
        note_path: {
          type: "string",
          description:
            "Path to the vault note, relative to the agent vault root (e.g., 'decisions/my-decision-42.md').",
        },
      },
    },
    async execute(_id, params) {
      const notePath = String(params.note_path || "").trim();
      if (!notePath) throw new Error("note_path is required");
      const qs = `agent=${agent}&note_path=${encodeURIComponent(notePath)}`;
      const data = await requestJson(config, `/api/brain/vault/read?${qs}`, { method: "GET" });
      const content = String(data.content || "(empty note)");
      const title = String(data.title || notePath);
      const text = `Vault note: ${title}\n\n${content}`;
      return { content: [{ type: "text", text }], details: data };
    },
  };
}

// --- Tool: recall_scan_sessions ---
function createRecallScanSessionsTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  return {
    name: "recall_scan_sessions",
    label: "Scan Session History",
    description:
      "Read recent conversation messages from the parent agent's session. Use this to find surrounding context, tone shifts, and conversational patterns.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        window: {
          type: "number",
          description: "Number of recent messages to retrieve (default 20, max 80).",
        },
      },
    },
    async execute(_id, params) {
      const window =
        typeof params.window === "number" && params.window > 0
          ? Math.min(Math.floor(params.window), 80)
          : 20;
      const qs = `agent=${agent}&window=${window}`;
      const data = await requestJson(config, `/api/recall/session-context?${qs}`, {
        method: "GET",
      });
      const messages = Array.isArray(data.messages) ? data.messages : [];
      const lines = messages.map((m, i) => {
        const role = String(m.role || "unknown").toUpperCase();
        const text = String(m.text || "").trim().slice(0, 500);
        const ts = String(m.created_at || "").slice(0, 19);
        return `[${i + 1}] ${role} (${ts}): ${text}`;
      });
      const text = `Session messages (${messages.length}):\n${lines.join("\n") || "(no messages)"}`;
      return { content: [{ type: "text", text }], details: data };
    },
  };
}

// --- Tool: recall_search_graph ---
function createRecallSearchGraphTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  return {
    name: "recall_search_graph",
    label: "Search Graph Notes",
    description:
      "Search the brain's knowledge graph for indexed vault notes. Returns note titles, types, and content previews. Use this for broader context and linked knowledge.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        query: {
          type: "string",
          description: "Natural language search query for graph notes.",
        },
        limit: {
          type: "number",
          description: "Maximum results to return (default 5).",
        },
      },
    },
    async execute(_id, params) {
      const query = typeof params.query === "string" ? params.query.trim() : "";
      const limit =
        typeof params.limit === "number" && params.limit > 0 ? Math.floor(params.limit) : 5;
      const parts = [`agent=${agent}`, `limit=${limit}`];
      if (query) parts.push(`query=${encodeURIComponent(query)}`);
      const qs = parts.join("&");
      const data = await requestJson(config, `/api/brain/graph/search?${qs}`, { method: "GET" });
      const notes = Array.isArray(data.notes) ? data.notes : [];
      const lines = notes.map((n, i) => {
        const title = String(n.title || "Untitled").trim();
        const noteType = String(n.note_type || "note");
        const preview = String(n.body_preview || "").trim().slice(0, 200);
        const path = String(n.note_path || "");
        return `${i + 1}. [${noteType}] ${title}\n   path=${path}\n   ${preview}`;
      });
      const text = query
        ? `Graph search for "${query}" (${notes.length} results):\n${lines.join("\n") || "(no results)"}`
        : `Graph notes (${notes.length}):\n${lines.join("\n") || "(no results)"}`;
      return { content: [{ type: "text", text }], details: data };
    },
  };
}

// --- System prompt injection per agent role ---
function buildRecallPromptGuidance(role) {
  const shared = [
    "You are a memory recall agent. Your ONLY job is to search for and return relevant information.",
    "Return your findings as valid JSON matching the schema in your system prompt.",
    "Do NOT engage in conversation. Do NOT ask follow-up questions. Search and return results.",
    "",
  ];

  if (role === "facts") {
    return shared
      .concat([
        "YOUR ROLE: Facts Recall Agent",
        "Search for explicit facts, literal statements, preferences, decisions, names, numbers, and commitments.",
        "Use `recall_search_memories` with keyword-focused queries. Try multiple keyword variations.",
        "Use `recall_read_vault` when a memory references a graph note.",
        "Return findings as: [{fact, source_id, source_kind, confidence, relevance}]",
      ])
      .join("\n");
  }
  if (role === "context") {
    return shared
      .concat([
        "YOUR ROLE: Context Recall Agent",
        "Search for implied context, tone shifts, social cues, and what was left unsaid.",
        "Use `recall_scan_sessions` to read surrounding conversation messages.",
        "Use `recall_search_graph` for linked graph notes that provide broader context.",
        "Use `recall_search_memories` for semantic matches.",
        "Return findings as: [{context_summary, inferred_intent, surrounding_evidence, social_dynamics, confidence, relevance}]",
      ])
      .join("\n");
  }
  if (role === "temporal") {
    return shared
      .concat([
        "YOUR ROLE: Temporal Recall Agent",
        "Reconstruct timelines, detect recurring patterns, and track topic evolution over time.",
        "Use `recall_search_memories` with date_from/date_to filters for time-windowed searches.",
        "Pay attention to created_at and updated_at timestamps on results.",
        "Use `recall_search_graph` for graph notes with temporal context.",
        "Return findings as: [{timeline_entry, recurring_pattern, frequency, escalation_status, date_range, confidence, relevance}]",
      ])
      .join("\n");
  }
  if (role === "scout_trajectory") {
    return [
      "You are a Topic Trajectory Scout. You run between conversation turns to predict what topics come next.",
      "Use `recall_scan_sessions` to read recent messages. Use `recall_search_memories` to pre-fetch memories for predicted topics.",
      "The message will tell you which agent_key to use — pass it to all tool calls.",
      "Return JSON: {current_topic, predicted_topics, staged_memories: [{topic, memories: [{id, title, content, relevance}]}]}",
    ].join("\n");
  }
  if (role === "scout_relevance") {
    return [
      "You are a Relevance Scorer Scout. You run between conversation turns to score memory results for genuine contextual relevance.",
      "Use `recall_search_memories` and `recall_search_graph` to find and score memories.",
      "The message will tell you which agent_key to use — pass it to all tool calls.",
      "Filter false positives ruthlessly. Surface memories the embedding search missed.",
      "Return JSON: {topic, scored_memories: [{id, title, original_score, adjusted_score, reason}], surfaced: [{id, title, reason}]}",
    ].join("\n");
  }
  return shared.join("\n");
}

export default function register(api) {
  api.registerTool(
    (ctx) => {
      const config = resolveConfig(api);
      if (!isAllowedAgent(ctx, config)) {
        return null;
      }
      const role = agentRole(ctx);
      const tools = [createRecallSearchMemoriesTool(config, ctx)];
      if (role === "facts") {
        tools.push(createRecallReadVaultTool(config, ctx));
      }
      if (role === "context") {
        tools.push(createRecallScanSessionsTool(config, ctx));
        tools.push(createRecallSearchGraphTool(config, ctx));
      }
      if (role === "temporal") {
        tools.push(createRecallSearchGraphTool(config, ctx));
      }
      if (role === "scout_trajectory") {
        tools.push(createRecallScanSessionsTool(config, ctx));
      }
      if (role === "scout_relevance") {
        tools.push(createRecallSearchGraphTool(config, ctx));
      }
      return tools;
    },
    {
      optional: true,
      names: [
        "recall_search_memories",
        "recall_read_vault",
        "recall_scan_sessions",
        "recall_search_graph",
      ],
    },
  );

  api.on("before_agent_start", async (_event, ctx) => {
    const config = resolveConfig(api);
    if (!isAllowedAgent(ctx, config)) {
      return;
    }
    const role = agentRole(ctx);
    return {
      appendSystemContext: buildRecallPromptGuidance(role),
    };
  });
}
