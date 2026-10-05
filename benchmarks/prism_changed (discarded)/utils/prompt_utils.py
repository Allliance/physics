format_instructions = r"""
### Standard Formatting Requirements for LaTeX Solutions
1) **One Formula Per Block**
   - Each formula must be wrapped in its own `$$...$$` block.
   - Avoid chaining multiple equalities or expressions in a single block.
   - Exception: Chained variable comparisons in inequalities are allowed **only if explicitly required**.
2) **No Terminal Punctuation**
   - Do not end any formula block with punctuation marks (e.g., `,`, `.`, `;`).
3) **SI Unit Format**
   - Always write units using `\\unit{}` to ensure proper parsing (e.g., `\\unit{m}`, `\\unit{m/s}`). Notice that the numbers should be put outside the unit, i.e. use $3\unit{km/h}$ instead of $\unit{3km/s}$.
4) **Strip Extra Formatting Commands**
    REMOVE the following:
   - Delimiters: `\left`, `\right`
   - Fonts/Styles: `\mathrm`, `\mathit`, `\mathbf`, `\text`
   - Spacing: `\,`, `\;`, `\!`, `~`, `\quad`, `\qquad`
   - Multi-line: `\begin{aligned}...\end{aligned}`
5) **Standard Calculus Notation**
    Use canonical forms for all calculus expressions:
   - Derivatives: `\frac{dy}{dx}`
   - Partial derivatives: `\frac{\partial f}{\partial x}`
   - Integrals: `\int_0^t v dt` (omit spacing commands)
   - Summations: `\sum_{i=1}^n x_i`
"""

format_instructions_for_review = r"""
1) **One Formula Per Block**
   - Each formula must be wrapped in its own `$$...$$` block.
   - Avoid chaining multiple equalities or expressions in a single block.
   - Exception: Chained variable comparisons in inequalities are allowed **only if explicitly required**.
2) **SI Unit Format**
   - Always write units using `\\unit{}` to ensure proper parsing (e.g., `\\unit{m}`, `\\unit{m/s}`). Notice that the numbers should be put outside the unit, i.e. use $3\unit{km/h}$ instead of $\unit{3km/s}$.
3) **Standard Calculus Notation**
    Use canonical forms for all calculus expressions:
   - Derivatives: `\frac{dy}{dx}`
   - Partial derivatives: `\frac{\partial f}{\partial x}`
   - Integrals: `\int_0^t v dt` (omit spacing commands)
   - Summations: `\sum_{i=1}^n x_i`
"""

problem_requirements_stage1 = r"""
0) You should KEEP washed solutions EQUIVALENT to the previous solutions. Except for formats and some necessary variable substitution, you are NOT ALLOWED to change the solution.
1) You should make sure all variables needed in the solution, no matter in the final answer or in the intermediate steps, are defined or specified in the problem, either in the context or in the subproblems. e.g. 'You should use $E_k$ for kinetic energy, $E_p$ for potential energy, $E$ for total energy, $M$ for the mass of the central body, $m$ for the mass of the satellite, $R$ for the radius of the orbit.'
2) You should make sure all variables and concepts are defined clearly in the problem.
3) For all accurate values, don't write them in decimals but fractions instead. For example instead of $$y=2.25 x$$ you should write $$y=\frac{9}{4}x$$. However if you believe the value is approximate (for example you think 2.25 is not an accurate value) then you should leave it as decimals.
4) You should try to avoid putting a representation in a formula block, but instead use equations or inequalities. For example instead of writing "The maximum energy is $$2E_0$$", you should write $$E_{max}=2E_0$$ and put the definition of E_{max} in the problem context. Even if it is hard to represent it with a single variable, you should write $$\text{ans}=...$, and mention that the final answer should be written in this form in the problem context. 
"""

problem_requirements_stage2 = r"""
1) You should add an entry "final_answer_form" which has three options "algebraic", "numerical" and "text-based" representing the form of the final answer. "text-based" means the final answer is not a calculation result or a derived formula, but instead a text description or statement. Notice that this only depends on the final answer in the standard solution, therefore each subquestion can only have one final_answer_form. If this is the same for all subproblems, you may write it as an entry of the whole problem, else you may add an entry for each subproblem separately. In any way, this should be a separate entry as item["final_answer_form"] for the whole problem or item["subquestions"][i]["final_answer_form"] for the i-th subquestion.
A hint on how to decide if an answer is algebraic or numerical: if the answer is a formula with multiple variables and each side of the formula has variables, it is algebraic; if there is only one variable or variables only exist in one side, it is numerical (e.g. $v_s=3\times 10^7\unit{m/s}$, $\rho_{min}\approx 1.5\times 10^3 \unit{kg/m^3}$ are both numerical answers.) Only the final formula would decide if it is algebraic or numerical. 
2) You should add an entry "final_answer_instructions" based on the final answer form. Similar to "final_answer_form", it should be either an entry of the whole problem (if the instruction is suitable for the whole problem) or separate entries for each subquestion. The instruction should contain the following information based on the final answer form:
a) If the final answer is algebraic, you should specify the format of the final answer in the problem, e.g., "Your final answer should be given in the form of $v_{min} = ... $, and your response should be written with $H, T, m, g$". The variable requirement for the final answer should fully match the final answer in the standard solution and make there's no redundant variables (for example, if $E_k=\frac 1 2 mv^2$, then you should at most provide two variables among $E_k, m, v$ for the final answer)
b) If the final answer is numerical, you should instead write 'Your final answer should express ... as a numerical value', and if the final answer is an approximate value, you should also specify the number of significant figures needed according to the standard answer. Moreover you should add an entry like {"significant_figures": 3} to the problem or subproblem.
c) If the final answer is text-based, you should try to restrict the form of final statement, for example you should write "Your final answer should be 'The equilibrium is stable/unstable.'", so that we can seek for the sentence to judge the correctness of the student answer.
You should NOT put the final answer instructions in the problem context. You should NOT do any modification to the json except from adding these two entries. You should NOT disclose the real answer but only its form in the final answer instruction. You should make sure all variables needed in the final answer are stated clearly in the final answer instruction.
"""

key_formulas_requirements = r"""
1) You should store the key formulas in a new field named 'key_formulas' in the output JSON, which should be a list of formulas like ["$$...$$", "$$...$$", ...]. Notice that this should be a field of the whole problem, not just a subproblem.
2) The final answer of each subproblem should be included in the key formulas, and final answer should be the last formula in the list.
3) The key formulas should be in the same format as they appear in the solution, and should be wrapped in double dollar signs `$$...$$`.
4) The key formulas should represent important progressions or results in the solution, not just definitions or variable substitutions.
"""

