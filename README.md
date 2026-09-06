# Resource-Aware ADAPT-VQE — CIA-3

Benchmarking VQE ansatz strategies on H2 and LiH (STO-3G) across increasing
noise levels, and testing a modified ADAPT-VQE operator-selection rule that
scores candidate operators by **gradient per unit of added circuit cost**.

---

## Option A vs Option B — what is claimed as novel

This distinction is enforced in the code: every result row carries an `option`
column, and the plots draw Option B dashed/hatched and Option A solid.

### Option B — baseline benchmark. **No novelty claimed.**

Three published, off-the-shelf methods, run as-is from their libraries.

| Strategy | Implementation | Notes |
|---|---|---|
| UCCSD | `qiskit_nature.second_q.circuit.library.UCCSD` | fixed chemistry-derived ansatz |
| Hardware-efficient | `qiskit.circuit.library.EfficientSU2` | linear entanglement, HF reference |
| Standard ADAPT-VQE | `qiskit_algorithms.AdaptVQE` | selects by **raw gradient magnitude** |

File: [`qiskit_baselines.py`](qiskit_baselines.py)

### Option A — the actual contribution.

A hand-rolled ADAPT-VQE loop in PennyLane where the operator-selection score is

```
    score(op) = |dE/dtheta_op| / (1 + lambda * cnot_cost(op))
```

instead of standard ADAPT-VQE's `score(op) = |dE/dtheta_op|`.

The rationale: an operator that lowers the energy a lot but adds many CNOTs is
a bad trade under noise, because the added depth is itself an error source.

File: [`pennylane_resource_aware_adapt.py`](pennylane_resource_aware_adapt.py)

**That file also contains a PennyLane reimplementation of *standard* ADAPT
(`ADAPT-VQE(standard,PL)`), which is NOT novel.** It exists as the control: it
shares an identical code path with the resource-aware version, and the only
difference is the scoring line. Without it, an Option A vs Option B comparison
would confound "new selection rule" with "different framework". The honest
headline comparison is:

```
  ADAPT-VQE(resource-aware)  vs  ADAPT-VQE(standard,PL)      <- rule vs rule
```

with `ADAPT-VQE(standard)` (Qiskit) present to show the two frameworks agree.

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

Run the validation gates first — this is the sanity check, and it is worth
running on its own before anything else:

```bash
python molecules.py
```

```bash
python noise_models.py
```

Then the pipeline:

```bash
python run_experiments.py
```

```bash
python analyze_results.py
```

Faster pipeline check (H2 only, 3 noise levels):

```bash
python run_experiments.py --quick
```

---

## What each file does

| File | Role |
|---|---|
| `molecules.py` | Shared Hamiltonians + exact FCI reference. **The bridge point.** |
| `noise_models.py` | Noise levels for both frameworks + equivalence self-test |
| `qiskit_baselines.py` | **Option B** — UCCSD, HEA, standard ADAPT-VQE |
| `pennylane_resource_aware_adapt.py` | **Option A** — resource-aware ADAPT + its control |
| `run_experiments.py` | Sweep: strategies × molecules × noise levels → CSV |
| `analyze_results.py` | Plots + summary tables |

Each module runs standalone as its own self-test (`python <file>.py`).

---

## Findings from building this — read before writing up

These are things that were checked, not assumed. Several changed the design.

### 1. PySCF does not work on Windows — the standard driver route is unavailable

`qiskit_nature`'s `PySCFDriver` is the usual way to build these Hamiltonians.
PySCF has no Windows wheels (it resolves to a source tarball on both Python
3.11 and 3.14), and the source build fails at the `cmake` build dependency.
This is a Windows limitation, not a Python-version one.

**Resolution:** PennyLane's built-in differentiable Hartree-Fock (`method="dhf"`,
pure Python) is the single source of truth for the molecular integrals, and the
Qiskit Hamiltonian is built from those *same* integrals via
`ElectronicEnergy.from_raw_integrals`. No PySCF anywhere.

This turned out better than the original plan. The two frameworks do not merely
"agree to some tolerance" — they are constructed from identical integrals, so
agreement is exact and any deviation would be a real convention bug.

Verified:

```
STEP 1  dhf integrals vs published full-space FCI (STO-3G)
H2          4 qubits   -1.13730604  vs lit -1.13727000   err 0.0360 mHa  PASS
LiH        12 qubits   -7.88240342  vs lit -7.88236200   err 0.0414 mHa  PASS

STEP 2  Qiskit <-> PennyLane Hamiltonian bridge
H2(full)         E_pl = E_qk        diff 3.77e-15 Ha  PASS
LiH(AS:2e,3o)    E_pl = E_qk        diff 3.11e-14 Ha  PASS
```

Both molecules reproduce literature FCI to well under chemical accuracy
(1.6 mHa), and the framework bridge is exact to machine precision.

### 2. LiH is run at a STRETCHED bond (3.0 Å), not equilibrium — say this in the writeup

