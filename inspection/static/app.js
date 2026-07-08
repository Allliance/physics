const state = {
  datasets: [],
  dataset: "",
  q: "",
  label: "",
  offset: 0,
  limit: 50,
  total: 0,
  labelOptions: [],
};

const els = {
  datasetSelect: document.querySelector("#datasetSelect"),
  searchInput: document.querySelector("#searchInput"),
  labelSelect: document.querySelector("#labelSelect"),
  summary: document.querySelector("#summary"),
  resultMeta: document.querySelector("#resultMeta"),
  sampleList: document.querySelector("#sampleList"),
  prevButton: document.querySelector("#prevButton"),
  nextButton: document.querySelector("#nextButton"),
  dialog: document.querySelector("#sampleDialog"),
  dialogEyebrow: document.querySelector("#dialogEyebrow"),
  dialogTitle: document.querySelector("#dialogTitle"),
  dialogContent: document.querySelector("#dialogContent"),
};

function debounce(fn, wait = 250) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

async function getJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function looksJson(value) {
  const trimmed = value.trim();
  return (
    (trimmed.startsWith("[") && trimmed.endsWith("]")) ||
    (trimmed.startsWith("{") && trimmed.endsWith("}"))
  );
}

function prettyValue(value) {
  if (typeof value !== "string") return text(value);
  if (!looksJson(value)) return value;
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function parseMaybeJson(value) {
  if (typeof value !== "string") return value;
  if (!looksJson(value)) return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function finalAnswerItems(value) {
  const parsed = parseMaybeJson(value);
  if (Array.isArray(parsed)) return parsed.map((item) => text(item));
  if (parsed && typeof parsed === "object") return [JSON.stringify(parsed, null, 2)];
  const raw = text(parsed).trim();
  return raw ? [raw] : [];
}

function renderMath(root) {
  if (!window.renderMathInElement) return;
  renderMathInElement(root, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
    strict: false,
  });
}

function setLoading(message) {
  els.sampleList.innerHTML = `<div class="empty-state">${message}</div>`;
}

function setError(message) {
  els.sampleList.innerHTML = `<div class="error-state">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderDatasets() {
  els.datasetSelect.innerHTML = state.datasets
    .map((dataset) => `<option value="${escapeHtml(dataset.id)}">${escapeHtml(dataset.label)}</option>`)
    .join("");

  if (state.datasets.length) {
    const preferred = state.datasets.find((dataset) => dataset.id.includes("FrontierPhysics"));
    state.dataset = (preferred || state.datasets[0]).id;
    els.datasetSelect.value = state.dataset;
  }

  els.summary.textContent = `${state.datasets.length} datasets discovered`;
}

function renderSamples(items) {
  if (!items.length) {
    els.sampleList.innerHTML = `<div class="empty-state">No samples match this question filter.</div>`;
    return;
  }

  els.sampleList.innerHTML = items
    .map((item) => {
      const tags = item.labels && item.labels.length ? item.labels : [item.split, item.part].filter(Boolean);
      const tagHtml = tags.map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("");
      const source = item.source_file ? `Source: ${escapeHtml(item.source_file)}` : "";
      return `
        <button class="sample-item" type="button" data-row-index="${item.row_index}">
          <div>
            <div class="sample-title">
              <span class="sample-id">${escapeHtml(item.id)}</span>
              ${tagHtml}
            </div>
            <div class="sample-question">${escapeHtml(item.question || "(No question field)")}</div>
          </div>
          <div class="sample-meta">${source}<br>${item.field_count} fields</div>
        </button>
      `;
    })
    .join("");

  for (const item of els.sampleList.querySelectorAll(".sample-item")) {
    item.addEventListener("click", () => openSample(item.dataset.rowIndex));
  }
  renderMath(els.sampleList);
}

function renderPageMeta() {
  const start = state.total === 0 ? 0 : state.offset + 1;
  const end = Math.min(state.offset + state.limit, state.total);
  const filters = [];
  if (state.q) filters.push(`question contains "${state.q}"`);
  if (state.label) filters.push(`label "${state.label}"`);
  els.resultMeta.textContent = `${start}-${end} of ${state.total} samples${filters.length ? ` matching ${filters.join(", ")}` : ""}`;
  els.prevButton.disabled = state.offset <= 0;
  els.nextButton.disabled = state.offset + state.limit >= state.total;
}

function renderLabelOptions() {
  const current = state.label;
  els.labelSelect.innerHTML = `<option value="">Any label</option>${state.labelOptions
    .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.value)} (${option.count})</option>`)
    .join("")}`;
  els.labelSelect.value = state.labelOptions.some((option) => option.value === current) ? current : "";
  state.label = els.labelSelect.value;
}

