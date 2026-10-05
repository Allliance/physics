def build_error_analysis_prompt(problem_context, student_answer, matches, score):
  return f"""
  You are a Physics Olympiad grader. Your task is to analyze a student's solution against a standard solution,
  using the provided detailed scoring breakdown, and determine the PRIMARY error cause (and optional secondary causes)
  from the taxonomy below. You do NOT need to align or map steps — the scored expressions already indicate where the
  solution is correct or incorrect. Focus on WHY the incorrect parts are wrong.

  Error taxonomy (choose labels exactly):
  - DAE: Diagram Analysis Error — incorrect interpretation of diagrams/figures/schematics.
  - PTAE: Physics Theorem/Application Error — misuse/misapplication of physical laws/principles.
  - MPUE: Modeling & Process Understanding Error — incorrect/incomplete physical model or process understanding.
  - CAE: Condition/Assumption Error — invalid/unjustified/misapplied conditions, including boundary/initial conditions.
  - VRE: Variable Relationship Error — incorrect relationships between physical quantities (e.g., constraints, kinematic relations).
  - DCE: Derivation & Computation Error — algebraic/symbolic manipulation mistakes, arithmetic/sign/substitution errors.
  - UDE: Unit/Dimension Error — unit inconsistency or dimensional mismatch.

  General guidance:
  1) Use the scoring breakdown to identify which expressions are incorrect.
  2) For the incorrect expressions, determine the earliest fundamental cause from the taxonomy.
  3) If multiple causes apply, select ONE primary label and list the rest as secondary.
  4) If diagrams are referenced but missing, do not assume their content; judge only from given text/expressions.

  Output STRICT JSON (no extra text, no markdown):
  {{
    "primary_error": "DAE|PTAE|MPUE|CAE|VRE|DCE|UDE",
    "secondary_errors": ["DAE|PTAE|MPUE|CAE|VRE|DCE|UDE"],
    "incorrect_expressions": ["strings of the incorrect student expressions"],
    "related_correct_expressions": ["strings of correct related student expressions if any"],
    "unit_dimension_status": "consistent|inconsistent|not-applicable|unknown",
    "assumption_mismatch": "none|present|unknown",
    "rationale": "2–5 concise sentences explaining the diagnosis",
    "confidence": 0.0-1.0
  }}

  PROBLEM CONTEXT:
  \"\"\" 
  {problem_context}
  \"\"\"

  STUDENT ANSWER:
  \"\"\" 
  {student_answer}
  \"\"\"

  AUTO-GRADER EQUATION MATCHES:
  \"\"\" 
  {matches}
  \"\"\"

  SCORE:
  \"\"\" 
  {score:.3f} (out of 1.0)
  \"\"\"
  """
