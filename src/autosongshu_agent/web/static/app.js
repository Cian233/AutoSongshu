import {
  applyAuthorizationById,
  bootstrap,
  connectRealtime,
  createKnowledgeDocumentFromSession,
  exportSession,
  interruptSession,
  loadSession,
  refreshData,
  refreshKnowledgeBases,
  reloadConfig,
  saveAuthorizationRecord,
  scheduleRenderApp,
  submitMessage,
  wireApprovalButtons,
  wireCommandAutocomplete,
} from "./api.js";
import {
  byId,
  escapeHtml,
  fetchJson,
  freezeMessageRendering,
  selectedSession,
  setAssistantPartExpanded,
  state,
  togglePanel,
  truncate,
  unfreezeMessageRendering,
} from "./state.js";
import {
  fillAuthorizationDraft,
  getDefaultAuthorizationDraft,
  hydrateAssistantPart,
  collectSelectedKnowledgeBaseIds,
  closeSearchPanel,
  isSearchPanelOpen,
  openSearchPanel,
  renderApp,
  setAuthorizationFeedback,
  setSelectedKnowledgeBaseIds,
  toggleSettings,
  wireSearchPanel,
} from "./render.js";

function on(id, eventName, handler) {
  byId(id)?.addEventListener(eventName, handler);
}

// ── Theme Management ──────────────────────────────────────────────
const THEME_STORAGE_KEY = "autosongshu-theme";
const THEME_CYCLE = ["system", "light", "dark"];

function getSystemPrefersDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

function resolveTheme(themeValue) {
  if (themeValue === "dark") return "dark";
  if (themeValue === "light") return "light";
  return getSystemPrefersDark() ? "dark" : "light";
}

function applyTheme(themeValue) {
  const resolved = resolveTheme(themeValue);
  const html = document.documentElement;
  if (resolved === "dark") {
    html.setAttribute("data-theme", "dark");
  } else {
    html.removeAttribute("data-theme");
  }
  // Update toggle button icon
  const btn = byId("theme-toggle-button");
  if (btn) {
    if (themeValue === "system") {
      btn.textContent = getSystemPrefersDark() ? "\uD83C\uDF19" : "\u2600\uFE0F";
      btn.setAttribute("aria-label", "主题：跟随系统");
    } else if (themeValue === "dark") {
      btn.textContent = "\uD83C\uDF19";
      btn.setAttribute("aria-label", "主题：深色");
    } else {
      btn.textContent = "\u2600\uFE0F";
      btn.setAttribute("aria-label", "主题：浅色");
    }
  }
}

function loadSavedTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") {
      return saved;
    }
  } catch (_) {}
  return "system";
}

export function toggleTheme() {
  const currentIndex = THEME_CYCLE.indexOf(state.theme);
  const nextIndex = (currentIndex + 1) % THEME_CYCLE.length;
  state.theme = THEME_CYCLE[nextIndex];
  applyTheme(state.theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  } catch (_) {}
}

// Apply theme immediately to avoid flash
state.theme = loadSavedTheme();
applyTheme(state.theme);

// Listen for system theme changes
try {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.theme === "system") {
      applyTheme("system");
    }
  });
} catch (_) {}

function chooseKnowledgeBaseId(defaultId = "") {
  if (!state.knowledgeBases.length) {
    return "";
  }
  const fallback = String(defaultId || state.knowledgeBases[0]?.id || "").trim();
  const options = state.knowledgeBases
    .map((item, index) => `${index + 1}. ${item.name || item.id} (${item.id})`)
    .join("\n");
  const input = window.prompt(`请选择目标知识库 ID：\n${options}`, fallback);
  if (input === null) {
    return null;
  }
  return String(input || "").trim();
}