grading_standard_rules = r"""
You have to use '[]' and '()' to wrap up the formulas for grading according to the following requirement:
1) The '[]' is a list wrapper, which indicates that, if an element (which could be a formula, another list or a tuple) is achieved by the student, the score for all previous elements should be given. Notice that its usage is largely encouraged as we wish to ensure if the student achieves a partial result with a different method he/she could be graded correctly. 
NOTICE: for a list, if the last element is achieved, the whole list as a single element is achieved.
2) The '()' is a tuple wrapper, which indicates that, the elements inside are independent, and the tuple could be achieved if and only if all elementsare achieved individually.
3) You should ensure your '[]' and '()' are paired correctly, and they should reflect the logical relationship between different formulas in the solution. 
4) You should only include formulas and make sure they are wrapped with double-dollar symbols ($$). All variables in your formulas should be already defined in the problem context. For example, if the solution uses $\\theta$ but it is not defined in the problem context (i.e. it is newly defined in the solution), you should not include any formula including $\\theta$ in the grading standard.
5) Every formula in the grading standard must exist in the original solution, you should not create any new formula in the grading standard, and you should not make any modification to the formulas: just directly copy them from the solution.
"""

grading_standard_rules_dag = r"""
1) You should organize the core formulas in a list, each formula represented by a dict including the following entries:
{
"index": the index of the formula, counting from 1.
"formula": the content of the formula, which should be a string wrapped with double-dollar ($$) symbols.
"dependency": this is the crucial part of the grading standard. The dependency should be a list of indices showing which previous formulas this one depends on, which indicates without those previous formulas this formula can't be derived. Notice that only direct causalities should be considered, for example if A leads to B and B leads to C, you don't need to put A in the dependency of C. A formula can never depend on another formula after it.
"is_final_answer": (optional) this is true if this formula is the final answer of a subproblem or the whole problem. The last formula among all should always be a final answer.
}
2) Every formula in the grading standard must exist in the original solution, you should not create any new formula in the grading standard, and you should not make any modification to the formulas: just directly copy them from the solution.
3) You should ensure that for an isolated question or subquestion, if the final answer is correct, the student should receive full score for it. That means, any formula should be 'reachable' from the final answer (or at least the final answer of one subproblem) in the dependency graph. If the final answer contains more than one formuls, you may simply mark multiple formulas as final answers.
"""

grading_standard_icl_example_dag = r"""
Example 1:
[
{
    "index": 1,
    "formula": "$$E_k=\frac{1}{2}mv^2$$",
    "dependency": []
},
{
    "index": 2,
    "formula": "$$E_p=-\frac{GMm}{r}$$",
    "dependency": []
},
{
    "index": 3,
    "formula": "$$\frac{1}{2}mv_0^2-\frac{GMm}{r}\geq 0$$",
    "dependency": [1,2]
},
{
    "index": 4,
    "formula": "$$v_0\geq\sqrt{\frac{2GM}{r}}$$",
    "dependency": [3],
    "is_final_answer": true
}
]

Example 2:
[
{
    "index": 1,
    "formula": "$$\frac{mv_0^2}{R} = \frac{GMm}{R^2}$$",
    "dependency": []
},
{
    "index": 2,
    "formula": "$$v_0 = \sqrt{\frac{GM}{R}}$$",
    "dependency": [1],
    "is_final_answer": true
},
{
    "index": 3,
    "formula": "$$\frac{1}{2}mv_0^2}-\frac{GMm}{r}\geq 0$$",
    "dependency": []
},
{
    "index": 4,
    "formula": "$$v_0\geq\sqrt{\frac{2GM}{r}}$$",
    "dependency": [3],
    "is_final_answer": true
}
]
"""

grading_standard_icl_example = r"""
Example 1:
[
    (
        $$E_k=\frac{1}{2}mv^2$$,
        $$E_p=-\frac{GMm}{r}$$
    ),
    $$\frac{1}{2}mv_0^2-\frac{GMm}{r}\geq 0$$,
    $$v_0\geq\sqrt{\frac{2GM}{r}}$$
]

For Example 1, if the last formula is achieved, the answer should receive the full score; else if $$\frac{1}{2}mv_0^2}-\frac{GMm}{r}\geq 0$$ equation is achieved, the score for writing the kinetic energy and potential energy should also be given. However, since the form of kinetic energy and potential energy are independent with each other, we use a tuple to indicate that these two formulas should be achieved independently.
Hint: For most cases, we wish to ensure that if the last formula of a subquestion is achieved, all score for the subquestion would be given.

Example 2: 

(
    [
        $$\frac{mv_0^2}{R} = \frac{GMm}{R^2}$$,
        $$v_0 = \sqrt{\frac{GM}{R}}$$
    ],
    [
        $$\frac{1}{2}mv_0^2}-\frac{GMm}{r}\geq 0$$,
        $$v_0\geq\sqrt{\frac{2GM}{r}}$$
    ]
)


Example 2 shows how to deal with multiple subquestions: If you think each subquestion is independent, you should use a tuple to indicate it; in the example, the tuple indicates the two subquestions are independent.
Notice that you should write a comma between two elements.
"""

def get_problem_context(problem):
    context = problem.get("context", "")
    if problem.get("final_answer_instruction"):
        context += f"\n{problem.get('final_answer_instruction')}"
    subquestions = problem.get("subquestions", [])
    for subquestion in subquestions:
        subproblem = subquestion.get("subproblem", "")
        letter = subquestion.get("letter", "")
        context += f"\n\n{letter}) {subproblem}"
        if subquestion.get("final_answer_instruction"):
            context += f"\n{str(subquestion.get('final_answer_instruction'))}"
    return context

def get_reference_solution(problem):
    solution = problem.get("solution", "")
    if solution != "":
        return solution
    subquestions = problem.get("subquestions", [])
    for subquestion in subquestions:
        subsolution = subquestion.get("solution", "")
        letter = subquestion.get("letter", "")
        solution += f"\n\nSolution for subproblem({letter}):\n {subsolution}"
    return solution


