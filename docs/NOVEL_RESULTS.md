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

## Free-running result (LiH(2e,3o)): noise-realized ahead at equal circuit cost

> **Superseded in part.** This is the free-running result on the 6-qubit system.
> The matched-operator-count control below shows the gap is largely a stopping-rule
> (circuit-length) effect, and the 10-qubit fair test at the end finds a
> marginal, not reliably signed, edge. Read it as the observation that motivated
> those controls, not as an established advantage.

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

---

## Fixed operator count (matched-k control)

The 0.5-1.4 mHa advantage above is confounded: the energy-plateau stop
terminates each rule at a different operator count, so part of the gap could be
"noise-realized built a different-length circuit" rather than "noise-realized
picked a better operator". To separate the two, `_adapt_loop` gained a
`fixed_k` parameter -- both stopping criteria disabled, exactly `k` operators
built, the top-scored candidate accepted at every step whether or not it lowers
the energy. `fixed_k_experiment.py` runs all four rules at `k = 6` on
LiH(2e,3o) (stretched 3.0 A), `lam_init = 1`, `opt_maxiter = 100`,
`n_candidates = 4`, noise scales `{0, 0.05x, 0.1x, 0.2x}` FakeManilaV2. Data:
`results/results_fixed_k.csv`.

**Energy error vs active-space FCI (mHa), k = 6 forced:**

| noise | standard | resource-aware | noise-realized | NR+adaptive-lam | delta (NR - std) | CNOT std / NR |
|---|---|---|---|---|---|---|
| 0.00  | 0.022  | 0.022  | 0.033  | 0.033  | **+0.011** | 30 / 32 |
| 0.05x | 3.946  | 3.946  | 3.980  | 3.980  | **+0.034** | 32 / 32 |
| 0.10x | 7.788  | 7.788  | 7.554  | 7.554  | **-0.235** | 32 / 32 |
| 0.20x | 15.302 | 15.302 | 16.190 | 16.190 | **+0.888** | 32 / 34 |

### Findings

1. **The guardrail did not trip.** At matched k the rules *do* choose
   different operators -- `noise_realized` selects a genuinely different
   Pauli-string sequence from `standard` at every noise scale (e.g. 0.1x:
   standard opens `D:YYYX@0123 S:YZX@123`, noise-realized opens
   `D:YXYY@0123 S:XZY@123`). `resource_aware` is byte-identical to `standard`
   everywhere, as always. So k=6 on LiH(2e,3o) *can* separate the rules by
   operator choice -- it just does not separate them by accuracy.

2. **At matched k, `noise_realized` does not consistently beat `standard`.**
   One scale better (0.1x, -0.24 mHa), three scales worse (+0.01, +0.03,
   +0.89 mHa), none by more than ~0.9 mHa. The sign is inconsistent and the
   magnitude is at or below the noise floor of the comparison.

3. **The margin does not widen at mild noise.** The earlier -0.46 / -0.90 mHa
   at 0.25x / 0.50x were measured at k = 1-2 (the plateau stop truncated the
   ansatz there). Forced out to k = 6 at *milder* noise, the one favourable
   point (0.1x) is *smaller* (-0.24 mHa), and 0.05x is a slight loss. The
   "deep ansatz + mild noise" regime does not help noise-realized here.

4. **Conclusion: the previously reported advantage is largely a
   circuit-length effect, not a better-choice-at-equal-cost effect.** In the
   free-running sweep `noise_realized`'s realised-`dE` score stopped it at a
   leaner circuit (26 vs 36 CNOT noiseless) and the plateau stop cut
   `standard` short under noise; the accuracy gap rode on that length
   difference. When every rule is pinned to the same k and the same ~32-CNOT
   budget, the pure operator-choice contribution of noise-realized on
   LiH(2e,3o) is ~0 and not reliably signed. This does not refute the rule --
   it means **LiH(2e,3o) is too small to demonstrate it**, the same
   conclusion the free-running data reached from the other direction. The
   10-qubit test (below) was run to settle it; it finds the same marginal,
   not reliably signed edge.

