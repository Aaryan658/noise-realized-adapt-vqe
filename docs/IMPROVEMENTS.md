# Beyond the Resource-Aware Rule: Better Directions for Noise-Robust ADAPT-VQE

*Research report | Generated 2026-09-03 | 11 sources | Confidence: High for the
published methods, Medium for the "expected payoff on H2/LiH" estimates*

## Executive summary

The resource-aware score `|grad| / (1 + lambda * cnot_cost)` was a null result
(see `RESULTS.md`). The literature explains *why* and points to strictly better
levers:

1. **The gradient is the wrong quantity to score under noise.** Its estimate is
   floored at the gate-error rate, so ranking by it is close to random once
   noise is on. Every serious recent ADAPT variant that targets robustness
   either scores by **actual energy reduction (Rotoselect / energy-based
   selection)** or by an **overlap with a cheap classical target**, not by the
   bare gradient.
2. **Depth reduction does not help against depolarizing noise** -- which is the
   noise model in this project. Long, Dalton, Barnes, Arvidsson-Shukur & Mertig
   (*Phys. Rev. A* **109**, 042413, 2024) show local-depolarizing error is
   proportional to **CNOT count, not circuit depth**, so a shallower circuit
   with the same CNOT count is no more accurate. The resource-aware rule already
   penalizes CNOT count (correct target); the problem is it never gets to act.
3. **The regime is hopeless for any VQE.** Yordanov & Arvidsson-Shukur et al.
   (*npj Quantum Inf.* **10**, 2024) find VQEs need per-gate error
   `p ~ 1e-6 ... 1e-4` to hit chemical accuracy. This study's noise scales
   0.25x-1x correspond to `p2 ~ 2.5e-3 ... 1e-2` -- one to two orders of
   magnitude too noisy. Nothing recovers correlation energy there, which is
   exactly what the sweep showed.

The actionable conclusion: **change the operator-scoring quantity and/or the
pool, not the cost penalty**; and if a noise-robustness claim is wanted, test at
`p <= 1e-3` with amplitude-damping / dephasing channels added (where depth
*does* matter), not pure depolarizing at device rates.

---

## 1. Score by energy reduction, not gradient (Rotoselect / energy-based ADAPT)

**What it is.** Instead of `score(op) = |dE/dtheta|_0`, score each candidate by
the **minimum of its one-parameter energy landscape**
`min_theta <H>(..., theta_op)` -- the actual energy the operator can buy if
added and its parameter optimised. The landscape is a low-order trigonometric
polynomial, so 3-5 energy evaluations per candidate reconstruct it exactly
(the "Rotoselect" trick). The minimiser `theta*` is then a **warm start** for
the subsequent full re-optimisation.

**Why it beats resource-aware here.** The project's own diagnostic showed the
noisy gradient estimate is floored at ~1e-2 and cannot rank operators. An
energy score is a *difference of energies at the same noise level*, so the
common-mode noise bias largely cancels and the ranking survives. It also
removes the need for the ad-hoc energy-plateau stop -- the score *is* the
energy gain, so "stop when the best score is below tol" is principled.

**Cost.** ~3-5x the per-candidate cost of a gradient (was ~0.6 s -> ~2-3 s on
6-qubit noisy LiH). Rossi, Kjellgren, Izmaylov, Sauer, Ziems & Coriani
(arXiv:2606.04786, 2026) halve that via an exact Hamiltonian transformation,
bringing energy-based selection to gradient-based cost.

**Effort in this codebase:** low-moderate. `_candidate_gradient` already builds
the trailing-candidate QNode; replace the central difference with a 5-point
`theta` scan + parabola/trig fit, return `-min` as the score. ~30 lines.
`lambda = 0` equivalence is lost (different criterion), but you gain a
`selection in {gradient, energy}` axis to compare -- a cleaner contribution
than the cost penalty.

