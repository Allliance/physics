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
  questionPreviewButton: document.querySelector("#questionPreviewButton"),
  questionPreviewDialog: document.querySelector("#questionPreviewDialog"),
  questionPreviewInput: document.querySelector("#questionPreviewInput"),
  questionPreviewOutput: document.querySelector("#questionPreviewOutput"),
  questionPreviewCount: document.querySelector("#questionPreviewCount"),
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

function groundTruthItems(value) {
  const parsed = parseMaybeJson(value);
  if (Array.isArray(parsed)) {
    return parsed.map((item, index) => ({ label: String(index + 1), answer: item }));
  }
  if (parsed && typeof parsed === "object") {
    return Object.entries(parsed).map(([label, answer]) => ({ label, answer }));
  }
  const raw = text(parsed).trim();
  return raw ? [{ label: "1", answer: raw }] : [];
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

function questionTextFromParsedJson(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const item = value.find((entry) => entry && typeof entry === "object" && "question" in entry);
    return item ? text(item.question) : text(value);
  }
  if (value && typeof value === "object" && "question" in value) {
    return text(value.question);
  }
  return text(value);
}

function decodeQuestionPreviewText(value) {
  const trimmed = value.trim();
  if (!trimmed) return "";

  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    looksJson(trimmed)
  ) {
    try {
      return questionTextFromParsedJson(JSON.parse(trimmed));
    } catch {
      // Fall through to fragment decoding for copied JSON field values.
    }
  }

  if (/^"question"\s*:/.test(trimmed)) {
    try {
      return questionTextFromParsedJson(JSON.parse(`{${trimmed.replace(/,\s*$/, "")}}`));
    } catch {
      // Fall through to fragment decoding for partial or malformed JSON.
    }
  }

  return value
    .replaceAll("\\r\\n", "\n")
    .replaceAll("\\n", "\n")
    .replaceAll("\\t", "\t")
    .replaceAll("\\\\", "\\");
}

function renderQuestionPreview() {
  const rawQuestion = els.questionPreviewInput.value;
  const question = decodeQuestionPreviewText(rawQuestion);
  const trimmed = question.trim();
  els.questionPreviewCount.textContent = `${question.length.toLocaleString()} chars`;
  els.questionPreviewOutput.classList.toggle("preview-placeholder", !trimmed);
  els.questionPreviewOutput.innerHTML = escapeHtml(trimmed || "Paste a question to preview it.");
  renderMath(els.questionPreviewOutput);
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
    const preferred =
      state.datasets.find((dataset) => dataset.type === "ground-truth extraction") ||
      state.datasets.find((dataset) => dataset.id.includes("FrontierPhysics"));
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

function currentDatasetName() {
  const dataset = state.datasets.find((item) => item.id === state.dataset);
  if (!dataset) return state.dataset.split(":").pop().split("/").pop() || "dataset";
  if (dataset.path) {
    if (dataset.type === "jsonl file") return dataset.path.split("/").pop().replace(/\.jsonl$/, "");
    const parts = dataset.path.split("/");
    if (dataset.type === "parquet file") return parts.slice(-3).join("/");
    return parts[parts.length - 1];
  }
  return dataset.label.replace(/\s+-\s+all prepared parts$/, "");
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
    const questionId = text(sample.id || sample.sample_id || sample.__line_number || rowIndex);
    els.dialogTitle.textContent = `${currentDatasetName()}:${questionId}`;
    renderFields(sample);
  } catch (error) {
    els.dialogTitle.textContent = "Unable to load sample";
    els.dialogContent.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }
}

function firstPresent(sample, keys) {
  return keys.find((key) => key in sample);
}