def get_eval_prompt(problem):
    """
    Generate a prompt for evaluating a problem.

    Args:
        problem (json): A JSON object containing the problem context.

    Returns:
        str: The formatted evaluation prompt.
    """
    
    
    context = get_problem_context(problem)
    prompt = f""" 
        You are a Physics expert. You are going to solve a physics problem and be graded accordingly. Here are some instructions you should follow to make sure your answer is graded correctly:
        1. You answer should be written in markdown format.
        2. You should provide your key steps and final answer in a clear and concise manner using double-dollar signs for formulas (e.g., $$E_0 = mgH + \frac 1 2 mv_0^2$$). However, put your definitions or uncrucial steps in single dollar signs (e.g., '$E$ is the energy of the system', or 'according to Newton\'s second law, $F=ma$').
        3. Use less text and more formulas to explain your reasoning.
        4. Your answer should satisfy the format below:
        {format_instructions}        
        Here is the problem context:
        ###
        {context}
        ###
        Please provide your solution step by step, and then give your final answer. You should try to use the variables given in the problem and avoid using new variables unless necessary. You should strictly follow the formatting requirements introduced in the problem for the final answer. 
        """
    
    return prompt

def get_wash_prompt_stage1(sample):
    return f"""
    You are an expert in Physics, and you are going to rewrite a given problem and solution into a standard form. The formatting requirements are below:
    {format_instructions}
    Moreover, you should make sure that the answers can be graded correctly, you should make sure the written form of the final answer is unified, which means:
    {problem_requirements_stage1}
    Now according to the requirements, please rewrite the problem and solution below. 
    {str(sample)}
    Your output should be in the same json format, keeping all entries even if unmodified. Don't forget any single entry or your output would be invalid.
    Your response should be formatted as '```json\n<your_rewritten_json>\n```', and nothing other than the rewritten json should be in your output.
    """

review_stage_1_icl_example = """

Example 1:
[Rewritten Problem and Solution] 
{
    "context": "A heavy star of mass $M$ and radius $R$ moves with velocity $\\mathbf { v }$ through a very dilute gas of mass density $\\rho$ 、It pulls particles toward itself by its gravitational field and captures all of the atoms that strike its surface. Find the drag force on the star with the approximation that the thermal velocities of the atoms are negligible relative to $| \\mathbf { v } |$ and the interactions of atoms with each other can be neglected. ",
    "images": [
      {
        "caption": "Fig. 1.88",
        "location": "/01-1/images/5c0b89a0f78216cf3afa94147ce971e5f135f5a7e9e281024a77d0a2eb63b236.jpg"
      }
    ],
    "solution": "In a frame moving with the star,gas atoms move with velocity $- \\mathbf { v }$ toward the star from infinity. Under the influence of the star's gravitational field,the trajectories of the gas atoms are as shown in Fig. 1.88.  \n\nLet $b$ be the largest impact parameter for which a gas atom can just be captured by the star and $\\boldsymbol { v }$ the velocity of the gas atom just before capturing. Conservation of angular momentum gives  \n\n$$\n\\displaystyle v R = b V ~ ,\n$$  \n\nand conservation of energy gives  \n\n$$\n\\frac { v ^ { 2 } } { 2 } - \\frac { G M } { R } = \\frac { V ^ { 2 } } { 2 }$$  \n\nfrom which we obtain  \n\n$$\nb ^ { 2 } = \\frac { R ^ { 2 } } { V ^ { 2 } } \\left( V ^ { 2 } + \\frac { 2 G M } { R } \\right)$$  \n\nThe drag force on the star is equal to the momentum absorbed per unit time:  \n\n$$\n\\begin{array} { l } { \\displaystyle \\mathbf { F } = \\frac { d \\mathbf { P } } { d t } = \\operatorname* { l i m } _ { \\Delta t \\to 0 } \\frac { \\pi b ^ { 2 } V \\Delta t \\cdot \\boldsymbol { \\rho } ( - \\mathbf { V } ) } { \\Delta t } } \\\\ { \\displaystyle = - \\pi b ^ { 2 } \\boldsymbol { \\rho } V \\mathbf { V } = - \\frac { \\pi R ^ { 2 } \\boldsymbol { \\rho } } { V } \\left( V ^ { 2 } + \\frac { 2 G M } { R } \\right) \\mathbf { V } . } \\end{array}\n$$",
    "id": 1116
}
[Example Response]
<judge>invalid</judge><reason>The solution contains the variables $b$, $F$, $P$ which are not defined in the problem context. The array contains more than one formula, which is not allowed.</reason>

Example 2:
[Rewritten Problem and Solution]
{
    "context": "A star of mass $M$ and radius $R$ is moving with velocity $\\mathbf{v}$ through a very dilute gas. The gas has uniform mass density $\\rho$. The gravitational field of the star pulls nearby atoms toward itself, and any atom that strikes the star's surface is captured. Assume that the thermal velocities of the gas atoms are negligible compared to $|\\mathbf{v}|$, and the atoms do not interact with each other. Find the drag force $\\mathbf{F}$ acting on the star due to the captured atoms, expressing your answer in terms of the variables defined in the problem: mass of the star $M$, radius of the star $R$, stellar velocity $\\mathbf{v}$ (with magnitude $V = |\\mathbf{v}|$), Newton's gravitational constant $G$, and the gas mass density $\\rho$. You may use $P$ to represent the momemtum, but it should not exist in your final answer.",
    "images": [
      {
        "caption": "Fig. 1.88",
        "location": "/01-1/images/5c0b89a0f78216cf3afa94147ce971e5f135f5a7e9e281024a77d0a2eb63b236.jpg"
      }
    ],
    "solution": "Consider the reference frame moving with the star. In this frame, gas atoms move with velocity $-\\mathbf{v}$ toward the star from infinity. Under the influence of the star's gravitational field, gas atom trajectories are deflected toward the star, as illustrated in Fig. 1.88.\n\nLet $b$ be the largest impact parameter such that an atom is captured by striking the star's surface. Let $V$ denote the star's speed relative to the gas, and $v$ denote the speed of the atom at radius $R$ immediately before capture.\n\nConservation of angular momentum gives\n\n$$\nv R = b V\n$$\n\nConservation of energy for an atom moving from infinity to the star's surface yields\n\n$$\n\\frac{v^2}{2} - \\frac{G M}{R} = \\frac{V^2}{2}\n$$\n\nSolving for $b$ gives\n\n$$\nb^2 = \\frac{R^2}{V^2} \\left( V^2 + \\frac{2 G M}{R} \\right)\n$$\n\nThe drag force $\\mathbf{F}$ equals the momentum absorbed per unit time. The star collects all atoms entering a cylinder of radius $b$ at velocity $V$:\n\n$$\n\\mathbf{F} = \\frac{d \\mathbf{P}}{dt}\n$$\n\n$$\n\\mathbf{F} = -\\pi b^2 \\rho V \\mathbf{v}\n$$\n\nSubstituting the value of $b^2$ gives\n\n$$\n\\mathbf{F} = -\\frac{\\pi R^2 \\rho}{V} \\left( V^2 + \\frac{2 G M}{R} \\right) \\mathbf{v}\n$$",
    "id": 1116
}
[Example Response]
The solution contains the following variables: $\mathbf{v}$, $R$, $b$, $F$, $P$, $M$, $G$, $\\rho$. They are all defined in the problem context. <judge>valid</judge><reason>All variables are defined in the problem context.</reason>

"""