5. **`adaptive_lambda` again reproduces fixed-`lambda` exactly** at every
   scale. `lambda_final` climbs to the 8.0 ceiling at 0.05x and 0.2x (six
   forced operators, most not helping -> controller pushes the cost penalty
   up), but with no cheaper gradient-competitive operator in the minimal-basis
   pool the argmax never moves. Same structural limitation documented above.

6. **Forcing operators past convergence costs accuracy under noise**, as
   expected: standard at k=6 noiseless is 0.022 mHa (vs 0.006-0.010 mHa when
   the plateau stop is allowed to roll back the last non-improving picks).
   The fixed-k circuits are a control, not a recommended configuration.

## The fair test: LiH(2e,5o), 10 qubits (GPU)

This was the experiment the previous sections left as future work. It was made
tractable by a CUDA density-matrix simulator, [`gpu_backend.py`](../gpu_backend.py),
enabled with `ADAPT_BACKEND=gpu`. It reproduces `default.mixed` to ~1e-14 (same
PennyLane gate decomposition, same Qiskit-convention depolarizing channels, same
noisy HF preparation) and evaluates a 10-qubit energy in ~0.02-0.04 s versus
50-140 s on the CPU path (~4000x). Setup: LiH stretched to 3.0 A, (2e,5o),
144-operator qubit-ADAPT pool, noise scales `{0, 0.05, 0.1, 0.2}` x FakeManilaV2
median gate errors, `opt_maxiter = 200`, exact expectations (no shot noise).
Driver: [`fair_test_10q.py`](../fair_test_10q.py); raw data in
`results/results_10q*.csv`. All runs are deterministic (single run per cell).

### Free-running (both stopping rules on, up to 16 operators)

Energy error vs active-space FCI in mHa, (CNOT count):

| noise | standard | resource-aware | noise-realized (4 cand.) | noise-realized (8 cand.) |
|---|---|---|---|---|
| 0 | 0.147 (128) | 0.138 (118) | 0.040 (130) | 0.042 (130) |
| 0.05 | 13.50 (52) | 14.05 (58) | 13.13 (52) | 13.12 (52) |
| 0.1 | 23.17 (48) | 24.74 (54) | 22.92 (48) | 22.87 (48) |
| 0.2 | 52.98 (20) | 43.58 (36) | 41.57 (44) | 41.48 (44) |

Adaptive lambda reproduced fixed lambda exactly (energy and operator sequence) in
all 24 cells, the same structural null as on 6 qubits.

### Matched operator count (`fixed_k`, both stopping rules off)

K = 4 (the length noise-realized reached at 0.2x), error in mHa:

| noise | standard | resource-aware | NR (4 cand.) | NR (8 cand.) |
|---|---|---|---|---|
| 0 | 5.52 | 24.55 | 5.52 | 5.52 |
| 0.05 | 14.98 | 30.14 | 14.63 | 14.60 |
| 0.1 | 23.90 | 35.71 | 23.68 | 23.61 |
| 0.2 | 42.26 | 46.52 | 41.87 | 41.48 |

K = 6, error in mHa (CNOT count):

| noise | standard | resource-aware | NR (4 cand.) | NR (8 cand.) |
|---|---|---|---|---|
| 0 | 2.95 (52) | 3.67 (54) | 2.95 (52) | 2.95 (52) |
| 0.05 | 13.50 (52) | 14.28 (54) | 13.13 (52) | 13.12 (52) |
| 0.1 | 29.71 (64) | 24.74 (54) | 30.01 (64) | 23.21 (52) |
| 0.2 | 55.98 (64) | 45.57 (54) | 55.59 (64) | 55.15 (64) |

### Findings

1. **The larger space does not rescue selection rules; circuit length dominates.**
   Even at 0.05x device noise no rule gets within 13 mHa of FCI, and runs stop at
   5-7 operators. Error grows steeply with noise scale and with operator count
   (standard at 0.2x: 42.3 mHa with 4 operators, 56.0 with 6).
2. **The free-running 11 mHa lead of noise-realized over standard at 0.2x is
   mostly the stopping rule.** Standard's plateau stop ended it at 2 operators and
   20 CNOTs. At matched K = 4 (44 CNOTs each) the gap is 0.8 mHa.