In STO-3G, LiH's correlation energy at equilibrium is concentrated almost
entirely in the *highest* virtual orbital, so a contiguous active space captures
nearly none of it:

| geometry | (2e,3o) 6q | (2e,4o) 8q | (2e,5o) 10q |
|---|---|---|---|
| d = 1.5949 Å (equilibrium) | 1.05 mHa | 1.82 mHa | 20.15 mHa |
| **d = 3.0 Å (used here)** | **16.26 mHa** | 16.90 mHa | 87.67 mHa |

At equilibrium with 6 qubits there is only ~1 mHa of correlation energy to
recover — **below chemical accuracy**. Every ansatz would sit on top of
Hartree-Fock and the benchmark could not distinguish any method from any other;
the plots would show noise and nothing else.

Stretching to 3.0 Å restores 16.3 mHa (comparable to H2's 20.3 mHa) while
staying at 6 qubits, and the stretched geometry is more multi-reference —
precisely the regime where adaptive ansätze are expected to beat a fixed UCCSD.
The 10-qubit equilibrium configuration is a valid alternative but ~16× more
expensive per point in density-matrix simulation.

**Error is measured against the FCI energy of the same active space**, not
full-space FCI. Using full-space FCI would add a constant ~19 mHa truncation
error to every method that has nothing to do with the ansatz.

### 3. The noise models needed real work to be comparable — this was the biggest risk

The brief asked to flag if Qiskit and PennyLane noise turned out not to be
comparable. **Feeding a FakeBackend NoiseModel to Qiskit while running
PennyLane on `default.mixed` is NOT comparable**, for three independent reasons:

1. **Gate basis.** Aer applies error per *native* gate after transpilation
   (FakeManilaV2: `cx/sx/x/rz`; FakeSherbrooke: `ecr/sx/x/rz`). PennyLane
   applies error to whatever is on the tape. The same logical circuit becomes a
   different number of noisy gates.
2. **Routing.** Transpiling to a real coupling map inserts SWAPs (3 CNOTs
   each). FakeSherbrooke is a 127-qubit heavy-hex device. PennyLane assumes
   all-to-all connectivity and inserts nothing.
3. **Readout error.** `qml.from_qiskit_noise` does **not** transfer Qiskit's
   `ReadoutError`. Verified: FakeManilaV2 carries 5 readout errors,
   FakeSherbrooke 127, and none survive conversion.

**Resolution — the "custom Kraus-channel translation" option from the brief,
which turned out to be both the simplest and the only defensible one.** Noise
levels are defined framework-independently as depolarizing channels whose rates
are *calibrated from real IBM backend data* (median gate errors read off the
fake backends), applied to the same canonical gate basis with all-to-all
connectivity on both sides. The PennyLane channels are built from Kraus
operators reproducing Qiskit's depolarizing convention exactly — the 2-qubit
channel is the true 16-Kraus channel, not two 1-qubit channels in sequence.

Verified by running the *same* circuit through both stacks:

```
noise level        <ZZZ> qiskit    <ZZZ> pennylane      |diff|
noiseless          0.6980468421      0.6980468421     0.00e+00  PASS
ManilaV2x1         0.6693464353      0.6693464353     6.66e-16  PASS
ManilaV2x4         0.5886411159      0.5886411159     1.11e-16  PASS
ManilaV2x20        0.2753930852      0.2753930852     4.44e-16  PASS

Noise sensitivity of the probe observable: spread=0.422654  OK
```

Agreement to ~4e-16 while the observable itself moves by 0.42 across the sweep.
(The sensitivity check matters: an earlier version of this test used a probe
whose expectation value was identically zero at every noise level, so it would
have "passed" even if the two models had disagreed completely.)

Raw FakeBackend models are still available via `--include-device-noise`, but
they are flagged `comparable=False`, are Qiskit-only, and are **excluded from
cross-framework plots by default**.

Calibrated rates actually used:

```
FakeManilaV2    median gate errors: p1=3.5387e-04  p2=1.0091e-02
FakeSherbrooke  median gate errors: p1=2.3623e-04  p2=7.7881e-03
```

### 4. `backprop` on `default.mixed` returns NaN — the brief's gradient method is unusable

The brief specified backprop through the circuit. In this environment
(PennyLane 0.45.1 / NumPy 2.5.2 / CPython 3.14) that returns NaN for every
gradient on `default.mixed`, which is the device noise channels require. It
fails **silently** — the forward energy stays exactly correct, so only the
gradients are poisoned. Measured on a bare two-gate RY/CNOT circuit:

| device | backprop | parameter-shift | finite-diff |
|---|---|---|---|
| `default.qubit` | OK | OK | OK |
| `default.mixed` | **NaN** | OK | OK |

**Resolution:** operator selection uses PennyLane's exact parameter-shift rule
or a central difference (verified to agree to ~1e-8 *with noise channels
present*; the self-test re-checks this every run). Central difference is the
default because it costs 0.56 s vs 4.18 s per candidate on 6-qubit LiH.
Parameter re-optimization uses COBYLA — gradient-free, and the **same optimizer
Option B uses**, so any Option A vs B difference cannot be blamed on the
optimizer.

### 5. The hardware-efficient baseline needed care to be a fair baseline

Two optimizer artifacts had to be fixed before HEA was a credible comparison:

- At all-zero parameters `EfficientSU2` is exactly the identity, so it sits on
  the HF state at a symmetric stationary point. COBYLA terminated having
  recovered **0.0% of the correlation energy**, reporting HF as a converged VQE
  result.
- With a single random start it converged (by COBYLA's own criterion, 1414
  iterations) to **21.6 mHa error on LiH — above the HF energy of 16.3 mHa**.
  Since the ansatz contains the identity its variational minimum cannot exceed
  HF, so that number was an optimizer artifact reported as an ansatz property.

Now uses best-of-3 restarts with the all-zero (HF) point as the first restart,
which makes the reported HEA energy provably ≤ E_HF. HEA still underperforms
the chemistry-derived ansätze — that is the honest baseline result and matches
the literature — but it now underperforms for ansatz reasons.

### 6. Fermionic excitations, not Givens rotations — this decides whether Option A is meaningful

The operator pool uses `qml.FermionicSingleExcitation` /
`FermionicDoubleExcitation`, which carry the full Jordan-Wigner Z-string, **not**
the 2-/4-wire Givens rotations `qml.SingleExcitation` / `DoubleExcitation`.

With Givens rotations the CNOT cost is essentially fixed (~2 for singles, ~14
for doubles) regardless of which orbitals are involved. `cnot_cost` would be
near-constant within each class, and `gradient/(1+cost)` would collapse into
"prefer singles over doubles" — a trivial rule needing no gradient information.
The Fermionic versions make cost grow with orbital-index span, so it genuinely
varies operator to operator, which is the variation the scoring rule exists to
exploit. Measured spread:

```
H2(full)         pool=3   CNOT cost min=8   max=48   spread=40
LiH(AS:2e,3o)    pool=8   CNOT cost min=8   max=80   spread=72
```

The self-test fails if this spread is zero. It also keeps the frameworks
comparable — Qiskit Nature's UCCSD is likewise Z-string based (272 CNOTs for 8
LiH operators).