def get_review_prompt_stage1(sample, original_sample=None):
    original_reference = ""
    if original_sample is not None:
        original_reference = (
            "\nFor reference, here is the original problem and solution before rewriting:\n"
            f"{str(original_sample)}\n"
            "Reject any rewrite that changes the final answer's numeric values or algebraic expressions."
        )
    prompt = f"""
    You are a professor, and now you should review whether your assistant correctly rewrote the problem and solution into a standard form.
    More specifically, he should make sure the written form of the final answer is unified, so that the student answers can be graded correctly. Below was your instruction to him which he should satisfy:
    {problem_requirements_stage1}
    Moreover, the formulas should also satisfy the following formatting requirements:
    {format_instructions_for_review}
    You must ensure that the final answer(s) in the rewritten solution are identical to the final answer(s) in the original problem and solution. Reject any rewrite that changes the final answer expression or value.
    You should return something like '<judge>valid</judge><reason>...</reason>' or '<judge>invalid</judge><reason>...</reason>'. You may think before your final output. Keep the reason concise.
    Below are some examples for you to understand it better:
    {review_stage_1_icl_example}
    Now, according to the instructions, you should decide if your assistant has rewritten the problem and solution correctly. Below is the problem and solution rewritten by your assistant:
    {str(sample)}
    {original_reference}
    """
    return prompt
    
def get_wash_prompt_stage2(sample):
    return f"""
    You are an expert in Physics, and you are going to rewrite a given problem to make it clearer. More specifically, we wish to clarify the requirement for the final answer of each problem, which means:
    {problem_requirements_stage2} 
    Now according to the requirements, please rewrite the problem and solution below. 
    {str(sample)}
    Your output should be in the same json format, keeping all entries even if unmodified, and add your new entries as required. Don't forget any single entry or your output would be invalid. Make sure you output a valid json.
    DO NOT put any hint for the final answer in the instruction! Only give some information to regularize the format!
    Your response should be formatted as '```json\n<your_rewritten_json>\n```', and nothing other than the rewritten json should be in your output.
    """

