const DEFAULT_BASE_URL = "http://127.0.0.1:4195";
const DEFAULT_TIMEOUT_MS = 12000;
const DEFAULT_ALLOWED_AGENTS = [
  
  
  
  
  
  
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
  const parts = agentId.split("-observer-"); return parts.length > 1 ? parts[0] : "assistant";
  
}

function observerRole(ctx) {
  const agentId = String((ctx && ctx.agentId) || "").trim();
  if (agentId.includes("-observer-facts")) return "facts";
  if (agentId.includes("-observer-patterns")) return "patterns";
  if (agentId.includes("-observer-relationships")) return "relationships";
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
    throw new Error(String(detail || `Memory observer API request failed (${response.status})`));
  }
  return parsed;
}

// --- Tool: observer_read_session ---
function createObserverReadSessionTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  return {
    name: "observer_read_session",
    label: "Read Session Messages",
    description:
      "Read recent conversation messages from the parent agent's active session. Use this to scan for information worth storing.",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        window: {
          type: "number",
          description: "Number of recent messages to retrieve (default 30, max 80).",
        },
      },
    },
    async execute(_id, params) {
      const window =
        typeof params.window === "number" && params.window > 0
          ? Math.min(Math.floor(params.window), 80)
          : 30;
      const qs = `agent=${agent}&window=${window}`;
      const data = await requestJson(config, `/api/recall/session-context?${qs}`, {
        method: "GET",
      });
      const messages = Array.isArray(data.messages) ? data.messages : [];
      const lines = messages.map((m, i) => {
        const role = String(m.role || "unknown").toUpperCase();
        const text = String(m.text || "").trim().slice(0, 600);
        const ts = String(m.created_at || "").slice(0, 19);
        return `[${i + 1}] ${role} (${ts}): ${text}`;
      });
      const text = `Session messages (${messages.length}):\n${lines.join("\n") || "(no messages)"}`;
      return { content: [{ type: "text", text }], details: data };
    },
  };
}

// --- Tool: observer_store_memory ---
function createObserverStoreMemoryTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  const role = observerRole(ctx);
  const kindMap = {
    facts: "observed_fact",
    patterns: "observed_pattern",
    relationships: "observed_relationship",
  };
  const sourceMap = {
    facts: "observer-facts",
    patterns: "observer-patterns",
    relationships: "observer-relationships",
  };
  return {
    name: "observer_store_memory",
    label: "Store Observed Memory",
    description:
      "Store an observation as a durable memory in the parent agent's memory store. Only store genuinely useful information.",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["content", "title"],
      properties: {
        content: {
          type: "string",
          description: "The full observation text with enough context to be useful standalone.",
        },
        title: {
          type: "string",
          description: "Short descriptive title for this observation.",
        },
        importance: {
          type: "number",
          description: "Importance score 1-100 (default 65). Higher for more durable/useful observations.",
        },
      },
    },
    async execute(_id, params) {
      const content = String(params.content || "").trim();
      const title = String(params.title || "").trim();
      if (!content) throw new Error("content is required");
      if (!title) throw new Error("title is required");
      const importance =
        typeof params.importance === "number" && params.importance > 0
          ? Math.min(Math.max(Math.floor(params.importance), 1), 100)
          : 65;
      const body = {
        content,
        title,
        agent_key: agent,
        kind: kindMap[role] || "observed_fact",
        source: sourceMap[role] || "observer-facts",
        importance,
        metadata: {
          observer_agent_id: String((ctx && ctx.agentId) || ""),
          observed_at: new Date().toISOString(),
        },
      };
      const data = await requestJson(config, "/api/memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const mem = data.memory || {};
      const text = `Stored observation: "${mem.title || title}" [${kindMap[role]}] importance=${importance}`;
      return { content: [{ type: "text", text }], details: data };
    },
  };
}