document.addEventListener("click", (event) => {
  const sessionButton = event.target.closest("[data-session-id]");
  if (sessionButton) {
    const sessionId = String(sessionButton.dataset.sessionId || "");
    if (sessionId && sessionId !== String(state.selectedSessionId || "")) {
      // Reset render signature caches to force a fresh render of the new session
      const root = byId("chat-thread");
      if (root) {
        Array.from(root.children).forEach((child) => {
          child.__renderSignature = undefined;
        });
        root.dataset.view = "loading";
        root.innerHTML = '<div class="empty-state">正在加载对话内容...</div>';
      }

      state.selectedSessionId = sessionId;
      // We don't call scheduleRenderApp here because loadSession will do it after data is ready.
      // If we call it now, renderMessagesFast might clear the loading state and show the empty welcome screen
      // because state.sessionDetails doesn't have the data yet.
      loadSession(sessionId, { render: true }).catch((error) => {
        console.error("Failed to load session:", error);
        if (root && root.dataset.view === "loading") {
          root.innerHTML = `<div class="empty-state error">加载失败：${escapeHtml(error.message || error)}</div>`;
        }
      });
    }
    return;
  }

  const authorizationCard = event.target.closest("[data-authorization-id]");
  if (authorizationCard) {
    const { authorizationId } = authorizationCard.dataset;
    const authorizationProfile = byId("authorization-profile");
    if (authorizationProfile) {
      authorizationProfile.value = authorizationId;
    }
    applyAuthorizationById(authorizationId);
  }
});

document.addEventListener(
    "toggle",
    (event) => {
      const details = event.target;
      if (!(details instanceof HTMLDetailsElement)) {
        return;
      }
      const { assistantPartKey } = details.dataset;
      if (!assistantPartKey) {
        return;
      }

      if (details.dataset.ignoreToggle === "true") {
        details.removeAttribute("data-ignore-toggle");
        return;
      }

      const messageId = String(details.dataset.messageId || "");
      setAssistantPartExpanded(assistantPartKey, details.open);
      if (details.open) {
      freezeMessageRendering(messageId);
      hydrateAssistantPart(details);
      return;
    }

    const body = details.querySelector("[data-assistant-part-body]");
    if (body) {
      body.innerHTML = "";
      body.hidden = true;
    }
    if (unfreezeMessageRendering(messageId) === 0) {
      scheduleRenderApp({ force: true });
    }
  },
  true,
);

document.addEventListener("change", (event) => {
  const selector = event.target.closest("[data-knowledge-selector]");
  if (!selector) {
    return;
  }
  const checked = Array.from(document.querySelectorAll("[data-knowledge-selector]:checked")).map(
    (item) => item.dataset.knowledgeSelector,
  );
  setSelectedKnowledgeBaseIds(checked);
  scheduleRenderApp({ force: true });
});