review_stage_2_icl_example = """

Example 1:
[Rewritten Problem] 
{
    "context": "The $\\eta'$ meson (let $M$ denote its mass) can decay into a $\\rho^0$ meson (mass $m$) and a photon ($\\gamma$), via the reaction: $\\eta' \\rightarrow \\rho^0 + \\gamma$. The decay is isotropic in the rest frame of the parent $\\eta'$ meson. Now suppose that a monoenergetic beam of $\\eta'$ mesons is traveling with speed $v$ in the laboratory frame. Let $\\theta$ be the angle at which the photon is emitted relative to the direction of the $\\eta'$ beam, as shown in Fig. 4.5. Define $P(\\theta)d(\\cos\\theta)$ to be the normalized probability that $\\cos\\theta$ lies in the interval $[\\cos\\theta, \\cos\\theta + d\\cos\\theta]$. All relevant variables: $M$ for the mass of the $\\eta'$ meson, $m$ for the mass of the $\\rho^0$ meson, $E_\\eta$ for the energy of the $\\eta'$ in the lab, $p_\\eta$ for its momentum, $\\gamma$ for its Lorentz factor, $E(\\theta)$ for the photon energy in the lab at angle $\\theta$, $\\bar{E}$ for photon energy in the $\\eta'$ rest frame.",
    "images": [
      {
        "caption": "Fig. 4.5",
        "location": "/04-4/images/1cd0b990833a8a34086f9aad5f9886b94757a5bd4c9830476e4b638851eb0f52.jpg"
      }
    ],
    "subquestions": [
      {
        "letter": "b",
        "subproblem": "Let $E(\\theta)$ be the laboratory energy of the photon emitted at angle $\\theta$. Compute $E(\\theta)$. Use $M$ for the mass of the $\\eta'$ meson, $m$ for the mass of the $\\rho^0$ meson, $E_\\eta$ for the energy of the $\\eta'$ meson in the lab, and $p_\\eta$ for its momentum.",
        "solution": "In the rest frame of the $\\eta'$ meson, by conservation of energy and momentum:\n$$\n\\bar{E}_p = M - \\bar{E}\n$$\n$$\n\\bar{p}_p = \\bar{p}\n$$\nThe invariant mass relation gives:\n$$\n\\bar{E}_p^2 - \\bar{p}_p^2 = m^2\n$$\nSubstitute $\\bar{E}_p = M - \\bar{E}$ and $\\bar{p}_p = \\bar{p}$:\n$$\n(M - \\bar{E})^2 - \\bar{p}^2 = m^2\n$$\nSince the photon is massless, $\\bar{p} = \\bar{E}$:\n$$\n(M - \\bar{E})^2 - \\bar{E}^2 = m^2\n$$\nExpand and simplify:\n$$\nM^2 - 2M\\bar{E} = m^2\n$$\nSolving for $\\bar{E}$:\n$$\n\\bar{E} = \\frac{M^2 - m^2}{2M}\n$$\nNow transform to the laboratory frame using the Lorentz transformation for energy:\n$$\n\\bar{E} = \\gamma E (1 - \\beta \\cos \\theta)\n$$\nSolving for $E$:\n$$\nE = \\frac{\\bar{E}}{\\gamma(1 - \\beta \\cos \\theta)}\n$$\nThe laboratory energy and momentum of the $\\eta'$ meson are $E_\\eta = \\gamma M$ and $p_\\eta = \\gamma M \\beta$. Substitute these into the denominator:\n$$\nE = \\frac{M^2 - m^2}{2 (E_\\eta - p_\\eta \\cos \\theta)}\n$$",
        "final_answer_form": "algebraic",
        "final_answer_instructions": "Your final answer should be given in the form of $E(\\theta)=\\ldots$, and your response should be written with $M, m, E_\\eta, p_\\eta, \\theta$."
      }
    ],
    "id": 4045
}
[Example Response]
<judge>valid</judge><reason>The instructions are clear and correct.</reason>

Example 2:
[Rewritten Problem] 
{
    "context": "An ionization chamber consists of a metal cylinder of radius $a$ and length $L$, with a thin wire of radius $b$ along the cylinder axis. The cylinder is maintained at a negative high voltage $-V_0$, while the wire is connected to ground through a resistor $R$, as illustrated in Fig. 1.61. The relevant physical quantities for this problem are as follows:\n- $a = 1 \\unit{cm}$ is the radius of the cylinder\n- $b = 0.1 \\unit{mm}$ is the radius of the central wire\n- $L = 50 \\unit{cm}$ is the length of the cylinder\n- $V_0 = 1000 \\unit{V}$ is the high voltage applied to the cylinder\n- $R = 1 \\times 10^5 \\Omega$ is the resistance connected to the wire\n- The mobility of argon ions (positive ions) is $\\mu_+ = 1.3 \\frac{\\unit{cm}}{\\unit{s}} \\cdot \\frac{\\unit{cm}}{\\unit{V}}$\n- The mobility of electrons is $\\mu_- = 6 \\times 10^3 \\frac{\\unit{cm}}{\\unit{s}} \\cdot \\frac{\\unit{cm}}{\\unit{V}}$\nLet $Q_0$ be the charge on the wire, $C$ the capacitance of the chamber, $N$ the number of electron-ion pairs produced, $e$ the elementary charge, $\\varepsilon_0$ the vacuum permittivity.\nYou should use $r$ for the radial coordinate (from the axis), $r_1$ and $r_2$ for initial and final radial positions, $\\Delta t_-$ and $\\Delta t_+$ for the electron and ion drift times respectively, and $\\Delta V$ for the voltage pulse at the anode. Assume the voltage is not sufficient to create ion multiplication near the wire (i.e., not a proportional counter). The detailed time-dependence of the voltage pulse is required for this problem.",
    "images": [
      {
        "caption": "Fig. 1.61",
        "location": "/02-1/images/59346453bdf4fd2dbd614be12c6f9b75cad91f41b32c92e7ad40bf9a5285c881.jpg"
      }
    ],
    "solution": "The system is naturally described in cylindrical coordinates $ (r, \\varphi, z) $, with the $z$-axis along the axis of the cylinder.\n\nAccording to Gauss' law, the electric field at a distance $r$ from the axis, between $b < r < a$, obeys\n$$\nE(r) \\propto \\frac{1}{r}\n$$\n\nConsidering the voltage difference:\n$$\n- \\int_{b}^{a} E(r) dr = -V_0\n$$\n\nSolving for $E(r)$:\n$$\nE(r) = \\frac{V_0}{r \\ln\\left(\\frac{a}{b}\\right)}\n$$\n\nIf $Q_0$ is the charge on the wire, then from Gauss' law:\n$$\nE(r) = \\frac{Q_0}{2 \\pi \\varepsilon_0 L r}\n$$\n\nThe capacitance $C$ of the chamber is given by:\n$$\nC = \\frac{Q_0}{V_0}\n$$\n\nSubstituting the previous expressions and solving for $C$:\n$$\nC = \\frac{2 \\pi \\varepsilon_0 L}{\\ln \\left(\\frac{a}{b}\\right)}\n$$\n\nWith $\\varepsilon_0 = 8.85 \\times 10^{-12} \\unit{F/m}$, $L = 0.5 \\unit{m}$, $a = 1 \\unit{cm} = 1 \\times 10^{-2} \\unit{m}$, $b = 0.1 \\unit{mm} = 1 \\times 10^{-4} \\unit{m}$:\n$$\nC = \\frac{2 \\pi \\times 8.85 \\times 10^{-12} \\times 0.5}{\\ln\\left(\\frac{1 \\times 10^{-2}}{1 \\times 10^{-4}}\\right)}\n$$\n$$\nC \\approx 6 \\times 10^{-12} \\unit{F}\n$$\n\nThe time constant of the circuit is:\n$$\n\\tau = RC\n$$\n$$\n\\tau = 10^5 \\times 6 \\times 10^{-12}\n$$\n$$\n\\tau = 6 \\times 10^{-7} \\unit{s}\n$$\n\nThe mobility $\\mu$ of a charged particle is defined by:\n$$\n\\mu = \\frac{1}{E} \\frac{dr}{dt}\n$$\n\nOr, rearranged:\n$$\ndt = \\frac{dr}{\\mu E}\n$$\n\nThus, the drift time for a particle from $r_1$ to $r_2$ is:\n$$\n\\Delta t = \\int_{r_1}^{r_2} \\frac{dr}{\\mu E(r)}\n$$\nSubstituting $E(r)$:\n$$\n\\Delta t = \\int_{r_1}^{r_2} \\frac{dr}{\\mu \\frac{V_0}{r \\ln \\left(\\frac{a}{b}\\right)}}\n$$\n$$\n\\Delta t = \\frac{\\ln \\left(\\frac{a}{b}\\right)}{\\mu V_0} \\int_{r_1}^{r_2} r dr\n$$\n$$\n\\Delta t = \\frac{\\ln \\left(\\frac{a}{b}\\right)}{2 \\mu V_0} \\left(r_2^2 - r_1^2\\right)\n$$\n\nFor an electron drifting from $r_1 = a/2$ to $r_2 = b$:\n$$\n\\Delta t_- = \\frac{\\ln \\left(\\frac{a}{b}\\right)}{2 \\mu_- V_0} \\left[\\left(\\frac{a}{2}\\right)^2 - b^2\\right]\n$$\n$$\n\\Delta t_- \\approx \\frac{\\ln \\left(\\frac{a}{b}\\right)}{2 \\mu_- V_0} \\cdot \\frac{a^2}{4}\n$$\nNow, plugging in the values:\n- $a = 1 \\unit{cm} = 1 \\times 10^{-2} \\unit{m} = 1 \\unit{cm}$\n- $b = 0.1 \\unit{mm} = 0.01 \\unit{cm}$\n- $\\mu_- = 6 \\times 10^3 \\frac{\\unit{cm}}{\\unit{s}} \\cdot \\frac{\\unit{cm}}{\\unit{V}}$\n- $V_0 = 1000 \\unit{V}$\n- $\\ln(\\frac{a}{b}) = \\ln(100) \\approx 4.605$\n- $a^2 = 1 \\unit{cm}^2 = 1 \\times 10^{-4} \\unit{m}^2$\n\n$$\n\\Delta t_- \\approx \\frac{4.605}{2 \\times 6 \\times 10^3 \\times 1000} \\times \\frac{1}{4}\n$$\n$$\n\\Delta t_- \\approx 9.6 \\times 10^{-8} \\unit{s}\n$$\n\nFor a positive ion drifting from $r_1 = a/2$ to $r_2 = a$:\n$$\n\\Delta t_+ = \\frac{\\ln \\left(\\frac{a}{b}\\right)}{2 \\mu_+ V_0} \\left[a^2 - \\left(\\frac{a}{2}\\right)^2\\right]\n$$\n$$\n\\Delta t_+ = \\frac{\\ln \\left(\\frac{a}{b}\\right)}{2 \\mu_+ V_0} \\cdot \\frac{3 a^2}{4}\n$$\nPlug in values ($\\mu_+ = 1.3 \\frac{\\unit{cm}}{\\unit{s}} \\cdot \\frac{\\unit{cm}}{\\unit{V}}$):\n$$\n\\Delta t_+ \\approx \\frac{4.605}{2 \\times 1.3 \\times 1000} \\times \\frac{3}{4}\n$$\n$$\n\\Delta t_+ \\approx 1.3 \\times 10^{-3} \\unit{s}\n$$\n\nThus,\n$$\n\\Delta t_- \\ll \\tau \\ll \\Delta t_+\n$$\n\nFor the voltage signal at the anode, consider energy conservation. When a charge $q$ moves by $dr$ in the field $E$, the change in the energy stored on the capacitance is:\n$$\nd\\left(\\frac{1}{2}CV^2\\right) = -q E dr\n$$\nAssuming $\\Delta V \\ll V_0$, so $V \\approx V_0$, this gives:\n$$\nC V_0 dV = -q E dr\n$$\nIntegrating both sides from $r = a/2$ to a general $r$, with $q = -Ne$ (for $N$ electrons):\n$$\nC V_0 \\Delta V = -q \\int_{a/2}^{r} E dr\n$$\nSubstituting $E(r)$:\n$$\nC V_0 \\Delta V = -q \\int_{a/2}^{r} \\frac{V_0}{r \\ln\\left(\\frac{a}{b}\\right)} dr\n$$\n$$\nC V_0 \\Delta V = -q \\frac{V_0}{\\ln\\left(\\frac{a}{b}\\right)} \\ln\\left(\\frac{2r}{a}\\right)\n$$\n$$\n\\Delta V = \\frac{-q}{C} \\frac{\\ln\\left(\\frac{2r}{a}\\right)}{\\ln\\left(\\frac{a}{b}\\right)}\n$$\n$$\n\\Delta V = \\frac{N e}{C} \\frac{\\ln\\left(\\frac{2r}{a}\\right)}{\\ln\\left(\\frac{a}{b}\\right)}\n$$\n\nThe relationship between $t$ and $r$ for the electron drift is:\n$$\nt = \\frac{\\ln\\left(\\frac{a}{b}\\right)}{2 \\mu_- V_0}\\left[\\left(\\frac{a}{2}\\right)^2 - r^2\\right]\n$$\n$$\nr^2 = \\left(\\frac{a}{2}\\right)^2 - \\frac{2 \\mu_- V_0}{\\ln\\left(\\frac{a}{b}\\right)} t\n$$\nSo\n$$\nr = \\frac{a}{2} \\left[1 - \\frac{t}{\\Delta t_-} \\right]^{1/2}\n$$\n\nThen the voltage as a function of time ($0 \\leq t \\leq \\Delta t_-$):\n$$\n\\Delta V (t) = \\frac{N e}{C} \\cdot \\frac{1}{2} \\ln\\left(1 - \\frac{t}{\\Delta t_-}\\right) / \\ln\\left(\\frac{a}{b}\\right)\n$$\nAlternatively, including the small $b$ term:\n$$\n\\Delta V (t) = \\frac{N e}{C} \\ln\\left(1 - \\frac{[1 - (\\frac{2b}{a})^2] t}{\\Delta t_-}\\right)^{1/2} / \\ln\\left(\\frac{a}{b}\\right)\n$$\nAt $t = \\Delta t_-$, all electrons reach the wire ($r = b$), and the voltage is:\n$$\n\\Delta V_{\\text{max}} = \\frac{N e}{C} \\frac{\\ln\\left(\\frac{2b}{a}\\right)}{\\ln\\left(\\frac{a}{b}\\right)}\n$$\nNumerically, with $N = 10^5$, $e = 1.6 \\times 10^{-19} \\unit{C}$, $C = 6 \\times 10^{-12} \\unit{F}$, $\\ln(50)/\\ln(100) \\approx 0.85$:\n$$\n\\Delta V_{\\text{max}} = -2.3 \\times 10^{-3} \\unit{V}\n$$\n\nAfter $t = \\Delta t_-$, the charge redistributes via the $RC$ circuit and the voltage exponentially returns to zero with time constant $\\tau$:\n$$\n\\Delta V (t) = \\Delta V_{\\text{max}} \\exp\\left(-\\frac{t - \\Delta t_-}{RC}\\right)\n$$\n\nThus, the voltage $\\Delta V$ as a function of time is:\n- For $0 \\leq t \\leq \\Delta t_-$,\n$$\n\\Delta V = 5.86 \\times 10^{-3} \\ln \\left[1 - \\frac{(1-\\frac{1}{50^2})^{1/2} t}{9.6 \\times 10^{-8}}\\right] \\unit{V}\n$$\n- For $t > 9.6 \\times 10^{-8} \\unit{s}$,\n$$\n\\Delta V = -2.3 \\times 10^{-3} \\exp \\left(-\\frac{t}{6 \\times 10^{-7}}\\right) \\unit{V}\n$$\n\nIn summary, the voltage across $R$ steps quickly to $-2.3 \\unit{mV}$ in time $\\Delta t_-$, and then returns to zero exponentially with time constant $RC$.\n\nBecause the ions move much more slowly and the induced charges on the electrodes are quickly discharged through the $RC$ circuit, their influence on the measured pulse shape of $\\Delta V$ is negligible.",
    "id": 1106,
    "final_answer_form": "algebraic",
    "final_answer_instructions": "Your final answer should be a formula for the voltage pulse $\\Delta V$ as a function of time $t$, and your response should be written in terms of $N, e, C, a, b, \\mu_-, V_0, t$, and any other necessary physical quantities defined in the problem. Clearly specify the expression for $\\Delta V(t)$ in piecewise form if needed.",
}
[Example Response]
The final answer instruction clearly states the variables needed, but it does not specifies how the final answer should be written clearly.<judge>invalid</judge><reason>You should state that the final answer should be given in the form of $\Delta V = \ldots$ to make it clearer.</reason>
"""


