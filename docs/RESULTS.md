# Results — Resource-Aware ADAPT-VQE is a Negative Result

**Claim tested (Option A):** replace standard ADAPT-VQE's operator-selection score

```
    score(op) = |dE/dtheta_op|
```

with a resource-aware score that penalises operators by the circuit cost they add,

```
    score(op) = |dE/dtheta_op| / (1 + lambda * cnot_cost(op)) .
```

**Finding:** on H2 and LiH (STO-3G, the systems in this study) the resource-aware
rule produces **the same ansatz as standard ADAPT at every noise level tested**,
and therefore the same energy. It is not worse; it is inert. Two independent
mechanisms make it inert, and removing the first one (which was a bug) exposed
the second one (which is structural).

All numbers below are from `results/results.csv` (40 runs: 2 molecules x 4 noise
scales x 5 strategies), `results/summary.csv`, and `logs/verify_fix.log`.

---

## 1. What the rule is supposed to do

ADAPT-VQE grows an ansatz one operator at a time, each step adding the pool
operator with the largest energy gradient. The premise of Option A: under
hardware noise, an operator that lowers the energy a lot but adds many entangling
gates can be a *net loss*, because every added CNOT is itself an error channel.
Dividing the gradient by `1 + lambda * cnot_cost` is meant to make ADAPT prefer
operators that buy the most energy per unit of added depth, yielding a shallower
circuit that survives noise better. `lambda` tunes the trade-off; `lambda = 0`
must recover standard ADAPT exactly.

For the rule to ever change the ansatz, two things must both hold at some ADAPT
step:

* **(P1)** at least two pool operators have comparable, non-negligible gradient, and
* **(P2)** those operators have *different* `cnot_cost`.

If (P1) fails there is nothing to choose between; if (P2) fails then
`grad / (1 + lambda * cost)` is a monotone rescaling of `grad` and `argmax` is
unchanged for every `lambda`.

---

## 2. The headline result

`analyze_results.py` prints:

```
molecule          noise   standard/mHa   resrc-aware/mHa   delta/mHa   depth std  depth RA
H2(full)           0.00         0.0000            0.0000      0.0000          9         9
H2(full)           0.25        15.2623           15.2623      0.0000          9         9
H2(full)           0.50        20.4098           20.4098      0.0000          0         0
H2(full)           1.00        20.5125           20.5125      0.0000          0         0
LiH(AS:2e,3o)      0.00         0.0039            0.0028     -0.0011         60        50
LiH(AS:2e,3o)      0.25         5.6951            5.6951      0.0000         16        16
LiH(AS:2e,3o)      0.50        10.1908           10.1908      0.0000         16        16
LiH(AS:2e,3o)      1.00        16.2796           16.2796      0.0000          9         9
```

`delta = 0.0000` at every noise level above zero, for both molecules. The only
non-zero entry is **noiseless LiH**, where the resource-aware rule builds a
depth-50 / 34-CNOT circuit instead of depth-60 / 42-CNOT and lands 0.001 mHa
*lower* — i.e. it does what it is supposed to, but only in the one regime
(no noise) where the depth saving cannot matter, and by an amount
(1 microhartree) that is noise in the optimiser.

Operator sequences (from `results.csv`) confirm the two rules make
*byte-identical* selections at every noise level > 0.

### `lambda = 0` consistency

`logs/verify_fix.log`, noiseless, both molecules:

```
lambda=0 consistency check ...
  ops match=True  |dE|=0.00e+00  PASS
```

`resource_aware_adapt(lam=0)` reproduces `standard_adapt_pennylane` exactly —
same operator sequence, energy identical to machine precision. This holds by
construction (the denominator becomes `1`) and is verified in the self-test.
Under noise it is *a fortiori* true, since resource-aware(lambda=1) already
equals standard there.

---

## 3. Why it fails — mechanism 1: equal-cost operators (fermionic pool)

The first implementation used whole fermionic excitations
(`qml.FermionicSingleExcitation` / `FermionicDoubleExcitation`) as pool
operators. On H2 and LiH(2e,3o) this makes the rule **algebraically** inert:

* **Singles have zero gradient at Hartree-Fock** (Brillouin's theorem). At the
  HF reference the first operator is always a double.
* **Every fermionic double Trotterises to the same 48-CNOT block** at this system
  size. The doubles that have a non-zero HF gradient are therefore all equal
  cost.

So (P2) fails at the only step that matters. Diagnostic
(`grad`, `std_score`, `ra_score` at HF, lambda = 1):

```
H2(full):     3 pool ops, 1 with non-zero gradient  (a double, cost 48)
LiH(2e,3o):   8 pool ops, 2 with non-zero gradient  (both doubles, both cost 48)
```

`grad / (1 + 48 lambda)` is a constant rescaling of `grad`; `argmax` never moves,
for any `lambda`. This was a genuine defect, not a property of the physics: the
fermionic pool simply has no cost variation among selectable operators.

---

## 4. Why it fails — mechanism 2: noise truncates the ansatz before selection matters (qubit-ADAPT pool)

Mechanism 1 was fixed by switching to a **qubit-ADAPT pool** (Tang et al.,
*PRX Quantum* **2**, 020310, 2021): each fermionic generator is expanded into its
individual Jordan-Wigner Pauli-string rotations `exp(-i theta P)`, and ADAPT
picks one Pauli rotation at a time. A weight-`w` Pauli string costs `2(w-1)`
CNOTs, and the JW Z-strings are retained so weight grows with orbital-index span.
This gives a real cost spectrum:

```
H2(full):     pool 12,  CNOT costs {4, 6}
LiH(2e,3o):   pool 40,  CNOT costs {4, 6, 8, 10}
```

(P2) now holds. And the rule *does* become non-inert — **noiselessly**. On LiH the
two rules agree for the first five operators, then diverge:

```
standard,PL (8 ops, depth 60, 42 CNOT, err 0.0039 mHa):
  D:XXYX@0123[6] S:YZX@012[4] D:XXYX@0145[6] D:YXYY@0145[6] S:YZX@123[4]
  D:XXYX@0123[6] S:YZX@012[4] D:YXYY@0145[6]

resource-aware (7 ops, depth 50, 34 CNOT, err 0.0028 mHa):
  D:XXYX@0123[6] S:YZX@012[4] D:XXYX@0145[6] D:YXYY@0145[6] S:YZX@123[4]
  S:XZY@123[4]  S:XZY@012[4]
```

At operators 6-8 resource-aware substitutes two cost-4 singles for standard's
cost-6 doubles and stops one operator earlier: -8 CNOTs, -10 depth.

**But under noise this divergence never happens.** ADAPT needs a stopping rule.
The textbook rule -- gradient norm below a threshold -- is unusable here: with a
noisy density-matrix simulation the candidate-gradient *estimate* is floored at
roughly the gate-error rate (~1e-2), never falls below the threshold, and the
loop runs to `max_operators`, piling noisy operators onto an already-converged
circuit (measured: H2 at 1x noise ran to 10 operators, 60 CNOTs, 452 mHa error --
worse than Hartree-Fock). The fix is an **energy-plateau stop**: after
re-optimising, if the new operator fails to lower the energy, roll it back; stop
after `patience` such failures.

That stop -- applied identically to both rules -- terminates the LiH ansatz at
**1-2 operators** under noise:

```
LiH, noise 0.25x:  both rules -> D:YYYX@0123[6] S:YZX@123[4]   (2 ops, 10 CNOT)
LiH, noise 0.50x:  both rules -> D:YYYX@0123[6] S:YZX@123[4]   (2 ops, 10 CNOT)
LiH, noise 1.00x:  both rules -> D:YXYY@0123[6]                (1 op,   6 CNOT)
H2,  noise 0.25x:  both rules -> D:YYYX@0123[6]                (1 op,   6 CNOT)
H2,  noise >=0.5x: both rules -> (0 operators, returns HF)
```

At operators 1-2 the two rules **must** agree:

* operator 1: the productive doubles all have the same cost (6), so
  `grad / (1 + 6 lambda)` ranks them exactly as `grad` does;
* operator 2: after the first double, the single `S:YZX@123` has *both* the
  largest gradient *and* (being one of the cheapest, cost 4) the largest
  resource-aware score -- the cheap choice and the greedy choice coincide.

The selection rules only diverge from operator 6 onward, and noise plus the
energy-plateau stop guarantees the ansatz never reaches operator 6. The regime
where the rule acts and the regime where the ansatz lives do not overlap.

The single noiseless LiH divergence sits at operators 6-8, where the energy is
already at FCI to 0.003 mHa -- the rule chooses among operators that no longer
change the answer.

---

## 5. What was *not* the contribution but did show up

The qubit-ADAPT **pool** (shallow individual Pauli rotations) beats Qiskit's
UCCSD-derived ADAPT pool badly under noise on LiH:

```
LiH, energy error (mHa)          noiseless   0.25x    0.5x     1.0x
  ADAPT (Qiskit, UCCSD pool)        0.000   171.3    237.3    344.0
  ADAPT (PennyLane, qubit pool)     0.004     5.70    10.19    16.28
  HEA (EfficientSU2)               14.17     16.88    24.35    28.49
  UCCSD (fixed)                     0.000   124.7    219.1    347.5
```

At 1x noise the qubit-ADAPT circuit (6-16 CNOTs) keeps error near the
Hartree-Fock gap while the Qiskit ADAPT circuit (252-388 CNOTs after its own
growth) is destroyed. **This is a pool/depth effect, shared identically by
`standard,PL` and `resource-aware`.** It is not evidence for the selection rule;
it is evidence that a shallow pool matters under noise -- which is the premise of
Option A, just not delivered by its mechanism. HEA is the fair nearest baseline
and the qubit-ADAPT circuits are competitive with it while being far shallower.

---

## 6. What would be needed to test the rule fairly

The rule needs an ADAPT run where **operator choice past ~step 5 still improves
the energy under noise**. That requires all of:

1. **A molecule/active space whose ADAPT ansatz is genuinely deep** -- 10-20
   operators needed for chemical accuracy, with the later operators each worth
   more than their added noise. LiH(2e,5o) (10 qubits), BeH2, or H4/H6 chains
   away from equilibrium are the usual candidates. LiH(2e,3o) converges in ~2
   useful operators under noise; there is no "deep tail" for the rule to
   reshape.

2. **A pool with cost variation among the operators that have large gradient at
   the same step** -- the qubit-ADAPT pool provides this in principle, but on a
   bigger active space one should check that the high-gradient operators at each
   step actually span several cost values (retain the JW Z-strings; the reduced
   "no Z-string" qubit pool collapses cost back to weight-2 vs weight-4 and the
   rule degenerates to "prefer singles").

3. **A noise level low enough that the deep ansatz is still worth building** --
   somewhere around 0.05x-0.2x of the FakeManilaV2 rate. At >=0.25x here every
   method is already past the point where added operators help, so ADAPT stops
   early and the rule has nothing to act on. This is the core tension: the rule
   matters only for deep circuits, and deep circuits only survive low noise.

4. **A stopping criterion that is not itself the thing truncating the ansatz.**
   The energy-plateau stop used here is necessary for a defensible noisy ADAPT,
   but it is aggressive. A fair test of the rule would fix the operator count
   (e.g. always build exactly `k` operators, no early stop) and compare
   `standard` vs `resource-aware` circuits at matched `k`, isolating "cheaper
   operators at the same count" from "different count".

A concrete minimal next experiment: LiH(2e,5o), 10 qubits, noise scale
`{0, 0.05, 0.1, 0.2}`, `max_operators = 16`, **no energy-plateau stop** (fixed
count), `lambda in {0, 0.5, 1, 2}`. Expect ~150 s per candidate gradient on 10
noisy qubits, so ~a few hours per (rule, noise, lambda) cell -- roughly 30-50x
this study's cost, which is why it was out of scope here.

---

## 7. Caveats on these numbers

* **No shot noise.** Expectation values are exact from the noisy density matrix
  (`shots = None`). Adding finite sampling would only add variance on top of a
  null mean difference.
* **LiH is stretched to 3.0 A** and run in a (2e,3o) active space; error is
  measured against the active-space FCI, not full-space FCI. See README finding
  #2.
* **Option A was scoped down** for runtime: `max_operators = 10`,
  `opt_maxiter = 120` (COBYLA), noise scales `{0, 0.25, 0.5, 1.0}`. The
  divergence-at-operator-6 behaviour and the equal-selection-under-noise
  behaviour were both reproduced at the module default `max_operators = 16` in
  `verify_fix.py` / the self-test, so the cap is not what produced the null
  result.
* **Gradient method** for selection is a central difference (verified against the
  exact parameter-shift rule to ~1e-8 with noise channels present; see the
  self-test). `backprop` on `default.mixed` returns NaN in this environment and
  is not used.
* The **energy-plateau / patience stop** (`energy_tol = 1e-5 Ha`, `patience = 2`)
  is a change from textbook ADAPT introduced *after* the sweep began blowing up
  under noise. It is applied identically to both selection rules and does not
  affect the `lambda = 0` equivalence.

---

## 8. One-paragraph version for the report

> We tested a resource-aware ADAPT-VQE operator-selection rule that scores pool
> operators by gradient divided by added CNOT cost, against standard
> gradient-only ADAPT, on H2 and LiH (STO-3G) across depolarising noise
> calibrated to FakeManilaV2. The rule produced an identical ansatz to standard
> ADAPT at every non-zero noise level for both molecules; `lambda = 0` reproduced
> standard ADAPT exactly, as required. The null result has a clean cause. With a
> fermionic-excitation pool the rule is algebraically inert on these systems:
> single excitations have zero gradient at Hartree-Fock (Brillouin), and the
> double excitations that carry the gradient all Trotterise to the same
> 48-CNOT cost, so the cost denominator cannot reorder them. Switching to a
> qubit-ADAPT pool of individual Pauli-string rotations gives a real cost
> spectrum and the rule does change the selection -- but only from the sixth
> operator onward, and only without noise; under noise a necessary
> energy-plateau stopping criterion terminates the ansatz at one or two
> operators, well before the step where the two rules differ. The rule acts on a
> part of the ansatz that hardware noise never lets ADAPT reach. A fair test
> needs a larger active space whose ADAPT ansatz stays deep under mild noise
> (e.g. LiH(2e,5o), 10 qubits, noise <= 0.2x, fixed operator count), which is
> ~30-50x the cost of this study.