// --- Tool: observer_check_existing ---
function createObserverCheckExistingTool(config, ctx) {
  const agent = parentAgentKey(ctx);
  return {
    name: "observer_check_existing",
    label: "Check Existing Memories",
    description:
      "Search existing memories to check if a similar observation is already stored. Use this before storing to avoid duplicates.",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["query"],
      properties: {
        query: {
          type: "string",
          description: "Short description of the observation to check for.",
        },
      },
    },
    async execute(_id, params) {
      const query = String(params.query || "").trim();
      if (!query) throw new Error("query is required");
      const qs = `query=${encodeURIComponent(query)}&limit=3&agent=${agent}`;
      const data = await requestJson(config, `/api/memory?${qs}`, { method: "GET" });
      const memories = Array.isArray(data.memories) ? data.memories : [];
      if (!memories.length) {
        return {
          content: [{ type: "text", text: "No similar memories found. Safe to store." }],
          details: { exists: false, memories: [] },
        };
      }
      const lines = memories.map((m, i) => {
        const title = String(m.title || "").trim() || "Untitled";
        const score = typeof m.score === "number" ? m.score.toFixed(2) : "n/a";
        const content = String(m.content || "").trim().slice(0, 150);
        return `${i + 1}. [score=${score}] ${title}: ${content}`;
      });
      const topScore = typeof memories[0].score === "number" ? memories[0].score : 0;
      const exists = topScore > 0.75;
      const text = exists
        ? `Similar memory already exists (score=${topScore.toFixed(2)}). Skip storing.\n${lines.join("\n")}`
        : `Related memories found but not duplicates (top score=${topScore.toFixed(2)}):\n${lines.join("\n")}`;
      return { content: [{ type: "text", text }], details: { exists, memories } };
    },
  };
}

// --- System prompt injection per observer role ---
function buildObserverPromptGuidance(role) {
  const shared = [
    "You are a background observation agent. You scan recent session messages and extract useful information to store as durable memory.",
    "Follow this process: 1) Read session messages, 2) Identify candidates, 3) Check for duplicates, 4) Store new observations.",
    "Return a JSON summary of what you observed and stored. Do NOT engage in conversation.",
    "",
  ];

  if (role === "facts") {
    return shared
      .concat([
        "YOUR ROLE: Fact Observer",
        "Extract concrete facts the USER stated: preferences, decisions, commitments, names, numbers, deadlines, technical choices.",
        "Skip conversational filler, transient context, and assistant-generated content.",
        "Store with kind='observed_fact', source='observer-facts'.",
        "Be selective. Quality over quantity. Only store facts useful in future recall.",
      ])
      .join("\n");
  }
  if (role === "patterns") {
    return shared
      .concat([
        "YOUR ROLE: Pattern Observer",
        "Detect behavioral patterns, recurring themes, workflow habits, and work style indicators.",
        "A pattern needs clear evidence: explicit statement or visible repetition.",
        "Do NOT infer patterns from a single instance.",
        "Store with kind='observed_pattern', source='observer-patterns'.",
      ])
      .join("\n");
  }
  if (role === "relationships") {
    return shared
      .concat([
        "YOUR ROLE: Relationship Observer",
        "Track people mentions, relationship dynamics, sentiment shifts, and social context.",
        "Focus on who the user interacts with, how they feel about them, and changes in dynamics.",
        "Skip casual name-drops without relational context.",
        "Store with kind='observed_relationship', source='observer-relationships'.",
      ])
      .join("\n");
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
      return [
        createObserverReadSessionTool(config, ctx),
        createObserverStoreMemoryTool(config, ctx),
        createObserverCheckExistingTool(config, ctx),
      ];
    },
    {
      optional: true,
      names: ["observer_read_session", "observer_store_memory", "observer_check_existing"],
    },
  );

  api.on("before_agent_start", async (_event, ctx) => {
    const config = resolveConfig(api);
    if (!isAllowedAgent(ctx, config)) {
      return;
    }
    const role = observerRole(ctx);
    return {
      appendSystemContext: buildObserverPromptGuidance(role),
    };
  });
}
