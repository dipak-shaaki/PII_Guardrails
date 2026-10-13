"use strict";

const TOKEN_RE = /<([A-Z][A-Z0-9_]*_\d+)>/g;
const SESSION_KEY = "pii_shield_session_id";

const state = {
  sessionId: sessionStorage.getItem(SESSION_KEY) || null,
  turns: [],
  serverHistory: null,
  busy: false,
};

const el = {
  composer: document.getElementById("composer"),
  message: document.getElementById("message"),
  send: document.getElementById("send"),
  examples: document.getElementById("examples"),
  banner: document.getElementById("banner"),
  sessionId: document.getElementById("session-id"),
  reset: document.getElementById("reset"),
  typed: document.getElementById("typed"),
  llmSaw: document.getElementById("llm-saw"),
  reply: document.getElementById("reply"),
  provider: document.getElementById("provider-badge"),
  tokenMap: document.getElementById("token-map"),
  llmReply: document.getElementById("llm-reply"),
  trace: document.getElementById("trace"),
  hood: document.getElementById("hood"),
  log: document.getElementById("log"),
  refresh: document.getElementById("refresh"),
  viewToggle: document.getElementById("view-toggle"),
};

/* ---------- token helpers ---------- */

function typeFromToken(token) {
  const inner = token.slice(1, -1);
  return inner.replace(/_\d+$/, "");
}

function hue(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
  return h;
}

// Build DOM nodes, never HTML: both user and LLM text are untrusted.
function tokensFragment(text) {
  const frag = document.createDocumentFragment();
  let last = 0;
  let m;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) {
      frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    }
    const type = typeFromToken(m[0]);
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.setProperty("--hue", hue(type));
    chip.title = type;
    chip.textContent = m[0];
    frag.appendChild(chip);
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    frag.appendChild(document.createTextNode(text.slice(last)));
  }
  return frag;
}

function setTokens(node, text) {
  node.classList.remove("empty");
  node.replaceChildren(tokensFragment(text || ""));
}

function setText(node, text) {
  node.classList.remove("empty");
  node.textContent = text || "";
}

function restore(text, tokenMap) {
  let out = text;
  for (const [token, value] of Object.entries(tokenMap || {})) {
    out = out.split(token).join(value);
  }
  return out;
}

/* ---------- examples ---------- */

const EXAMPLES = [
  { label: "Name + email", text: "Hi, I'm Dipak Sharma and my email is dipak@example.com." },
  { label: "Phone number", text: "You can reach me on +1 415 555 0142 tomorrow." },
  { label: "Credit card", text: "My card number is 4111 1111 1111 1111, please charge it." },
  { label: "Plain question", text: "What's the capital of France?" },
];

for (const ex of EXAMPLES) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "example";
  btn.textContent = ex.label;
  btn.addEventListener("click", () => {
    el.message.value = ex.text;
    el.message.focus();
  });
  el.examples.appendChild(btn);
}

/* ---------- rendering ---------- */

function showBanner(kind, text) {
  el.banner.hidden = false;
  el.banner.className = "banner " + kind;
  el.banner.textContent = text;
}

function hideBanner() {
  el.banner.hidden = true;
}

function renderPanels(turn) {
  setText(el.typed, turn.raw);
  setTokens(el.llmSaw, turn.llmQuery);
  setText(el.reply, turn.reply);

  if (turn.provider) {
    el.provider.hidden = false;
    const p = turn.provider.toLowerCase();
    el.provider.className = "badge provider " + (p.includes("groq") ? "groq" : p.includes("gemini") ? "gemini" : "other");
    el.provider.textContent = turn.provider;
  } else {
    el.provider.hidden = true;
  }

  renderTokenMap(turn.tokenMap);
  setTokens(el.llmReply, turn.llmReply || "(none)");
  renderTrace(turn.trace || []);
}

