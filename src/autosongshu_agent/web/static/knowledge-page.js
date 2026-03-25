const state = {
  bases: [],
  baseDetails: new Map(),
  selectedBaseId: null,
  keyword: "",
  activeTab: "documents",
  hitQuery: "",
  hitResults: [],
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

function selectedBase() {
  if (!state.selectedBaseId) {
    return null;
  }
  return (
    state.baseDetails.get(state.selectedBaseId) ||
    state.bases.find((item) => item.id === state.selectedBaseId) ||
    null
  );
}

function filteredBases() {
  const keyword = String(state.keyword || "").trim().toLowerCase();
  if (!keyword) {
    return state.bases;
  }
  return state.bases.filter((item) => String(item.name || "").toLowerCase().includes(keyword));
}

function renderBaseList() {
  const root = byId("kbp-base-list");
  const count = byId("kbp-base-count");
  if (!root) {
    return;
  }

  const items = filteredBases();
  if (count) {
    count.textContent = `${items.length} 个`;
  }

  if (!items.length) {
    root.innerHTML = `
      <div class="kbp-empty-card">
        <h4>暂无知识库</h4>
        <p>先创建一个知识库，再导入文档内容。</p>
      </div>
    `;
    return;
  }

  root.innerHTML = items
    .map((item) => {
      const active = item.id === state.selectedBaseId;
      return `
        <button class="kbp-dataset-card ${active ? "active" : ""}" data-base-id="${escapeHtml(item.id)}" type="button">
          <div class="kbp-dataset-card-head">
            <strong title="${escapeHtml(item.name || item.id)}">${escapeHtml(item.name || item.id)}</strong>
            <span class="kbp-doc-badge">${Number(item.document_count || 0)} 文档</span>
          </div>
          <p class="kbp-dataset-card-desc">${escapeHtml(baseDescription(item))}</p>
          <div class="kbp-dataset-card-foot">
            <span>${Number(item.chunk_count || 0)} 分片</span>
            <em>更新于 ${escapeHtml(formatDate(item.updated_at || item.created_at))}</em>
          </div>
        </button>
      `;
    })
    .join("");
}

function documentsMarkup(base) {
  const docs = Array.isArray(base?.documents) ? base.documents : [];
  const docsMarkup = docs.length
    ? docs
        .map(
          (doc) => `
            <article class="kbp-doc-card">
              <div class="kbp-doc-head">
                <strong title="${escapeHtml(doc.title || doc.id)}">${escapeHtml(doc.title || doc.id)}</strong>
                <button class="kbp-btn kbp-btn-ghost kbp-btn-xs" data-delete-doc-id="${escapeHtml(doc.id)}" type="button">删除</button>
              </div>
              <div class="kbp-doc-meta">
                <span>${Number(doc.word_count || 0)} words</span>
                <span>${Number(doc.chunk_count || 0)} chunks</span>
                <span>${escapeHtml(formatDate(doc.updated_at || doc.created_at))}</span>
              </div>
              ${doc.source ? `<p class="kbp-doc-source">来源：${escapeHtml(doc.source)}</p>` : ""}
              <p class="kbp-doc-preview">${escapeHtml(doc.content_preview || "")}</p>
            </article>
          `,
        )
        .join("")
    : `
      <div class="kbp-empty-inline">
        <h4>还没有文档</h4>
        <p>可直接粘贴文本，或上传 txt / md / html 文件。</p>
      </div>
    `;

  return `
    <section class="kbp-panel">
      <div class="kbp-panel-head">
        <h3>知识库设置</h3>
      </div>
      <div class="kbp-two-col">
        <label class="kbp-field">
          <span>名称</span>
          <input id="kbp-edit-name" type="text" value="${escapeHtml(base?.name || "")}" />
        </label>
        <label class="kbp-field">
          <span>描述</span>
          <input id="kbp-edit-description" type="text" value="${escapeHtml(base?.description || "")}" />
        </label>
      </div>
      <div class="kbp-actions">
        <button class="kbp-btn kbp-btn-primary" id="kbp-save-base" type="button">保存设置</button>
        <button class="kbp-btn kbp-btn-danger" id="kbp-delete-base" type="button">删除知识库</button>
      </div>
    </section>

    <section class="kbp-panel">
      <div class="kbp-panel-head">
        <h3>导入文档</h3>
      </div>
      <div class="kbp-import-grid">
        <label class="kbp-field">
          <span>文档标题</span>
          <input id="kbp-doc-title" type="text" placeholder="例如：登录流程说明" />
        </label>
        <label class="kbp-field">
          <span>来源（可选）</span>
          <input id="kbp-doc-source" type="text" placeholder="wiki / URL / 文件路径" />
        </label>
      </div>
      <label class="kbp-field">
        <span>文本内容</span>
        <textarea id="kbp-doc-content" rows="6" placeholder="可直接粘贴文档内容"></textarea>
      </label>
      <label class="kbp-field">
        <span>或上传文件</span>
        <input id="kbp-doc-file" type="file" />
      </label>
      <div class="kbp-actions">
        <button class="kbp-btn kbp-btn-primary" id="kbp-save-doc" type="button">保存文档</button>
      </div>
    </section>

    <section class="kbp-panel">
      <div class="kbp-panel-head">
        <h3>文档列表</h3>
        <span class="kbp-panel-meta">${docs.length} 个文档</span>
      </div>
      <div class="kbp-doc-list">${docsMarkup}</div>
    </section>
  `;
}

function hitTestingMarkup(base) {
  const results = Array.isArray(state.hitResults) ? state.hitResults : [];
  const resultsMarkup = results.length
    ? results
        .map(
          (item, index) => `
            <article class="kbp-hit-card">
              <div class="kbp-hit-head">
                <strong>#${index + 1} ${escapeHtml(item.document_title || item.document_id)}</strong>
                <span>${Number(item.score || 0).toFixed(2)}</span>
              </div>
              <p class="kbp-hit-meta">chunk ${Number(item.chunk_index || 0)} · ${escapeHtml(item.knowledge_base_name || "")}</p>
              <div class="kbp-hit-content">${escapeHtml(item.content || "")}</div>
            </article>
          `,
        )
        .join("")
    : `
      <div class="kbp-empty-inline">
        <h4>暂无命中结果</h4>
        <p>输入问题并点击“测试命中”查看检索效果。</p>
      </div>
    `;

  return `
    <section class="kbp-panel">
      <div class="kbp-panel-head">
        <h3>命中测试</h3>
      </div>
      <label class="kbp-field">
        <span>查询问题</span>
        <textarea id="kbp-hit-query" rows="4" placeholder="例如：登录接口限流策略有哪些？">${escapeHtml(state.hitQuery)}</textarea>
      </label>
      <div class="kbp-actions">
        <button class="kbp-btn kbp-btn-primary" id="kbp-run-hit" type="button">测试命中</button>
      </div>
      <p class="kbp-hint">当前知识库：${escapeHtml(base?.name || base?.id || "")}</p>
    </section>

    <section class="kbp-panel">
      <div class="kbp-panel-head">
        <h3>检索结果</h3>
        <span class="kbp-panel-meta">${results.length} 条</span>
      </div>
      <div class="kbp-hit-list">${resultsMarkup}</div>
    </section>
  `;
}

function renderMain() {
  const root = byId("kbp-main");
  if (!root) {
    return;
  }

  const base = selectedBase();
  if (!base) {
    root.innerHTML = `
      <div class="kbp-empty-main">
        <h3>请选择一个知识库</h3>
        <p>可在上方创建新的知识库，或从左侧卡片中选择已有知识库进行管理。</p>
      </div>
    `;
    return;
  }

  root.innerHTML = `
    <section class="kbp-detail-head">
      <div class="kbp-detail-copy">
        <h2>${escapeHtml(base.name || base.id)}</h2>
        <p>${escapeHtml(baseDescription(base))}</p>
      </div>
      <div class="kbp-stat-chips">
        <span>${Number(base.document_count || 0)} 文档</span>
        <span>${Number(base.chunk_count || 0)} 分片</span>
        <span>更新于 ${escapeHtml(formatDate(base.updated_at || base.created_at))}</span>
      </div>
    </section>

    <nav class="kbp-tabs">
      <button class="${state.activeTab === "documents" ? "active" : ""}" data-tab="documents" type="button">文档管理</button>
      <button class="${state.activeTab === "hit-testing" ? "active" : ""}" data-tab="hit-testing" type="button">命中测试</button>
    </nav>

    <section class="kbp-detail-body">
      ${state.activeTab === "documents" ? documentsMarkup(base) : hitTestingMarkup(base)}
    </section>
  `;
}

function render() {
  renderBaseList();
  renderMain();
}

async function loadBaseDetail(knowledgeBaseId) {
  if (!knowledgeBaseId) {
    return null;
  }
  const detail = await fetchJson(`/api/knowledge/bases/${encodeURIComponent(knowledgeBaseId)}`);
  state.baseDetails.set(knowledgeBaseId, detail);
  return detail;
}

async function refreshBases({ keepSelection = true } = {}) {
  const previous = keepSelection ? state.selectedBaseId : null;
  const payload = await fetchJson("/api/knowledge/bases");
  state.bases = payload.items || [];

  if (previous && state.bases.some((item) => item.id === previous)) {
    state.selectedBaseId = previous;
  } else {
    state.selectedBaseId = state.bases[0]?.id || null;
    state.hitResults = [];
    state.hitQuery = "";
  }

  if (state.selectedBaseId) {
    await loadBaseDetail(state.selectedBaseId);
  }

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

  await refreshBases({ keepSelection: false });
}

async function saveBase() {
  const baseId = String(state.selectedBaseId || "");
  if (!baseId) {
    return;
  }

  const name = String(byId("kbp-edit-name")?.value || "").trim();
  const description = String(byId("kbp-edit-description")?.value || "").trim();
  if (!name) {
    window.alert("名称不能为空");
    return;
  }

  await fetchJson(`/api/knowledge/bases/${encodeURIComponent(baseId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description || null }),
  });

  await refreshBases({ keepSelection: true });
}

async function deleteBase() {
  const baseId = String(state.selectedBaseId || "");
  if (!baseId) {
    return;
  }

  if (!window.confirm("确认删除这个知识库及其全部文档吗？")) {
    return;
  }

  await fetchJson(`/api/knowledge/bases/${encodeURIComponent(baseId)}`, {
    method: "DELETE",
  });

  state.baseDetails.delete(baseId);
  state.selectedBaseId = null;
  state.hitResults = [];
  state.hitQuery = "";

  await refreshBases({ keepSelection: false });
}

async function saveDocument() {
  const baseId = String(state.selectedBaseId || "");
  if (!baseId) {
    return;
  }

  const title = String(byId("kbp-doc-title")?.value || "").trim();
  const source = String(byId("kbp-doc-source")?.value || "").trim();
  const content = String(byId("kbp-doc-content")?.value || "").trim();
  const fileInput = byId("kbp-doc-file");
  const file = fileInput?.files?.[0] || null;

  if (!title) {
    window.alert("请输入文档标题");
    return;
  }
  if (!file && !content) {
    window.alert("请填写文档内容或上传文件");
    return;
  }

  if (file) {
    const form = new FormData();
    form.set("title", title);
    if (source) {
      form.set("source", source);
    }
    form.set("file", file);

    await fetchJson(`/api/knowledge/bases/${encodeURIComponent(baseId)}/documents/upload`, {
      method: "POST",
      body: form,
      timeoutMs: 30000,
    });
  } else {
    await fetchJson(`/api/knowledge/bases/${encodeURIComponent(baseId)}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        source: source || null,
        source_type: "text",
        content,
      }),
      timeoutMs: 30000,
    });
  }

  const titleInput = byId("kbp-doc-title");
  const sourceInput = byId("kbp-doc-source");
  const contentInput = byId("kbp-doc-content");
  if (titleInput) {
    titleInput.value = "";
  }
  if (sourceInput) {
    sourceInput.value = "";
  }
  if (contentInput) {
    contentInput.value = "";
  }
  if (fileInput) {
    fileInput.value = "";
  }

  await loadBaseDetail(baseId);
  await refreshBases({ keepSelection: true });
}