def get_review_prompt_stage2(sample):
    prompt = f"""
    You are a professor, and now you should review whether your assistant correctly rewrote the problem to make it clearer for the students. More specifically, he should clarify the requirement for the final answer of each problem. Below is the instruction you provided to him earlier:
    {problem_requirements_stage2}
    You should return something like '<judge>valid</judge><reason>...</reason>' or '<judge>invalid</judge><reason>...</reason>'. You may think before your final output. Keep the reason concise.
    Below are some examples for you to understand it better:
    {review_stage_2_icl_example}
    Now, according to the instructions, you should decide if your assistant has rewritten the problem correctly. Below is the problem rewritten by your assistant:
    {str(sample)}
    """
    return prompt
    
def get_wash_prompt_stage3(sample, use_dag=False, return_extra_only=True):
    prompt = f"""
    You are an expert in Physics, and you are setting up a grading standard for a given problem. More specifically, your job is to find the 'core formulas' in the solution. These core formulas should reflect some significant progress in solving the problem and thus you think they are worth some credit.
    Moreover, you have to organize them in a given format to set up a grading standard.
    {grading_standard_rules if not use_dag else grading_standard_rules_dag}
    Below are some examples for you to better understand the requirement.
    {grading_standard_icl_example if not use_dag else grading_standard_icl_example_dag}
    Now, according the requirement, please write the grading standard for the problem and solution below.
    {str(sample)}
    
    """
    if return_extra_only:
        prompt += """
        Your output should be formatted in a markdown code block as '```\n<your_grading_standard>\n```', and nothing other than your grading standard should be in your output. Remember that nothing expect the formulas should exist in the grading standard, including any comments or descriptions.
        """
    else:
        prompt += """
        Your output should be in the same json format, keeping all entries even if unmodified, and add a new entry "grading_standard" for the whole problem. You should not modify the original problem or solution.
        Your response should be formatted as '```json\n<your_rewritten_json>\n```', and nothing other than the rewritten json should be in your output.
        """
    return prompt

