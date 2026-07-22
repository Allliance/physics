const state = {
  datasets: [],
  dataset: "",
  q: "",
  label: "",
  scoreSort: "",
  offset: 0,
  limit: 50,
  total: 0,
  labelOptions: [],
};

const els = {
  datasetSelect: document.querySelector("#datasetSelect"),
  searchInput: document.querySelector("#searchInput"),
  labelSelect: document.querySelector("#labelSelect"),
  scoreSortSelect: document.querySelector("#scoreSortSelect"),
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
    ignoredClasses: ["katex", "katex-display", "manual-katex"],
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

function normalizeEscapedLatex(value) {
  return text(value)
    .replace(/\\\\([A-Za-z])/g, "\\$1")
    .replace(/\\\\([[\](){}])/g, "\\$1");
}

function richTextHtml(value, { normalizeLatex = false } = {}) {
  const display = normalizeLatex ? normalizeEscapedLatex(value) : text(value);
  return escapeHtml(display || "(empty)");
}

function mathBlockHtml(math) {
  if (window.katex) {
    const rendered = katex.renderToString(math, {
      displayMode: true,
      throwOnError: false,
      strict: false,
    });
    return `<span class="manual-katex">${rendered}</span>`;
  }
  return `\\[${escapeHtml(math)}\\]`;
}

function renderDatasets() {
  els.datasetSelect.innerHTML = state.datasets
    .map((dataset) => `<option value="${escapeHtml(dataset.id)}">${escapeHtml(dataset.label)}</option>`)
    .join("");

  if (state.datasets.length) {
    const preferred =
      state.datasets.find((dataset) => dataset.type === "ground-truth extraction issues") ||
      state.datasets.find((dataset) => dataset.type === "ground-truth extraction") ||
      state.datasets.find((dataset) => dataset.type === "original test set" && dataset.id.includes("FrontierPhysics")) ||
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
      const tagHtml = tags
        .map((tag) => `<span class="${pillClass(tag)}">${escapeHtml(tag)}</span>`)
        .join("");
      const source = item.source_file ? `Source: ${escapeHtml(item.source_file)}` : "";
      const score = scoreLabel(item);
      const facts = [
        item.has_solution ? "Solution" : "",
        item.ground_truth_count ? `${item.ground_truth_count} extracted GT` : "",
        `${item.field_count} fields`,
      ].filter(Boolean);
      const meta = [score, source, ...facts].filter(Boolean).map(escapeHtml).join("<br>");
      return `
        <button class="sample-item" type="button" data-row-index="${item.row_index}">
          <div>
            <div class="sample-title">
              <span class="sample-id">${escapeHtml(item.id)}</span>
              ${tagHtml}
            </div>
            <div class="sample-question">${escapeHtml(item.question || "(No question field)")}</div>
          </div>
          <div class="sample-meta">${meta}</div>
        </button>
      `;
    })
    .join("");

  for (const item of els.sampleList.querySelectorAll(".sample-item")) {
    item.addEventListener("click", () => openSample(item.dataset.rowIndex));
  }
  renderMath(els.sampleList);
}

