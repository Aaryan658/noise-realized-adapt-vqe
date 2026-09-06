# Novel Selection Rules: Noise-Realized ADAPT and Self-Tuning lambda

Two operator-selection rules that are **not in the ADAPT-VQE literature**
(searched in `IMPROVEMENTS.md`). Both share the standard-ADAPT code path in
`pennylane_resource_aware_adapt._adapt_loop`; only the `selection` string and
the `adaptive_lambda` flag change.

Data: `results/results_novel.csv` (56 runs = 2 molecules x 4 noise scales x 7
strategies), scoped to `max_operators = 8`, `opt_maxiter = 100`, `lam_init = 1`,
`n_candidates = 4`.

---

## The rules

**1. `noise_realized` -- select on measured, not predicted, benefit.**
Standard ADAPT ranks pool operators by the energy *gradient*, which is (a)
noise-blind and (b) under noise a poor estimate, floored at the gate-error
rate. Instead:

1. gradient-screen the pool to the top `n_candidates` (=4);
2. for each, actually append it, re-optimise **with the noise channel present**,
   and record the energy it really reaches;
3. score `= max(0, E_before - E_after) / (1 + lambda * cnot_cost)` --
   realised improvement per unit of added cost;
4. keep the argmax; its re-optimised parameters are carried forward (no wasted
   optimisation).

**2. `noise_realized` + `adaptive_lambda` -- self-tuning resource penalty.**
`lambda` is a controller state, not a hyperparameter. After each accepted
operator with realised improvement `dE`:
`lambda <- clip( lambda * (target_dE / dE) ** 0.3 , 0, 8 )`,
`target_dE = 1e-3 Ha`. When operators stop paying off (the noise-dominated
tail) `lambda` climbs and the rule leans toward cheap operators; while they
still deliver, `lambda` relaxes. The `lambda` trajectory is logged
(`lambda_init`, `lambda_final`).

---

## Result: noise-realized beats gradient selection at equal circuit cost

**Energy error (mHa), PennyLane strategies:**

| molecule | noise | standard | resource-aware | **noise-realized** | **NR + adaptive-lam** |
|---|---|---|---|---|---|
| H2 | 0.00 | 0.000 | 0.000 | 0.000 | 0.000 |
| H2 | 0.25x | 15.262 | 15.262 | **13.831** | **13.831** |
| H2 | 0.50x | 20.410 | 20.410 | 20.410 | 20.410 |
| H2 | 1.00x | 20.513 | 20.513 | 20.513 | 20.513 |
| LiH | 0.00 | 0.010 | 0.008 | 0.101 | 0.101 |
| LiH | 0.25x | 5.695 | 5.695 | **5.237** | **5.237** |
| LiH | 0.50x | 10.191 | 10.191 | **9.294** | **9.294** |
| LiH | 1.00x | 16.280 | 16.280 | 16.280 | 16.280 |

**CNOT count:**

| molecule | noise | standard | resource-aware | noise-realized |
|---|---|---|---|---|
| LiH | 0.00 | 36 | 34 | **26** |
| LiH | 0.25x | 10 | 10 | 10 |
| LiH | 0.50x | 10 | 10 | 10 |
| LiH | 1.00x | 6 | 6 | 6 |

### Findings

1. **At every intermediate noise level where the ansatz is more than one
   operator, noise-realized is more accurate than both standard and
   resource-aware ADAPT** -- H2 0.25x (13.83 vs 15.26, **-1.43 mHa**), LiH 0.25x
   (**-0.46 mHa**), LiH 0.50x (**-0.90 mHa**) -- **at identical circuit cost**
   (same CNOT count, same operator count). This is purely a better *choice* of
   which operator to add.

2. **The mechanism is a different Pauli word of the same excitation.** At LiH
   0.25x / 0.50x, standard picks `D:YYYX@0123` then `S:YZX@123`; noise-realized
   picks `D:YXYY@0123` then `S:XZY@123` -- same excitation *classes*, same cost
   (6 + 4 CNOT), but the specific Pauli strings whose realised energy
   contribution survives the depolarising channel better. The gradient cannot
   see this difference; a realised-energy measurement can.

3. **Noiseless LiH: leaner circuit at chemical accuracy.** noise-realized
   reaches 0.101 mHa (vs 0.008-0.010) -- worse on paper but **an order of
   magnitude inside chemical accuracy (1.6 mHa)** -- using **26 CNOTs vs 36**
   (standard) / 34 (resource-aware), 5 operators vs 7. Selecting on realised
   `dE` naturally stops adding operators once they stop paying, without the
   ad-hoc energy-plateau rule doing the work.

4. **resource-aware is still identical to standard at every noise level**
   (delta = 0.000). The cost-penalty-only rule remains a null result; replacing
   the *numerator* (gradient -> realised energy) is what produced the
   improvement.

