import {
  applyAuthorizationById,
  bootstrap,
  connectRealtime,
  createKnowledgeDocumentFromSession,
  interruptSession,
  loadSession,
  refreshData,
  refreshKnowledgeBases,
  saveAuthorizationRecord,
  scheduleRenderApp,
  submitMessage,
  wireApprovalButtons,
  wireCommandAutocomplete,
} from "./api.js";
import {
  byId,
  escapeHtml,
  freezeMessageRendering,
  setAssistantPartExpanded,
  state,
  unfreezeMessageRendering,
} from "./state.js";
import {
  fillAuthorizationDraft,
  getDefaultAuthorizationDraft,
  hydrateAssistantPart,
  collectSelectedKnowledgeBaseIds,
  renderApp,
  setAuthorizationFeedback,
  setSelectedKnowledgeBaseIds,
  toggleSettings,
} from "./render.js";

function on(id, eventName, handler) {
  byId(id)?.addEventListener(eventName, handler);
}

function focusById(id) {
  byId(id)?.focus();
}

function selectedSessionDetail() {
  if (!state.selectedSessionId) {
    return null;
  }
  const sessionId = String(state.selectedSessionId);
  return (
    state.sessionDetails.get(sessionId) ||
    state.sessions.find((item) => String(item.id) === sessionId) ||
    null
  );
}

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
    focusById("goal");
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

    const session = selectedSessionDetail();
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
  on("settings-button", "click", () => toggleSettings(true));
  on("close-settings", "click", () => toggleSettings(false));
  on("save-settings", "click", () => toggleSettings(false));
  on("settings-backdrop", "click", () => toggleSettings(false));

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
    if (event.key === "Escape" && state.settingsOpen) {
      toggleSettings(false);
    }
  });

  try {
    await bootstrap();
    await refreshKnowledgeBases({ loadDetail: true });
    connectRealtime();
    wireApprovalButtons();
    wireCommandAutocomplete();
  } catch (error) {
    const chatThread = byId("chat-thread");
    if (chatThread) {
      chatThread.innerHTML = `
        <article class="message assistant message-failed">
          <div class="message-label-row">
            <span class="message-label">助手</span>
          </div>
          <div class="message-bubble">
            <div class="markdown-body">${String(error.message || error)}</div>
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
