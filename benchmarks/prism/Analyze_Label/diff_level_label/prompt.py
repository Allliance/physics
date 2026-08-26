# The prompt template used for annotating the difficulty level of problems.
prompt_2 = """
You are an experienced Physics Olympiad coach and grader.
Classify olympiad-level physics problems using TWO dimensions (1–3 each):
C1 Conceptual depth (principles & modeling complexity)
C2 Computation burden (algebra/numeric length, error-prone)

Rules:
- Do NOT solve or judge correctness; only estimate difficulty.
- Use the provided SOLUTION only to estimate step depth/concepts.
- Do not use outside tools or knowledge beyond the given text.
- Keep outputs concise.

Output STRICT JSON:
{{
  "scores": {{"C1":1-3,"C2":1-3}},
  "rationales": {{"C1":"≤20 words","C3":"≤20 words"}},
  "reasoning": "2–3 concise sentences",
  "confidence": 0.0–1.0
}}

PROBLEM:
{problem}

SOLUTION (only for estimating steps/concepts; do NOT grade correctness):
{solution}
"""




# prompt_0="""" You are an experienced Physics Olympiad coach and grader.
# You will be given a high-level olympiad physics problem.  
# Your task is to classify the problem's difficulty into one of three categories: **Easy**, **Medium**, or **Difficult**.

# Please evaluate difficulty based on:
# 1. **Physics concepts** – rarity and depth of the required principles (e.g., standard textbook formula vs. advanced or less common theorem).  
# 2. **Analytical modeling** – complexity of setting up equations, assumptions, and representations (e.g., diagrams, multi-body systems, non-linear effects).  
# 3. **Mathematical reasoning** – algebraic manipulation, calculus, or other advanced math required.  
# 4. **Multi-step reasoning depth** – number of dependent logical/derivation steps before obtaining the final result.  
# 5. **Computation effort** – numerical calculation difficulty, susceptibility to errors, and length of derivation.

# **Difficulty guidelines**:
# - **Easy** – Requires common physics principles, minimal modeling, and fewer than ~3 main reasoning steps.  
# - **Medium** – Involves moderately uncommon concepts, multi-step derivations (~3–6 main steps), or moderately complex modeling.  
# - **Difficult** – Requires rare or advanced concepts, intricate multi-step derivations (6+ steps), or novel modeling strategies; typical of top-tier competition problems.

# **Output format (JSON)**:
# ```json
# {
#   "difficulty": "Easy | Medium | Difficult",
#   "reasoning": "Brief explanation of why this difficulty level was chosen."
# }

# PROBLEM:
# {problem}

# SOLUTION (only for estimating steps/concepts; do NOT grade correctness):
# {solution}
# """

# prompt_1 = """
# You are an experienced Physics Olympiad coach and grader.
# Classify the difficulty of olympiad-level physics problems into one of:
# - Easy
# - Medium
# - Difficult
# (If not enough information, use Unclassifiable.)

# Use THREE dimensions (1–3 each):
# C1 Conceptual depth (principles & modeling complexity)
# C2 Reasoning depth (derivation steps + math sophistication)
# C3 Computation burden (algebra/numeric length, error-prone)

# Mapping total T = C1+C2+C3:
# - Easy: 3–4
# - Medium: 5–7
# - Difficult: 8–9

# Tie-breaking:
# - If C1=2 → at least Medium
# - If C2=3 and C3≥2 → Difficult
# - On boundaries, choose the harder label

# Rules:
# - Do NOT solve or judge correctness; only estimate difficulty.
# - Use the provided SOLUTION only to estimate step depth/concepts.
# - Do not use outside tools or knowledge beyond the given text.
# - Keep outputs concise.

# Output STRICT JSON:
# {{
#   "difficulty": "Easy|Medium|Difficult|Unclassifiable",
#   "scores": {{"C1":1-3,"C2":1-3,"C3":1-3}},
#   "rationales": {{"C1":"≤20 words","C2":"≤20 words","C3":"≤20 words"}},
#   "estimated_steps": int|null,
#   "reasoning": "2–3 concise sentences",
#   "confidence": 0.0–1.0
# }}

# PROBLEM:
# {problem}

# SOLUTION (only for estimating steps/concepts; do NOT grade correctness):
# {solution}
# """


