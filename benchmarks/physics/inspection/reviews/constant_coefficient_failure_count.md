# Constant-Coefficient Failure Count

Question: among the hard-set responses, how often did the judge mark a response wrong because the variables/dependence were otherwise right, but a numerical constant, prefactor, coefficient, or normalization was wrong?

Scope: `final_datasets/hardest.parquet`, 342 problem rows, 4 evaluations per row.

## Count

- Clear coefficient-only problem rows: **23 / 342** (6.7%)
- Borderline coefficient/convention rows: **3 / 342** (0.9%)
- Clear + borderline: **26 / 342** (7.6%)

At the evaluation-attempt level, the strict heuristic found **45 attempt-level hits** across the four attempts.

## Clear Rows

- `FrontierPhysics test cmft/5.6.1`
- `FrontierPhysics test textbook/7.2`
- `FrontierPhysics test vi/2`
- `FrontierPhysics train kinetic/3.10`
- `FrontierPhysics train textbook/3.8.3`
- `FrontierPhysics train textbook/7.4`
- `FrontierPhysics train thermo-early-universe/9.9`
- `Physics test Statistical Mechanics/19-5`
- `Physics test electro/1_17`
- `Physics train Quantum Mechanics/27-3`
- `Physics train atomic/2-18`
- `Physics train atomic/3-31`
- `Physics train atomic/3-36`
- `Physics train electro/1_75`
- `Physics train electro/1_89`
- `Physics train optics/1-39`
- `Physics train optics/2-2`
- `Physics train optics/3-1`
- `Physics train quantum/4011`
- `Physics train quantum/5003`
- `Physics train quantum/5069`
- `Physics validation Electricity and Magenetism/10-3`
- `Physics validation Electricity and Magenetism/10-7`

## Borderline Rows

- `Physics train mechanics/2_27`: functional dependence/direction partly correct, but judge also says the “constant” is not actually constant and omitted other dependence
- `Physics train mechanics/3_46`: algebraic form can match after redefining eta, but judge also notes missing mu0/4pi, extra c, and sign/convention issues
- `Physics validation Quantum Mechanics/23-2`: judge reason includes coefficient-like formula mismatch, but the main issue is incidence-direction/scattering setup mismatch

## Interpretation

This is a noticeable but not dominant failure mode. Roughly **7%** of the hard problems are clean cases where the model appears to know the correct variable dependence or functional shape but loses on an overall coefficient, prefactor, phase factor, normalization, or unit-scale constant.

For benchmark design, this supports including problems where the final answer is not just proportionality/scaling. Require the exact coefficient and normalization, especially in optics, E&M, quantum perturbation theory, statistical mechanics, and order-of-magnitude atomic/nuclear estimates.
