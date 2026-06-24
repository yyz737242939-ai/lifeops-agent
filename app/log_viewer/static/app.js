const state = {
  sessions: [],
  selectedId: null,
  source: "all",
  runId: "all",
  kind: "events",
  payload: null,
  expanded: false,
};

const elements = {
  sessionList: document.querySelector("#session-list"),
  sessionSearch: document.querySelector("#session-search"),
  sourceFilter: document.querySelector("#source-filter"),
  runFilter: document.querySelector("#run-filter"),
  sessionTitle: document.querySelector("#session-title"),
  sessionMeta: document.querySelector("#session-meta"),
  kindButtons: [...document.querySelectorAll(".kind-button")],
  eventFilter: document.querySelector("#event-filter"),
  contentSearch: document.querySelector("#content-search"),
  toggleAll: document.querySelector("#toggle-all"),
  refresh: document.querySelector("#refresh"),
  summary: document.querySelector("#summary"),
  events: document.querySelector("#events"),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) return "未知时间";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function shortSessionId(sessionId) {
  return sessionId.replace("session_", "").replaceAll("_", " · ");
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

async function loadSessions(preserveSelection = true) {
  const payload = await fetchJson("/api/sessions");
  state.sessions = payload.sessions.map(session => ({
    ...session,
    viewer_id: session.viewer_id || session.session_id,
    source: session.source || (session.legacy ? "legacy" : "application"),
    run_id: session.run_id || null,
    case_id: session.case_id || null,
  }));
  rebuildRunFilter();
  renderSessions();

  if (!state.sessions.length) {
    showEmpty("还没有日志", "运行一次 LifeOps Agent 后刷新这里。");
    return;
  }

  const selectionExists = preserveSelection && state.sessions.some(item => item.viewer_id === state.selectedId);
  if (!selectionExists) state.selectedId = state.sessions[0].viewer_id;
  renderSessions();
  await loadLog();
}

function renderSessions() {
  const query = elements.sessionSearch.value.trim().toLowerCase();
  const matches = state.sessions.filter(session => {
    if (state.source !== "all" && session.source !== state.source) return false;
    if (state.runId !== "all" && session.run_id !== state.runId) return false;
    return JSON.stringify(session).toLowerCase().includes(query);
  });
  elements.sessionList.innerHTML = matches.map(session => `
    <button class="session-item ${session.viewer_id === state.selectedId ? "active" : ""}" data-session-id="${escapeHtml(session.viewer_id)}">
      <strong>${escapeHtml(session.case_id ? `${session.case_id} · ${shortSessionId(session.session_id)}` : shortSessionId(session.session_id))}</strong>
      <time>${escapeHtml(formatTime(session.started_at))}</time>
      ${session.run_id ? `<span class="session-source">${escapeHtml(session.run_id)}</span>` : ""}
      <span class="file-dots">
        <span class="file-dot ${session.has_events ? "ready" : ""}">EVENT</span>
        <span class="file-dot ${session.has_llm ? "ready" : ""}">LLM</span>
        <span class="file-dot ${session.has_application ? "ready" : ""}">APP</span>
      </span>
    </button>
  `).join("") || `<div class="empty-state"><p>没有匹配的会话</p></div>`;

  elements.sessionList.querySelectorAll("[data-session-id]").forEach(button => {
    button.addEventListener("click", async () => {
      state.selectedId = button.dataset.sessionId;
      renderSessions();
      await loadLog();
    });
  });
}

function selectedSession() {
  return state.sessions.find(item => item.viewer_id === state.selectedId);
}

function rebuildRunFilter() {
  const current = state.runId;
  const runIds = [...new Set(state.sessions.map(session => session.run_id).filter(Boolean))].sort().reverse();
  elements.runFilter.innerHTML = `<option value="all">全部测试运行</option>${runIds.map(runId => `<option value="${escapeHtml(runId)}">${escapeHtml(runId)}</option>`).join("")}`;
  if (runIds.includes(current)) elements.runFilter.value = current;
  else state.runId = "all";
}

function updateKindButtons() {
  const session = selectedSession();
  elements.kindButtons.forEach(button => {
    const kind = button.dataset.kind;
    button.classList.toggle("active", kind === state.kind);
    button.disabled = Boolean(session) && !session[`has_${kind}`];
  });
}

async function loadLog() {
  const session = selectedSession();
  if (!session) return;
  if (!session[`has_${state.kind}`]) {
    state.kind = ["events", "llm", "application"].find(kind => session[`has_${kind}`]);
  }
  updateKindButtons();
  elements.sessionTitle.textContent = session.case_id || shortSessionId(session.session_id);
  elements.sessionMeta.textContent = `${session.run_id ? `${session.run_id} · ` : ""}${formatTime(session.started_at)} · ${state.kind.toUpperCase()}`;

  try {
    state.payload = await fetchJson(`/api/sessions/${encodeURIComponent(session.viewer_id)}/${state.kind}`);
    rebuildEventFilter();
    renderPayload();
  } catch (error) {
    elements.summary.innerHTML = "";
    elements.events.innerHTML = `<div class="error-message">${escapeHtml(error.message)}</div>`;
  }
}

function rebuildEventFilter() {
  const current = elements.eventFilter.value;
  const eventTypes = [...new Set((state.payload.events || []).map(event => event.event).filter(Boolean))].sort();
  elements.eventFilter.innerHTML = `<option value="">全部事件</option>${eventTypes.map(type => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`).join("")}`;
  if (eventTypes.includes(current)) elements.eventFilter.value = current;
}

function eventClass(type = "") {
  if (type.includes("error") || type.includes("denied")) return "error";
  if (type.includes("capability") || type.includes("skill")) return "capability";
  if (type.includes("tool")) return "tool";
  return "";
}

function latestChatRunState(events) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const runState = events[index]?.run_state;
    if (runState && typeof runState === "object") return runState;
  }
  return null;
}

function chatRunSummaryCards(events) {
  const runState = latestChatRunState(events);
  if (!runState) return "";

  const scope = runState.state_scope === "single_agent_chat"
    ? "单次 Agent.chat()"
    : "单次 Agent.chat()（旧日志）";
  const llmRounds = runState.chat_llm_round_count ?? runState.llm_rounds ?? "-";
  const llmRequests = runState.chat_llm_request_count ?? runState.llm_attempts ?? "-";
  const toolAttempts = runState.chat_tool_execution_attempt_count ?? runState.total_tool_calls ?? "-";

  return `
    <article class="summary-card scope-card"><span>RunState 统计范围</span><strong>${escapeHtml(scope)}</strong></article>
    <article class="summary-card"><span>本次 Chat · LLM 逻辑轮次</span><strong>${escapeHtml(llmRounds)}</strong></article>
    <article class="summary-card"><span>本次 Chat · LLM API 请求</span><strong>${escapeHtml(llmRequests)}</strong></article>
    <article class="summary-card"><span>本次 Chat · 工具执行尝试</span><strong>${escapeHtml(toolAttempts)}</strong></article>
  `;
}

function renderPayload() {
  if (!state.payload) return;
  const allEvents = state.payload.events || [];
  const typeFilter = elements.eventFilter.value;
  const query = elements.contentSearch.value.trim().toLowerCase();
  const visibleEvents = allEvents.filter(event => {
    if (typeFilter && event.event !== typeFilter) return false;
    return !query || JSON.stringify(event).toLowerCase().includes(query);
  });

  elements.summary.innerHTML = `
    <article class="summary-card"><span>日志类型</span><strong>${escapeHtml(state.payload.kind || state.kind)}</strong></article>
    <article class="summary-card"><span>事件总数</span><strong>${allEvents.length}</strong></article>
    <article class="summary-card"><span>当前显示</span><strong>${visibleEvents.length}</strong></article>
    ${state.kind === "events" ? chatRunSummaryCards(allEvents) : ""}
  `;

  if (!visibleEvents.length) {
    showEmpty("没有匹配事件", "调整事件类型或搜索内容。");
    return;
  }

  elements.events.innerHTML = visibleEvents.map((event, index) => {
    const type = event.event || "unknown_event";
    return `
      <details class="event-card ${eventClass(type)}" ${state.expanded ? "open" : ""}>
        <summary class="event-header">
          <span class="event-index">${String(index + 1).padStart(2, "0")}</span>
          <span class="event-title">
            <strong>${escapeHtml(type)}</strong>
            <time>${escapeHtml(formatTime(event.timestamp))}</time>
          </span>
          <span class="event-badge">${escapeHtml(state.kind.toUpperCase())}</span>
        </summary>
        <div class="event-body"><pre>${escapeHtml(JSON.stringify(event, null, 2))}</pre></div>
      </details>
    `;
  }).join("");
}

function showEmpty(title, message) {
  elements.events.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">{ }</div>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(message)}</p>
    </div>`;
}

elements.sessionSearch.addEventListener("input", renderSessions);
elements.sourceFilter.addEventListener("change", () => {
  state.source = elements.sourceFilter.value;
  renderSessions();
});
elements.runFilter.addEventListener("change", () => {
  state.runId = elements.runFilter.value;
  renderSessions();
});
elements.eventFilter.addEventListener("change", renderPayload);
elements.contentSearch.addEventListener("input", renderPayload);
elements.kindButtons.forEach(button => {
  button.addEventListener("click", async () => {
    if (button.disabled || state.kind === button.dataset.kind) return;
    state.kind = button.dataset.kind;
    await loadLog();
  });
});
elements.toggleAll.addEventListener("click", () => {
  state.expanded = !state.expanded;
  elements.toggleAll.textContent = state.expanded ? "全部收起" : "全部展开";
  document.querySelectorAll(".event-card").forEach(card => { card.open = state.expanded; });
});
elements.refresh.addEventListener("click", () => loadSessions(true));

loadSessions(false).catch(error => {
  elements.events.innerHTML = `<div class="error-message">${escapeHtml(error.message)}</div>`;
});