3. **Noise-realized is consistently but marginally ahead at K = 4** (0.2-0.8 mHa at
   every noisy scale), **and not reliably signed at K = 6** (NR-4 is +0.3 mHa worse
   than standard at 0.1x; NR-8 is 6.5 mHa better at 0.1x with 52 vs 64 CNOTs, but
   ties standard at 0.2x). Its edge depends on the candidate count and is not a
   stable ordering.
4. **Cost-aware selection helps only past the noise-optimal length.** At K = 6 and
   0.1x-0.2x, resource-aware is 5-10 mHa better than standard because it selects
   cheaper operators (54 vs 64 CNOTs). At K = 4 it is 4-25 mHa worse, since there
   is no excess depth to remove.
5. **Noiselessly** standard and noise-realized select the same operators at K = 4
   and every rule reaches chemical accuracy in the free-running case.

### What this does and does not support

Supported (in this simulation): gradient selection with a plateau stop is
competitive with the more expensive rule once circuit length is controlled, and
the cost penalty pays off only when the ansatz would otherwise grow past the
noise-optimal length. Not supported: that noise-realized selection is generally
better. Limits: one molecule and geometry, one deterministic run per cell (no
error bars, so differences of a few tenths of a mHa are not established), exact
expectations (no shot noise), depolarizing gate noise only (no readout, coherent,
or amplitude-damping errors).

### Next experiments

Literature review (2025-2026) points to finite-shot operator selection as the
largest open risk: distinguishing the top gradient needs ~1/||g||^2 shots and
gradient troughs cause false convergence (arXiv:2512.25004); noise, coherent and
incoherent, can prevent selection from converging and is mitigated by
dynamical decoupling + ZNE (arXiv:2609.17501); gradient-free energy-fit selection
(GGA-VQE, Feniou et al. 2025) is more shot-noise resilient. Planned, in order:

1. Finite-shot selection: per-term shot noise in the GPU simulator, sweep
   1e3-1e6 shots, report selection accuracy and stall rate, and compare rules at
   equal *total shots* (not equal iterations).
2. Realistic channels: amplitude damping, dephasing, coherent over-rotation,
   readout error; test TETRIS layering on the non-depolarizing channels.
3. Mitigation on the selection step: ZNE by gate folding and readout mitigation.
4. Statistics: bond-length sweep and other molecules, >= 5 repeats, paired
   comparisons with Wilson intervals (arXiv:2503.16589 for repeat counts).
5. Emulator (FakeBackend with routing and readout), then a small real-device run.

---

## Paragraph for the report

> We test two operator-selection rules for noisy ADAPT-VQE. The first,
> *noise-realized selection*, replaces the energy gradient with the energy an
> operator actually achieves when appended and re-optimised under the noise
> channel, penalised by its CNOT cost. On H2 and stretched LiH(2e,3o)
> (depolarising noise calibrated to FakeManilaV2) it is 0.5-1.4 mHa more accurate
> than gradient ADAPT in a free-running sweep, but a matched operator-count
> control shows the margin is inconsistent in sign once circuit length is fixed,
> so it is largely a stopping-rule effect; noiselessly it reaches chemical
> accuracy with 26 CNOTs where gradient ADAPT uses 36. The second rule makes the
> cost weight lambda a feedback controller; it tracks the noise regime correctly
> but never changes a selection, because the minimal-basis pools contain no
> cheap-yet-useful operator to switch to. A 10-qubit LiH(2e,5o) fair test, run on
> a CUDA density-matrix simulator that matches the CPU reference to 1e-14,
> confirms the picture: circuit length dominates (no rule is within 13 mHa of FCI
> at 0.05x device noise); noise-realized's 11 mHa free-running lead at 0.2x falls
> to 0.8 mHa at a matched four operators; at six operators cost-aware rules win by
> 5-10 mHa because they choose cheaper operators; and noise-realized is only
> marginally, and not reliably, ahead of gradient selection. Cost of
> noise-realized selection is ~2-2.5x gradient ADAPT. These are single
> deterministic runs on one molecule with exact expectations and depolarising
> noise only; finite-shot sampling and richer noise channels are the needed next
> tests.