async function deleteDocument(documentId) {
  const baseId = String(state.selectedBaseId || "");
  if (!baseId || !documentId) {
    return;
  }

  if (!window.confirm("确认删除这个文档吗？")) {
    return;
  }

  await fetchJson(
    `/api/knowledge/bases/${encodeURIComponent(baseId)}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );

  await loadBaseDetail(baseId);
  await refreshBases({ keepSelection: true });
}

async function runHitTesting() {
  const baseId = String(state.selectedBaseId || "");
  if (!baseId) {
    return;
  }

  const query = String(byId("kbp-hit-query")?.value || "").trim();
  state.hitQuery = query;
  if (!query) {
    state.hitResults = [];
    render();
    return;
  }

  const payload = await fetchJson("/api/knowledge/hit-testing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      knowledge_base_id: baseId,
      query,
      limit: 10,
    }),
  });

  state.hitResults = payload.items || [];
  render();
}

document.addEventListener("click", (event) => {
  const baseButton = event.target.closest("[data-base-id]");
  if (baseButton) {
    state.selectedBaseId = String(baseButton.dataset.baseId || "");
    state.activeTab = "documents";
    state.hitResults = [];
    loadBaseDetail(state.selectedBaseId)
      .then(() => render())
      .catch((error) => window.alert(String(error.message || error)));
    return;
  }

  const tabButton = event.target.closest("[data-tab]");
  if (tabButton) {
    state.activeTab = String(tabButton.dataset.tab || "documents");
    render();
    return;
  }

  const deleteDocButton = event.target.closest("[data-delete-doc-id]");
  if (deleteDocButton) {
    const documentId = String(deleteDocButton.dataset.deleteDocId || "");
    deleteDocument(documentId).catch((error) => window.alert(String(error.message || error)));
    return;
  }

  if (event.target.closest("#kbp-create")) {
    createBase().catch((error) => window.alert(String(error.message || error)));
    return;
  }

  if (event.target.closest("#kbp-save-base")) {
    saveBase().catch((error) => window.alert(String(error.message || error)));
    return;
  }

  if (event.target.closest("#kbp-delete-base")) {
    deleteBase().catch((error) => window.alert(String(error.message || error)));
    return;
  }

  if (event.target.closest("#kbp-save-doc")) {
    saveDocument().catch((error) => window.alert(String(error.message || error)));
    return;
  }

  if (event.target.closest("#kbp-run-hit")) {
    runHitTesting().catch((error) => window.alert(String(error.message || error)));
  }
});

document.addEventListener("DOMContentLoaded", async () => {
  byId("kbp-refresh")?.addEventListener("click", () => {
    refreshBases({ keepSelection: true }).catch((error) => window.alert(String(error.message || error)));
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
    const bootstrap = await fetchJson("/api/knowledge/bootstrap");
    state.bases = bootstrap.items || [];
    state.selectedBaseId = state.bases[0]?.id || null;
    if (state.selectedBaseId) {
      await loadBaseDetail(state.selectedBaseId);
    }
    render();
  } catch (error) {
    const root = byId("kbp-main");
    if (root) {
      root.innerHTML = `
        <div class="kbp-empty-main">
          <h3>加载失败</h3>
          <p>${escapeHtml(String(error.message || error))}</p>
        </div>
      `;
    }
  }
});
