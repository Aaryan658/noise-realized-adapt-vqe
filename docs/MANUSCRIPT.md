# Noise-Realized Operator Selection for ADAPT-VQE: A Cross-Framework Benchmark on H2 and LiH under Calibrated Depolarizing Noise

**Author Name**, *Department / Institution, City, Country, email*

> Course research manuscript. The baseline comparison (Section IV-E) is
> reproducible and robust; the three proposed selection rules are a
> characterized null (Sections IV-C, IV-F). Figures are in `results/` and
> `results/novel/`.

---

## Abstract

The Adaptive Derivative-Assembled Pseudo-Trotter Variational Quantum Eigensolver (ADAPT-VQE) builds a molecular ansatz one operator at a time, at each step adding the pool operator with the largest energy gradient. On noisy hardware the gradient is a questionable guide: the added operator's contribution is corrupted by decoherence, and the gradient estimate itself sits close to the gate-error rate regardless of the true slope. We ask whether a cost- or noise-aware selection score does better, using a controlled benchmark on H2 (4 qubits, full space) and stretched LiH in a (2e,3o) active space (6 qubits), STO-3G basis, under depolarizing noise calibrated to the IBM FakeManilaV2 backend, with the Qiskit and PennyLane noise footings verified equal to 10^-15 on a probe observable so that the selection rule is the only independent variable. The main comparison is unambiguous: the compact all-to-all qubit-ADAPT ansatz reaches 5.7 to 16.3 mHa on stretched LiH across the noise sweep, against 125 to 348 mHa for fixed UCCSD and 172 to 344 mHa for Qiskit's routed ADAPT, and it matches or beats the hardware-efficient ansatz at comparable depth -- confirming that for depolarizing noise the two-qubit-gate count, not the algorithm, sets the error. Against this baseline we test three selection rules sharing one code path. A cost-penalized rule, `score = |g| / (1 + lambda c)`, is inert: it reproduces standard ADAPT at every non-zero noise level, for an analytic reason we give. A noise-realized rule, which scores each shortlisted operator by the energy it actually reaches after re-optimization with the noise channel applied, is 0.5 to 1.4 mHa more accurate than standard ADAPT at 0.25x to 0.50x noise in a free-running sweep; but a matched operator-count control shows this margin is inconsistent in sign once every rule is forced to the same circuit length (delta vs standard +0.01 / +0.03 / -0.24 / +0.89 mHa at k = 6), so it is largely a circuit-length effect of the stopping rule rather than a better operator choice. A self-tuning cost-penalty controller tracks the noise regime correctly but never changes a selection on these systems. We conclude that minimal-basis H2 and LiH(2e,3o) are too small to establish or refute a selection-quality advantage, and we identify the 10-qubit active space that would settle it.

**Index Terms —** Variational quantum eigensolver, ADAPT-VQE, operator selection, quantum chemistry, NISQ, depolarizing noise, ansatz construction.

---

## I. Literature review

### A. Motivation and scope

The Variational Quantum Eigensolver (VQE) estimates the ground-state energy of a molecular Hamiltonian by tuning the parameters of a quantum circuit to minimize the measured value of the expectation of H in the trial state [1]. Its accuracy on near-term hardware depends on the ansatz. A shallow ansatz cannot represent the correlated wavefunction; a deep one accumulates enough gate error to destroy the state before it is measured [2], [3]. Fixed ansatze commit to one side of this trade-off in advance: the hardware-efficient ansatz (HEA) chooses shallowness [4], and unitary coupled cluster (UCCSD) chooses chemical completeness at a cost of hundreds of two-qubit gates. ADAPT-VQE [5] builds the ansatz adaptively, adding operators from a pool one at a time, each chosen to maximize the current energy-gradient magnitude, and re-optimizing all parameters after each addition. The circuits it produces are compact and problem-specific, and reach chemical accuracy with far fewer parameters than fixed UCCSD.

This work asks one question: is the gradient the right quantity to select on when the device is noisy? Under noise, an operator that lowers the energy steeply but adds many entangling gates can be a net loss, because each added CNOT is an error channel, and the gradient itself, measured on a noisy state, is a biased and unreliable estimate. We test a cost-aware rule, find it inert on minimal-basis small molecules, explain why, and propose a selection criterion based on measured rather than predicted energy reduction.

### B. Ansatz pools for ADAPT-VQE