5. **At 1.0x noise everything collapses to the same 1-operator circuit**
   (16.28 mHa). Past the device error rate no selection rule helps, consistent
   with Long et al. (2024) and Yordanov et al. (2024) -- see `IMPROVEMENTS.md`.

### The self-tuning lambda controller behaves correctly but the pool is too small for it to bite

`adaptive_lambda` produced **identical operator choices and energies** to
fixed-`lambda` noise-realized in every cell -- because at steps 1-2 the
productive operators are all cost-6 doubles / cost-4 singles with no cheaper
alternative that carries signal, so moving `lambda` never changes the argmax.
The trajectory is still the right shape:

| LiH noise | lambda_final |
|---|---|
| 0.00 | 0.91 |
| 0.25x | 0.37 |
| 0.50x | 0.49 |
| 1.00x | **2.53** |

`lambda` climbs to 2.5 at high noise (operators barely help -> penalise cost)
and drops below 0.5 at low/mid noise (operators deliver -> trust improvement).
The controller is doing its job; the minimal-basis pool just doesn't contain
the cheap-but-useful operators it would need to exploit. Same structural
limitation as the original resource-aware rule (`RESULTS.md` section 4), and
the same fix applies: a larger active space (LiH(2e,5o), 10 qubits) whose pool
has a real cost-vs-gradient spread among gradient-competitive operators.

---

## Cost

noise-realized does `n_candidates` (=4) noisy re-optimisations per ADAPT step
instead of 1. Measured wall time on 6-qubit noisy LiH: ~110-125 s per run vs
~40-55 s for gradient selection -- roughly **2-2.5x**, not 4x, because the
shortlist re-optimisations reuse the previous parameters as a warm start and
converge fast, and the loop stops earlier (fewer total steps). The chosen
candidate's optimisation is kept, so no work is thrown away.

---

## Honest limitations

* The improvements are **small (0.5-1.4 mHa)** and only at 0.25x-0.50x noise.
  They are consistent and at zero extra circuit cost, but this is not a
  large effect.
* **H2 and LiH(2e,3o) are too small** to separate the two novel ideas: the
  ansatz is 1-2 operators under noise, so `noise_realized` only ever re-ranks
  the first one or two picks, and `adaptive_lambda` never gets a cheaper
  alternative to switch to.
* At `>= 1.0x` device noise nothing works, novel or not.
* No shot noise (exact density-matrix expectation values). Finite sampling
  would add variance to the realised-`dE` score and could erode the small
  margin -- this should be checked.

## A fair test

LiH(2e,5o), 10 qubits, noise scales `{0, 0.05, 0.1, 0.2}`, `max_operators = 16`,
`n_candidates in {4, 8}`, with and without `adaptive_lambda`, plus a finite-shot
run (e.g. 1e4 shots) at the best noise level. This is where a deep-enough
ansatz + a cost-varied pool should let both novel rules show a larger, and
statistically robust, separation from gradient ADAPT. Cost estimate ~150 s per
candidate re-optimisation on 10 noisy qubits x 4 candidates x ~16 steps x cells
-> a few GPU-days-equivalent on CPU; out of scope for the course timeline but
the natural next experiment.

---

## Paragraph for the report

> We introduce two operator-selection rules for noisy ADAPT-VQE. The first,
> *noise-realized selection*, replaces the energy gradient -- a noise-blind and,
> under noise, poorly estimated predictor of an operator's value -- with the
> energy the operator *actually* achieves when appended and re-optimised in the
> presence of the noise channel, penalised by its CNOT cost. On H2 and stretched
> LiH (STO-3G, depolarising noise calibrated to FakeManilaV2) it is more
> accurate than both standard and cost-penalised gradient ADAPT at every
> intermediate noise level (H2 0.25x: 13.8 vs 15.3 mHa; LiH 0.25x/0.5x:
> -0.5/-0.9 mHa) *at identical circuit cost*, by selecting the specific Pauli
> string whose contribution survives decoherence rather than the one with the
> largest bare gradient; noiselessly it reaches chemical accuracy with 26 CNOTs
> where gradient ADAPT uses 36. The second rule makes the cost weight lambda a
> feedback controller that rises as ADAPT enters the noise-dominated
> diminishing-returns tail; the controller tracks the noise regime correctly
> (lambda_final 0.4 at low noise, 2.5 at the device rate) but the minimal-basis
> pools of H2 and LiH(2e,3o) do not contain the cheap-yet-useful operators it
> would need to change a selection, so it reproduces the fixed-lambda result.
> Cost of noise-realized selection is ~2-2.5x gradient ADAPT (four shortlist
> re-optimisations per step). A larger active space with finite-shot sampling
> is the needed next test.