review_stage_3_icl_example = """

Example 1:
[Problem] 
{
    ...,
    "grading_standard": "[$$E_k=\\frac{1}{2}mv^2$$,$$E_p=-\\frac{GMm}{r}$$,$$\\frac{1}{2}mv_0^2-\\frac{GMm}{r}\geq 0$$,$$v_0\geq\sqrt{\\frac{2GM}{r}}$$]"
}
[Example Response]
<judge>invalid</judge><reason>$$E_k=\\frac{1}{2}mv^2$$ and $$E_p=-\\frac{GMm}{r}$$,$$\\frac{1}{2}mv_0^2-\\frac{GMm}{r}\geq 0$$ should be parallel.</reason>

Example 2:
[Problem]
{
    "context": "In atomic hydrogen, the ground state experiences hyperfine splitting due to the interaction between the magnetic moments of the proton and electron. The energy difference between these hyperfine levels can be denoted as $\\Delta E$. The known experimental value for the frequency corresponding to this splitting is $\\Delta \nu_{hf} = 1.42 \\times 10^{9} \\unit{s^{-1}}$. Planck's constant is $h = 4.14 \\times 10^{-15} \\unit{eV \\cdot s}$. Among the given options\u2014$10^{-7} \\unit{eV}$, $10^{-5} \\unit{eV}$, $10^{-3} \\unit{eV}$, $10^{-1} \\unit{eV}$\u2014which is closest to the energy $\\Delta E$ of the hyperfine splitting in hydrogen? You should use $\\Delta \nu_{hf}$ for the hyperfine transition frequency, $h$ for Planck's constant, and $\\Delta E$ for the hyperfine energy splitting.",
    "images": [],
    "solution": "The energy associated with the hyperfine splitting is given by\n$$\n\\Delta E = h \\Delta \nu_{hf}\n$$\nThe value of Planck's constant is\n$$\nh = 4.14 \\times 10^{-15} \\unit{eV \\cdot s}\n$$\nThe frequency for the hyperfine transition in hydrogen is\n$$\n\\Delta \nu_{hf} = 1.42 \\times 10^{9} \\unit{s^{-1}}\n$$\nSubstituting the values, we get\n$$\n\\Delta E = 4.14 \\times 10^{-15} \\times 1.42 \\times 10^{9} \\unit{eV}\n$$\nCalculating,\n$$\n\\Delta E = 5.8788 \\times 10^{-6} \\unit{eV}\n$$\nRounding to one significant figure,\n$$\n\\Delta E \\approx 6 \\times 10^{-6} \\unit{eV}\n$$\nAmong the options provided, the closest value is\n$$\n10^{-5} \\unit{eV}\n$$",
    "id": 1029,
    "final_answer_form": "numerical",
    "final_answer_instructions": "Your final answer should express which option is numerically closest to the computed energy splitting, in the units provided.",
    "grading_standard": "[    $$\\Delta E = h \\Delta \\nu_{hf}$$,    $$h = 4.14 \\times 10^{-15} \\ \\mathrm{eV \\cdot s}$$,    $$\\Delta \\nu_{hf} = 1.42 \\times 10^{9} \\ \\mathrm{s^{-1}}$$,    $$\\Delta E = 4.14 \\times 10^{-15} \\times 1.42 \\times 10^{9} \\ \\mathrm{eV}$$,    $$\\Delta E = 5.8788 \\times 10^{-6} \\ \\mathrm{eV}$$,    $$\\Delta E \\approx 6 \\times 10^{-6} \\ \\mathrm{eV}$$,    $$10^{-5} \\ \\mathrm{eV}$$]",
}
[Example Response]
<judge>invalid</judge><reason>The solution writes \\unit{eV}, but in the grading standard it is changed into \\mathrm{eV}.</reason>

"""