function renderFields(sample) {
  const label = text(sample.repair_status || sample.__part || sample.verdict || sample.part || sample.label || sample.domain || "unlabeled");
  const isRepairSample = "repaired_question" in sample || "original_question" in sample;
  const sections = isRepairSample
    ? [
        { title: "Original Question", key: firstPresent(sample, ["original_question", "question"]), kind: "text" },
        { title: "Repaired Question", key: firstPresent(sample, ["repaired_question"]), kind: "text" },
        { title: "Ground Truths", key: firstPresent(sample, ["ground_truths", "ground_truth", "final_answers", "answers"]), kind: "answers" },
        { title: "Solution", key: firstPresent(sample, ["solution", "solutions", "answer", "explanation"]), kind: "text" },
      ].filter((section) => section.key)
    : [
        { title: "Question", key: firstPresent(sample, ["question", "questions", "statement", "problem", "prompt"]), kind: "text" },
        { title: "Ground Truths", key: firstPresent(sample, ["ground_truths", "ground_truth", "final_answers", "answers"]), kind: "answers" },
        { title: "Solution", key: firstPresent(sample, ["solution", "solutions", "answer", "explanation"]), kind: "text" },
      ].filter((section) => section.key);

  const fieldHtml = (section) => {
    const key = section.key;
    const value = prettyValue(sample[key]);
    const safeKey = section.title.toLowerCase().replaceAll(" ", "-");
    const fieldClass = ["field", `field-${safeKey}`, "field-primary"].join(" ");
    const length = text(sample[key]).length;
    const valueHtml =
      section.kind === "answers"
        ? finalAnswersHtml(sample[key], sample.null_answer_reasons || sample.ground_truth_failure_reasons)
        : `<div class="field-value">${escapeHtml(value || "(empty)")}</div>`;
    return `
      <section class="${fieldClass}">
        <div class="field-name">
          <span>${escapeHtml(section.title)}</span>
          <span>${length.toLocaleString()} chars</span>
        </div>
        ${valueHtml}
      </section>
    `;
  };

  els.dialogContent.innerHTML = `
    ${labelBarHtml(label)}
    <div class="primary-fields${isRepairSample ? " repair-fields" : ""}">
      ${sections.map((section) => fieldHtml(section)).join("")}
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

function finalAnswersHtml(value, failureReasons = {}) {
  const items = groundTruthItems(value);
  const reasons = parseMaybeJson(failureReasons);
  if (!items.length) {
    return `<div class="field-value">(empty)</div>`;
  }
  return `
    <div class="answer-list">
      ${items
        .map(({ label, answer }) => {
          const unavailable = answer === null;
          const reason = reasons && typeof reasons === "object" ? text(reasons[label]) : "";
          return `
            <div class="answer-card${unavailable ? " answer-card-unavailable" : ""}">
              <div class="answer-label"><span class="part-badge">(${escapeHtml(label)})</span> Ground truth</div>
              ${unavailable
                ? `<div class="answer-unavailable"><strong>Not extractable from the solution</strong><span>${escapeHtml(reason || "No reason supplied.")}</span></div>`
                : `<div class="answer-render">${answerDisplayHtml(text(answer))}</div>
                   <details class="answer-source">
                     <summary>Selected source content</summary>
                     <pre>${escapeHtml(text(answer))}</pre>
                   </details>`}
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function escapedDollarCount(value) {
  let count = 0;
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] !== "$") continue;
    let slashes = 0;
    for (let cursor = index - 1; cursor >= 0 && value[cursor] === "\\"; cursor -= 1) slashes += 1;
    if (slashes % 2 === 0) count += 1;
  }
  return count;
}

function answerDisplayHtml(answer) {
  let display = answer.trim();
  if (!display) return "(empty)";

  // Exact extracted spans occasionally begin/end inside a solution display-math
  // block. Remove delimiter-only lines for presentation; the untouched text is
  // always available under "Exact source substring".
  display = display
    .split("\n")
    .filter((line) => !/^(\s*)(\$\$|\\\[|\\\])(\s*)$/.test(line))
    .join("\n")
    .trim();

  const hasDelimiters = /\$|\\\(|\\\)|\\\[|\\\]/.test(display);
  if (!hasDelimiters) {
    const plainWords = /^[\p{L}\s-]+$/u.test(display);
    const math = plainWords
      ? `\\text{${display.replaceAll("\\", "\\\\").replaceAll("{", "\\{").replaceAll("}", "\\}")}}`
      : display;
    return `\\[${escapeHtml(math)}\\]`;
  }

  // Balance a truncated inline delimiter at the edge of an exact source span.
  if (escapedDollarCount(display.replaceAll("$$", "")) % 2 === 1) display += "$";
  return escapeHtml(display);
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

els.questionPreviewButton.addEventListener("click", () => {
  renderQuestionPreview();
  els.questionPreviewDialog.showModal();
  requestAnimationFrame(() => els.questionPreviewInput.focus());
});

els.questionPreviewInput.addEventListener("input", renderQuestionPreview);

loadDatasets().catch((error) => {
  els.summary.textContent = "Unable to load datasets";
  setError(error.message);
});