### 7. No shot noise anywhere

Expectation values are computed exactly from the noisy density matrix
(`shots=None`, `precision=0`). The study is about how circuit depth interacts
with *gate* noise; shot noise would add a second, unrelated error source scaling
as 1/√shots that would obscure the depth effect. **These are not shot-limited
results** — say so in the writeup.

---

## Noiseless validation results

Every strategy at zero noise — the correctness check before any noise sweep.
UCCSD and both ADAPT variants recover the correlation energy exactly.

```
molecule        strategy                      energy   err/mHa  depth  CNOT
H2(full)        UCCSD                    -1.13730603     0.000     82    56
H2(full)        HEA(reps=2)              -1.13062485     6.681     11     6
H2(full)        ADAPT-VQE(standard)      -1.13730603     0.000     72    48
LiH(AS:2e,3o)   UCCSD                    -7.72709271     0.000    363   272
LiH(AS:2e,3o)   HEA(reps=2)              -7.71413842    12.955     13    10
LiH(AS:2e,3o)   ADAPT-VQE(standard)      -7.72709252     0.000    187   132
```

Note ADAPT already reaches UCCSD accuracy at roughly half the depth on LiH
(187 vs 363) — that is the standard ADAPT-VQE result, Option B, not a
contribution of this project.

---

## Interpreting the Option A result

`analyze_results.py` prints the headline table directly:

```
molecule   noise   standard/mHa   resource-aware/mHa   delta/mHa   depth std   depth RA
```

`delta < 0` means the resource-aware rule is more accurate at that noise level.
Read it alongside the depth columns — the claim being tested is that a shallower
circuit survives noise better, so the result to look for is **a depth reduction
that holds accuracy at low noise and wins at high noise**.

A fair writeup should also report the case where it does *not* help. The scoring
rule is a heuristic with a known bias: because cost appears in the denominator
with no normalization, it always penalizes doubles relative to singles, and if
the molecule genuinely needs an expensive double excitation the rule may refuse
to pick it and converge to a worse energy. `lambda` is exposed
(`resource_aware_adapt(..., lam=...)`) precisely so this trade-off can be swept;
`lambda=0` recovers standard ADAPT exactly, which is a useful consistency check.

---

## Environment

Validated on Windows 11, CPython 3.14.2, in a `.venv`:

```
qiskit 2.3.0          qiskit-aer 0.17.2        qiskit-nature 0.8.0
qiskit-algorithms 0.4.0                        qiskit-ibm-runtime 0.45.0
pennylane 0.45.1      pennylane-qiskit 0.45.0  numpy 2.5.2   scipy 1.16.3
```

Console output is deliberately ASCII-only — the Windows console defaults to
cp1252 and raises `UnicodeEncodeError` on characters like `Δ`.
