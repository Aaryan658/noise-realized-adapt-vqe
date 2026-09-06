# Noise-Realized Operator Selection for ADAPT-VQE

A controlled, cross-framework benchmark of ADAPT-VQE operator-selection rules for
H<sub>2</sub> and stretched LiH (STO-3G) under depolarizing noise calibrated to
IBM `FakeManilaV2`. Qiskit and PennyLane are placed on a noise footing that
agrees to ~10<sup>-15</sup> on a probe observable, so any difference between
strategies is attributable to the strategy and not the framework.

> **Status — preliminary.** The adaptive-ansatz baseline result is solid and
> reproducible. The three novel selection rules are a **characterized null**:
> none shows a robust advantage over gradient selection on the two test
> systems, and the reasons are structural (see [Selection-rule
> experiments](#selection-rule-experiments-null-result)). A 10-qubit active
> space is required for a fair test; that is future work.

---

## Result 1 — adaptive qubit-ADAPT beats every fixed-ansatz baseline under noise

Energy error vs active-space FCI (mHa) and CNOT count, from
[`results/results.csv`](results/results.csv):

| system / noise | qubit-ADAPT (this repo) | UCCSD | HEA(reps=2) | Qiskit ADAPT (routed) |
|---|---|---|---|---|
| LiH  0.25× | **5.7**  / 10 CX | 124.7 / 272 CX | 16.9 / 10 CX | 171.3 / 388 CX |
| LiH  0.50× | **10.2** / 10 CX | 219.1 / 272 CX | 24.3 / 10 CX | 237.3 / 308 CX |
| LiH  1.00× | **16.3** / 6 CX  | 347.5 / 272 CX | 28.5 / 10 CX | 344.0 / 252 CX |
| H<sub>2</sub> 0.50× | **20.4** / 0 CX | 188.5 / 56 CX | 30.3 / 6 CX | 170.0 / 48 CX |

The compact all-to-all qubit-ADAPT ansatz is 10–20× more accurate than UCCSD and
HEA at every noise level, at a fraction of the two-qubit-gate count. Qiskit's own
ADAPT does *worse* than UCCSD under noise because transpilation and routing
inflate a 6-qubit circuit to 250–390 CNOTs — an illustration that routing
overhead, not the algorithm, is what breaks textbook ADAPT on hardware.

This reproduces a known result (adaptive ansätze beat fixed ansätze under noise)
on a tightly controlled, framework-matched footing. It is used here as the
control, not claimed as novel.

## Selection-rule experiments (null result)

Three rules were tested against standard gradient-based selection, all sharing
one code path in
[`_adapt_loop`](pennylane_resource_aware_adapt.py):

| rule | score | outcome |
|---|---|---|
| **resource-aware** | `\|g\| / (1 + λ·cnot_cost)` | **Inert.** Byte-identical ansatz to standard ADAPT at every non-zero noise level. `λ=0` reproduces standard exactly. Analytic reason: the gradient-competitive pool operators all cost 6 CNOTs, so the denominator is constant across the selectable set and `\|g\|/(1+λc)` is a monotone rescaling of `\|g\|`. |
| **noise-realized** | `max(0, ΔE_realised) / (1 + λ·cnot_cost)` — score each shortlisted operator by the energy it *actually* reaches after re-optimization *with the noise channel applied* | **Small, not robust.** Free-running: 0.5–1.4 mHa more accurate than standard at 0.25×/0.5× noise. But a matched operator-count control ([`docs/NOVEL_RESULTS.md` § Fixed operator count](docs/NOVEL_RESULTS.md)) shows that at forced *k*=6 the delta vs standard is +0.01 / +0.03 / −0.24 / +0.89 mHa — sign-inconsistent — so the free-running gap was largely a circuit-length effect from the energy-plateau stop truncating rules at different *k*. Noiselessly it does reach chemical accuracy with 26 CNOTs vs 36 for gradient selection — a real efficiency point. |
| **noise-realized + self-tuning λ** | λ as a feedback controller that rises in the noise-dominated tail | **Not exercised.** The controller tracks the noise regime (λ_final ≈ 0.4 low noise, → 8.0 ceiling at the device rate) but the minimal-basis pool has no cheaper gradient-competitive operator for it to switch to, so it never changes a selection. |

**Bottom line:** on H<sub>2</sub> and LiH(2e,3o) the ansatz is 1–6 operators
under noise — too shallow for a selection rule to express an advantage, and the
pool is too cost-degenerate for the cost penalty to bite. The honest next
experiment is LiH(2e,5o) (10 qubits); see [`docs/NOVEL_RESULTS.md` § A fair
test](docs/NOVEL_RESULTS.md).

At ≥ 1× the real `FakeManilaV2` gate-error rate every method fails to recover
any correlation energy, consistent with published gate-error thresholds for VQE.

---

## Repository layout

```
molecules.py                      shared dhf Hamiltonians + active-space FCI; the Qiskit/PennyLane bridge
noise_models.py                   framework-independent calibrated depolarizing channels + equivalence self-test
qiskit_baselines.py               Option B baselines: UCCSD, HEA, Qiskit AdaptVQE
pennylane_resource_aware_adapt.py qubit-ADAPT pool + the four selection rules + self-test
run_experiments.py                sweep: strategies × molecules × noise → CSV
fixed_k_experiment.py             matched-operator-count control (fixed_k) for the selection rules
analyze_results.py                comparison tables + figures
verify_fix.py                     pre-sweep checks: cost spread, selection divergence at λ=1, λ=0 ≡ standard

docs/    MANUSCRIPT.md (IEEE-format write-up) · RESULTS.md (resource-aware null, in detail)
         NOVEL_RESULTS.md (novel rules + matched-k control) · IMPROVEMENTS.md (literature survey)
results/ results.csv (5-strategy baseline run) · results_novel.csv (4 selection rules)
         results_fixed_k.csv (matched-k control) · summary.csv · figures · novel/
logs/    raw stdout from the sweeps and self-tests
CIA3_notebook.ipynb   Colab/Jupyter reproduction of the fast sections (run from repo root)
```

Every module also runs standalone as its own self-test: `python <module>.py`.

## Reproduce

```bash
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

```bash
make validate      # molecular references + Qiskit/PennyLane noise equivalence
```

```bash
make selftest      # per-module self-tests
```

```bash
make baseline      # Result 1: 5-strategy sweep -> results/results.csv
```

```bash
make selection     # the 4 selection rules -> results/results_novel.csv
```

```bash
make fixed-k       # matched-operator-count control -> results/results_fixed_k.csv
```

```bash
make figures       # comparison tables + PNGs from the CSVs
```

Without `make`, the underlying commands are listed in the [`Makefile`](Makefile).
The selection and fixed-k sweeps take 1–2 h each (noisy density-matrix
simulation; `noise_realized` does 4 re-optimizations per ADAPT step).

## Key design decisions (checked, not assumed)

1. **No PySCF** (no Windows wheels). PennyLane differentiable Hartree–Fock
   (`method="dhf"`) is the single source of truth for integrals; the Qiskit
   Hamiltonian is built from the *same* integrals, so the two spectra agree to
   ≤ 5×10<sup>-14</sup> Ha, not merely to a tolerance.
2. **LiH is stretched to 3.0 Å**, not equilibrium: in STO-3G the equilibrium
   (2e,3o) active space holds only ~1 mHa of correlation, below chemical
   accuracy. Stretching restores 16.3 mHa at 6 qubits and a more
   multireference geometry. Error is measured against that active space's FCI.
3. **Noise is made comparable by construction.** Depolarizing channels with
   rates read off real `FakeManilaV2` calibration data, applied to the same
   canonical gate set with all-to-all connectivity on both sides; the PennyLane
   channels are the exact 16-Kraus form of Qiskit's convention. Probe
   observable agrees to ~4×10<sup>-16</sup>. Raw device models (readout +
   routing) are Qiskit-only and flagged `comparable=False`.
4. **`backprop` on `default.mixed` returns NaN** in this stack (silently — the
   forward energy stays correct). Operator selection uses a central difference
   checked against exact parameter-shift to ~10<sup>-8</sup> with noise
   present; re-optimization uses COBYLA, the same gradient-free optimizer as
   the Qiskit baselines.
5. **ADAPT needs an energy-based stop under noise.** The gradient-norm stop
   never fires (the candidate-gradient estimate is floored near the gate-error
   rate); left alone the loop piles noisy operators onto a converged circuit.
   An energy-plateau stop rolls back operators that fail to lower the best
   energy by ≥ 10<sup>-5</sup> Ha. `fixed_k` disables both stops for the
   matched-count control.
6. **No shot noise** anywhere (exact density-matrix expectation values). Finite
   sampling would add 1/√shots variance to the realized-ΔE score and is an
   open check.

## Environment

Validated on Windows 11, CPython 3.14.2, in a `.venv`:

```
qiskit 2.3.0   qiskit-aer 0.17.2   qiskit-nature 0.8.0   qiskit-algorithms 0.4.0
qiskit-ibm-runtime 0.45.0   pennylane 0.45.1   pennylane-qiskit 0.45.0
numpy 2.5.2   scipy 1.16.3
```

Console output is ASCII-only (`cp1252` default on the Windows console).

## Citing

See [`CITATION.cff`](CITATION.cff). This is a course research project
(Continuous Internal Assessment); the code and data are released for
reproducibility.

## License

[MIT](LICENSE).
