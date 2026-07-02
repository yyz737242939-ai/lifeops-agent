const state = {
  currentView: "dashboard",
  data: null,
  chat: [],
  agentRunning: false,
  todoFilter: "all",
  budgetStatus: null,
};

const elements = {
  navItems: [...document.querySelectorAll(".nav-item")],
  views: [...document.querySelectorAll(".view")],
  pageTitle: document.querySelector("#page-title"),
  status: document.querySelector("#status"),
  refresh: document.querySelector("#refresh"),
  dashboardGrid: document.querySelector("#dashboard-grid"),
  todoForm: document.querySelector("#todo-form"),
  todoList: document.querySelector("#todo-list"),
  todoFilterButtons: [...document.querySelectorAll("[data-todo-filter]")],
  wellbeingForm: document.querySelector("#wellbeing-form"),
  wellbeingFilterForm: document.querySelector("#wellbeing-filter-form"),
  wellbeingList: document.querySelector("#wellbeing-list"),
  expenseForm: document.querySelector("#expense-form"),
  financeFilterForm: document.querySelector("#finance-filter-form"),
  budgetForm: document.querySelector("#budget-form"),
  checkBudget: document.querySelector("#check-budget"),
  budgetStatus: document.querySelector("#budget-status"),
  financeSummary: document.querySelector("#finance-summary"),
  expenseList: document.querySelector("#expense-list"),
  activityForm: document.querySelector("#activity-form"),
  activityList: document.querySelector("#activity-list"),
  memoryFilterForm: document.querySelector("#memory-filter-form"),
  memoryList: document.querySelector("#memory-list"),
  agentForm: document.querySelector("#agent-form"),
  clearAgent: document.querySelector("#clear-agent"),
  chatHistory: document.querySelector("#chat-history"),
  agentRunState: document.querySelector("#agent-run-state"),
  agentActions: document.querySelector("#agent-actions"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function titleCase(value) {
  return String(value || "-").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function showStatus(message, type = "info") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`;
  if (message) window.setTimeout(() => {
    if (elements.status.textContent === message) showStatus("");
  }, 2800);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

function formPayload(form) {
  const payload = {};
  new FormData(form).forEach((value, key) => {
    const text = String(value).trim();
    payload[key] = text === "" ? null : text;
  });
  for (const key of ["amount", "sleep_hours", "available_minutes"]) {
    if (payload[key] !== undefined && payload[key] !== null) payload[key] = Number(payload[key]);
  }
  return payload;
}

async function loadState() {
  state.data = await api("/api/state");
  renderAll();
}

function setView(view) {
  state.currentView = view;
  elements.navItems.forEach(item => item.classList.toggle("active", item.dataset.view === view));
  elements.views.forEach(panel => panel.classList.toggle("active", panel.dataset.viewPanel === view));
  elements.pageTitle.textContent = titleCase(view);
}

function renderDashboard() {
  const dashboard = state.data.dashboard;
  const summary = dashboard.expense_summary || {};
  const latest = dashboard.latest_wellbeing;
  const activities = dashboard.recommended_activities || [];
  elements.dashboardGrid.innerHTML = `
    <article class="metric-card">
      <span>Open Todos</span>
      <strong>${escapeHtml(dashboard.open_todo_count)}</strong>
      <p>${escapeHtml(dashboard.todo_count)} total tasks</p>
    </article>
    <article class="metric-card">
      <span>Spending</span>
      <strong>$${escapeHtml((summary.total_amount || 0).toFixed ? summary.total_amount.toFixed(2) : summary.total_amount || 0)}</strong>
      <p>${escapeHtml(summary.count || 0)} records</p>
    </article>
    <article class="metric-card">
      <span>Wellbeing</span>
      <strong>${escapeHtml(latest?.mood ? titleCase(latest.mood) : "-")}</strong>
      <p>${escapeHtml(latest?.energy ? `${titleCase(latest.energy)} energy` : "No recent check-in")}</p>
    </article>
    <article class="wide-panel">
      <h3>Next Tasks</h3>
      <div class="compact-list">
        ${(dashboard.recent_todos || []).map(todo => `<p><b>${escapeHtml(todo.priority)}</b> ${escapeHtml(todo.title)}</p>`).join("") || "<p>No todos yet.</p>"}
      </div>
    </article>
    <article class="wide-panel">
      <h3>Today Options</h3>
      <div class="compact-list">
        ${activities.map(activity => `<p><b>${escapeHtml(activity.name)}</b> ${escapeHtml(activity.duration_minutes)} min · ${escapeHtml(activity.reason)}</p>`).join("") || "<p>No recommendations yet.</p>"}
      </div>
    </article>
  `;
}

function renderTodos() {
  const todos = [...state.data.todos]
    .filter(todo => state.todoFilter === "all" || todo.status === state.todoFilter)
    .sort((a, b) => (a.status === "done") - (b.status === "done") || a.id - b.id);
  elements.todoList.innerHTML = todos.map(todo => `
    <article class="list-item ${todo.status === "done" ? "done" : ""}">
      <div>
        <strong>${escapeHtml(todo.title)}</strong>
        <p>${escapeHtml(titleCase(todo.priority))}${todo.due_date ? ` · ${escapeHtml(todo.due_date)}` : ""}</p>
        <form class="inline-edit todo-edit-form" data-todo-id="${todo.id}">
          <input name="title" value="${escapeHtml(todo.title)}" aria-label="Todo title">
          <select name="priority" aria-label="Todo priority">
            <option value="medium" ${todo.priority === "medium" ? "selected" : ""}>Medium</option>
            <option value="high" ${todo.priority === "high" ? "selected" : ""}>High</option>
            <option value="low" ${todo.priority === "low" ? "selected" : ""}>Low</option>
          </select>
          <input name="due_date" type="date" value="${escapeHtml(todo.due_date || "")}" aria-label="Todo due date">
          <button type="submit">Save</button>
        </form>
      </div>
      <div class="item-actions">
        ${todo.status !== "done" ? `<button data-complete="${todo.id}">Done</button>` : ""}
        <button data-delete="${todo.id}" class="danger">Delete</button>
      </div>
    </article>
  `).join("") || `<div class="empty-state">No todos yet.</div>`;

  elements.todoList.querySelectorAll("[data-complete]").forEach(button => {
    button.addEventListener("click", () => mutate(`/api/todos/${button.dataset.complete}/complete`, {}, "Todo completed."));
  });
  elements.todoList.querySelectorAll("[data-delete]").forEach(button => {
    button.addEventListener("click", () => mutate(`/api/todos/${button.dataset.delete}/delete`, {}, "Todo deleted."));
  });
  elements.todoList.querySelectorAll(".todo-edit-form").forEach(form => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      try {
        await api(`/api/todos/${form.dataset.todoId}`, {
          method: "PATCH",
          body: JSON.stringify(formPayload(form)),
        });
        await loadState();
        showStatus("Todo updated.", "success");
      } catch (error) {
        showStatus(error.message, "error");
      }
    });
  });
}

function renderWellbeing() {
  const wellbeing = state.data.wellbeing || { logs: [] };
  elements.wellbeingList.innerHTML = wellbeing.logs.map(log => `
    <article class="list-item">
      <div>
        <strong>${escapeHtml(log.log_date)}</strong>
        <p>${escapeHtml(titleCase(log.mood))} mood · ${escapeHtml(titleCase(log.energy))} energy · ${escapeHtml(log.sleep_hours ?? "-")}h sleep</p>
        ${log.note ? `<small>${escapeHtml(log.note)}</small>` : ""}
        <form class="inline-edit wellbeing-edit-form" data-log-date="${escapeHtml(log.log_date)}">
          <input name="sleep_hours" type="number" min="0" max="24" step="0.5" value="${escapeHtml(log.sleep_hours ?? "")}" aria-label="Sleep hours">
          <select name="mood" aria-label="Mood">
            <option value="">-</option>
            <option value="bad" ${log.mood === "bad" ? "selected" : ""}>Bad</option>
            <option value="neutral" ${log.mood === "neutral" ? "selected" : ""}>Neutral</option>
            <option value="good" ${log.mood === "good" ? "selected" : ""}>Good</option>
          </select>
          <select name="energy" aria-label="Energy">
            <option value="">-</option>
            <option value="low" ${log.energy === "low" ? "selected" : ""}>Low</option>
            <option value="medium" ${log.energy === "medium" ? "selected" : ""}>Medium</option>
            <option value="high" ${log.energy === "high" ? "selected" : ""}>High</option>
          </select>
          <button type="submit">Save</button>
        </form>
      </div>
    </article>
  `).join("") || `<div class="empty-state">No check-ins in the last 7 days.</div>`;
  elements.wellbeingList.querySelectorAll(".wellbeing-edit-form").forEach(form => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      try {
        await api("/api/wellbeing", {
          method: "POST",
          body: JSON.stringify({
            ...formPayload(form),
            log_date: form.dataset.logDate,
          }),
        });
        await loadState();
        showStatus("Wellbeing updated.", "success");
      } catch (error) {
        showStatus(error.message, "error");
      }
    });
  });
}

function renderFinance() {
  const summary = state.data.finance.summary;
  const categories = Object.entries(summary.category_totals || {});
  const filters = state.data.finance.filters || {};
  elements.financeSummary.innerHTML = `
    <article><span>Total</span><strong>$${escapeHtml(Number(summary.total_amount || 0).toFixed(2))}</strong></article>
    <article><span>Records</span><strong>${escapeHtml(summary.count || 0)}</strong></article>
  `;
  elements.expenseList.innerHTML = `
    ${(filters.category || filters.start_date || filters.end_date) ? `<p class="filter-note">Filtered by ${escapeHtml(filters.category || "all categories")} ${escapeHtml(filters.start_date || "")}${filters.end_date ? ` to ${escapeHtml(filters.end_date)}` : ""}</p>` : ""}
    ${categories.length ? `<div class="category-strip">${categories.map(([category, amount]) => `<span>${escapeHtml(category)} $${escapeHtml(Number(amount).toFixed(2))}</span>`).join("")}</div>` : ""}
    ${state.data.finance.recent_expenses.map(expense => `
      <article class="list-item">
        <div>
          <strong>$${escapeHtml(Number(expense.amount).toFixed(2))} · ${escapeHtml(expense.category)}</strong>
          <p>${escapeHtml(expense.description)} · ${escapeHtml(expense.spent_date)}</p>
        </div>
      </article>
    `).join("") || `<div class="empty-state">No expenses yet.</div>`}
  `;
  renderBudgetStatus();
}

function renderBudgetStatus() {
  const status = state.budgetStatus;
  if (!status) {
    elements.budgetStatus.innerHTML = `<p class="muted">Set or check a category budget.</p>`;
    return;
  }
  const amount = status.budget?.amount;
  elements.budgetStatus.innerHTML = `
    <article class="${status.over_budget ? "over-budget" : ""}">
      <strong>${escapeHtml(status.category)} · ${escapeHtml(titleCase(status.period))}</strong>
      <p>${escapeHtml(status.start_date)} to ${escapeHtml(status.end_date)}</p>
      <p>Budget: ${amount == null ? "-" : `$${escapeHtml(Number(amount).toFixed(2))}`} · Spent: $${escapeHtml(Number(status.spent || 0).toFixed(2))}</p>
      <p>Remaining: ${status.remaining == null ? "-" : `$${escapeHtml(Number(status.remaining).toFixed(2))}`}</p>
    </article>
  `;
}

function renderActivities() {
  elements.activityList.innerHTML = state.data.activities.map(activity => `
    <article class="list-item">
      <div>
        <strong>${escapeHtml(activity.name)}</strong>
        <p>${escapeHtml(activity.duration_minutes)} min · ${escapeHtml(activity.cost_level)} · ${escapeHtml(activity.energy_required)} energy</p>
        <small>${escapeHtml(activity.reason)}</small>
      </div>
    </article>
  `).join("") || `<div class="empty-state">No matching activity.</div>`;
}

function renderMemory() {
  const memories = state.data.memories?.items || [];
  elements.memoryList.innerHTML = memories.map(memory => `
    <article class="list-item">
      <div>
        <strong>${escapeHtml(titleCase(memory.type))}</strong>
        <p>${escapeHtml(memory.content)}</p>
        <small>${escapeHtml(memory.id)}${memory.tags?.length ? ` · ${escapeHtml(memory.tags.join(", "))}` : ""}</small>
      </div>
      <div class="item-actions">
        <button data-delete-memory="${escapeHtml(memory.id)}" class="danger">Delete</button>
      </div>
    </article>
  `).join("") || `<div class="empty-state">No active memories.</div>`;
  elements.memoryList.querySelectorAll("[data-delete-memory]").forEach(button => {
    button.addEventListener("click", async () => {
      try {
        const payload = await api(`/api/memories/${encodeURIComponent(button.dataset.deleteMemory)}/delete`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        state.data.memories = payload.memories;
        renderMemory();
        showStatus("Memory deleted.", "success");
      } catch (error) {
        showStatus(error.message, "error");
      }
    });
  });
}

function renderChat() {
  const intro = `
    <article class="chat-message assistant">
      <strong>LifeOps</strong>
      <p>Ask about your todos, wellbeing, spending, or activity options. Structured forms remain the clearest place for direct edits.</p>
    </article>
  `;
  const messages = state.chat.map(message => `
    <article class="chat-message ${escapeHtml(message.role)}">
      <strong>${message.role === "user" ? "You" : "LifeOps"}</strong>
      <p>${escapeHtml(message.content).replaceAll("\n", "<br>")}</p>
    </article>
  `).join("");
  elements.chatHistory.innerHTML = intro + messages;
  elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
}

function renderRunState(runState) {
  if (!runState) {
    elements.agentRunState.innerHTML = `<p>No Agent run yet.</p>`;
    return;
  }
  elements.agentRunState.innerHTML = `
    <dl>
      <div><dt>Status</dt><dd>${escapeHtml(runState.status)}</dd></div>
      <div><dt>Stop reason</dt><dd>${escapeHtml(runState.stop_reason || "-")}</dd></div>
      <div><dt>LLM rounds</dt><dd>${escapeHtml(runState.llm_rounds)}</dd></div>
      <div><dt>LLM requests</dt><dd>${escapeHtml(runState.llm_requests)}</dd></div>
      <div><dt>Tool attempts</dt><dd>${escapeHtml(runState.tool_attempts)}</dd></div>
      <div><dt>Actions</dt><dd>${escapeHtml(runState.successful_actions)} ok · ${escapeHtml(runState.failed_actions)} failed</dd></div>
    </dl>
  `;
  renderActionFacts(runState);
}

function renderActionFacts(runState) {
  const actions = runState?.actions || [];
  const writes = runState?.write_actions || [];
  elements.agentActions.innerHTML = `
    <div class="action-summary">
      <strong>${escapeHtml(writes.length)}</strong>
      <span>write actions</span>
    </div>
    ${actions.map(action => `
      <p class="${action.is_write ? "write-action" : ""}">
        ${escapeHtml(action.tool_name)} · ${escapeHtml(action.status)}
      </p>
    `).join("") || "<p>No tool actions.</p>"}
  `;
}

function renderAll() {
  renderDashboard();
  renderTodos();
  renderWellbeing();
  renderFinance();
  renderActivities();
  renderMemory();
  renderChat();
}

async function mutate(path, payload, successMessage) {
  try {
    await api(path, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await loadState();
    showStatus(successMessage, "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
}

elements.navItems.forEach(item => {
  item.addEventListener("click", () => setView(item.dataset.view));
});

elements.refresh.addEventListener("click", () => {
  loadState().then(() => showStatus("Refreshed.", "success")).catch(error => showStatus(error.message, "error"));
});

elements.todoForm.addEventListener("submit", async event => {
  event.preventDefault();
  await mutate("/api/todos", formPayload(elements.todoForm), "Todo added.");
  elements.todoForm.reset();
});

elements.todoFilterButtons.forEach(button => {
  button.addEventListener("click", () => {
    state.todoFilter = button.dataset.todoFilter;
    elements.todoFilterButtons.forEach(item => item.classList.toggle("active", item === button));
    renderTodos();
  });
});

elements.wellbeingForm.addEventListener("submit", async event => {
  event.preventDefault();
  await mutate("/api/wellbeing", formPayload(elements.wellbeingForm), "Check-in saved.");
});

elements.wellbeingFilterForm.addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const payload = await api("/api/wellbeing/query", {
      method: "POST",
      body: JSON.stringify(formPayload(elements.wellbeingFilterForm)),
    });
    state.data.wellbeing = payload.wellbeing;
    renderWellbeing();
    showStatus("Wellbeing range updated.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
});

elements.expenseForm.addEventListener("submit", async event => {
  event.preventDefault();
  await mutate("/api/expenses", formPayload(elements.expenseForm), "Expense recorded.");
  elements.expenseForm.reset();
});

elements.financeFilterForm.addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const payload = await api("/api/finance/query", {
      method: "POST",
      body: JSON.stringify(formPayload(elements.financeFilterForm)),
    });
    state.data.finance = payload.finance;
    renderFinance();
    showStatus("Finance filters applied.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
});

async function submitBudget(path, successMessage) {
  try {
    const payload = await api(path, {
      method: "POST",
      body: JSON.stringify(formPayload(elements.budgetForm)),
    });
    state.budgetStatus = payload.budget_status;
    renderBudgetStatus();
    showStatus(successMessage, "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
}

elements.budgetForm.addEventListener("submit", async event => {
  event.preventDefault();
  await submitBudget("/api/budgets", "Budget saved.");
});

elements.checkBudget.addEventListener("click", async () => {
  await submitBudget("/api/budgets/check", "Budget checked.");
});

elements.activityForm.addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const payload = await api("/api/activities/recommend", {
      method: "POST",
      body: JSON.stringify(formPayload(elements.activityForm)),
    });
    state.data.activities = payload.activities;
    renderActivities();
    showStatus("Recommendations updated.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
});

elements.memoryFilterForm.addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const payload = await api("/api/memories/query", {
      method: "POST",
      body: JSON.stringify(formPayload(elements.memoryFilterForm)),
    });
    state.data.memories = payload.memories;
    renderMemory();
    showStatus("Memory filters applied.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
});

elements.agentForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (state.agentRunning) return;
  const payload = formPayload(elements.agentForm);
  const message = payload.message;
  if (!message) return;
  state.chat.push({ role: "user", content: message });
  renderChat();
  elements.agentForm.querySelector("button").disabled = true;
  state.agentRunning = true;
  showStatus("LifeOps is thinking...", "info");
  try {
    const response = await api("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    state.chat.push({ role: "assistant", content: response.answer });
    state.data = response.state;
    renderAll();
    renderRunState(response.run_state);
    elements.agentForm.reset();
    showStatus("Agent turn completed.", "success");
  } catch (error) {
    state.chat.push({ role: "assistant", content: error.message });
    renderChat();
    showStatus(error.message, "error");
  } finally {
    elements.agentForm.querySelector("button").disabled = false;
    state.agentRunning = false;
  }
});

elements.clearAgent.addEventListener("click", async () => {
  try {
    await api("/api/agent/reset", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.chat = [];
    renderChat();
    renderRunState(null);
    renderActionFacts(null);
    showStatus("Agent conversation cleared.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  }
});

loadState().catch(error => showStatus(error.message, "error"));
