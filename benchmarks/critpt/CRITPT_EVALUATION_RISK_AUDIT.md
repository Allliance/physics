# CritPt public-test evaluation-risk audit

## Scope and classification

This audit reviews all 70 public-test challenge statements and their supplied Python templates. It does not use or assume access to hidden ground truths or grader implementation, and it does not attempt to solve the problems. The risk labels assess whether a scientifically correct answer could plausibly be rejected by a narrow reference-answer comparison.

For the headline split, **symbolic** means the template requests a SymPy expression, interval, or set containing symbolic expressions. Everything else is grouped as **numeric/structured**: fixed floats/integers, numeric vectors, categorical sets, booleans, or functions that return numbers when called on numeric inputs. Mixed tasks are assigned according to their principal scientific output.

- Symbolic: **29/70 (41.4%)**
- Numeric/structured: **41/70 (58.6%)**

This binary split hides important subtypes. Numeric/structured tasks include lookup- or simulation-dependent values, lists whose length must be inferred, sets of labels, and callable predicates. They are not all safe for literal equality. Symbolic tasks range from simple algebra to distributions, asymptotic expansions, phase conventions, branch cuts, and gauge-dependent expressions.

Risk levels:

- **Low**: the statement/template appears to define a substantially unique output and ordinary semantic or tolerant comparison should work.
- **Medium**: conventions, numerical tolerance, representation, or completeness require care.
- **High**: material underspecification, multiple scientifically valid conventions/answers, missing numerical methodology, or difficult symbolic equivalence is apparent from the prompt.

## Per-challenge audit