function renderTokenMap(tokenMap) {
  if (!tokenMap || Object.keys(tokenMap).length === 0) {
    el.tokenMap.className = "panel-body empty";
    el.tokenMap.textContent = "No tokens this turn (or EXPOSE_TOKEN_MAP is off).";
    return;
  }
  el.tokenMap.className = "panel-body";
  const grid = document.createElement("div");
  grid.className = "kv";
  for (const [token, value] of Object.entries(tokenMap)) {
    const k = document.createElement("span");
    k.className = "chip";
    k.style.setProperty("--hue", hue(typeFromToken(token)));
    k.textContent = token;
    const v = document.createElement("span");
    v.className = "v";
    v.textContent = value;
    grid.append(k, v);
  }
  el.tokenMap.replaceChildren(grid);
}

function renderTrace(trace) {
  el.trace.className = "trace";
  if (!trace.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No tool activity on this turn.";
    el.trace.replaceChildren(li);
    return;
  }
  const items = trace.map((event) => {
    const li = document.createElement("li");
    const kind = document.createElement("span");
    kind.className = "kind " + event.kind;
    kind.textContent = event.kind.replace("_", " ");
    const content = document.createElement("span");
    content.className = "content";
    content.replaceChildren(tokensFragment(event.content || ""));
    li.append(kind, content);
    return li;
  });
  el.trace.replaceChildren(...items);
}

function turnCard(turn, tokenized) {
  const card = document.createElement("div");
  card.className = "turn" + (turn.blocked ? " blocked" : "");

  const lines = [
    { who: "you", text: tokenized ? turn.llmQuery : turn.raw, cls: "user" },
    { who: "assistant", text: tokenized ? turn.llmReply : turn.reply, cls: "assistant" },
  ];
  for (const line of lines) {
    const row = document.createElement("div");
    row.className = "line " + line.cls;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = line.who;
    const bubble = document.createElement("span");
    bubble.className = "bubble";
    if (tokenized) {
      bubble.replaceChildren(tokensFragment(line.text || ""));
    } else {
      bubble.textContent = line.text || "";
    }
    row.append(who, bubble);
    card.appendChild(row);
  }
  return card;
}

function renderLog() {
  const tokenized = el.viewToggle.checked;

  if (state.serverHistory) {
    renderServerLog(tokenized);
    return;
  }

  if (!state.turns.length) {
    el.log.className = "log-body empty";
    el.log.textContent =
      "Turns will stack here, so you can watch tokens get reused across the conversation.";
    return;
  }
  el.log.className = "log-body";
  el.log.replaceChildren(...state.turns.map((t) => turnCard(t, tokenized)));
}

function renderServerLog(tokenized) {
  const { history, token_map } = state.serverHistory;
  el.log.className = "log-body";
  const note = document.createElement("div");
  note.className = "muted";
  note.style.color = "var(--faint)";
  note.style.fontSize = "0.78rem";
  note.textContent = "Stored session, exactly as the server keeps it (tokens only).";
  const frag = document.createDocumentFragment();
  frag.appendChild(note);
  for (const msg of history) {
    if (msg.role === "system") continue;
    const card = document.createElement("div");
    card.className = "turn " + (msg.role === "assistant" ? "assistant" : "user");
    const row = document.createElement("div");
    row.className = "line " + (msg.role === "assistant" ? "assistant" : "user");
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = msg.role === "tool" ? "tool" : msg.role === "assistant" ? "assistant" : "you";
    const bubble = document.createElement("span");
    bubble.className = "bubble";
    const shown = tokenized ? msg.content : restore(msg.content, token_map);
    if (tokenized) {
      bubble.replaceChildren(tokensFragment(shown));
    } else {
      bubble.textContent = shown || "";
    }
    row.append(who, bubble);
    card.appendChild(row);
    frag.appendChild(card);
  }
  el.log.replaceChildren(frag);
}

/* ---------- network ---------- */

