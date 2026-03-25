const state = {
  bases: [],
  keyword: "",
};

const DEFAULT_TIMEOUT_MS = 15000;

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function baseDescription(base) {
  const description = String(base?.description || "").trim();
  if (description) {
    return description;
  }
  return "未填写描述";
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function shortId(value, maxLength = 12) {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength)}...`;
}

function buildBasePath(baseId, tab = "documents") {
  const normalizedTab = tab === "hit-testing" ? "hit-testing" : "documents";
  return `/knowledge/bases/${encodeURIComponent(String(baseId || ""))}/${normalizedTab}`;
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options || {};
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer =
    controller && timeoutMs > 0 ? window.setTimeout(() => controller.abort(), timeoutMs) : null;

  try {
    const response = await fetch(
      url,
      controller ? { ...fetchOptions, signal: controller.signal } : fetchOptions,
    );
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_) {
        payload = text;
      }
    }
    if (!response.ok) {
      const detail =
        typeof payload === "object" && payload && "detail" in payload
          ? payload.detail
          : typeof payload === "string"
            ? payload
            : response.statusText;
      throw new Error(String(detail || "Request failed."));
    }
    return payload;
  } catch (error) {
    if (controller?.signal?.aborted) {
      throw new Error("请求超时，请稍后重试。");
    }
    throw error;
  } finally {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
  }
}

function filteredBases() {
  const keyword = String(state.keyword || "").trim().toLowerCase();
  if (!keyword) {
    return state.bases;
  }
  return state.bases.filter((item) => {
    const name = String(item.name || "").toLowerCase();
    const description = String(item.description || "").toLowerCase();
    return name.includes(keyword) || description.includes(keyword);
  });
}

function renderOverviewStats() {
  const totalBases = state.bases.length;
  const totalDocs = state.bases.reduce((sum, item) => sum + Number(item.document_count || 0), 0);
  const totalChunks = state.bases.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0);

  const basesEl = byId("kbp-stat-bases");
  const docsEl = byId("kbp-stat-docs");
  const chunksEl = byId("kbp-stat-chunks");

  if (basesEl) {
    basesEl.textContent = formatCount(totalBases);
  }
  if (docsEl) {
    docsEl.textContent = formatCount(totalDocs);
  }
  if (chunksEl) {
    chunksEl.textContent = formatCount(totalChunks);
  }
}

function renderBaseList() {
  const root = byId("kbp-base-list");
  const count = byId("kbp-base-count");
  if (!root) {
    return;
  }

  const items = filteredBases();
  if (count) {
    count.textContent = state.keyword ? `${items.length} / ${state.bases.length}` : `${items.length} 个`;
  }

  if (!items.length) {
    const hasKeyword = Boolean(String(state.keyword || "").trim());
    root.innerHTML = `
      <div class="kbp-empty-card">
        <h4>${hasKeyword ? "没有匹配的知识库" : "暂无知识库"}</h4>
        <p>${hasKeyword ? "你可以清空搜索词，或者先创建新的知识库。" : "先创建一个知识库，再导入文档开始沉淀经验。"}</p>
      </div>
    `;
    return;
  }

  root.innerHTML = items
    .map((item) => {
      const baseId = String(item.id || "");
      const documentsPath = buildBasePath(baseId, "documents");
      const hitPath = buildBasePath(baseId, "hit-testing");
      return `
        <article class="kbp-dataset-card" data-open-doc-url="${escapeHtml(documentsPath)}">
          <div class="kbp-dataset-card-head">
            <strong title="${escapeHtml(item.name || baseId)}">${escapeHtml(item.name || baseId)}</strong>
            <span class="kbp-doc-badge">${formatCount(item.document_count)} 文档</span>
          </div>
          <p class="kbp-dataset-card-desc">${escapeHtml(baseDescription(item))}</p>
          <div class="kbp-dataset-card-stats">
            <span>${formatCount(item.chunk_count)} 分片</span>
            <span title="${escapeHtml(baseId)}">ID ${escapeHtml(shortId(baseId))}</span>
          </div>
          <div class="kbp-dataset-card-foot">
            <em>更新于 ${escapeHtml(formatDate(item.updated_at || item.created_at))}</em>
          </div>
          <div class="kbp-dataset-card-actions">
            <a class="kbp-btn kbp-btn-primary kbp-btn-xs" href="${escapeHtml(documentsPath)}">文档管理</a>
            <a class="kbp-btn kbp-btn-ghost kbp-btn-xs" href="${escapeHtml(hitPath)}">命中测试</a>
          </div>
        </article>
      `;
    })
    .join("");
}

function render() {
  renderOverviewStats();
  renderBaseList();
}

async function refreshBases() {
  const payload = await fetchJson("/api/knowledge/bootstrap");
  state.bases = payload.items || [];
  render();
}

async function createBase() {
  const name = String(byId("kbp-create-name")?.value || "").trim();
  const description = String(byId("kbp-create-description")?.value || "").trim();

  if (!name) {
    window.alert("请输入知识库名称");
    return;
  }

  await fetchJson("/api/knowledge/bases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description || null }),
  });

  const nameInput = byId("kbp-create-name");
  const descInput = byId("kbp-create-description");
  if (nameInput) {
    nameInput.value = "";
  }
  if (descInput) {
    descInput.value = "";
  }

  await refreshBases();
}

document.addEventListener("click", (event) => {
  const createButton = event.target.closest("#kbp-create");
  if (createButton) {
    createBase().catch((error) => window.alert(String(error.message || error)));
    return;
  }

  const card = event.target.closest("[data-open-doc-url]");
  if (!card) {
    return;
  }

  if (event.target.closest("a, button, input, textarea, label")) {
    return;
  }
  const url = String(card.dataset.openDocUrl || "");
  if (url) {
    window.location.href = url;
  }
});

document.addEventListener("DOMContentLoaded", async () => {
  byId("kbp-refresh")?.addEventListener("click", () => {
    refreshBases().catch((error) => window.alert(String(error.message || error)));
  });

  byId("kbp-search")?.addEventListener("input", (event) => {
    state.keyword = String(event.target.value || "");
    renderBaseList();
  });

  const createOnEnter = (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      createBase().catch((error) => window.alert(String(error.message || error)));
    }
  };

  byId("kbp-create-name")?.addEventListener("keydown", createOnEnter);
  byId("kbp-create-description")?.addEventListener("keydown", createOnEnter);

  try {
    await refreshBases();
  } catch (error) {
    const root = byId("kbp-base-list");
    if (root) {
      root.innerHTML = `
        <div class="kbp-empty-card">
          <h4>加载失败</h4>
          <p>${escapeHtml(String(error.message || error))}</p>
        </div>
      `;
    }
  }
});
