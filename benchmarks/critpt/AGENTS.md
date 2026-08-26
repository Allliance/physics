# CritPt Evaluation Invariants

## Required two-step output pipeline

For CritPt runs with `parsing=false`, do not submit the model's first response.
That response is the reasoning/derivation stage and is usually Markdown.

Always run the second formatting step from `solve_with_parse.py`:

1. Preserve the model's first response as the previous assistant message.
2. Render `ParsePrompt.default_system_prompt(code_template=...)` with the
   challenge's `code_template`.
3. Ask the model to populate that template without new reasoning.
4. Submit the second response as `generated_code`.

Before any grading request, validate all submissions:

- The batch has exactly 70 unique expected `Challenge_<n>_main` IDs.
- Every `generated_code` contains executable Python from the supplied template.
- Extracted Python parses with `ast.parse` and defines or populates the expected
  `answer` symbol.
- Never treat Markdown `Final Answer:` text alone as a valid CritPt submission.

The Artificial Analysis public grader returns aggregate metrics only. A
successful request consumes grading quota, so perform the format validation
before submission.
