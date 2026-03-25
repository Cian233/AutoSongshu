const pageDataset = document.body?.dataset || {};

const state = {
  bases: [],
  baseDetails: new Map(),
  documentDetails: new Map(),
  selectedBaseId: String(pageDataset.baseId || "").trim(),
  keyword: "",
  activeTab: String(pageDataset.activeTab || "documents") === "hit-testing" ? "hit-testing" : "documents",
  hitQuery: "",
  hitResults: [],
  activeDocument: null,
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

function buildBasePath(baseId, tab = state.activeTab) {
  const normalizedTab = tab === "hit-testing" ? "hit-testing" : "documents";
  return `/knowledge/bases/${encodeURIComponent(String(baseId || ""))}/${normalizedTab}`;
}

function documentCacheKey(baseId, documentId) {
  return `${String(baseId || "").trim()}:${String(documentId || "").trim()}`;
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
  const selectedId = String(state.selectedBaseId);
  return (
    state.baseDetails.get(selectedId) ||
    state.bases.find((item) => String(item.id) === selectedId) ||
    null
  );
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
    root.innerHTML = `
      <div class="kbp-empty-inline">
        <h4>没有匹配项</h4>
        <p>换一个关键词再试试。</p>
      </div>
    `;
    return;
  }

  const selectedId = String(state.selectedBaseId);
  root.innerHTML = items
    .map((item) => {
      const active = String(item.id) === selectedId;
      const path = buildBasePath(item.id, state.activeTab);
      return `
        <a class="kbp-side-item ${active ? "active" : ""}" href="${escapeHtml(path)}">
          <strong title="${escapeHtml(item.name || item.id)}">${escapeHtml(item.name || item.id)}</strong>
          <span>${formatCount(item.document_count)} 文档 · ${formatCount(item.chunk_count)} 分片</span>
        </a>
      `;
    })
    .join("");
}

function documentsMarkup(base) {
  const docs = Array.isArray(base?.documents) ? base.documents : [];
  const docsMarkup = docs.length
    ? docs
        .map(
          (doc) => {
            const preview = String(doc.content_preview || "")
              .replace(/\s+/g, " ")
              .trim();
            const compactPreview = preview
              ? preview.length > 120
                ? `${preview.slice(0, 120)}...`
                : preview
              : "暂无预览内容";
            return `
              <article class="kbp-doc-row">
                <div class="kbp-doc-row-main">
                  <strong title="${escapeHtml(doc.title || doc.id)}">${escapeHtml(doc.title || doc.id)}</strong>
                  <p class="kbp-doc-row-preview">${escapeHtml(compactPreview)}</p>
                  ${doc.source ? `<span class="kbp-doc-source-tag" title="${escapeHtml(doc.source)}">${escapeHtml(doc.source)}</span>` : ""}
                </div>
                <div class="kbp-doc-row-meta">
                  <span class="kbp-meta-chip">${formatCount(doc.word_count)} words</span>
                  <span class="kbp-meta-chip">${formatCount(doc.chunk_count)} chunks</span>
                  <span class="kbp-meta-chip">${formatCount(doc.content_length || 0)} chars</span>
                  <span class="kbp-meta-chip">${escapeHtml(formatDate(doc.updated_at || doc.created_at))}</span>
                </div>
                <div class="kbp-doc-row-actions">
                  <button class="kbp-btn kbp-btn-ghost kbp-btn-xs" data-view-doc-id="${escapeHtml(doc.id)}" type="button">详情</button>
                  <button class="kbp-btn kbp-btn-ghost kbp-btn-xs" data-delete-doc-id="${escapeHtml(doc.id)}" type="button">删除</button>
                </div>
              </article>
            `;
          },
        )
        .join("")
    : `
      <div class="kbp-empty-inline">
        <h4>还没有文档</h4>
        <p>可直接粘贴文本，或上传 txt / md / html 文件。</p>
      </div>
    `;

  return `
    <section class="kbp-doc-grid">
      <section class="kbp-panel kbp-panel-settings">
        <div class="kbp-panel-head">
          <div class="kbp-panel-title">
            <h3>知识库设置</h3>
            <p>调整名称和描述，便于团队检索与复用。</p>
          </div>
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

      <section class="kbp-panel kbp-panel-docs">
        <div class="kbp-panel-head">
          <div class="kbp-panel-title">
            <h3>文档列表</h3>
            <p>面向检索的文档视图，支持详情与删除。</p>
          </div>
          <div class="kbp-panel-actions">
            <span class="kbp-panel-meta">${docs.length} 个文档</span>
            <button class="kbp-btn kbp-btn-primary kbp-btn-xs" id="kbp-toggle-import" type="button">新增文档</button>
          </div>
        </div>
        ${
          docs.length
            ? `
          <div class="kbp-doc-table-head">
            <span>文档</span>
            <span>元信息</span>
            <span>操作</span>
          </div>
          <div class="kbp-doc-table">${docsMarkup}</div>
        `
            : `<div class="kbp-doc-table kbp-doc-table-empty">${docsMarkup}</div>`
        }
      </section>
    </section>

    <details class="kbp-panel kbp-import-details" id="kbp-import-details">
      <summary class="kbp-import-summary">
        <div class="kbp-panel-title">
          <h3>导入文档</h3>
          <p>支持文本直贴与文件上传，导入后自动分块与向量化。</p>
        </div>
        <span class="kbp-import-state">点击展开</span>
      </summary>
      <div class="kbp-import-content">
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
      </div>
    </details>
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
                <span class="kbp-hit-score">${Number(item.score || 0).toFixed(2)}</span>
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
        <div class="kbp-panel-title">
          <h3>命中测试</h3>
          <p>用于验证分块与检索策略是否覆盖关键知识点。</p>
        </div>
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
        <div class="kbp-panel-title">
          <h3>检索结果</h3>
          <p>按重排分数展示最相关片段。</p>
        </div>
        <span class="kbp-panel-meta">${results.length} 条</span>
      </div>
      <div class="kbp-hit-list">${resultsMarkup}</div>
    </section>
  `;
}

