const state = { q: "", tag: "", status: "all", audit: "", scoreSort: "", offset: 0, limit: 50, total: 0 };
const $ = (selector) => document.querySelector(selector);
const els = {
  summary: $("#summary"), search: $("#searchInput"), tag: $("#tagSelect"),
  status: $("#statusSelect"), audit: $("#auditSelect"), scoreSort: $("#scoreSortSelect"),
  meta: $("#resultMeta"), list: $("#sampleList"), prev: $("#prevButton"), next: $("#nextButton"),
  dialog: $("#sampleDialog"), dialogEyebrow: $("#dialogEyebrow"),
  dialogTitle: $("#dialogTitle"), dialogContent: $("#dialogContent"), close: $("#closeDialog"),
};

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function renderMath(root) {
  if (!window.renderMathInElement) return;
  renderMathInElement(root, {
    delimiters: [
      { left: "$$", right: "$$", display: true }, { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false }, { left: "\\(", right: "\\)", display: false },
    ], throwOnError: false, strict: false,
  });
}

async function getJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function debounce(fn, delay = 250) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

function score(value) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(2);
}

function auditLabel(verdict) {
  return ({
    NATIVE_SOLVED: "native solved", GRADER_FALSE_NEGATIVE: "grader false negative",
    REFERENCE_ANSWER_ISSUE: "reference issue", MODEL_WRONG: "model wrong",
    UNCERTAIN: "uncertain", NOT_REVIEWED: "not reviewed",
  })[verdict] || verdict;
}

function auditTone(verdict) {
  if (["NATIVE_SOLVED", "GRADER_FALSE_NEGATIVE"].includes(verdict)) return "solved";
  if (verdict === "MODEL_WRONG") return "unsolved";
  return "warning";
}

function failureStageLabel(stage) {
  return ({
    LATEX_PARSE_FAILURE: "LaTeX → SymPy parsing failed",
    SYMPY_NORMALIZATION_FAILURE: "SymPy normalization failed",
    TREE_DISTANCE_FAILURE: "Tree-distance calculation failed",
    TREE_EQUIVALENCE_FALSE_NEGATIVE: "Canonicalization/tree comparison missed equivalence",
  })[stage] || stage;
}

function renderList(items) {
  if (!items.length) {
    els.list.innerHTML = '<div class="empty">No PHYBench questions match these filters.</div>';
    return;
  }
  els.list.innerHTML = items.map((item) => `
    <button class="sample-item" data-id="${escapeHtml(item.id)}">
      <div>
        <div class="sample-title"><strong>#${escapeHtml(item.id)}</strong><span class="pill">${escapeHtml(item.tag)}</span><span class="pill ${auditTone(item.audit_verdict)}">${escapeHtml(auditLabel(item.audit_verdict))}</span></div>
        <div class="question-preview">${escapeHtml(item.question)}</div>
      </div>
      <div class="sample-score"><strong>${score(item.best_eed)}</strong><span>best EED</span><small>${item.attempt_count} attempt${item.attempt_count === 1 ? "" : "s"}</small></div>
    </button>`).join("");
  els.list.querySelectorAll(".sample-item").forEach((button) => button.addEventListener("click", () => openSample(button.dataset.id)));
  renderMath(els.list);
}