review_stage_3_icl_example_dag = """

Example 1:
[Problem] 
{
    ...,
    "grading_standard": "[
        {
            "index": 1,
            "formula": "$$E_k = \\frac{1}{2} m v^2$$",
            "dependency": []
        },
        {
            "index": 2,
            "formula": "$$E_p = -\\frac{G M m}{r}$$",
            "dependency": [1]
        },
        {
            "index": 3,
            "formula": "$$\\frac{1}{2} m v_0^2 - \\frac{G M m}{r} \\geq 0$$",
            "dependency": [2]
        },
        {
            "index": 4,
            "formula": "$$v_0 \\geq \\sqrt{\\frac{2 G M}{r}}$$",
            "dependency": [3]
        }
    ]"
}
[Example Response]
<judge>invalid</judge><reason>Formula 2 does not depend on formula 1.</reason>

Example 2:
[Problem]
{
    "context": "In atomic hydrogen, the ground state experiences hyperfine splitting due to the interaction between the magnetic moments of the proton and electron. The energy difference between these hyperfine levels can be denoted as $\\Delta E$. The known experimental value for the frequency corresponding to this splitting is $\\Delta \nu_{hf} = 1.42 \\times 10^{9} \\unit{s^{-1}}$. Planck's constant is $h = 4.14 \\times 10^{-15} \\unit{eV \\cdot s}$. Among the given options\u2014$10^{-7} \\unit{eV}$, $10^{-5} \\unit{eV}$, $10^{-3} \\unit{eV}$, $10^{-1} \\unit{eV}$\u2014which is closest to the energy $\\Delta E$ of the hyperfine splitting in hydrogen? You should use $\\Delta \nu_{hf}$ for the hyperfine transition frequency, $h$ for Planck's constant, and $\\Delta E$ for the hyperfine energy splitting.",
    "images": [],
    "solution": "The energy associated with the hyperfine splitting is given by\n$$\n\\Delta E = h \\Delta \nu_{hf}\n$$\nThe value of Planck's constant is\n$$\nh = 4.14 \\times 10^{-15} \\unit{eV \\cdot s}\n$$\nThe frequency for the hyperfine transition in hydrogen is\n$$\n\\Delta \nu_{hf} = 1.42 \\times 10^{9} \\unit{s^{-1}}\n$$\nSubstituting the values, we get\n$$\n\\Delta E = 4.14 \\times 10^{-15} \\times 1.42 \\times 10^{9} \\unit{eV}\n$$\nCalculating,\n$$\n\\Delta E = 5.8788 \\times 10^{-6} \\unit{eV}\n$$\nRounding to one significant figure,\n$$\n\\Delta E \\approx 6 \\times 10^{-6} \\unit{eV}\n$$\nAmong the options provided, the closest value is\n$$\n10^{-5} \\unit{eV}\n$$",
    "id": 1029,
    "final_answer_form": "numerical",
    "final_answer_instructions": "Your final answer should express which option is numerically closest to the computed energy splitting, in the units provided.",
    "grading_standard": "[
        {
            "index": 1,
            "formula": "$$\\Delta E = h \\Delta \\nu_{hf}$$",
            "dependency": []
        },
        {
            "index": 2,
            "formula": "$$h = 4.14 \\times 10^{-15} \\ \\mathrm{eV \\cdot s}$$",
            "dependency": []
        },
        {
            "index": 3,
            "formula": "$$\\Delta \\nu_{hf} = 1.42 \\times 10^{9} \\ \\mathrm{s^{-1}}$$",
            "dependency": []
        },
        {
            "index": 4,
            "formula": "$$\\Delta E = 4.14 \\times 10^{-15} \\times 1.42 \\times 10^{9} \\ \\mathrm{eV}$$",
            "dependency": [1, 2, 3]
        },
        {
            "index": 5,
            "formula": "$$\\Delta E = 5.8788 \\times 10^{-6} \\ \\mathrm{eV}$$",
            "dependency": [4]
        },
        {
            "index": 6,
            "formula": "$$\\Delta E \\approx 6 \\times 10^{-6} \\ \\mathrm{eV}$$",
            "dependency": [5]
        },
        {
            "index": 7,
            "formula": "$$10^{-5} \\ \\mathrm{eV}$$",
            "dependency": [6]
        }
    ]"
}
[Example Response]
<judge>invalid</judge><reason>The solution writes \\unit{eV}, but in the grading standard it is changed into \\mathrm{eV}.</reason>

"""


def get_review_prompt_stage3(sample, method="dag"):
    prompt = f"""
    You are a professor, and now you should review whether your assistant correctly wrote the grading standard for a problem. He should extract the 'core formulas' from the solution and organize them into a grading standard. Below are the rules for the grading standard.
    {grading_standard_rules if method!="dag" else grading_standard_rules_dag}
    Below are some examples for you to better understand the requirement.
    {grading_standard_icl_example if method!="dag" else grading_standard_icl_example_dag}
    You should return something like '<judge>valid</judge><reason>...</reason>' or '<judge>invalid</judge><reason>...</reason>'. You may think before your final output. Keep the reason concise.
    Below are some examples for you to understand it better:
    {review_stage_3_icl_example if method!="dag" else review_stage_3_icl_example_dag}
    Now, according to the instructions, you should decide if your assistant has rewritten the problem correctly. Below is the problem rewritten by your assistant:
    {str(sample)}
    """
    return prompt

def get_wash_prompt_stage4(sample, return_extra_only=True):
    prompt = r"""
    You are an expert in Physics, and you are organizing the grading materials for a given problem. More specifically, your job is to find the variables newly defined in the solution that were not defined in the problem context, and write them down as a json.
    If there are new variables defined in the solution, for example the solution defines $u=\frac{1}{r}$, and $u$ is a newly defined variable, then you response should be:
    ```json
    {
        "u": "\frac{1}{r}"
    }
    ```
    If the variable is not straighforwardly defined with a formula like 'define $u=1/r$, for example if it is defined via text description, or its formula expression is calculated afterwards, you may ignore it. Make sure all values in your json are formulas in LaTeX, and make sure you don't directly use a result in the stardard solution as the definition. 
    For example, if the solution defines $a$ as the acceleration, then calculates $a=2g$, you should ignore it and NOT define $a=2g$.
    
    If there are multiple new variables, you may simply include multiple items in the json.
    If there is no new variable, your response should be exactly "No new variable found in the solution." Nothing else should exist in your response.
    Now, below is the problem and solution.
    """
    prompt += f"\n{str(sample)}\n"
    prompt += r"Notice that if there are new variables, your response should be formatted as ```json\n<your_json>\n```, and nothing else should exist in your json. If there is no new variable, you should not include any json in your response."
    return prompt