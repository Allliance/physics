# Problem Patterns in GPT-5.5 High Physics Failures

This report looks at the *problems themselves*, not the model's solutions. The
question is: among problems GPT-5.5 High failed on, what common problem types or
topic patterns should inform a physics benchmark?

Source data:

- Full evaluated set: 1,406 rows from `FrontierPhysics/all` and `Physics/all`
- Original hard set: 342 rows with score `< 1`
- Non-visual hard set: 325 rows after excluding 17 explicit missing-figure /
  missing-external-information cases
- Four attempts per hard row are stored in `final_datasets/hardest.parquet`

Useful review queues:

- `inspection/reviews/hardest_gpt55_high_nonvisual_failures_80.json`
- `inspection/reviews/hardest_gpt55_high_failures_20.json`

## Main Conclusion

The failures are not concentrated in one narrow physics topic. They are
concentrated in a *style of problem*:

> Multi-part, calculation-heavy, mathematically dense physics problems where the
> correct answer depends on exact setup, conventions, limiting assumptions,
> units, and bookkeeping across several steps.

If you want a benchmark that targets current LLM weakness, replicate that
behavior rather than only sampling from one subject area.

## Topic-Level Signal

Broad topic distribution in the 325-row non-visual hard set:

| Broad area | Hard rows |
|---|---:|
| Quantum / atomic / condensed matter | 111 |
| E&M / circuits / EM waves | 57 |
| Classical mechanics | 54 |
| Thermo / statistical mechanics | 49 |
| Optics / waves | 34 |
| Advanced/statistical field theory | 20 |

These roughly track the full dataset composition. Quantum/atomic/condensed
matter is the largest bucket, but it is also the largest bucket in the full
dataset. The more specific topic failure rates are more informative:

| Topic/source | Rows in full eval | Score `< 1` rate | Score `0` rate |
|---|---:|---:|---:|
| `simons_dataset` | 21 | 38.1% | 0.0% |
| `kardar-fields` | 38 | 31.6% | 0.0% |
| `electro` | 189 | 30.2% | 18.5% |
| `optics` | 136 | 29.4% | 14.7% |
| `kardar_particles` | 70 | 27.1% | 0.0% |
| `Quantum Mechanics` | 35 | 25.7% | 2.9% |
| `Electricity and Magenetism` | 40 | 25.0% | 17.5% |
| `statistics` | 177 | 24.3% | 9.6% |
| `atomic` | 176 | 23.3% | 7.4% |
| `quantum` | 185 | 23.2% | 6.0% |
| `mechanics` | 188 | 18.1% | 5.3% |

Interpretation:

- `electro` and `optics` have high failure rates and high zero-score rates.
- Advanced field-theory sources have high failure rates but fewer total
  all-zero rows; these problems are hard but often partially solved.
- Quantum/atomic/condensed matter contributes the most failures by count.
- Classical mechanics still produces many hard failures when the problem asks
  for an exact observable or careful setup.

## Problem-Shape Enrichment

The non-visual hard set is enriched for several problem features compared with
the full evaluated set:

| Feature | Full set | Non-visual hard set |
|---|---:|---:|
| Explicit multi-part prompt | 76.3% | 86.5% |
| Dataset multipart row | 69.6% | 80.0% |
| Math-dense prompt | 35.3% | 41.2% |
| Estimate / order-of-magnitude language | 23.0% | 28.6% |
| Long prompt > 1k chars | 10.3% | 15.7% |
| Moving frame / relativity language | 19.1% | 21.8% |
| Optical geometry / wave language | 7.7% | 11.1% |
| References visual material | 26.5% | 33.5% |

This suggests benchmark candidates should not just be "hard topics"; they
should be problems with enough structure that a model must maintain a coherent
state over several subparts.

## Highest-Value Problem Patterns to Replicate

### 1. Multi-Part Problems With Coupled Subparts

Pattern:

- Part (b) depends on the setup or result of part (a).
- Later parts change one assumption, frame, boundary condition, or limit.
- The problem is not separable into independent factual questions.

Examples from the failure set:

- Thermodynamic cycles with several heat/work legs.
- Quantum state classification followed by perturbative energy calculation.
- Moving-interface E&M with angles first, coefficients second.

Benchmark design:

- Use 3-5 explicit subparts.
- Make each subpart short but dependent.
- Score each subpart independently.

### 2. Convention-Sensitive Physics

Pattern:

- The topic is familiar, but the answer depends on sign, direction, axis,
  orientation, incoming/outgoing convention, or which quantity is called
  positive.

Examples:

- Moving reflecting wall and beat frequency.
- Lorentz-transformed E&M fields.
- Quantum scattering matrices.
- Magnetic moment signs and angular momentum projections.

Benchmark design:

- State conventions explicitly.
- Ask for vector direction or sign, not just magnitude.
- Include distractor-adjacent observables, such as reflected frequency vs beat
  frequency.

### 3. Quantitative Estimates With Physical Constants and Units

Pattern:

- Problems are short, but the numerical answer depends on choosing the correct
  physical approximation and units.

Examples:

- Nuclear Coulomb-energy estimates.
- Scattering cross sections in barns/cm²/m².
- Solar neutrino flux from solar constant.
- Radiative heating estimates.

Benchmark design:

- Ask for a numerical estimate with units.
- Include enough constants to be self-contained.
- Require the final answer in a specified unit system.

### 4. Advanced Graduate Derivations

Pattern:

- The prompt is compact but assumes graduate-level formalism.
- The result is not a canned one-line formula.
- Correctness depends on normalization and limiting assumptions.

Examples:

- Kardar/statistical field theory rows.
- Pathria/stat mech derivations.
- Interacting electron gas estimates.
- Series/critical scaling problems.

Benchmark design:

- Require derivation plus final expression.
- Ask the model to define normalization choices.
- Use references where the expected convention is unambiguous.

### 5. Optics and Wave Problems With Geometry

Pattern:

- The model must translate aperture/lens/slit geometry into formulas.
- Often involves intensity, amplitudes, coherence, diffraction envelopes, or
  Fresnel coefficients.

Examples:

- Unequal slits and diffraction pattern.
- Fresnel reflection by polarization.
- Field amplitudes from power density.
- Coherence length from bandwidth.

Benchmark design:

- If geometry is visual, include an image or rewrite it fully in text.
- Ask for both formula and numerical scale.
- Include unit conversions like mW/cm² to SI.

### 6. Thermodynamic Bookkeeping

Pattern:

- The difficulty is not knowing a law, but tracking the correct state function,
  reference state, process leg, or extensive factor.

Examples:

- Modified Carnot cycles.
- Entropy/enthalpy/Gibbs free energy at phase transition.
- Heat shields and blackbody radiation.
- Glass/crystal heat capacity integrations.

Benchmark design:

- Use tables of states or text-only cycles.
- Ask explicitly which legs absorb/reject heat.
- Include sign convention for work and heat.

### 7. Quantum State Classification and Ordering

Pattern:

- Correct answer is a structured object, not just a number.
- The problem asks for state ordering, allowed spins, degeneracies, or
  perturbative splitting.

Examples:

- Identical fermions in a well.
- Hydrogen fine-structure state in weak/strong fields.
- Isospin multiplet constraints.
- Multi-step scattering potentials.

Benchmark design:

- Ask for state labels, degeneracy, spin, and energy ordering.
- Include a second part requiring an integral or perturbative correction.

## What Not To Overfit To

### Missing Diagrams

There are 17 explicit failures where the model said a needed figure, circuit,
graph, geometry, or external data source was missing. These are useful for
dataset hygiene but not ideal benchmark content unless the diagram is included.

Files:

- `final_datasets/hardest_visual_external_failures.parquet`

### One-Off Reference Ambiguities

Some individual failures may depend on conventions or reference assumptions. A
benchmark should manually verify each selected item and make hidden assumptions
explicit.

### Pure Topic Sampling

Sampling only "quantum" or only "E&M" is less targeted than sampling problem
structures. The same weakness pattern appears across several topics.

## Recommended Benchmark Blueprint

For a new physics benchmark, I would build a balanced hard set with sections
like this:

| Section | Target behavior |
|---|---|
| Relativistic E&M and moving media | signs, axes, frame transformations |
| Quantum angular momentum/scattering | conventions, state labels, branch tracking |
| Nuclear/atomic estimates | units, constants, approximations |
| Thermodynamic cycles/bookkeeping | process legs, signs, state functions |
| Optics/waves with geometry | aperture/lens geometry, intensities, unit conversions |
| Classical mechanics exact observables | choosing the requested observable |
| Advanced stat mech/field theory | normalization, scaling, limiting assumptions |

Each item should be:

- self-contained, or include the necessary image/diagram;
- explicitly multi-part when appropriate;
- scored part-wise;
- convention-explicit;
- designed so a plausible-looking derivation is not enough.

## Practical Sampling Rule

To replicate the failure behavior, sample problems satisfying at least two of:

1. Explicit multi-part structure.
2. Requires a symbolic derivation plus a final numerical/simplified expression.
3. Requires careful sign, vector direction, or convention tracking.
4. Requires a physical approximation or limiting regime.
5. Requires unit conversion or constants.
6. Has a structured answer: state ordering, table, matrix, process legs, or
   part-wise classification.
7. Comes from graduate-level E&M, quantum, stat mech, optics, or condensed
   matter.

That recipe is a better benchmark target than a single topic label.