function sampleScore(sample) {
  const value =
    sample.latest_judge_score ??
    sample.model_score ??
    sample.score;
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function scoreLabel(sample) {
  const score = sampleScore(sample);
  return score === null ? "Score: unscored" : `Score: ${score.toFixed(3)}`;
}

function pillClass(tag) {
  const normalized = text(tag).toLowerCase();
  const classes = ["pill"];
  if (normalized === "not self-contained" || normalized === "self-contained:no") {
    classes.push("pill-danger");
  } else if (normalized === "likely self-contained" || normalized === "self-contained:likely") {
    classes.push("pill-success");
  }
  return classes.join(" ");
}

function renderPageMeta() {
  const start = state.total === 0 ? 0 : state.offset + 1;
  const end = Math.min(state.offset + state.limit, state.total);
  const filters = [];
  if (state.q) filters.push(`question contains "${state.q}"`);
  if (state.label) filters.push(`label "${state.label}"`);
  if (state.scoreSort) filters.push(`score ${state.scoreSort === "asc" ? "lowest first" : "highest first"}`);
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
    score_sort: state.scoreSort,
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
    els.dialogEyebrow.textContent = `Sample ${rowIndex} · ${scoreLabel(sample)}`;
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

function groundTruthTitle(key) {
  return key === "final_answers" ? "Extracted Ground Truths" : "Ground Truths";
}

function renderFields(sample) {
  if (sample.evaluation_parts) {
    renderEvaluationFields(sample);
    return;
  }
  const label = text(sample.repair_status || sample.__part || sample.verdict || sample.part || sample.label || sample.domain || "unlabeled");
  const isRepairSample = "repaired_question" in sample || "original_question" in sample;
  const hasProcessedQuestion = !isRepairSample && "processed_question" in sample;
  const answerKey = firstPresent(sample, ["ground_truths", "ground_truth", "final_answers", "answers"]);
  const sections = isRepairSample
    ? [
        { title: "Original Question", key: firstPresent(sample, ["original_question", "question"]), kind: "text" },
        { title: "Repaired Question", key: firstPresent(sample, ["repaired_question"]), kind: "text" },
        { title: groundTruthTitle(answerKey), key: answerKey, kind: "answers" },
        { title: "Solution", key: firstPresent(sample, ["solution", "solutions", "answer", "explanation"]), kind: "text" },
      ].filter((section) => section.key)
    : [
        { title: hasProcessedQuestion ? "Original Question" : "Question", key: firstPresent(sample, ["question", "questions", "statement", "problem", "prompt"]), kind: "text" },
        { title: "Processed Question", key: firstPresent(sample, ["processed_question"]), kind: "text" },
        { title: groundTruthTitle(answerKey), key: answerKey, kind: "answers" },
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
  const reviewNote = text(sample.review_note || "").trim();
  const selfContainmentComment = text(sample.self_containment_comment || "").trim();
  const latestEvaluation = latestEvaluationHtml(sample);
  const issueMeta = [
    sample.issue_type ? `issue: ${text(sample.issue_type)}` : "",
    sample.dataset ? `dataset: ${text(sample.dataset)}` : "",
    sample.original_row_index !== undefined ? `source row: ${text(sample.original_row_index)}` : "",
  ].filter(Boolean).join(" · ");

  els.dialogContent.innerHTML = `
    ${labelBarHtml(label)}
    <div class="primary-fields${isRepairSample ? " repair-fields" : ""}">
      ${reviewNote ? `<div class="format-warning"><strong>Review note:</strong> ${escapeHtml(reviewNote)}</div>` : ""}
      ${selfContainmentComment ? `<div class="self-containment-warning"><strong>Self-containment review:</strong> ${escapeHtml(selfContainmentComment)}</div>` : ""}
      ${issueMeta ? `<div class="judge-reason"><strong>Issue metadata</strong><span>${escapeHtml(issueMeta)}</span></div>` : ""}
      ${sections.map((section) => fieldHtml(section)).join("")}
      ${latestEvaluation}
    </div>
  `;
  renderMath(els.dialogContent);
}

function latestEvaluationHtml(sample) {
  const modelResponse = text(sample.latest_model_response || "").trim();
  const extractedAnswer = text(sample.latest_extracted_answer || "").trim();
  const judgeParts = parseMaybeJson(sample.latest_judge_parts || []);
  const hasJudgeParts = Array.isArray(judgeParts) && judgeParts.length;
  if (!modelResponse && !extractedAnswer && !hasJudgeParts) return "";

  const score = sample.latest_judge_score === null || sample.latest_judge_score === undefined
    ? "unscored"
    : Number(sample.latest_judge_score).toFixed(3);
  const meta = [
    sample.latest_eval_model ? `model: ${text(sample.latest_eval_model)}` : "",
    sample.latest_eval_mode ? `mode: ${text(sample.latest_eval_mode)}` : "",
    sample.latest_eval_artifact ? `artifact: ${text(sample.latest_eval_artifact)}` : "",
  ].filter(Boolean).join(" · ");

  const judgeHtml = hasJudgeParts
    ? `
      <section class="field field-judge-judgments field-primary">
        <div class="field-name">
          <span>Judge Judgment By Part</span>
          <span>score ${escapeHtml(score)}</span>
        </div>
        <div class="judge-part-list">
          ${judgeParts.map((part) => judgePartHtml(part)).join("")}
        </div>
      </section>
    `
    : "";

  return `
    <div class="latest-evaluation">
      <div class="judge-reason"><strong>Latest evaluation</strong><span>${escapeHtml(meta || `score ${score}`)}</span></div>
      ${modelResponse ? `<details class="model-response" open><summary>Model response</summary><div class="rendered-text">${richTextHtml(modelResponse)}</div></details>` : ""}
      ${extractedAnswer ? `<details class="model-response"><summary>Extracted boxed answer</summary><div class="rendered-text">${richTextHtml(extractedAnswer)}</div></details>` : ""}
      ${judgeHtml}
    </div>
  `;
}

function judgePartHtml(part) {
  const score = part && part.score !== undefined && part.score !== null ? Number(part.score) : null;
  const tone = score === 1 ? "part-correct" : score === 0 ? "part-incorrect" : "part-unscored";
  const scoreText = score === null ? "unscored" : String(score);
  return `
    <article class="judge-part-card ${tone}">
      <div class="judge-part-head">
        <span class="part-badge">(${escapeHtml(text(part.part || "?"))})</span>
        <strong>Score ${escapeHtml(scoreText)}</strong>
      </div>
      <div class="judge-part-reason">${escapeHtml(text(part.reason || "(no reason)"))}</div>
    </article>
  `;
}

function renderEvaluationFields(sample) {
  const score = Number(sample.score || 0);
  const label = `${sample.selection || sample.mode || "evaluation"} · ${sample.dataset} · score ${score.toFixed(3)}`;
  const parts = parseMaybeJson(sample.evaluation_parts) || {};
  const partHtml = Object.entries(parts)
    .map(([part, result]) => {
      const correct = result.judge_correct === true;
      const referenceTitle = text(result.reference_title || "Ground truth");
      const referenceAnswer = text(
        result.reference_answer === undefined ? result.ground_truth : result.reference_answer,
      );
      const referenceIsSolution = referenceTitle.toLowerCase().includes("solution");
      const cleanedGroundTruths = text(result.cleaned_ground_truths || "");
      const judgeRawResponse = text(result.judge_raw_response || "").trim();
      const judgeUsage = text(result.judge_usage || "").trim();
      return `
        <section class="evaluation-part ${correct ? "part-correct" : "part-incorrect"}">
          <div class="evaluation-part-head">
            <span class="part-badge">(${escapeHtml(part)})</span>
            <strong>${correct ? "Judge: correct" : "Judge: incorrect"}</strong>
          </div>
          <div class="answer-comparison">
            <div class="comparison-card candidate-answer">
              <div class="comparison-title">Extracted final answer</div>
              <div class="answer-render">${answerDisplayHtml(text(result.extracted_answer))}</div>
            </div>
            <div class="comparison-card reference-answer">
              <div class="comparison-title">${escapeHtml(referenceTitle)}</div>
              <div class="answer-render">${referenceIsSolution ? richTextHtml(referenceAnswer, { normalizeLatex: true }) : answerDisplayHtml(referenceAnswer)}</div>
            </div>
          </div>
          ${cleanedGroundTruths ? `<details class="answer-source"><summary>Cleaned extracted ground truths</summary><pre>${escapeHtml(cleanedGroundTruths)}</pre></details>` : ""}
          <div class="judge-reason"><strong>Judge reason</strong><span>${escapeHtml(text(result.judge_reason) || "(none)")}</span></div>
          ${judgeRawResponse ? `<details class="answer-source"><summary>Raw judge response</summary><pre>${escapeHtml(judgeRawResponse)}</pre></details>` : ""}
          ${judgeUsage ? `<details class="answer-source"><summary>Judge metadata</summary><pre>${escapeHtml(judgeUsage)}</pre></details>` : ""}
        </section>`;
    })
    .join("");
  const formatErrors = Array.isArray(sample.format_errors) ? sample.format_errors : parseMaybeJson(sample.format_errors);
  const reviewNote = text(sample.review_note || sample.manual_review_reason || "").trim();
  const selfContainmentComment = text(sample.self_containment_comment || "").trim();
  const solution = text(sample.solution || "").trim();
  const attempts = parseMaybeJson(sample.evaluation_attempts) || [];
  const attemptsHtml = Array.isArray(attempts) && attempts.length
    ? `<details class="model-response"><summary>All ${attempts.length} evaluations</summary>${attempts.map((attempt) => {
        const attemptParts = attempt.part_scores ? JSON.stringify(attempt.part_scores, null, 2) : "";
        return `
          <section class="attempt-block">
            <div class="judge-reason"><strong>Repeat ${escapeHtml(text(attempt.repeat))} · score ${escapeHtml(text(attempt.score))}</strong><span>${escapeHtml(attemptParts)}</span></div>
            <details class="answer-source"><summary>Generated response</summary><div class="rendered-text">${richTextHtml(attempt.generated_response || "")}</div></details>
            <details class="answer-source"><summary>Judge response</summary><pre>${escapeHtml(text(attempt.judge_response || ""))}</pre></details>
          </section>
        `;
      }).join("")}</details>`
    : "";
  const candidateMeta = [
    sample.source_file ? `source ${sample.source_file}` : "",
    sample.key ? `key ${sample.key}` : "",
    sample.part_ids ? `judged parts ${text(sample.part_ids)}` : "",
  ].filter(Boolean).join(" · ");
  els.dialogContent.innerHTML = `
    ${labelBarHtml(label)}
    <div class="primary-fields">
      ${reviewNote ? `<div class="format-warning"><strong>Review note:</strong> ${escapeHtml(reviewNote)}</div>` : ""}
      ${selfContainmentComment ? `<div class="self-containment-warning"><strong>Self-containment review:</strong> ${escapeHtml(selfContainmentComment)}</div>` : ""}
      ${candidateMeta ? `<div class="judge-reason"><strong>Candidate metadata</strong><span>${escapeHtml(candidateMeta)}</span></div>` : ""}
      <section class="field field-question field-primary">
        <div class="field-name"><span>Question</span><span>${text(sample.question).length.toLocaleString()} chars</span></div>
        <div class="field-value">${escapeHtml(text(sample.question))}</div>
      </section>
      <div class="evaluation-parts">${partHtml}</div>
      ${formatErrors && formatErrors.length ? `<div class="format-warning"><strong>Format errors:</strong> ${escapeHtml(formatErrors.join("; "))}</div>` : ""}
      ${solution ? `<details class="model-response" open><summary>Final solution</summary><div class="rendered-text">${richTextHtml(solution, { normalizeLatex: true })}</div></details>` : ""}
      <details class="model-response"><summary>Full model response</summary><div class="rendered-text">${richTextHtml(sample.full_model_response)}</div></details>
      ${attemptsHtml}
    </div>`;
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
    return mathBlockHtml(math);
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

els.scoreSortSelect.addEventListener("change", () => {
  state.scoreSort = els.scoreSortSelect.value;
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
