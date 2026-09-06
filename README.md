# noise-realized-adapt-vqe

Benchmarking VQE ansatz strategies on H2 and LiH (STO-3G) across increasing
depolarizing noise, and testing three ADAPT-VQE operator-selection rules against
the standard gradient rule.

**This is a preliminary study. The main results are not conclusive** — see
[Status](#status) below and [`MANUSCRIPT.md`](MANUSCRIPT.md) Sections IV-E / IV-F.

---

## Status

Three selection rules were tested against standard gradient-based ADAPT-VQE.
Outcomes:

| Rule | Idea | Outcome |
|---|---|---|
| **resource-aware** `\|g\|/(1+λc)` | penalize operators by added CNOT cost | **Null result.** Identical ansatz to standard ADAPT at every non-zero noise level, for both molecules. Structural reason identified (see below). `λ=0` reproduces standard exactly. |
| **noise-realized** (novel) | score by the energy an operator *actually* reaches after re-optimization *with the noise channel applied*, per unit cost | **Small positive, not conclusive.** Beats standard and resource-aware by 0.5–1.4 mHa at 0.25× and 0.50× device noise, at *identical* circuit cost. No effect at 0× or ≥1×. Effect size is small and only two systems were tested. |
| **noise-realized + self-tuning λ** (novel) | make λ a feedback controller that rises in the noise-dominated tail | **Untested on these systems.** The controller tracks the noise regime correctly (λ_final ≈ 0.4 low noise, ≈ 2.5 at device rate) but the H2 / LiH(2e,3o) pools contain no cheaper alternative operator for it to switch to, so it never changes a selection. Needs a larger active space. |

What is **not** a contribution of this project: the qubit-ADAPT pool, the ADAPT
algorithm, the depolarizing noise model, the UCCSD / HEA / Qiskit-ADAPT
baselines. Standard ADAPT-VQE reaching UCCSD accuracy at lower depth is a known
result, reproduced here as a control.

At ≥ 1× the real FakeManilaV2 gate-error rate, **every** method (novel or
baseline) fails to recover any correlation energy. That regime is consistent
with published gate-error thresholds for VQE and is not informative about
selection rules.

---

## Headline numbers

Energy error vs active-space FCI (mHa), PennyLane rules, from
[`results/results_novel.csv`](results/results_novel.csv):

```
molecule  scale  standard  resource-aware  noise-realized  NR+adaptive-λ
H2        0.00     0.000        0.000          0.000           0.000
H2        0.25    15.262       15.262         13.831          13.831
H2        0.50    20.410       20.410         20.410          20.410     (0 operators; returns HF)
H2        1.00    20.513       20.513         20.513          20.513     (0 operators)
LiH       0.00     0.010        0.008          0.101           0.101     (all << chemical accuracy)
LiH       0.25     5.695        5.695          5.237           5.237
LiH       0.50    10.191       10.191          9.294           9.294
LiH       1.00    16.280       16.280         16.280          16.280     (1 operator; collapse)
```

CNOT count of the LiH ansatz: noiseless 36 / 34 / 26 for standard /
resource-aware / noise-realized; 10 / 10 / 10 at 0.25× and 0.50×; 6 / 6 / 6 at
1×. So the noise-realized improvement at 0.25× and 0.50× is a better *choice* of
operator at the same cost, not a cheaper circuit.

Full write-ups: [`MANUSCRIPT.md`](MANUSCRIPT.md) (IEEE-format),
[`RESULTS.md`](RESULTS.md) (the resource-aware null result in detail),
[`NOVEL_RESULTS.md`](NOVEL_RESULTS.md) (the novel rules),
[`IMPROVEMENTS.md`](IMPROVEMENTS.md) (literature survey of alternatives).

---

## Why the resource-aware rule is inert

At the Hartree-Fock reference, `standard` and `resource_aware` select the
*same* operator, for two reasons that both hold on minimal-basis small
molecules:

- Single excitations have exactly zero gradient at HF (Brillouin's theorem), so
  the first operator is always a double.
- With the qubit-ADAPT pool, the double-excitation Pauli strings that carry a
  non-zero HF gradient (8 of 12 for H2, 8 of 40 for LiH) all have Pauli weight 4
  and cost **6 CNOTs**. Equal cost.

With the numerator varying but the denominator constant across the *selectable*
operators, `|g|/(1+λc)` is a monotone rescaling of `|g|`: the arg-max never
changes, for any λ. The two rules do diverge if the ansatz grows deep enough
(for noiseless LiH, from operator 6), but under noise the energy-plateau stop
truncates the ansatz at 1–2 operators, before that point. Verified:
`resource_aware` and `standard` produce byte-identical operator sequences at
every non-zero noise level.

---

## Quick start

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

Validation gates first (Hamiltonian references and cross-framework noise
equivalence):

```bash
python molecules.py
```

```bash
python noise_models.py
```

Fast pipeline check (H2 only):

```bash
python run_experiments.py --quick
```

The scoped sweep used for the reported numbers (56 runs, ~2 h; incremental CSV):

```bash
python run_experiments.py --skip-validation --out results/results_novel.csv --pl-max-operators 8 --pl-opt-maxiter 100
```

```bash
python analyze_results.py --csv results/results_novel.csv --outdir results/novel
```

[`CIA3_notebook.ipynb`](CIA3_notebook.ipynb) reproduces the fast sections live
(Colab: run the SETUP cell, restart, run all) and loads the pre-computed sweep.

---

## Files

| File | Role |
|---|---|
| `molecules.py` | Shared `dhf` Hamiltonians + active-space FCI reference. The Qiskit/PennyLane bridge. |
| `noise_models.py` | Framework-independent calibrated depolarizing channels + equivalence self-test |
| `qiskit_baselines.py` | Baselines: UCCSD, HEA, Qiskit AdaptVQE |
| `pennylane_resource_aware_adapt.py` | qubit-ADAPT pool + the four selection rules + self-test |
| `run_experiments.py` | Sweep: strategies × molecules × noise → CSV (written row by row) |
| `analyze_results.py` | Comparison tables + figures |
| `verify_fix.py` | Pre-sweep checks: cost spread, selection divergence at λ=1, λ=0 ≡ standard |
| `CIA3_notebook.ipynb` | Colab/Jupyter reproduction |
| `results/` | `results_novel.csv` (all 4 rules), `results.csv` (earlier 5-strategy run), figures |
| `*.log` | Raw stdout from the sweeps and checks |

Each module also runs standalone as its own self-test (`python <file>.py`).

---

## Design decisions that were checked, not assumed

### 1. No PySCF (Windows). Integrals from PennyLane `dhf`.

`qiskit_nature`'s `PySCFDriver` needs PySCF, which has no Windows wheels and
fails its source build at `cmake`. PennyLane's differentiable Hartree-Fock
(`method="dhf"`, pure Python) is the single source of truth for the integrals,
and the Qiskit Hamiltonian is built from those same integrals via
`ElectronicEnergy.from_raw_integrals`. The two frameworks are therefore
constructed from identical numbers, not merely agreeing to a tolerance.
Verified: `dhf` reproduces literature full-space FCI to 0.036 mHa (H2) and
0.041 mHa (LiH); the Qiskit ↔ PennyLane spectrum difference is ≤ 5e-14 Ha.

### 2. LiH is run at a stretched bond (3.0 A), not equilibrium.

In STO-3G, LiH's equilibrium correlation energy is concentrated in the highest
virtual orbital, so a contiguous (2e,3o) active space captures only ~1 mHa,
below chemical accuracy, and every ansatz would sit on HF. Stretching to 3.0 A
restores 16.3 mHa of active-space correlation (comparable to H2's 20.3 mHa) at
6 qubits, and the geometry is more multireference. Error is measured against the
FCI energy of that same active space, not full-space FCI.

### 3. Qiskit and PennyLane noise had to be made comparable.

Feeding a FakeBackend `NoiseModel` to Qiskit while running PennyLane on
`default.mixed` is not comparable: different native gate sets, Qiskit inserts
routing SWAPs while PennyLane assumes all-to-all connectivity, and readout error
does not survive `qml.from_qiskit_noise`. Instead, noise is defined
framework-independently as depolarizing channels with rates calibrated from real
FakeManilaV2 data (`p1 = 3.54e-4`, `p2 = 1.01e-2`), applied to the same
canonical gate set on both sides, with the PennyLane channels built from Kraus
operators reproducing Qiskit's convention exactly. The same probe circuit
through both stacks agrees to ~4e-16 while the probe observable moves by 0.42
across the noise sweep. Raw device models are still available via
`--include-device-noise`, flagged `comparable=False`, and excluded from
cross-framework plots.

### 4. `backprop` on `default.mixed` returns NaN.

In this stack (PennyLane 0.45.1 / NumPy 2.5.2 / CPython 3.14) back-propagation
on the mixed-state device returns NaN for every gradient, silently — the forward
energy stays correct. Operator selection uses a central difference (checked
against the exact parameter-shift rule to ~1e-8 with noise present) and
parameter re-optimization uses COBYLA, the same gradient-free optimizer as the
Qiskit baselines.

### 5. ADAPT needs an energy-based stop under noise.

The textbook gradient-norm stop never fires under noise, because the candidate
gradient *estimate* is floored near `p2` (~1e-2). Left alone, the loop runs to
`max_operators` and piles noisy operators onto an already-converged circuit
(measured: H2 at 1× ran to 10 operators / 60 CNOTs / 452 mHa error, worse than
HF). The driver adds an energy-plateau stop: roll back an operator that fails to
lower the best energy by ≥ 1e-5 Ha, after a patience of 2. Applied identically
to all four rules, so `λ=0` still equals standard ADAPT.

### 6. Pool: individual JW Pauli-string rotations (qubit-ADAPT), Z-strings kept.

The first design used whole fermionic excitations
(`FermionicSingleExcitation` / `FermionicDoubleExcitation`). That made the
resource-aware score algebraically inert on these systems: the productive
doubles all Trotterize to the same 48-CNOT block, so cost was constant across
selectable operators. The pool was switched to the qubit-ADAPT pool [Tang et
al., *PRX Quantum* 2, 020310] — each fermionic generator expanded into its
Jordan-Wigner Pauli-string rotations `exp(-iθP)`, CNOT cost `2(w-1)` per string,
Z-strings retained so cost grows with orbital-index span. Measured cost spectrum:

```
H2(full)         pool = 12   CNOT cost {4, 6}
LiH(AS:2e,3o)    pool = 40   CNOT cost {4, 6, 8, 10}
```

`verify_fix.py` checks that this spread is non-trivial, that `resource_aware`
now selects a different sequence from `standard` on noiseless LiH, and that
`λ=0` reproduces `standard` exactly.

### 7. No shot noise anywhere.

Expectation values are exact from the noisy density matrix (`shots=None`). The
study is about circuit cost vs gate noise; shot noise would add an unrelated
1/sqrt(shots) error. Finite sampling would add variance to the noise-realized
score and could erode its small margin — this is an open check.

---

## Environment

Validated on Windows 11, CPython 3.14.2, in a `.venv`:

```
qiskit 2.3.0          qiskit-aer 0.17.2        qiskit-nature 0.8.0
qiskit-algorithms 0.4.0                        qiskit-ibm-runtime 0.45.0
pennylane 0.45.1      pennylane-qiskit 0.45.0  numpy 2.5.2   scipy 1.16.3
```

Console output is ASCII-only (the Windows console defaults to cp1252 and raises
`UnicodeEncodeError` on characters like the Greek delta).