function friendlyError(status, body) {
  if (body && body.error) return body.error;
  if (status === 422) return "That message was rejected (empty, too long, or a bad session id).";
  if (status === 409) return "This session is busy. Try again in a moment.";
  if (status === 503) return "The service is temporarily unavailable. Try again shortly.";
  if (status === 502) return "The language model request was rejected.";
  return `Request failed (HTTP ${status}).`;
}

async function sendMessage(text) {
  const payload = { message: text };
  if (state.sessionId) payload.session_id = state.sessionId;

  let res;
  try {
    res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    showBanner("error", "Network error. Is the server running?");
    return;
  }

  let body = null;
  try {
    body = await res.json();
  } catch {
    /* keep body null */
  }

  if (!res.ok) {
    showBanner("error", friendlyError(res.status, body));
    return;
  }

  hideBanner();
  state.sessionId = body.session_id;
  sessionStorage.setItem(SESSION_KEY, state.sessionId);
  updateSessionLabel();
  state.serverHistory = null;

  const turn = {
    raw: text,
    llmQuery: body.llm_query,
    llmReply: body.llm_reply,
    reply: body.reply,
    blocked: body.blocked,
    provider: body.provider,
    trace: body.trace,
    tokenMap: body.token_map,
  };
  state.turns.push(turn);
  renderPanels(turn);
  renderLog();

  if (body.blocked) {
    showBanner("blocked", "Blocked — " + body.reply);
  }

  if (state.turns.length === 1) el.hood.open = true;
}

function updateSessionLabel() {
  el.sessionId.textContent = state.sessionId || "new";
  el.sessionId.title = state.sessionId || "";
}

function clearPanels() {
  el.typed.className = "panel-body empty";
  el.typed.textContent = "Your message will appear here.";
  el.llmSaw.className = "panel-body empty";
  el.llmSaw.textContent = "Placeholders appear here.";
  el.reply.className = "panel-body empty";
  el.reply.textContent = "The assistant reply appears here.";
  el.provider.hidden = true;
  el.tokenMap.className = "panel-body empty";
  el.tokenMap.textContent = "No tokens yet.";
  el.llmReply.className = "panel-body empty";
  el.llmReply.textContent = "Tokenized model output.";
  el.trace.className = "trace empty";
  el.trace.replaceChildren(Object.assign(document.createElement("li"), { className: "muted", textContent: "No tool activity on this turn." }));
}

function setBusy(busy) {
  state.busy = busy;
  el.send.disabled = busy;
  el.composer.classList.toggle("busy", busy);
}

/* ---------- events ---------- */

el.composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = el.message.value.trim();
  if (!text || state.busy) return;
  el.message.value = "";
  setBusy(true);
  try {
    await sendMessage(text);
  } finally {
    setBusy(false);
  }
});

el.reset.addEventListener("click", async () => {
  const sid = state.sessionId;
  if (sid) {
    try {
      await fetch(`/sessions/${encodeURIComponent(sid)}`, { method: "DELETE" });
    } catch {
      /* clearing locally regardless */
    }
  }
  state.sessionId = null;
  state.turns = [];
  state.serverHistory = null;
  sessionStorage.removeItem(SESSION_KEY);
  updateSessionLabel();
  clearPanels();
  hideBanner();
  el.log.className = "log-body empty";
  el.log.textContent =
    "Turns will stack here, so you can watch tokens get reused across the conversation.";
});

el.refresh.addEventListener("click", async () => {
  if (!state.sessionId) {
    showBanner("error", "No active session yet. Send a message first.");
    return;
  }
  setBusy(true);
  try {
    const res = await fetch(`/sessions/${encodeURIComponent(state.sessionId)}`);
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      showBanner("error", friendlyError(res.status, body));
      return;
    }
    hideBanner();
    state.serverHistory = await res.json();
    renderLog();
  } catch {
    showBanner("error", "Network error while loading the session.");
  } finally {
    setBusy(false);
  }
});

el.viewToggle.addEventListener("change", renderLog);

/* ---------- boot ---------- */
updateSessionLabel();
hideBanner();