document.addEventListener("DOMContentLoaded", async () => {
  const runForm = byId("run-form");
  const goal = byId("goal");

  runForm?.addEventListener("submit", submitMessage);
  goal?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    runForm?.requestSubmit();
  });

  on("new-chat-button", "click", () => {
    state.selectedSessionId = null;
    scheduleRenderApp({ force: true });
    byId("goal")?.focus();
  });
  on("refresh-button", "click", () => {
    refreshData().catch((error) => window.alert(String(error.message || error)));
  });
  on("pause-button", "click", () => {
    if (!state.selectedSessionId) {
      return;
    }
    interruptSession(state.selectedSessionId).catch((error) => window.alert(String(error.message || error)));
  });
  on("distill-knowledge-button", "click", async () => {
    if (state.isDistillingKnowledge) {
      return;
    }
    if (!state.selectedSessionId) {
      window.alert("请先选择一个会话。");
      return;
    }
    if (!state.knowledgeBases.length) {
      window.alert("请先创建知识库。");
      return;
    }

    const session = selectedSession();
    const linkedIds = Array.isArray(session?.knowledge_base_ids)
      ? session.knowledge_base_ids.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    const preferredKnowledgeBaseId =
      linkedIds[0] || collectSelectedKnowledgeBaseIds()[0] || String(state.selectedKnowledgeBaseId || "").trim();
    let knowledgeBaseId = preferredKnowledgeBaseId;
    if (!knowledgeBaseId || linkedIds.length > 1) {
      const chosen = chooseKnowledgeBaseId(preferredKnowledgeBaseId);
      if (chosen === null) {
        return;
      }
      knowledgeBaseId = chosen;
    }
    if (!knowledgeBaseId) {
      window.alert("请选择要写入的知识库。");
      return;
    }

    state.isDistillingKnowledge = true;
    scheduleRenderApp({ force: true });
    try {
      const result = await createKnowledgeDocumentFromSession(state.selectedSessionId, { knowledgeBaseId });
      const savedTitle = String(result?.document?.title || "").trim();
      window.alert(savedTitle ? `已沉淀：${savedTitle}` : "已沉淀");
    } catch (error) {
      window.alert(`沉淀失败：${String(error.message || error)}`);
    } finally {
      state.isDistillingKnowledge = false;
      scheduleRenderApp({ force: true });
    }
  });
  on("export-session-button", "click", () => {
    if (!state.selectedSessionId) {
      return;
    }
    exportSession(state.selectedSessionId, "markdown");
  });
  on("settings-button", "click", () => toggleSettings(true));
  on("close-settings", "click", () => toggleSettings(false));
  on("save-settings", "click", () => toggleSettings(false));
  on("settings-backdrop", "click", () => toggleSettings(false));
  on("theme-toggle-button", "click", toggleTheme);
  on("reload-config-button", "click", async () => {
    const configPath = byId("config-path")?.value || "";
    const result = await reloadConfig(configPath || undefined);
    if (result) {
      window.alert("配置已重新加载成功");
    }
  });

  on("save-authorization", "click", saveAuthorizationRecord);
  on("authorization-profile", "change", (event) => {
    if (!event.target.value) {
      setAuthorizationFeedback("New sessions will use the current form values.");
      return;
    }
    applyAuthorizationById(event.target.value);
  });
  on("reset-settings", "click", () => {
    const authorizationProfile = byId("authorization-profile");
    const configPath = byId("config-path");
    const skillDirs = byId("skill-dirs");

    if (authorizationProfile) {
      authorizationProfile.value = "";
    }
    if (configPath) {
      configPath.value = state.defaultConfigPath;
    }
    if (skillDirs) {
      skillDirs.value = "";
    }

    setSelectedKnowledgeBaseIds([]);
    fillAuthorizationDraft(getDefaultAuthorizationDraft());
    setAuthorizationFeedback("Reset to default settings.", "success");
    scheduleRenderApp({ force: true });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (isSearchPanelOpen()) {
        closeSearchPanel();
        return;
      }
      if (state.settingsOpen) {
        toggleSettings(false);
      }
    }
  });

  // ── Keyboard Shortcuts ────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (!mod) return;

    switch (e.key.toLowerCase()) {
      case "n":
        e.preventDefault();
        document.getElementById("new-chat-button")?.click();
        break;
      case ",":
        e.preventDefault();
        document.getElementById("settings-button")?.click();
        break;
      case "f":
        e.preventDefault();
        // Open the search panel for message search
        openSearchPanel();
        break;
      case "d":
        if (e.shiftKey) {
          e.preventDefault();
          toggleTheme();
        }
        break;
    }
  });

  // ── Sidebar Panel Toggle Sync ────────────────────────────────
  document.querySelectorAll(".sidebar-panel").forEach((panel) => {
    panel.addEventListener("toggle", () => {
      const panelKey = panel.dataset.panelKey;
      if (panelKey) {
        togglePanel(panelKey);
      }
    });
  });

  try {
    await bootstrap();
    await refreshKnowledgeBases({ loadDetail: true });
    connectRealtime();
    wireApprovalButtons();
    wireCommandAutocomplete();
    wireSearchPanel();
  } catch (error) {
    const chatThread = byId("chat-thread");
    if (chatThread) {
      chatThread.innerHTML = `
        <article class="message assistant message-failed">
          <div class="message-label-row">
            <span class="message-label">助手</span>
          </div>
          <div class="message-bubble">
            <div class="markdown-body">${escapeHtml(String(error.message || error))}</div>
          </div>
        </article>
      `;
    }
  }
});

window.addEventListener("beforeunload", () => {
  if (state.eventSource) {
    state.eventSource.close();
  }
});