function documentDetailModalMarkup() {
  const doc = state.activeDocument;
  if (!doc) {
    return "";
  }

  const content = String(doc.content || doc.content_preview || "").trim();
  return `
    <div class="kbp-modal-backdrop" data-doc-modal-backdrop="1">
      <section class="kbp-modal" data-doc-modal-card="1" role="dialog" aria-modal="true" aria-label="文档详情">
        <div class="kbp-modal-head">
          <div class="kbp-modal-title">
            <h3>${escapeHtml(doc.title || doc.id || "文档详情")}</h3>
            <p>${escapeHtml(doc.source ? `来源：${doc.source}` : "无来源信息")}</p>
          </div>
          <button class="kbp-btn kbp-btn-ghost kbp-btn-xs" id="kbp-close-doc-detail" type="button">关闭</button>
        </div>
        <div class="kbp-modal-meta">
          <span class="kbp-meta-chip">${formatCount(doc.word_count)} words</span>
          <span class="kbp-meta-chip">${formatCount(doc.chunk_count)} chunks</span>
          <span class="kbp-meta-chip">${formatCount(doc.content_length)} chars</span>
          <span class="kbp-meta-chip">${escapeHtml(formatDate(doc.updated_at || doc.created_at))}</span>
        </div>
        <pre class="kbp-modal-content">${escapeHtml(content || "暂无文档内容")}</pre>
      </section>
    </div>
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
        <h3>找不到该知识库</h3>
        <p>该知识库可能已删除，返回列表后重新选择。</p>
        <div class="kbp-actions">
          <a class="kbp-btn kbp-btn-primary" href="/knowledge">返回知识库列表</a>
        </div>
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
        <span>${formatCount(base.document_count)} 文档</span>
        <span>${formatCount(base.chunk_count)} 分片</span>
        <span title="${escapeHtml(base.id || "")}">ID ${escapeHtml(shortId(base.id || ""))}</span>
        <span>更新于 ${escapeHtml(formatDate(base.updated_at || base.created_at))}</span>
      </div>
    </section>

    <nav class="kbp-tabs">
      <a class="${state.activeTab === "documents" ? "active" : ""}" href="${escapeHtml(buildBasePath(base.id, "documents"))}">文档管理</a>
      <a class="${state.activeTab === "hit-testing" ? "active" : ""}" href="${escapeHtml(buildBasePath(base.id, "hit-testing"))}">命中测试</a>
    </nav>

    <section class="kbp-detail-body">
      ${state.activeTab === "documents" ? documentsMarkup(base) : hitTestingMarkup(base)}
    </section>

    ${documentDetailModalMarkup()}
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

async function refreshBases({ keepSelection = true, allowRedirect = true } = {}) {
  const previous = keepSelection && state.selectedBaseId ? String(state.selectedBaseId) : null;
  const payload = await fetchJson("/api/knowledge/bases");
  state.bases = payload.items || [];

  const hasPrevious = previous && state.bases.some((item) => String(item.id) === previous);
  if (hasPrevious) {
    state.selectedBaseId = previous;
  } else {
    state.selectedBaseId = state.bases[0]?.id ? String(state.bases[0].id) : "";
  }

  if (!state.selectedBaseId) {
    state.activeDocument = null;
    render();
    return;
  }

  if (!hasPrevious && previous && allowRedirect) {
    window.location.replace(buildBasePath(state.selectedBaseId, state.activeTab));
    return;
  }

  await loadBaseDetail(state.selectedBaseId);
  if (state.activeDocument && String(state.activeDocument.knowledge_base_id || "") !== String(state.selectedBaseId)) {
    state.activeDocument = null;
  }
  render();
}

async function openDocumentDetail(documentId) {
  const baseId = String(state.selectedBaseId || "");
  const normalizedDocumentId = String(documentId || "").trim();
  if (!baseId || !normalizedDocumentId) {
    return;
  }

  const cacheKey = documentCacheKey(baseId, normalizedDocumentId);
  const cached = state.documentDetails.get(cacheKey);
  if (cached) {
    state.activeDocument = cached;
    render();
    return;
  }

  const payload = await fetchJson(
    `/api/knowledge/bases/${encodeURIComponent(baseId)}/documents/${encodeURIComponent(normalizedDocumentId)}`,
  );
  state.documentDetails.set(cacheKey, payload);
  state.activeDocument = payload;
  render();
}

function closeDocumentDetail() {
  if (!state.activeDocument) {
    return;
  }
  state.activeDocument = null;
  render();
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

  await refreshBases({ keepSelection: true, allowRedirect: false });
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

  window.location.href = "/knowledge";
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
  await refreshBases({ keepSelection: true, allowRedirect: false });
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

  if (String(state.activeDocument?.id || "") === String(documentId)) {
    state.activeDocument = null;
  }
  state.documentDetails.delete(documentCacheKey(baseId, documentId));

  await loadBaseDetail(baseId);
  await refreshBases({ keepSelection: true, allowRedirect: false });
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
  const viewDocButton = event.target.closest("[data-view-doc-id]");
  if (viewDocButton) {
    const documentId = String(viewDocButton.dataset.viewDocId || "");
    openDocumentDetail(documentId).catch((error) => window.alert(String(error.message || error)));
    return;
  }

  const deleteDocButton = event.target.closest("[data-delete-doc-id]");
  if (deleteDocButton) {
    const documentId = String(deleteDocButton.dataset.deleteDocId || "");
    deleteDocument(documentId).catch((error) => window.alert(String(error.message || error)));
    return;
  }

  if (event.target.closest("#kbp-close-doc-detail")) {
    closeDocumentDetail();
    return;
  }

  const modalBackdrop = event.target.closest("[data-doc-modal-backdrop]");
  if (modalBackdrop && !event.target.closest("[data-doc-modal-card]")) {
    closeDocumentDetail();
    return;
  }

  if (event.target.closest("#kbp-toggle-import")) {
    const importDetails = byId("kbp-import-details");
    if (importDetails) {
      importDetails.open = true;
      importDetails.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
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
    refreshBases({ keepSelection: true, allowRedirect: false }).catch((error) =>
      window.alert(String(error.message || error)),
    );
  });

  byId("kbp-search")?.addEventListener("input", (event) => {
    state.keyword = String(event.target.value || "");
    renderBaseList();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.activeDocument) {
      closeDocumentDetail();
    }
  });

  try {
    await refreshBases({ keepSelection: true, allowRedirect: true });
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