async function loadDatasets() {
  const payload = await getJson("/api/datasets");
  state.datasets = payload.datasets;
  renderDatasets();
  if (state.dataset) await loadSamples();
}

async function loadSamples() {
  if (!state.dataset) return;
  setLoading("Loading samples...");
  const params = new URLSearchParams({
    dataset: state.dataset,
    q: state.q,
    label: state.label,
    offset: state.offset,
    limit: state.limit,
  });

  try {
    const payload = await getJson(`/api/samples?${params}`);
    state.total = payload.total;
    state.labelOptions = payload.label_options || [];
    renderLabelOptions();
    renderPageMeta();
    renderSamples(payload.items);
  } catch (error) {
    state.total = 0;
    renderPageMeta();
    setError(error.message);
  }
}

async function openSample(rowIndex) {
  const params = new URLSearchParams({ dataset: state.dataset, row_index: rowIndex });
  els.dialogEyebrow.textContent = `Sample ${rowIndex}`;
  els.dialogTitle.textContent = "Loading...";
  els.dialogContent.innerHTML = "";
  els.dialog.showModal();

  try {
    const payload = await getJson(`/api/sample?${params}`);
    const sample = payload.sample;
    els.dialogTitle.textContent = text(sample.id || sample.sample_id || sample.__line_number || rowIndex);
    renderFields(sample);
  } catch (error) {
    els.dialogTitle.textContent = "Unable to load sample";
    els.dialogContent.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderFields(sample) {
  const label = text(sample.__part || sample.verdict || sample.part || sample.label || "unlabeled");
  const primaryKeys = ["question", "final_answers", "solution"].filter((key) => key in sample);

  const fieldHtml = (key, mode) => {
    const value = prettyValue(sample[key]);
    const safeKey = key.replaceAll("_", "-");
    const fieldClass = ["field", `field-${safeKey}`, "field-primary"].join(" ");
    const length = text(sample[key]).length;
    const title = {
      question: "Question",
      final_answers: "Ground Truth",
      solution: "Solution",
    }[key] || key;
    const valueHtml =
      key === "final_answers"
        ? finalAnswersHtml(sample[key])
        : `<div class="field-value">${escapeHtml(value || "(empty)")}</div>`;
    return `
      <section class="${fieldClass}">
        <div class="field-name">
          <span>${escapeHtml(title)}</span>
          <span>${length.toLocaleString()} chars</span>
        </div>
        ${valueHtml}
      </section>
    `;
  };

  els.dialogContent.innerHTML = `
    ${labelBarHtml(label)}
    <div class="primary-fields">
      ${primaryKeys.map((key) => fieldHtml(key)).join("")}
    </div>
  `;
  renderMath(els.dialogContent);
}

function labelBarHtml(label) {
  const normalized = label.toLowerCase();
  let tone = "neutral";
  if (normalized.includes("fully") || normalized.includes("full")) tone = "full";
  if (normalized.includes("partial")) tone = "partial";
  if (normalized.includes("non")) tone = "non";
  return `
    <div class="label-bar label-${tone}">
      <span class="label-dot"></span>
      <span>${escapeHtml(label.replaceAll("_", " "))}</span>
    </div>
  `;
}

function finalAnswersHtml(value) {
  const answers = finalAnswerItems(value);
  if (!answers.length) {
    return `<div class="field-value">(empty)</div>`;
  }
  return `
    <div class="answer-list">
      ${answers
        .map((answer, index) => {
          const trimmed = answer.trim();
          const math = trimmed.startsWith("\\") || /[\\$_^{}]/.test(trimmed) ? trimmed : `\\text{${trimmed.replaceAll("\\", "\\\\").replaceAll("{", "\\{").replaceAll("}", "\\}")}}`;
          return `
            <div class="answer-card">
              <div class="answer-label">Ground truth ${index + 1}</div>
              <div class="answer-render">\\[${escapeHtml(math)}\\]</div>
              <details class="answer-source">
                <summary>Source</summary>
                <pre>${escapeHtml(answer)}</pre>
              </details>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

els.datasetSelect.addEventListener("change", () => {
  state.dataset = els.datasetSelect.value;
  state.label = "";
  state.offset = 0;
  loadSamples();
});

els.searchInput.addEventListener(
  "input",
  debounce(() => {
    state.q = els.searchInput.value.trim();
    state.offset = 0;
    loadSamples();
  }),
);

els.labelSelect.addEventListener("change", () => {
  state.label = els.labelSelect.value;
  state.offset = 0;
  loadSamples();
});

els.prevButton.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  loadSamples();
});

els.nextButton.addEventListener("click", () => {
  state.offset += state.limit;
  loadSamples();
});

loadDatasets().catch((error) => {
  els.summary.textContent = "Unable to load datasets";
  setError(error.message);
});