async function loadSamples() {
  els.list.innerHTML = '<div class="empty">Loading questions…</div>';
  const params = new URLSearchParams({ q: state.q, tag: state.tag, status: state.status, audit: state.audit, score_sort: state.scoreSort, offset: state.offset, limit: state.limit });
  try {
    const payload = await getJson(`/api/samples?${params}`);
    state.total = payload.total;
    const start = state.total ? state.offset + 1 : 0;
    const end = Math.min(state.offset + state.limit, state.total);
    els.meta.textContent = `${start}–${end} of ${state.total}`;
    els.prev.disabled = state.offset === 0;
    els.next.disabled = state.offset + state.limit >= state.total;
    renderList(payload.items);
  } catch (error) {
    els.list.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

function field(title, value, className = "") {
  return `<section class="field ${className}"><header>${escapeHtml(title)}</header><div class="field-value">${escapeHtml(value || "(empty)")}</div></section>`;
}

function attemptHtml(attempt) {
  const usage = attempt.usage || {};
  const usageText = `${Number(usage.input_tokens || 0).toLocaleString()} input · ${Number(usage.output_tokens || 0).toLocaleString()} output · ${Number(usage.reasoning_output_tokens || 0).toLocaleString()} reasoning`;
  return `<section class="attempt ${attempt.success ? "attempt-success" : ""}">
    <header><div><strong>Round ${attempt.round}</strong><span class="pill ${attempt.success ? "solved" : "unsolved"}">${attempt.success ? "exact match" : "not matched"}</span></div><div class="attempt-score">EED ${score(attempt.eed_score)}</div></header>
    <div class="attempt-answer">${escapeHtml(attempt.final_answer || "(empty)")}</div>
    ${attempt.normalized_final_answer !== attempt.final_answer ? `<details><summary>Normalized answer sent to EED</summary><pre>${escapeHtml(attempt.normalized_final_answer)}</pre></details>` : ""}
    <footer>${escapeHtml(usageText)} · tree distance ${escapeHtml(attempt.distance)} · relative ${escapeHtml(attempt.relative_distance)}</footer>
  </section>`;
}

async function openSample(id) {
  els.dialogEyebrow.textContent = `PHYBench #${id}`;
  els.dialogTitle.textContent = "Loading…";
  els.dialogContent.innerHTML = "";
  els.dialog.showModal();
  try {
    const { sample } = await getJson(`/api/sample?id=${encodeURIComponent(id)}`);
    els.dialogEyebrow.textContent = `${sample.tag} · ${sample.solved ? `Solved in round ${sample.solved_round}` : "Unsolved after 5 rounds"}`;
    els.dialogTitle.textContent = `PHYBench #${sample.id} · Best EED ${score(sample.best_eed)}`;
    els.dialogContent.innerHTML = `
      <section class="audit-banner ${auditTone(sample.audit_verdict)}"><strong>${escapeHtml(auditLabel(sample.audit_verdict))}</strong><span>${escapeHtml(sample.audit_reason)}</span>${sample.eed_failure_stage ? `<span><b>Native EED failure:</b> ${escapeHtml(failureStageLabel(sample.eed_failure_stage))}</span>` : ""}${sample.audit_equivalent_rounds.length ? `<small>Equivalent round(s): ${sample.audit_equivalent_rounds.join(", ")}</small>` : ""}</section>
      ${field("Question", sample.question, "question-field")}
      <div class="reference-grid">${field("Reference answer", sample.reference_answer, "answer-field")}${field("Official solution", sample.solution, "solution-field")}</div>
      <section><h3>Model attempts</h3><div class="attempts">${sample.attempts.map(attemptHtml).join("")}</div></section>`;
    renderMath(els.dialogContent);
  } catch (error) {
    els.dialogTitle.textContent = "Unable to load question";
    els.dialogContent.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

async function init() {
  const meta = await getJson("/api/meta");
  els.summary.textContent = `${meta.total} questions · ${meta.solved} solved · ${meta.unsolved} unsolved`;
  els.tag.innerHTML += meta.tags.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join("");
  await loadSamples();
}

els.search.addEventListener("input", debounce(() => { state.q = els.search.value.trim(); state.offset = 0; loadSamples(); }));
els.tag.addEventListener("change", () => { state.tag = els.tag.value; state.offset = 0; loadSamples(); });
els.status.addEventListener("change", () => { state.status = els.status.value; state.offset = 0; loadSamples(); });
els.audit.addEventListener("change", () => { state.audit = els.audit.value; state.offset = 0; loadSamples(); });
els.scoreSort.addEventListener("change", () => { state.scoreSort = els.scoreSort.value; state.offset = 0; loadSamples(); });
els.prev.addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadSamples(); });
els.next.addEventListener("click", () => { state.offset += state.limit; loadSamples(); });
els.close.addEventListener("click", () => els.dialog.close());
els.dialog.addEventListener("click", (event) => { if (event.target === els.dialog) els.dialog.close(); });
init().catch((error) => { els.summary.textContent = "Failed to load"; els.list.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; });