The original ADAPT-VQE pool holds fermionic single and double excitations [5]. Each fermionic excitation carries a Jordan-Wigner (JW) Z-string, so its CNOT cost grows with the span of the orbital indices it couples. Tang et al. proposed qubit-ADAPT [6], which breaks each fermionic generator into its individual Pauli-string rotations; a weight-w Pauli string is realized by a CNOT staircase of 2(w-1) gates, so a minimal pool of such rotations produces much shallower circuits than fermionic ADAPT at the price of more iterations. Yordanov et al. proposed qubit-excitation-based (QEB) ADAPT [7], whose excitation evolutions act on a fixed number of qubits, 2 CNOTs for a single and 13 for a double regardless of orbital span, and which additionally select among the top-n gradient candidates by the energy reduction each one achieves after re-optimization; this cuts CNOT counts by a further 15 to 25 percent on LiH, H6 and BeH2. Claudino et al. [8] compared fermionic and qubit pools and quantified the iteration, parameter and CNOT trade-offs and the dependence on the gradient threshold. Our benchmark uses the qubit-ADAPT pool because it is the smallest change that gives pool operators a varying CNOT cost, which any cost-aware rule needs in order to be non-trivial.

### C. Reducing ADAPT circuit cost

Several methods target circuit cost directly. TETRIS-ADAPT-VQE [9] drops the one-operator-per-iteration rule: after adding the top-gradient operator it also adds every later operator whose qubit support is disjoint from what has already been placed that iteration, giving shallower and denser circuits at the same CNOT and parameter count. Long et al. [10] build a non-commutation framework for this kind of layering and show, by simulation, that shallower circuits improve resilience to amplitude-damping and dephasing noise but not to depolarizing noise: for local depolarizing channels the error tracks the number of two-qubit gates, not the depth. Ramoa et al. [11] cut resources through coupled-exchange operators and gradient-information reuse. Shkolnikov et al. [12] address the O(pool size) measurement cost of the gradient screen and the symmetry violations that naive pools can introduce.

### D. Selection criteria beyond the gradient

The selection objective is an underused lever. Overlap-ADAPT-VQE [13] grows the ansatz to maximize overlap with an inexpensive classical target wavefunction rather than to minimize energy, which avoids energy plateaus and local minima and produces far more compact circuits. Rotoselect [14] uses the fact that a single gate's energy landscape is a low-order trigonometric polynomial: three evaluations reconstruct it exactly and give both the optimal parameter and the achievable energy in closed form, which is the basis for energy-based rather than gradient-based scoring. Rossi et al. [15] make energy-based selection as cheap as gradient-based via an exact Hamiltonian transformation and report, on LiH, BeH2 and H2O, that the re-optimization strategy and orbital optimization often matter more than the scoring rule for weakly correlated systems. Nykanen et al. [16] reuse informationally complete measurement data taken for the energy to estimate all pool gradients at once, removing the per-iteration measurement cost. A 2026 preprint on Hamiltonian-aware ADAPT [17] folds non-local Hamiltonian matrix-element information into the criterion and prunes redundant operators. All of these energy-based criteria are evaluated noiselessly, none scores operators by their contribution as realized under the noise channel, and cost-penalized selection is essentially unstudied.

### E. Noise, trainability, and gate-error limits

McClean et al. [18] showed that sufficiently expressive random circuits have barren plateaus, with gradients that vanish exponentially in qubit number. Wang et al. [19] proved that hardware noise on its own flattens the cost landscape exponentially in circuit depth, independent of expressibility, so that gradients, and gradient-based operator selection, become steadily less informative as circuits grow. This is the basis for the observation, central to this paper, that the noisy candidate-gradient estimate is floored and cannot rank operators. Yordanov et al. [20] established, by density-matrix simulation, that VQEs need per-gate error rates of roughly 10^-6 to 10^-4 to reach chemical accuracy for small molecules, which bounds the regime in which any selection rule can matter.

### F. Identified gap and novelty of this work

The literature agrees on three points: the ansatz pool sets the achievable circuit cost [6], [7], [11]; for depolarizing noise the error scales with two-qubit-gate count rather than depth [10]; and the selection objective is a powerful but underused lever [13]-[17], while noise makes the gradient an unreliable estimator of that objective [19]. Three specific gaps remain open, and this project addresses each.

First, selection by realized rather than predicted benefit under noise. Every existing ADAPT variant, fermionic [5], qubit [6], QEB [7], TETRIS [9], Overlap [13], screens the pool using a quantity computed on a clean or lightly perturbed state: an energy gradient [5]-[9], a wavefunction overlap [13], or a closed-form noiseless energy landscape [14], [15]. The QEB n-candidate step [7] and the energy-based criteria of [14], [15] do evaluate an actual energy reduction, but only in the noiseless setting. No prior work re-optimizes each shortlisted operator with the device noise channel applied and selects by the energy it actually delivers there. This project introduces noise-realized selection, which does exactly that. It selects different Pauli strings from the bare-gradient rule within an equal-gradient excitation class; whether that choice is systematically better is tested by a matched operator-count control (Section IV-C), and on the systems here it is not established.