| # | Class | Risk | Evaluation concern |
|---:|---|---|---|
| 1 | Numeric vector | **High** | The listed invariant basis appears dimensionally inconsistent/redundant (for example bare terms of the wrong curvature weight). Coefficients depend on basis identities, trace conventions, and ordering. Exact float-vector comparison cannot recognize an equivalent anomaly written in another invariant basis. |
| 2 | Symbolic + labels | **High** | A non-Markovian renewal-growth calculation with a perturbative noise expansion can be expressed through implicit roots/Laplace transforms in several equivalent forms. The stated “Gaussian” noise is also described as positive with mean zero, an internal inconsistency. Monotonic-effect labels may depend on parameter regime. |
| 3 | Symbolic | **High** | A geodesic one-point function is defined only up to operator normalization and holographic counterterm/prefactor conventions. The relation between bulk mass and boundary dimension and the insertion coordinate dependence are not fully specified. Many answers differing by constants or by using (m) versus Δ can be valid. |
| 4 | Discrete set | **High** | Three temporally overlapping pulses allow many photon-number channels. The prompt does not state the selection/conservation rule, coherence model, or whether all channels or a dominant channel are wanted. Multiple OAM/helicity pairs can result, and temporal envelopes complicate what “the 23rd harmonic” means. |
| 5 | Symbolic | **Medium** | Hypergeometric derivatives can reduce to logarithms, radicals, elliptic/hypergeometric derivatives, or piecewise forms. Endpoint behavior at α=0,1 and branch choices matter; naive structural comparison is unsafe. |
| 6 | Numeric + integers | **Medium** | Chern numbers explicitly have global-sign freedom, so both sign-related tuples must pass. The Wannier-spread value depends on plane-wave cutoff boundary handling, eigenvector derivatives, mesh quadrature, and band ordering; two-decimal equality needs tolerance. |
| 7 | Symbolic | **Medium** | Equivalent QFI formulas may contain powers of (2q-1), exponentials, or expanded fidelity factors. Parameter normalization for the scaled average and QFI convention can introduce factors of (d,n). Algebraic semantic comparison is needed. |
| 8 | Numeric triple | **High** | The requested perturbation ratios require equations of motion, gauge fixing, mode normalization, horizon-crossing prescription, and a numerical integration protocol not supplied in the prompt. Ratios involving perturbations can be gauge/convention dependent. |
| 9 | Numeric | **High** | “Use these values in the equations of motion” does not actually provide the equations or all initial data (notably scale-factor normalization). Numerical solver/stopping conventions affect the e-fold count. |
| 10 | Numeric | **High** | As in #9, the full torsion/Chern-Simons equations and numerical prescription are absent. The initial velocity is unusually large relative to the mass scale, making implementation choices consequential. |
| 11 | Symbolic pair | **High** | One-loop beta-function coefficients depend on coupling normalization, RG-time direction, OPE normalization, and scheme. The prompt states an IR sign convention but not enough normalization detail to force unique coefficients. |
| 12 | Symbolic phase | **High** | A phase is only defined modulo (2π) and changes under rephasing of basis states/parafermion conventions. SymPy equality will not generally recognize modularly equivalent exponents or roots of unity. |
| 13 | Exact structured set | **High** | Verlinde-line labels have field identifications, electron equivalences, selection rules, and possible duplicate representatives. Expectation values may be equivalent complex roots written in many forms; set completeness and representative choice are convention-sensitive. |
| 14 | Numeric | **High** | A finite (100\times100) disordered replicated spin-model root requires a precise numerical algorithm, disorder/boundary-condition summation, and interpolation. “(y=0)” may occur asymptotically or have finite-size numerical ambiguity. |
| 15 | Symbolic | **High** | The Kraus list as written is questionable for trace preservation unless weights/normalizations satisfy extra relations. Boundary placement of the string, finite-(N) versus thermodynamic assumptions, and AKLT normalization can yield different formulas. |
| 16 | Numeric | **High** | A critical Hubbard interaction is method dependent (mean field, QMC, DMFT, finite-size scaling, etc.). No computational method, units/normalization interpretation, tolerance, or precise phase diagnostic is specified. |
| 17 | Numeric | **High** | The entropy definition has a likely sign issue ((S=-\partial F/\partial T) conventionally), and the disorder/large-(N) saddle and coupling normalization matter. A literature-specific number is likely intended rather than a uniquely derivable prompt-only value. |
| 18 | Symbolic pair | **High** | Optical-binding spring constants depend on Green-tensor, phase, time-averaging, sign, and amplitude conventions. Equivalent trigonometric forms are common, and the prompt does not fully define how (E_i) are normalized. |
| 19 | Symbolic triple | **High** | Quadrature noise can be vacuum-normalized to 1, 1/2, or another spectral-density convention. Loss modeled as amplitude versus intensity transmission and “maximum squeezed” wording can change formulas. Hyperbolic/trigonometric equivalence is nontrivial. |
| 20 | Callable numeric formula | **Medium** | The template expects numerical code over arbitrary inputs, not a symbolic object. Unit conversions (nm, mW), ellipsoid polarizability convention, moment of inertia, and dipole-coupling approximations must match exactly; tolerant testcase comparison is required. |
| 21 | Numeric triple | **High** | Plus-distribution discretization at ξ=1, quadrature weights, endpoint treatment, matrix construction, DGLAP integration, and interpolation are underspecified. Different reasonable numerical implementations can produce different values. |
| 22 | Symbolic | **High** | The requested (f(x)) depends “only on (x)” despite the state family containing θ; the reparameterization of the optimization variable is not specified. Entropy log base and endpoint conventions also matter. |
| 23 | Symbolic piecewise | **High** | Loop-integral answers depend on Fourier, (i0), dimensional-regularization, UV/IR pole labeling, and distribution conventions. Algebraically equivalent log forms differ by branches; omitted delta/plus terms are a major grading hazard. |
| 24 | Symbolic piecewise | **High** | The Coulomb-gauge quasi-PDF is distribution-valued. Plus prescriptions, delta terms, gauge singularities, renormalization conventions, and log branches cannot be robustly checked by ordinary expression equality. |
| 25 | Symbolic | **High** | The statement/template are internally inconsistent: (E_p) is both derived and passed, and the displayed derived definition appears to use Δ where the threshold relation uses Doppler δ. Spectral and luminosity-frame conventions can shift redshift/Doppler powers. |
| 26 | Numeric | **Medium** | A three-significant-figure cavity shift is reproducible only if all cavity radius/field parameters and modal-sum prescription from the setup are used exactly. Renormalization/subtraction and near-resonance handling can vary. |
| 27 | Numeric | **Medium** | Optimizing spin squeezing requires a stated dynamical master equation, time domain, finite-(N) approximation, and dB convention ((10\log_{10}ξ^2) versus related definitions). Numerical optimization tolerances matter. |
| 28 | Numeric exponents | **High** | “Correction along (y)” is not self-identifying without the full observable/context, and zero-frequency/zero-temperature limits may not commute. Exponents can depend on dispersion anisotropy and definitions of transport versus quasiparticle lifetime. |
| 29 | Symbolic pair | **High** | Optical-lattice tunneling has several standard deep-lattice asymptotics with convention-dependent lattice depth, recoil energy, Gaussian widths, and prefactors. The beam geometry and harmonic approximation can be parameterized in equivalent but hard-to-match ways. |
| 30 | Symbolic | **High** | Haar-orthogonal averages over state overlaps admit many equivalent inner-product/conjugation forms. The template’s Ket objects and starred kets make canonicalization fragile; dimension conventions (d,d_P,d_B) must match the source derivation. |
| 31 | Numeric pair | **Medium** | Explicit tolerances are supplied, which helps, but the eigenproblem still depends on discretization, boundary conditions, and the detailed base state in the setup. A tolerance-aware grader is essential. |
| 32 | Numeric triple | **High** | The eigenfunction ratio depends on eigenvector normalization only if (w) and (T) share a fixed coupled normalization; sign/phase conventions can flip it. Critical values have tolerances, but no tolerance is stated for the ratio. |
| 33 | Mixed set + numbers | **High** | Particle labels A/B/C and variables (r,v,w,z) are source-context dependent. Threshold scaling and a lower bound do not necessarily identify a unique decimal (s), and equality at/above the bound is ambiguous. |
| 34 | Symbolic | **Medium** | Trigonometric qMPS correlators can have very different rational/trigonometric forms. The thermodynamic limit can be piecewise at transfer-matrix degeneracies, which a generic symbolic simplifier may miss. |
| 35 | Numeric vector | **High** | The supplied state amplitudes are finite-precision partial data. The constraint nullspace may have multiple Hamiltonians unless uniqueness is numerically established; normalization by one coefficient fails if near zero. Solver tolerance and rounding can make exact vector comparison invalid. A residual-based grader is preferable. |
| 36 | Symbolic + threshold | **High** | “Observe oscillatory behavior” requires a quantitative criterion. The minimal (n) may follow a pole/eigenvalue condition with integer rounding, while the requested type is SymPy expression. Multiple forms and boundary conventions are plausible. |
| 37 | Mixed categorical/numeric | **Medium** | The prompt gives a concrete cutoff and mesh, but band isolation and gap definitions near crossings require tolerances. Topological and Wannier answers depend on symmetry/gauge interpretation; `N/A` logic must be graded coherently. |
| 38 | Symbolic asymptotic | **High** | “Temperature dependence” may mean only a power law, a proportionality class, or a full prefactor. Constants such as (k_B) are absent from template inputs, and asymptotically equivalent expressions are not literal equals. |
| 39 | Symbolic | **High** | Density-matrix coherences depend on master-equation details, initial atomic state, coherent-state conventions, complex conjugation of α, and limiting cases (n=n'). Gamma/factor-of-two conventions and factorial/gamma-function forms impede comparison. |
| 40 | Symbolic set | **Medium** | Dispersion roots have sign-paired branches and equivalent square-root factorizations. Branch choice, stability sign convention for (e^{-iωt}), and whether multiplicities/zero modes appear in a set require explicit handling. |
| 41 | Numeric | **High** | Finite-size corrections in diffusion Monte Carlo depend on the precise correction scheme, trial wavefunction, kinetic/potential decomposition, and literature data. Two significant digits does not specify an acceptance tolerance near rounding boundaries. |
| 42 | Mixed numbers + booleans | **High** | Several prose questions are compressed into booleans whose names/descriptions are inconsistent: `is_long_range` is documented as which scattering gives longer mean free path, while `is_longer` asks nearly the same thing. Physical answers can be regime dependent. |
| 43 | Numeric tuple | **Medium** | Charges are defined modulo an electron and mapped to a half-open interval, which is good, but boundary values (±1/2), sign of Frank angle, rotation/Wannier angular-momentum convention, and translation-class representatives can differ. |
| 44 | Counts + numeric | **High** | Degenerate-ground-state counting depends on exact versus numerical degeneracy, flux-sector definition, boundary conditions, and finite-size geometry. Three-decimal energy comparison needs tolerance. |
| 45 | Callable boolean | **Medium** | The predicate should accept arbitrary numeric masses, but equalities/boundaries and positivity are unspecified. Equivalent analytic conditions can be implemented differently; behavioral testcases, including boundary cases, are necessary. |
| 46 | Numeric lists | **High** | Identifying “scar states” requires a threshold/selection rule for overlap and a definition of the symmetry subspace. Near-degenerate ordering, number of returned states, diagonalization precision, and rounding make literal list equality brittle. |
| 47 | Numeric | **High** | The operator (L), trace domain, spatial integration range, discretization, and boundary conditions must be completely specified in the omitted setup. Six-decimal accuracy is unrealistic if any of these are implicit or numerical. |
| 48 | Numeric | **High** | Analytic continuation is not unique from integer replica data without growth/analyticity conditions. The definition of (Z(n,η)), branch choice, and numerical continuation method can materially alter eight-decimal results. |
| 49 | Symbolic asymptotic | **High** | Expressions are equivalent only modulo (O(1)), while ordinary symbolic equality will treat different constants as unequal. Log-base conversion and regrouping — e.g. λog₂ z versus λn z/λn2 — add further equivalence risk. |
| 50 | Integer | **Medium** | The statement explicitly warns of multiplicities, so a grader must count configurations rather than distinct terminal tuples. If the recurrence/configuration rules in setup are complete, the integer is unique; otherwise interpretation of indistinguishable histories is risky. |
| 51 | Symbolic | **Medium** | Generating functions can be presented as rational functions, radicals, roots of a recurrence, or algebraically transformed elementary expressions. Domain/formal-power-series branch selection matters. |
| 52 | Numeric | **High** | The overlap depends on normalization conventions for hyperangular/Efimov functions and numerical roots. Asking to “calculate (N,H,G)” but returning only (P) hides intermediate convention checks; three decimals needs tolerance. |
| 53 | Symbolic pair | **High** | Curvature coefficients depend on Fefferman–Graham/obstruction-tensor normalization, residue conventions, dimension-dependent identities, and symmetrization factors. Equivalent tensor bases may move coefficients between terms. |
| 54 | Structured numeric sets | **High** | Magic wavelengths depend on atomic data set, hyperfine/Zeeman state, polarization quantization axis, linewidth treatment, and rounding. “All” roots in 400–600 nm is database/model dependent; integer rounding can merge or split roots. |
| 55 | Numeric pair | **High** | A literature-defined σ function requires units, material parameters, broadening, and the precise low-temperature formula from setup. Three decimals alone does not remove model/numerical ambiguity. |
| 56 | Numeric list | **High** | Detector sensitivity curve, dark-matter coherence model, signal integration, overdensity interpretation, and year conversion are required. The two observation regimes may scale differently if coherence time is crossed. |
| 57 | Numeric list | **High** | Sensitivity depends on detector noise, force response, dark-photon coherence/distribution, and material charge-to-mass conventions. The prompt is effectively literature/data dependent and exact numeric equality is unsafe. |
| 58 | Categorical set | **High** | Magnetic space group inference can yield multiple symmetry-allowed subgroups depending on magnetic order parameter direction/domain. BNS versus OG setting and origin-choice equivalents require canonicalization; the prompt asks for all possible groups. |
| 59 | Symbolic set | **High** | Reciprocal indices are periodic modulo (M); different Brillouin-zone representatives are equivalent. Structure factors can differ by origin-dependent phases, normalization, sign, and first-order rearrangement. Set equality will not capture these equivalences. |
| 60 | Symbolic | **Medium** | QFI expressions can be algebraically transformed and γ may be signed/complex depending on point-spread-function conventions. Parameter reparametrization for θ requires nuisance-parameter treatment, potentially changing the result. |
| 61 | Integer + float | **High** | “Achievable probability” and evolution time usually arise from an optimization with multiple local maxima. Rounding (T) before versus after optimizing changes (P); tie-breaking and tolerance are not specified. |
| 62 | Symbolic + interval | **High** | The interval may be a union/piecewise function of integer (k), with endpoint openness and parity branches. Phase periodicity yields equivalent interval representatives. The unusual `k_value` dispatch while retaining symbolic (k) creates implementation-specific answers. |
| 63 | Numeric pair | **High** | Contextuality robustness depends on the operational-equivalence scenario and whether all states/effects/measurements are allowed. The two notions can be formulated as different linear programs; three decimals needs solver tolerance and a fully specified polytope. |
| 64 | Numeric pair | **High** | For complex insertion points a CFT correlator is generally complex, yet the template requires `float`; this is a direct type mismatch unless a modulus, real part, or special convention is intended. Operator normalization and conformal-block branch choices also matter. |
| 65 | Symbolic set | **High** | “Indecomposable” requires quotienting by trace identities, cyclicity, fermionic signs, equations of motion, and derivatives. Equivalent operator bases need not contain the same expressions, so set equality against one basis is conceptually wrong. |
| 66 | Symbolic polynomial/series | **Medium** | A truncated generating function can be written expanded, factored, or with an (O(q^{16})) term. “Index of trace relations” sign/grading conventions must be fixed, but polynomial coefficient comparison is robust once canonicalized. |
| 67 | Symbolic | **High** | Quantum capacity is often a regularized optimization and may have piecewise dimension dependence. Log base, channel definition, and use of degradability/antidegradability at the boundary matter; equivalent entropy/log forms need semantic comparison. |
| 68 | Numeric | **High** | “As accurate as possible” gives no tolerance. Matrix logarithm/eigenvalue degeneracy, definition of standard (f)-divergence, and numerical differentiation versus analytic differentiation can produce method-dependent digits. |
| 69 | Numeric | **High** | A supremum over density operators may be unattained or only known through a theorem/numerical optimization. Relative-entropy convention, channel parameterization, and boundary-state regularization affect evaluation; no precision is specified. |
| 70 | Numeric | **High** | The operator (N), tensor-leg ordering, and whether ψ denotes a ket, projector, or density matrix must be explicit. Tensor-network contraction conventions can change normalization; a float return hides whether an exact rational is expected. |

## Main evaluation risks

### Numeric/structured tasks

Numeric outputs are not automatically easy to grade. Literal equality is generally inappropriate for floats; a grader should use stated rounding or absolute/relative tolerances. More importantly, many numeric tasks are not uniquely determined by the prompt alone. The clearest examples are:

- missing or method-dependent simulations/equations (#8–10, #14, #16, #21, #31–32, #41, #46–48, #52, #55–57, #61, #63, #68–69);
- explicit equivalence classes or conventions (#6 global Chern sign, #43 charge modulo (e));
- inverse problems or optimization with nonunique solutions (#35, #46, #61, #69);
- categorical bases/settings with equivalent labels (#13, #54, #58);
- an apparent output-type mismatch (#64 requests floats for a generally complex correlator).

Thus a simple scalar equality check would be safe for only a minority of the 41 numeric/structured tasks. Even apparently fixed integers or floats can be literature- or implementation-specific.

### Symbolic tasks

The symbolic tasks contain several kinds of equivalence that are difficult for both generic CAS simplification and reference-string comparison:

- algebraic/trigonometric/hyperbolic rearrangements (#5, #7, #18–19, #34, #40, #51, #60, #66);
- phases modulo (2π), roots of unity, and gauge/basis rephasings (#12–13);
- distributions, plus prescriptions, delta terms, and log branches (#23–24);
- tensor identities and alternative invariant/operator bases (#1, #53, #65);
- asymptotic equivalence modulo ignored terms or constants (#38, #49);
- periodic Brillouin-zone representatives and origin-dependent phases (#59);
- piecewise domains, branch cuts, or intervals (#5, #22–24, #40, #62, #67).

Robust symbolic evaluation therefore needs more than `simplify(candidate-reference) == 0`. Depending on the problem it may require assumptions, piecewise-domain checks, numerical sampling away from singularities, modular-phase comparison, distribution-aware testing, basis reduction, residual/constraint checking, or human review.

## Recommended grading design

1. Execute the submitted template and validate output types and shapes first.
2. For numeric outputs, use declared rounding/tolerances plus independent residual checks where possible; never raw float equality.
3. For symbolic outputs, combine canonicalization, assumption-aware simplification, and high-precision randomized substitution over valid domains.
4. Add problem-specific equivalence logic for modular phases, global signs, charge classes, intervals, sets, tensor/operator bases, and distributions.
5. Grade inverse/optimization problems by constraints or objective quality (#35, #46, #61, #69), not distance from one reference vector.
6. Escalate convention-sensitive, literature-dependent, or internally inconsistent items to expert review or exclude them from aggregate model comparisons until clarified.