Sources: [Ostaszewski et al. Rotoselect, Quantum 5, 391 (2021)](https://quantum-journal.org/papers/q-2021-01-28-391/) ·
[Rossi et al. 2026, arXiv:2606.04786](https://doi.org/10.48550/arxiv.2606.04786) ·
[Nykanen et al. AIM-ADAPT-VQE, PRA 2025](https://link.aps.org/doi/10.1103/t1hr-y7c8)

---

## 2. Swap the pool: qubit-excitation-based ADAPT (QEB-ADAPT-VQE)

**What it is.** Yordanov, Armaos, Barnes & Arvidsson-Shukur
(*Commun. Phys.* **4**, 228, 2021) replace fermionic creation/annihilation
operators with **qubit-excitation operators** `Q_i = (X_i + iY_i)/2`. Their
evolutions act on a *fixed* number of qubits: **2 CNOTs for a single
excitation, 13 for a double**, independent of orbital-index span, and they
admit local circuit optimisations that Pauli-string (qubit-ADAPT) evolutions
do not. QEB-ADAPT also uses an **n-candidate selection**: take the top-`n`
operators by gradient, re-optimise each, keep the one with the largest actual
`Delta E`. For LiH/H6/BeH2, `n = 10` gives a further 15-25% CNOT reduction.

**Why it's better than resource-aware.** It attacks the quantity that actually
drives depolarizing error (total CNOT count) *structurally* -- a double
excitation is 13 CNOTs no matter where it sits -- rather than hoping a
selection tie-break finds a cheaper operator. And its n-candidate step is an
energy-based selection (see #1) in disguise. Trade-off: ~2x the variational
parameters of fermionic ADAPT.

**Effort:** moderate. Need the QEB single/double circuit templates (Yordanov
et al. 2020, arXiv:2011.10540, Figs. 1-2; PennyLane has
`qml.SingleExcitation` / `qml.DoubleExcitation` which are the Givens-rotation
qubit-excitation forms at 2 / ~13-16 CNOTs -- close enough for a course
project). Replace `build_pool` and `PoolOperator.make`. This is a
**published, citeable** contribution axis: "fermionic vs qubit vs QEB pool
under calibrated noise on H2/LiH".

Source: [Yordanov et al., Commun. Phys. 4, 228 (2021)](https://doi.org/10.1038/s42005-021-00730-0)

---

## 3. Layer the ansatz: TETRIS-ADAPT-VQE

**What it is.** Anastasiou, Chen, Mayhall, Barnes & Economou
(*Phys. Rev. Research* **6**, 013254, 2024) lift the one-operator-per-iteration
rule: add the largest-gradient operator, then also every next operator whose
support is **disjoint** from what's already been placed this iteration. Same
CNOT count and parameter count as ADAPT, **significantly shallower depth**,
and the pool gradient is measured a fraction as often.

**Why relevant / caveat.** Depth reduction is free here. BUT Long & Mertig et
al. (2024) show explicitly that **layering does not improve resilience to
depolarizing noise** (error ~ CNOT count, unchanged), only to
amplitude-damping and dephasing (error ~ depth, on idle + active qubits).
Since this project uses depolarizing channels, TETRIS alone would reproduce
the null result -- *unless* you also add amplitude-damping / dephasing
channels to `noise_models.py`, in which case it should show a genuine win.
That combination (TETRIS + AD/dephasing noise) is an honest, novel-ish
experiment.

**Effort:** low-moderate. Modify `_adapt_loop` step to keep adding
disjoint-support operators from the sorted gradient list until the qubits are
covered. `noise_models.py` already has a Kraus framework; adding
`amplitude_damping` / `phase_damping` Kraus sets is ~20 lines.

Sources: [Anastasiou et al., PRR 6, 013254 (2024)](https://doi.org/10.1103/PhysRevResearch.6.013254) ·
[Long et al., PRA 109, 042413 (2024)](https://doi.org/10.1103/physreva.109.042413)

---

## 4. Grow toward a cheap classical target: Overlap-ADAPT-VQE

**What it is.** Feniou, Hassan, Traore, Giner, Maday & Piquemal
(*Commun. Phys.* **6**, 192, 2023): instead of minimising energy (which walks
into local minima and energy plateaus -> overparameterised, deep circuits),
grow the ansatz to **maximise overlap with an intermediate target
wavefunction** that already has most of the correlation -- e.g. a small
selected-CI / CIPSI vector, or even CISD. Then polish with a short ADAPT run.
Reaches chemical accuracy with ~40 operators where standard ADAPT needs 150+
on stretched H6.

**Why it's better here.** The project's energy-plateau stop exists *only*
because energy-guided growth stalls under noise. If the growth target is a
known classical vector, there is no plateau to fall into and the stopping
criterion is "overlap high enough". For H2/LiH(2e,3o) the active-space FCI
vector is trivially available classically, so the overlap can be computed
**with no extra quantum cost**.

**Effort:** moderate-high. Need the target vector (you already diagonalise the
active-space Hamiltonian in `molecules.fci_energy` -- return the eigenvector
too) and an overlap-gradient selection. Strongest "compact ansatz" story, but
the most code.

Source: [Feniou et al., Commun. Phys. 6, 192 (2023)](https://doi.org/10.1038/s42005-023-01312-y)

---

## 5. Keep the cost penalty, but fix its three real problems

If the resource-aware idea must stay the headline, the literature says make
these changes -- each is a defensible refinement:

* **Weight by measured per-gate error, not a uniform `lambda`.** Long et al.
  show depolarizing error ~ sum of two-qubit gate error probabilities. So the
  principled denominator is `1 + sum_g p2_g` over the CNOTs the operator adds,
  using the *calibrated* `p2` already in `noise_models.py`, not an abstract
  `lambda * count`. This turns a hyperparameter into a hardware quantity.
* **Score numerator by energy, not gradient** (see #1) so the thing being
  divided is not noise-floored.
* **Give the rule room to act.** It only diverges from standard past operator
  ~5; the noisy ansatz never gets there. Either (a) fix the operator count `k`
  and compare `standard` vs `resource-aware` circuits at matched `k` (isolates
  "cheaper operators, same count"), or (b) move to an active space whose ADAPT
  ansatz stays deep under mild noise (LiH(2e,5o), 10q, `p <= 1e-3`).

Rossi et al. (2026) benchmark exactly the "matched `k`, last vs full
re-optimisation" design and find the re-optimisation strategy and orbital
optimisation matter *more* than the scoring rule for weakly correlated systems
-- a useful framing if the result stays null.

---

## 6. Hamiltonian-aware and measurement-reuse selection (context, lower priority)

* **Hamiltonian-Aware ADAPT** (arXiv:2606.13118, 2026): a selection criterion
  that folds in Hamiltonian matrix-element information (breaking the *local*
  commutator-gradient view), plus pruning of redundant/degraded operators.
  Reports smaller ansatze, no energy plateaus, lower measurement cost, "no
  extra classical or quantum overhead". Newest idea in this space; worth citing
  as future work.
* **AIM-ADAPT-VQE** (*Phys. Rev. A*, 2025): reuse informationally-complete
  measurement data taken for the energy to estimate *all* pool gradients for
  free -- removes the `O(|pool|)` measurement overhead of the selection step.
  Orthogonal to the scoring question; relevant if measurement cost is a
  reported metric.

---

## Key takeaways

1. **Best single change for this project:** replace the gradient score with an
   **energy-reduction (Rotoselect) score** (#1). Low effort, directly fixes the
   "noise-floored numerator" failure, removes the need for the ad-hoc stop, and
   gives a clean `gradient vs energy selection` comparison axis.
2. **Best structural change:** move to the **QEB pool** (#2) -- fixed-cost
   excitations attack CNOT count (the quantity that matters for depolarizing
   noise) by construction, and it is a published, benchmarked method.
3. **If a depth/noise claim is wanted:** add **amplitude-damping + dephasing**
   channels and test **TETRIS layering** (#3); depth reduction provably helps
   there but not against the pure depolarizing model currently used.
4. **Fix the test, not just the method:** run at `p <= 1e-3` and/or fixed
   operator count `k`; at the current 0.25x-1x device rates no VQE of any kind
   reaches chemical accuracy, so no selection rule can be distinguished.
5. **The resource-aware functional form is not wrong** -- penalising CNOT count
   is the right target for depolarizing noise -- it just needs an energy-based
   numerator, hardware-calibrated weights, and a regime where ADAPT builds a
   deep enough ansatz for selection to matter.

---

## Sources

1. [Long, Dalton, Barnes, Arvidsson-Shukur, Mertig — Layering and subpool exploration for adaptive VQE, *Phys. Rev. A* 109, 042413 (2024)](https://doi.org/10.1103/physreva.109.042413) — depolarizing error ~ CNOT count not depth; layering helps AD/dephasing only.
2. [Yordanov, Armaos, Barnes, Arvidsson-Shukur — Qubit-excitation-based ADAPT-VQE, *Commun. Phys.* 4, 228 (2021)](https://doi.org/10.1038/s42005-021-00730-0) — fixed 2/13-CNOT excitations; n-candidate energy-reduction selection.
3. [Anastasiou, Chen, Mayhall, Barnes, Economou — TETRIS-ADAPT-VQE, *Phys. Rev. Research* 6, 013254 (2024)](https://doi.org/10.1103/PhysRevResearch.6.013254) — multi-operator disjoint-support layering; shallower, same CNOTs.
4. [Feniou et al. — Overlap-ADAPT-VQE, *Commun. Phys.* 6, 192 (2023)](https://doi.org/10.1038/s42005-023-01312-y) — grow by overlap with a classical target; ultra-compact ansatze, avoids plateaus.
5. [Rossi, Kjellgren, Izmaylov, Sauer, Ziems, Coriani — Resource-efficient energy-based operator selection, arXiv:2606.04786 (2026)](https://doi.org/10.48550/arxiv.2606.04786) — Rotoselect at gradient-selection cost; benchmarks selection vs re-optimisation vs orbital-opt on LiH/BeH2/H2O.
6. [Nykanen et al. — Mitigating the measurement overhead of ADAPT-VQE with optimized informationally complete measurements, *Phys. Rev. A* (2025)](https://link.aps.org/doi/10.1103/t1hr-y7c8) — AIM-ADAPT-VQE; reuse energy measurement data for all gradients; discusses gradient vs energy selection.
7. [Yordanov, Barnes, Arvidsson-Shukur — Quantifying the effect of gate errors on VQEs, *npj Quantum Inf.* 10 (2024)](https://www.nature.com/articles/s41534-024-00808-x) — VQEs need p ~ 1e-6..1e-4 for chemical accuracy; density-matrix study.
8. [Hamiltonian-Aware ADAPT-VQE, arXiv:2606.13118 (2026)](https://arxiv.org/html/2606.13118v1) — non-local selection criterion + redundant-operator pruning; avoids energy plateaus.
9. [Tang et al. — Qubit-ADAPT-VQE, *PRX Quantum* 2, 020310 (2021)](https://doi.org/10.1103/PRXQuantum.2.020310) — the individual-Pauli-string pool this project already adopted; CNOT count 2(l-1) per string.
10. [Grimsley, Economou, Barnes, Mayhall — original ADAPT-VQE, *Nat. Commun.* 10, 3007 (2019)](https://doi.org/10.1038/s41467-019-10988-2) — the gradient-selection baseline.
11. [Ostaszewski, Grant, Benedetti — Rotoselect, *Quantum* 5, 391 (2021)](https://quantum-journal.org/papers/q-2021-01-28-391/) — structure optimisation by 1D energy-landscape minimisation.

## Methodology

Searched 6 queries via Exa (`web_search_exa`) across arXiv, APS, Nature
Communications Physics, and npj Quantum Information. ~30 results reviewed;
11 primary sources retained (all peer-reviewed except two 2026 arXiv preprints,
flagged). Sub-questions: (a) noise-aware / hardware-aware ADAPT selection
criteria; (b) shallow-circuit ADAPT variants (TETRIS, qubit/QEB pools);
(c) energy-based vs gradient-based selection; (d) does depth reduction help
under realistic noise; (e) gate-error tolerance of VQEs. Gap: no source was
found that tests exactly `grad/(1+lambda*cost)` -- it appears to be genuinely
un-studied, consistent with this project being a (negative) first look.