Second, a CNOT-cost penalty on the selection score. Cost-aware operator pools exist (qubit, QEB, coupled-exchange [6], [7], [11]), but a selection score of the form gradient divided by (1 + lambda times added CNOT count) is, as far as we can find, untested in the ADAPT literature. This project implements and benchmarks it, and establishes a negative result with an analytic cause: on minimal-basis H2 and LiH the rule is provably inert, because single excitations have zero gradient at Hartree-Fock (Brillouin's theorem) and the gradient-carrying doubles are all equal cost, so the denominator cannot re-rank them; and where the rule would act, noise has already truncated the ansatz. Recording this prevents its being re-attempted.

Third, a self-tuning resource penalty. In every cost-aware scheme the cost weight is a fixed hyperparameter set before the run. This project makes lambda a feedback controller that rises as ADAPT enters the noise-dominated tail and relaxes while operators still deliver, so the algorithm adjusts its own cost-accuracy trade-off to the noise it observes. The controller tracks the regime correctly, with lambda near 0.4 at low noise and near 2.5 at the device error rate, but the two test systems do not contain the cheap alternative operators it would need to change a selection.

In short, the contributions are: a tightly controlled cross-framework benchmark showing the compact qubit-ADAPT ansatz is markedly more noise-tolerant than fixed UCCSD, the hardware-efficient ansatz, and routed Qiskit ADAPT; a controlled negative result showing a gradient-per-cost selection rule is structurally inert on minimal-basis small molecules, with the analytic reason identified; noise-realized operator selection, which scores candidates by their measured energy contribution under the noise channel and shows a small free-running accuracy gain that a matched operator-count control attributes mainly to circuit length rather than operator choice; and a self-tuning cost-penalty controller that tracks the noise regime but is not exercised by the test systems. All comparisons are made on a Qiskit-PennyLane noise footing verified equivalent to 10^-15 on a probe observable, so the selection rule is the only independent variable.

---

## II. Methodology

### A. Molecular systems and reference energies

Two systems are benchmarked in the STO-3G basis. H2 at d = 0.735 A is treated in the full space, 4 spin-orbitals and 4 qubits. LiH is stretched to d = 3.0 A and reduced to a (2 electron, 3 orbital) active space with a frozen core, 6 qubits. The stretched geometry is deliberate. At equilibrium, LiH's STO-3G correlation energy in a contiguous (2e,3o) active space is only about 1 mHa, below chemical accuracy, so every ansatz would sit on top of Hartree-Fock and noise would dominate. Stretching to 3.0 A restores 16.3 mHa of active-space correlation, comparable to H2's 20.3 mHa, keeps the simulation at 6 qubits, and gives a more multireference state.

All molecular integrals come from PennyLane's differentiable Hartree-Fock (dhf) backend, a pure-Python implementation. PySCF is not used, as it has no Windows build. The Qiskit-side Hamiltonian is constructed from the same integrals through ElectronicEnergy.from_raw_integrals. Because both frameworks are built from the same integrals, agreement is exact rather than approximate, and any disagreement is a convention bug rather than numerical noise. Validation confirms this: the dhf integrals reproduce published full-space FCI to 0.036 mHa for H2 and 0.041 mHa for LiH; the Qiskit and PennyLane Hamiltonians share a spectrum to within 5e-14 Ha; and Hartree-Fock lies above FCI in every case. Energy error is measured against the FCI energy of the active-space qubit Hamiltonian, not the full-space FCI, so the constant active-space truncation error does not swamp the ansatz comparison.

### B. Operator pool

The pool is the qubit-ADAPT pool [6]. Each fermionic single and double excitation generator is Jordan-Wigner mapped and expanded into its Pauli-string rotations. The JW Z-strings are kept, so a Pauli word's weight, and its CNOT cost 2(w-1), grows with the orbital-index span of the excitation it comes from. This gives a real spectrum of operator costs: {4, 6} CNOTs for the 12-operator H2 pool, and {4, 6, 8, 10} for the 40-operator LiH pool. Without this spread, any rule of the form gradient over (1 + lambda times cost) is a monotone rescaling of the gradient and can never change the arg-max.

### C. Noise model on an equivalent footing

Feeding a device NoiseModel into Qiskit while running PennyLane on default.mixed does not give a comparable footing. The two use different native gate sets, Qiskit inserts routing SWAPs while PennyLane assumes all-to-all connectivity, and readout error does not transfer across the conversion. Instead we use a framework-independent noise specification: single- and two-qubit depolarizing channels with rates read from the real calibration data of the IBM FakeManilaV2 fake backend, with measured medians p1 = 3.54e-4 and p2 = 1.01e-2. The PennyLane channels are built from Pauli-mixture Kraus operators that reproduce Qiskit-Aer's depolarizing convention exactly. A self-test builds one fixed RY/RZ/RX and CNOT circuit in both frameworks, applies each side's channels, and compares a three-qubit Z observable. Agreement is within 6.7e-16 across noise scales 0x, 1x, 4x and 20x, with a probe-observable spread of 0.42 confirming the test is not vacuous. Noise is applied after decomposition to the canonical gate set {RX, RY, RZ, H, CNOT}, and a run-time guard checks that the noisy energy differs from the noiseless one, which guards against a silent no-op. The noise axis is swept at scales {0, 0.25, 0.50, 1.0} times the device rate. Beyond about 1x no method recovers correlation energy [20].

### D. Selection rules

Four PennyLane selection rules share one ADAPT driver. Only the scoring line differs.

standard uses score(op) = the gradient magnitude, the textbook ADAPT criterion [5].

resource_aware uses score(op) = gradient magnitude over (1 + lambda times added CNOT count), with lambda >= 0. Setting lambda = 0 must recover standard exactly.

noise_realized, the proposed rule, gradient-screens the pool to the top n_candidates (4). For each shortlisted operator it appends the operator, re-optimizes the full parameter vector with the noise channel applied, and records the energy reached. It then scores by max(0, E_before minus E_after) over (1 + lambda times added CNOT count), the realized improvement per unit of added cost. The winning candidate's re-optimized parameters are carried forward, so no optimization work is wasted.

noise_realized with adaptive_lambda, also proposed, makes lambda a controller state rather than a hyperparameter. After each accepted operator with realized improvement dE, lambda is multiplied by (dE_target over dE) raised to the 0.3 power and clipped to [0, 8], with dE_target = 1e-3 Ha. When operators stop paying off, lambda climbs and the rule leans toward cheap operators; while they still deliver, lambda relaxes.

### E. Optimizer and stopping

Parameter re-optimization uses gradient-free COBYLA, the same optimizer as the Qiskit baselines, so any difference is due to the selection rule and not the optimizer. The candidate-selection gradient is a central difference on the trailing parameter at theta = 0, checked against PennyLane's exact parameter-shift rule to about 1e-8 with noise channels present. Back-propagation on default.mixed returns NaN in this software stack and is not used. Two stopping criteria apply to all rules alike: the gradient norm falling below 1e-3, and an energy-plateau rule that rolls back an operator failing to lower the best energy by at least 1e-5 Ha, after a patience of two consecutive failures. The plateau rule is what actually terminates the loop under noise, because the candidate-gradient estimate is floored near p2 and the norm criterion never fires. For the matched-operator-count control of Section IV-C, a `fixed_k` mode disables both criteria and forces exactly k operators, accepting the top-scored candidate at every step regardless of whether it lowers the energy.

### F. Baselines

Three Option-B baselines run in Qiskit for context: fixed UCCSD, hardware-efficient ansatz EfficientSU2 with two repetitions, and Qiskit's native AdaptVQE over a UCCSD-derived pool. All 2 molecules by 4 noise scales by 7 strategies, 56 runs, are executed. The PennyLane rules are scoped to at most 8 operators and 100 COBYLA iterations per step to bound wall time.

---

## III. Proof of concept / implementation

### A. Software architecture

The pipeline is six Python modules with a strict dependency order. molecules.py is the shared ground truth: it builds the dhf Hamiltonian, derives the Qiskit operator from the same integrals, and exposes validate(). noise_models.py defines the framework-independent NoiseSpec, the calibrated make_noise_levels(), the exact Kraus operators, and the cross-framework selftest(). qiskit_baselines.py implements UCCSD, HEA and Qiskit AdaptVQE against a canonical basis and the shared noise model. pennylane_resource_aware_adapt.py holds the pool builder, the shared _adapt_loop with all four selection rules, and a selftest() covering pool-cost spread, noise application, gradient-method agreement, noiseless convergence to FCI, selection divergence at lambda = 1, and lambda = 0 equal to standard. run_experiments.py drives the sweep and writes one CSV row per run as it completes, so an interrupted multi-hour sweep leaves usable partial data. analyze_results.py produces the comparison tables and the two figures. A Jupyter and Colab notebook reproduces sections 1 to 5 live and loads the pre-computed sweep for section 6.

### B. The vacuous-selection diagnostic

Before any noise sweep, a diagnostic evaluates every pool operator's gradient at the Hartree-Fock reference and reports which operator standard and resource_aware at lambda = 1 each select. For both molecules the two rules select the same operator, for a structural reason. Single excitations have exactly zero gradient at Hartree-Fock by Brillouin's theorem, so the first operator is always a double. With the qubit-ADAPT pool, the double-excitation Pauli strings that carry a non-zero HF gradient, 8 of 12 for H2 and 8 of 40 for LiH, all have Pauli weight 4 and cost 6 CNOTs. With the numerator varying but the denominator constant across the selectable operators, the score is a monotone rescaling of the gradient, and the arg-max does not change for any lambda. The two rules do diverge if the ansatz grows deep enough. For noiseless LiH they first differ at operator 6, where resource_aware substitutes two cost-4 singles for two cost-6 doubles. Under noise the energy-plateau rule stops the ansatz at 1 or 2 operators, before the divergence point. This is verified: resource_aware and standard produce identical operator sequences at every non-zero noise level, and resource_aware at lambda = 0 reproduces standard with an energy difference of 0.

### C. Implementing noise-realized selection

noise_realized reuses the driver's trial-and-optimize machinery. At each step it forms the gradient-screened shortlist and calls the same trial-optimization routine used for the single greedy pick once per shortlisted candidate, each warm-started from the current parameters plus a zero, then selects by realized improvement per cost. The measured overhead on 6-qubit noisy LiH is about 2 to 2.5 times the wall time of gradient selection, not 4 times, because the warm-started re-optimizations converge quickly and the loop stops in fewer total steps. adaptive_lambda adds a three-line multiplicative controller after each accepted operator and logs the lambda trajectory in the lambda_init and lambda_final CSV columns. Both rules leave the standard and resource_aware code paths, and the lambda = 0 equivalence, untouched.

---

## IV. Result analysis and comparative analysis

### A. The resource-aware rule is a null result

Table I gives the PennyLane energy errors. The difference between resource_aware at lambda = 1 and standard is 0.000 mHa at every noise scale above zero, for both molecules. The only non-zero entry is noiseless LiH, where resource_aware builds a 34-CNOT circuit instead of 36 and lands 0.002 mHa lower, doing what it is designed to do but only where the saved gates cannot matter. The operator sequences confirm identical selection under noise. This is a clean negative result with an analytic cause, given in Section III-B: on minimal-basis small molecules the gradient-carrying operators are equal cost, so a cost denominator cannot re-rank them, and where the rule would act, noise has already truncated the ansatz.

**TABLE I. Energy error (mHa) vs FCI, PennyLane selection rules.** (scale = multiple of FakeManilaV2 gate error)

| System | scale | standard | resource-aware | noise-realized | NR + adaptive-lambda |
|---|---|---|---|---|---|
| H2 | 0.00 | 0.000 | 0.000 | 0.000 | 0.000 |
| H2 | 0.25 | 15.262 | 15.262 | 13.831 | 13.831 |
| H2 | 0.50 | 20.410 | 20.410 | 20.410 | 20.410 |
| H2 | 1.00 | 20.513 | 20.513 | 20.513 | 20.513 |
| LiH | 0.00 | 0.010 | 0.008 | 0.101 | 0.101 |
| LiH | 0.25 | 5.695 | 5.695 | 5.237 | 5.237 |
| LiH | 0.50 | 10.191 | 10.191 | 9.294 | 9.294 |
| LiH | 1.00 | 16.280 | 16.280 | 16.280 | 16.280 |

### B. Noise-realized selection: a small free-running gain

In the free-running sweep, where each rule stops on its own energy-plateau criterion, noise_realized is more accurate than both standard and resource_aware at every intermediate noise level where the ansatz grows past one operator: H2 at 0.25x (13.83 vs 15.26 mHa, a 1.43 mHa gain), LiH at 0.25x (0.46 mHa), and LiH at 0.50x (0.90 mHa). At these points Table II shows the same CNOT count and operator count as standard, so the ansatz noise_realized builds is nominally the same size. The operator sequences differ: at LiH 0.25x and 0.50x, standard selects the Pauli words D:YYYX@0123 then S:YZX@123, while noise_realized selects D:YXYY@0123 then S:XZY@123 -- the same excitation classes and the same 6 plus 4 CNOT cost, but different specific Pauli strings. The bare gradient cannot separate strings within an excitation class; a realized-energy measurement can. Whether this different choice is actually the better one, rather than an artifact of where each rule's stopping criterion halts, is tested in Section IV-C.

**TABLE II. CNOT count of the constructed LiH ansatz (free-running).**

| scale | standard | resource-aware | noise-realized |
|---|---|---|---|
| 0.00 | 36 | 34 | 26 |
| 0.25 | 10 | 10 | 10 |
| 0.50 | 10 | 10 | 10 |
| 1.00 | 6 | 6 | 6 |

In the noiseless limit noise_realized reaches 0.101 mHa on LiH, an order of magnitude inside chemical accuracy (1.6 mHa), using 26 CNOTs and 5 operators against 36 CNOTs and 7 operators for gradient selection. Selecting on realized dE stops operator growth once operators stop paying, without the energy-plateau rule doing the work; this leaner-circuit-at-accuracy result is not affected by the control below.

At the 1.0x device rate every rule collapses to the same single-operator circuit (LiH 16.28 mHa; H2 returns Hartree-Fock at 20.5 mHa), consistent with the gate-error threshold of [20] and the depth and CNOT analysis of [10].

Figure 1 (energy_error_vs_noise.png): energy error vs noise scale, one panel per molecule, all seven strategies.

### C. Matched operator count: the fixed-cost gain is not robust

The free-running comparison in Section IV-B confounds two effects. The energy-plateau stop halts each rule at a different operator count under noise, so part of the noise_realized advantage could be that its realized-dE score simply builds a different-length circuit, not that it chooses better operators. To separate them, the ADAPT driver was given a `fixed_k` mode that disables both stopping criteria and forces exactly k operators, accepting the top-scored candidate at every step whether or not it lowers the energy. All four rules were run at k = 6 on LiH(2e,3o), lambda_init = 1, 100 COBYLA iterations per step, noise scales {0, 0.05x, 0.1x, 0.2x}.

**TABLE III. Matched operator count (k = 6), LiH(2e,3o): energy error (mHa) and delta vs standard.**

| scale | standard | resource-aware | noise-realized | NR + adaptive-lambda | delta (NR - std) | CNOT std / NR |
|---|---|---|---|---|---|---|
| 0.00  | 0.022  | 0.022  | 0.033  | 0.033  | +0.011 | 30 / 32 |
| 0.05x | 3.946  | 3.946  | 3.980  | 3.980  | +0.034 | 32 / 32 |
| 0.10x | 7.788  | 7.788  | 7.554  | 7.554  | -0.235 | 32 / 32 |
| 0.20x | 15.302 | 15.302 | 16.190 | 16.190 | +0.888 | 32 / 34 |

At matched k the rules do choose different operators -- noise_realized selects a different Pauli-string sequence from standard at every scale, so the failure mode of an identical-selection collapse did not occur. But the accuracy difference is inconsistent in sign and small: noise_realized is better at one scale (0.1x, by 0.24 mHa) and worse at the other three (by up to 0.89 mHa), with resource_aware again identical to standard everywhere. The 0.25x and 0.50x advantages of Section IV-B were measured at k = 1 to 2, where the plateau stop truncated the ansatz; forced out to k = 6 at milder noise the effect neither reproduces nor grows. The conclusion is that on LiH(2e,3o) the free-running gain of noise_realized is mainly a circuit-length effect of the stopping rule, and a genuine operator-choice advantage, if one exists, is below what this system can resolve. Data: `results/results_fixed_k.csv`; script: `fixed_k_experiment.py`.

### D. The self-tuning lambda controller

adaptive_lambda produced the same operator choices and energies as fixed-lambda noise_realized in every cell of Tables I and III. The reason is the pool limitation from Section III-B: the productive operators are all cost-6 doubles or cost-4 singles with no cheaper alternative carrying signal, so moving lambda never changes the arg-max. The controller still behaves as designed. In the free-running sweep on LiH, lambda_final is 0.91 noiseless, 0.37 at 0.25x, 0.49 at 0.50x, and 2.53 at 1.0x; in the matched-k runs it climbs to the 8.0 ceiling at 0.05x and 0.2x as the forced non-improving operators drive the cost penalty up. Demonstrating an effect on selection needs a system whose pool contains cheap and useful operators, for example a (2e,5o) active space.

### E. Comparative analysis against Option-B baselines

Table IV places the PennyLane rules against the Qiskit baselines on LiH; this is the study's clearest result. The qubit-ADAPT pool, shared by all four PennyLane rules, is far more noise-tolerant than the deep UCCSD-derived circuits. At the 1.0x device rate the PennyLane rules hold 16.3 mHa while fixed UCCSD (272 CNOTs) and Qiskit AdaptVQE (252 CNOTs after growth) exceed 340 mHa -- worse than doing nothing. Qiskit's ADAPT is worse than fixed UCCSD under noise because transpilation to a device coupling map inflates a 6-qubit circuit to 250 to 390 CNOTs; the algorithm is the same, the routing is what breaks it. This agrees with [10]: depolarizing error scales with two-qubit-gate count, not depth. The hardware-efficient ansatz (10 CNOTs) is the fair nearest baseline, and the qubit-ADAPT circuits match or beat it (LiH 1.0x: 16.3 vs 28.5 mHa) at comparable depth. On top of this pool advantage, noise-realized selection adds at best a further 0.5 to 1.4 mHa over standard,PL in the free-running sweep, which Section IV-C shows is not a robust operator-choice effect; the pool-and-depth advantage is the part that holds.

**TABLE IV. LiH energy error (mHa), all strategies (free-running).**

| scale | UCCSD | HEA | ADAPT (Qiskit) | standard,PL | resource-aware | noise-realized |
|---|---|---|---|---|---|---|
| 0.00 | 0.000 | 14.17 | 0.000 | 0.010 | 0.008 | 0.101 |
| 0.25 | 124.7 | 16.88 | 171.3 | 5.695 | 5.695 | 5.237 |
| 0.50 | 219.1 | 24.35 | 237.3 | 10.191 | 10.191 | 9.294 |
| 1.00 | 347.5 | 28.49 | 344.0 | 16.280 | 16.280 | 16.280 |

Figure 2 (circuit_depth.png): transpiled depth and CNOT count per strategy. UCCSD and Qiskit ADAPT are 100 to 270 CNOTs, the PennyLane qubit-ADAPT circuits 6 to 36.

### F. Limitations

The proposed selection rules are not shown to work. The noise-realized free-running gain is small (0.5 to 1.4 mHa), confined to 0.25x and 0.50x noise, and is attributed by the matched-count control (Section IV-C) mainly to circuit length rather than operator choice. H2 and LiH(2e,3o) are too small to separate the proposals: the noisy ansatz is 1 to 6 operators deep, the self-tuning controller never changes a selection, and its benefit is untested. Expectation values are exact, with no shot noise; finite sampling would add variance to the realized-dE score. At and above 1.0x device noise nothing works, for any method. The PennyLane sweep is scoped (at most 8 operators, 100 COBYLA iterations per step) for wall-time reasons; qualitative findings were reproduced at the module default of 16 operators. Only one molecule pair, one basis, one geometry, and one noise family (depolarizing) are tested. The one result that is solid is the pool-and-depth advantage of qubit-ADAPT over the fixed and routed baselines, which reproduces a known effect on a controlled footing.

### G. What a fair test needs

A conclusive test of both proposals is LiH(2e,5o), 10 qubits, at noise scales {0, 0.05, 0.1, 0.2}, at least 16 operators, with a finite-shot run (about 1e4 shots) at the best noise level, and repeated across bond distances. That regime has a deep enough noisy ansatz for operator choice past step 5 to still matter, a pool with a real cost-versus-gradient spread among gradient-competitive operators, and mild enough noise that added operators still help. It is roughly 30 to 50 times the compute of this study and was out of scope for the timeline.

### H. Conclusion

The clear result of this study is comparative: the compact all-to-all qubit-ADAPT ansatz is 10 to 20 times more accurate than fixed UCCSD, the hardware-efficient ansatz, and Qiskit's routed ADAPT on stretched LiH at every noise level, at a fraction of the two-qubit-gate count, which confirms on a controlled cross-framework footing that for depolarizing noise the CNOT count sets the error. Against this baseline, a cost-penalized ADAPT selection rule, gradient over (1 + lambda times cost), is structurally inert on minimal-basis H2 and LiH, for an analytic reason. A noise-realized rule that scores operators by the energy they achieve under the noise channel gives a small free-running accuracy gain over gradient ADAPT, but a matched operator-count control shows the gain is inconsistent in sign once circuit length is held fixed, so it is not established as a better operator choice on these systems; its one robust effect is a leaner circuit at chemical accuracy in the noiseless limit. A self-tuning cost-penalty controller tracks the noise regime correctly but is not exercised by the test systems. All comparisons use a cross-framework noise footing verified equivalent to 1e-15 on a probe observable. A conclusive test of the selection rules needs the larger active space of Section IV-G.

---

## V. References

[1] A. Peruzzo et al., "A variational eigenvalue solver on a photonic quantum processor," Nat. Commun., vol. 5, art. 4213, 2014.

[2] M. Cerezo et al., "Variational quantum algorithms," Nat. Rev. Phys., vol. 3, no. 9, pp. 625-644, 2021.

[3] J. Tilly et al., "The Variational Quantum Eigensolver: a review of methods and best practices," Phys. Rep., vol. 986, pp. 1-128, 2022.

[4] A. Kandala et al., "Hardware-efficient variational quantum eigensolver for small molecules and quantum magnets," Nature, vol. 549, pp. 242-246, 2017.

[5] H. R. Grimsley, S. E. Economou, E. Barnes, and N. J. Mayhall, "An adaptive variational algorithm for exact molecular simulations on a quantum computer," Nat. Commun., vol. 10, art. 3007, 2019.

[6] H. L. Tang et al., "Qubit-ADAPT-VQE: An adaptive algorithm for constructing hardware-efficient ansatze on a quantum processor," PRX Quantum, vol. 2, no. 2, art. 020310, 2021.

[7] Y. S. Yordanov, V. Armaos, C. H. W. Barnes, and D. R. M. Arvidsson-Shukur, "Qubit-excitation-based adaptive variational quantum eigensolver," Commun. Phys., vol. 4, art. 228, 2021.

[8] D. Claudino, J. Wright, A. J. McCaskey, and T. S. Humble, "Benchmarking adaptive variational quantum eigensolvers," Front. Chem., vol. 8, art. 606863, 2020.

[9] P. G. Anastasiou, Y. Chen, N. J. Mayhall, E. Barnes, and S. E. Economou, "TETRIS-ADAPT-VQE: An adaptive algorithm that yields shallower, denser circuit ansatze," Phys. Rev. Research, vol. 6, no. 1, art. 013254, 2024.

[10] C. K. Long, K. Dalton, C. H. W. Barnes, D. R. M. Arvidsson-Shukur, and N. Mertig, "Layering and subpool exploration for adaptive variational quantum eigensolvers: Reducing circuit depth, runtime, and susceptibility to noise," Phys. Rev. A, vol. 109, no. 4, art. 042413, 2024.

[11] M. Ramoa, L. P. Santos, N. J. Mayhall, E. Barnes, and S. E. Economou, "Reducing the resources required by ADAPT-VQE using coupled exchange operators and improved subroutines," arXiv:2407.08696, 2024.

[12] V. O. Shkolnikov, N. J. Mayhall, S. E. Economou, and E. Barnes, "Avoiding symmetry roadblocks and minimizing the measurement overhead of adaptive variational quantum eigensolvers," Quantum, vol. 7, art. 1040, 2023.

[13] C. Feniou, M. Hassan, D. Traore, E. Giner, Y. Maday, and J.-P. Piquemal, "Overlap-ADAPT-VQE: practical quantum chemistry on quantum computers via overlap-guided compact ansatze," Commun. Phys., vol. 6, art. 192, 2023.

[14] M. Ostaszewski, E. Grant, and M. Benedetti, "Structure optimization for parameterized quantum circuits," Quantum, vol. 5, art. 391, 2021.

[15] E. Rossi, E. R. Kjellgren, A. F. Izmaylov, S. P. A. Sauer, E. Ziems, and S. Coriani, "Resource-efficient energy-based operator selection for adaptive quantum eigensolvers," arXiv:2606.04786, 2026.

[16] A. Nykanen, W. Mihalikova, M. Rossmannek, I. Tavernelli, and D. Mendive-Tapia, "Mitigating the measurement overhead of ADAPT-VQE with optimised informationally complete generalised measurements," Phys. Rev. A, 2025.

[17] "Hamiltonian-Aware ADAPT-VQE: a non-local operator-selection criterion with redundant-operator pruning," arXiv:2606.13118, 2026.

[18] J. R. McClean, S. Boixo, V. N. Smelyanskiy, R. Babbush, and H. Neven, "Barren plateaus in quantum neural network training landscapes," Nat. Commun., vol. 9, art. 4812, 2018.

[19] S. Wang et al., "Noise-induced barren plateaus in variational quantum algorithms," Nat. Commun., vol. 12, art. 6961, 2021.

[20] Y. S. Yordanov, C. H. W. Barnes, and D. R. M. Arvidsson-Shukur, "Quantifying the effect of gate errors on variational quantum eigensolvers for quantum chemistry," npj Quantum Inf., vol. 10, art. 43, 2024.

[21] V. Bergholm et al., "PennyLane: Automatic differentiation of hybrid quantum-classical computations," arXiv:1811.04968, 2022.

[22] Qiskit contributors, "Qiskit: An Open-source Framework for Quantum Computing," 2024. Available: https://www.qiskit.org

---

*Verify the arXiv identifiers, volume and article numbers, and author lists for [11], [15], [16], and [17] against the published versions before submission; [15] and [17] are 2026 preprints and their metadata may have changed.*
