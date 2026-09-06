"""
pennylane_resource_aware_adapt.py -- OPTION A: THE CONTRIBUTION.

Hand-rolled ADAPT-VQE in PennyLane with two operator-selection rules sharing
one identical code path:

    standard        score(op) = |dE/dtheta_op|                          (baseline)
    resource_aware  score(op) = |dE/dtheta_op| / (1 + lam*cnot_cost(op))   (NEW)

Rationale for the new rule: an operator that lowers the energy a lot but adds
many CNOTs is a bad trade under noise, because the added depth is itself a
source of error. Dividing by the added cost prefers operators that buy the
most energy per unit of circuit depth.

WHY BOTH RULES LIVE IN THIS FILE
--------------------------------
`standard` here is a PennyLane reimplementation of ordinary ADAPT-VQE. It is
NOT the Option B result -- Option B's ADAPT is Qiskit's AdaptVQE class. Having
a PennyLane standard-ADAPT means the resource-aware comparison is rule-vs-rule
inside one framework, so any difference cannot be blamed on Qiskit-vs-PennyLane
implementation details. The Qiskit ADAPT and the PennyLane standard ADAPT
should land on similar energies; selftest() checks this, and a large gap is a
bug rather than a finding.

TWO IMPLEMENTATION CHOICES THE RESULT DEPENDS ON
------------------------------------------------
1. A qubit-ADAPT POOL of individual Jordan-Wigner Pauli-string rotations
   (Tang et al., PRX Quantum 2, 020310, 2021), NOT whole fermionic
   excitations.

   The first design used qml.FermionicSingleExcitation /
   FermionicDoubleExcitation as pool operators. That made the resource-aware
   score VACUOUS -- it never changed which operator was selected -- for a
   structural reason:

     * singles have exactly zero gradient at the Hartree-Fock reference
       (Brillouin's theorem), so the first operator is always a double; and
     * every fermionic double Trotterises to the SAME 48-CNOT block at this
       system size, so the doubles that do have a gradient are all equal cost.

   With grad numerator varying but cost denominator constant across the
   operators that can actually be chosen, `grad / (1 + lam*cost)` is a
   monotonic rescaling of `grad`: argmax is unchanged, for every lambda.
   Confirmed by diagnostic on H2 and LiH(2e,3o).

   The fix: expand each fermionic generator into its individual JW Pauli
   strings and let ADAPT pick one Pauli rotation exp(-i theta P) at a time.
   A weight-w Pauli string costs 2*(w-1) CNOTs, and the JW Z-strings are
   RETAINED so weight grows with the orbital-index span of the source
   excitation. Cost now takes several distinct values among operators with
   comparable, nonzero gradient, which is the variation the scoring rule
   exists to exploit. lambda=0 still reproduces standard ADAPT on the same
   pool exactly (selftest checks this).

   Caveat for the writeup: an individual Pauli rotation is not
   particle-number preserving the way a full fermionic excitation is, so the
   ADAPT state can carry small support outside the HF particle-number sector.
   selftest() reports <N> of the converged state; the analysis flags any
   energy below the active-space FCI reference.

2. Noise is applied AFTER decomposition to the canonical gate set.
   qml.add_noise matches on operations present in the tape; an undecomposed
   tape contains FermionicDoubleExcitation, which matches none of the
   RX/RY/RZ/CNOT conditions, so the noise model would silently apply NOTHING
   and every noise sweep would be a flat line. The QNode is therefore built as
   decompose -> add_noise, and _assert_noise_is_applied() verifies at runtime
   that noise actually moved the energy.

GRADIENTS: DEVIATION FROM THE BRIEF, AND WHY
--------------------------------------------
The brief asked for backprop through the circuit. That is NOT usable here:

    default.mixed + diff_method="backprop" returns NaN for every gradient
    in this environment (PennyLane 0.45.1 / NumPy 2.5.2 / CPython 3.14).

It fails silently -- the forward energy stays exactly correct, so the circuit
looks fine and only the gradients are poisoned. Measured on a two-gate
RY/CNOT circuit with no state preparation at all:

    device          backprop   parameter-shift   finite-diff
    default.qubit   OK         OK                OK
    default.mixed   NaN        OK                OK

Since Option A must run on a mixed-state device (noise channels require it),
backprop is off the table. What is used instead:

  * OPERATOR SELECTION (the scored quantity -- must be exact): the derivative
    w.r.t. the trailing candidate parameter at theta=0. Available as
    PennyLane's exact parameter-shift rule, or as a central difference.
    Both were checked to agree to ~1e-8 WITH noise channels present;
    selftest() re-verifies this. Central difference is the default because
    parameter-shift costs 4.2 s vs 0.56 s per candidate on 6-qubit LiH, and
    the selection rule only needs the ordering of scores.

  * PARAMETER RE-OPTIMIZATION: COBYLA, gradient-free. Besides avoiding an
    enormous gradient bill inside the optimizer loop, this is the SAME
    optimizer Option B uses, so any Option A vs B difference cannot be
    attributed to the optimizer.

At theta=0 the selection derivative equals the ADAPT commutator gradient
<psi|[H, A]|psi>, which is what the brief asked to score on.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import numpy as np
import pennylane as qml
from pennylane import numpy as pnp

import molecules as mol
import noise_models as nz

warnings.filterwarnings("ignore")

# Gate set both frameworks are held to (mirrors qiskit_baselines.CANONICAL_BASIS).
CANONICAL_GATE_SET = {
    "RX", "RY", "RZ", "Hadamard", "PauliX", "PauliY", "PauliZ",
    "CNOT", "S", "T", "SX", "GlobalPhase", "Identity",
}

DEFAULT_LAMBDA = 1.0          # the weight in the (1 + lam*cost) denominator
# The qubit-ADAPT pool grows the ansatz one Pauli rotation at a time rather
# than one whole excitation, so it needs more operators than the old fermionic
# pool (which used 8). run_experiments.py overrides this with a smaller value
# to keep the noisy sweep tractable.
DEFAULT_MAX_OPERATORS = 16
DEFAULT_GRAD_TOL = 1e-3
DEFAULT_OPT_MAXITER = 200
# Energy-improvement stop. The gradient-norm criterion alone is unusable under
# noise: the candidate-gradient ESTIMATE is floored at roughly the gate-error
# rate (~1e-2), so grad_norm never falls below DEFAULT_GRAD_TOL and the loop
# always runs to max_operators, piling noisy operators onto a circuit that was
# already converged. So the loop also tracks the best energy seen and stops
# after DEFAULT_PATIENCE consecutive operators that each fail to beat it by at
# least DEFAULT_ENERGY_TOL, then rolls back to that best state. The tolerance
# is deliberately tiny -- it must not veto the sub-mHa tail improvements that
# a noiseless run legitimately takes on the way to FCI; it only fires when an
# operator does not help at all, which is the noisy failure mode. Applied
# identically to both selection rules, so lam=0 still reproduces standard
# ADAPT exactly.
DEFAULT_ENERGY_TOL = 1e-5
DEFAULT_PATIENCE = 2

# ----------------------------------------------------------------------------
# NOVEL selection rules (this project's contribution; not in the ADAPT
# literature surveyed in IMPROVEMENTS.md).
#
#   selection="noise_realized"
#       The gradient is a NOISE-BLIND predictor of an operator's benefit, and
#       under noise its estimate is floored at the gate-error rate so it barely
#       ranks operators at all. Instead: gradient-screen to the top
#       DEFAULT_N_CANDIDATES operators, actually append each, re-optimise UNDER
#       THE NOISE CHANNEL, and score by the energy it REALLY buys, cost-
#       penalised:
#           score(op) = max(0, E_now - E_after_op) / (1 + lam * cnot_cost(op))
#       i.e. realised improvement per unit of added cost, measured not
#       predicted.
#
#   adaptive_lambda=True   (self-tuning resource penalty)
#       lam is not a fixed hyperparameter but a controller state. After each
#       accepted operator, if its realised improvement was small (ADAPT has
#       entered the noise-dominated diminishing-returns tail) lam is pushed up
#       so the rule leans harder toward cheap operators; if the operator
#       delivered, lam relaxes. Multiplicative update toward a target
#       per-operator improvement, clamped to [LAMBDA_MIN, LAMBDA_MAX].
# ----------------------------------------------------------------------------
DEFAULT_N_CANDIDATES = 4          # gradient-screened shortlist for noise_realized
ADAPT_LAMBDA_TARGET_DE = 1e-3     # per-operator improvement the controller aims at
ADAPT_LAMBDA_GAIN = 0.3           # controller exponent (gentle)
LAMBDA_MIN, LAMBDA_MAX = 0.0, 8.0

# "central"         -- central difference on the candidate parameter (fast)
# "parameter-shift" -- PennyLane's exact analytic rule (slower, reference)
# Both verified to agree to ~1e-8 with noise present; see selftest().
DEFAULT_GRAD_METHOD = "central"
CENTRAL_DIFF_STEP = 1e-5


# ==========================================================================
# Operator pool
# ==========================================================================
@dataclass
class PoolOperator:
    label: str
    kind: str                  # "single" | "double" -- source excitation class
    pauli_word: str            # e.g. "YXZZXX" (no identities), len == len(wires)
    wires: list                # wires the word acts on, ascending
    cnot_cost: int

    def make(self, theta):
        """
        Build the underlying PennyLane operator WITHOUT assuming a queuing
        context. Needed because resource counting happens outside any QNode,
        where a PoolOperator is just a wrapper and would otherwise be handed
        straight to the decomposer.

        exp(-i theta/2 * P) for a single Pauli string P -- the qubit-ADAPT
        pool element. See module docstring note 1.
        """
        return qml.PauliRot(theta, self.pauli_word, wires=self.wires)

    def apply(self, theta):
        """Queue the operator inside a QNode."""
        self.make(theta)


def materialize(pool_ops, params=None):
    """PoolOperator wrappers -> concrete PennyLane operators."""
    if params is None:
        params = [0.1] * len(pool_ops)
    return [op.make(float(t)) for op, t in zip(pool_ops, params)]


def _decompose_ops(ops):
    """Decompose a list of operations into the canonical gate set."""
    tape = qml.tape.QuantumScript(ops, [])
    (new_tape,), _ = qml.transforms.decompose([tape], gate_set=CANONICAL_GATE_SET)
    return list(new_tape.operations)


def _resources(ops, n_wires) -> dict:
    """
    CNOT count and circuit depth of `ops` after decomposition.

    Depth uses the standard per-wire layering definition (the same one
    Qiskit's QuantumCircuit.depth() uses) so the depth columns from the two
    frameworks mean the same thing.
    """
    flat = _decompose_ops(ops)
    frontier = {w: 0 for w in range(n_wires)}
    cnots = 0
    for op in flat:
        ws = [int(w) for w in op.wires]
        if not ws:
            continue
        layer = max(frontier[w] for w in ws) + 1
        for w in ws:
            frontier[w] = layer
        if op.name == "CNOT":
            cnots += 1
    return {"depth": max(frontier.values()) if frontier else 0,
            "cnot_count": cnots,
            "gate_count": len(flat)}


def _pauli_children(gen) -> list[tuple[str, list]]:
    """
    Distinct Pauli words of a Jordan-Wigner-mapped anti-Hermitian generator,
    each as (word_string, wires). Identity terms are dropped; the sign of the
    coefficient is absorbed into the rotation angle so it is discarded here.
    """
    jw = qml.jordan_wigner(gen)
    try:
        _, ops = jw.terms()
    except (AttributeError, ValueError):
        return []
    out: list[tuple[str, list]] = []
    for o in ops:
        ps = qml.pauli.pauli_sentence(o)
        words = list(ps.keys())
        if len(words) != 1:
            continue
        pw = words[0]
        if len(pw) == 0:                       # pure identity
            continue
        wires = sorted(int(w) for w in pw.wires)
        word = "".join(pw[w] for w in wires)
        out.append((word, wires))
    return out


def build_pool(spec: mol.MoleculeSpec) -> list[PoolOperator]:
    """
    qubit-ADAPT pool (Tang et al., PRX Quantum 2, 020310): the individual
    Jordan-Wigner Pauli-string rotations that make up the fermionic UCCSD
    singles and doubles generators, each as its own exp(-i theta P) pool
    operator.

    The JW Z-strings are RETAINED, so a Pauli word's weight -- hence its CNOT
    cost, 2*(weight-1) -- grows with the orbital-index span of the excitation
    it came from. That spread of cost across operators with comparable,
    nonzero gradient is exactly what the fermionic-excitation pool lacked and
    what the resource-aware score needs; see module docstring note 1.
    """
    from pennylane.fermi import FermiWord

    _, n_qubits, _, n_elec = mol.pennylane_hamiltonian(spec)
    singles, doubles = qml.qchem.excitations(n_elec, n_qubits)

    seen: set[str] = set()
    pool: list[PoolOperator] = []

    def _add(children, kind):
        for word, wires in children:
            key = f"{word}:{tuple(wires)}"
            if key in seen:
                continue
            seen.add(key)
            cost = _resources(
                [qml.PauliRot(0.1, word, wires=list(wires))], n_qubits
            )["cnot_count"]
            pool.append(PoolOperator(
                label=f"{kind[0].upper()}:{word}@{''.join(map(str, wires))}",
                kind=kind, pauli_word=word, wires=list(wires), cnot_cost=cost,
            ))

    for (r, p) in singles:
        w = FermiWord({(0, p): "+", (1, r): "-"})
        _add(_pauli_children(w - w.adjoint()), "single")

    for (s, r, q, p) in doubles:
        w = FermiWord({(0, q): "+", (1, p): "+", (2, r): "-", (3, s): "-"})
        _add(_pauli_children(w - w.adjoint()), "double")

    return pool


# ==========================================================================
# Circuit / QNode construction
# ==========================================================================
def _make_qnode(spec, noise: nz.NoiseSpec, selected: list[PoolOperator],
                trailing: PoolOperator | None = None,
                diff_method: str | None = None):
    """
    QNode for <H>, one parameter per selected operator plus an optional
    trailing candidate used for gradient screening.

    Order is decompose -> add_noise; see module docstring note 2.
    """
    H, n_qubits, hf, _ = mol.pennylane_hamiltonian(spec)
    dev = qml.device("default.mixed", wires=n_qubits)
    ops = list(selected) + ([trailing] if trailing is not None else [])

    # requires_grad=False is essential. pnp.array() defaults to requires_grad
    # True, and autograd then tries to differentiate through the integer
    # occupation-number state of BasisState. That does not raise -- it
    # silently returns NaN for EVERY gradient, which propagates through
    # L-BFGS-B and yields NaN energies while the forward pass still looks
    # perfectly correct.
    hf_state = pnp.array(hf, requires_grad=False)

    def circuit(params):
        qml.BasisState(hf_state, wires=range(n_qubits))
        for theta, op in zip(params, ops):
            op.apply(theta)
        return qml.expval(H)

    # NOTE: diff_method is deliberately NOT "backprop" -- it returns NaN on
    # default.mixed in this environment (see module docstring).
    qnode = qml.QNode(circuit, dev, interface="autograd",
                      diff_method=diff_method or "parameter-shift")
    qnode = qml.transforms.decompose(qnode, gate_set=CANONICAL_GATE_SET)
    pl_nm = nz.pennylane_noise_model(noise)
    if pl_nm is not None:
        qnode = qml.add_noise(qnode, pl_nm)
    return qnode


def _assert_noise_is_applied(spec, noise: nz.NoiseSpec) -> bool:
    """
    Guard against the silent-no-op failure mode in module docstring note 2:
    if decomposition and noise insertion are ordered wrongly the 'noisy'
    energy equals the noiseless one exactly, and every noise sweep would be a
    flat line that looks like a result.
    """
    if noise.is_noiseless:
        return True
    pool = build_pool(spec)
    probe = [pool[-1]]
    p = pnp.array([0.3], requires_grad=True)
    clean = nz.make_noise_levels(scales=(0.0,))[0]
    e_clean = float(_make_qnode(spec, clean, probe)(p))
    e_noisy = float(_make_qnode(spec, noise, probe)(p))
    return abs(e_noisy - e_clean) > 1e-12


# ==========================================================================
# The ADAPT loop
# ==========================================================================
def _optimize(qnode, x0, maxiter=DEFAULT_OPT_MAXITER):
    """
    Re-optimize all parameters with COBYLA (gradient-free).

    Deliberately gradient-free for two reasons: an exact-gradient call costs
    ~4 s per parameter on 6-qubit noisy LiH, which inside an L-BFGS loop runs
    to hours per ADAPT step; and Option B's VQE also uses COBYLA, so keeping
    the same optimizer here means an Option A vs B difference cannot be
    blamed on the optimizer.
    """
    from scipy.optimize import minimize

    def fun(x):
        return float(qnode(pnp.array(np.asarray(x, dtype=float),
                                     requires_grad=False)))

    res = minimize(fun, np.asarray(x0, dtype=float), method="COBYLA",
                   options={"maxiter": maxiter})
    return np.asarray(res.x, dtype=float), float(res.fun), int(
        getattr(res, "nfev", 0))


def _candidate_gradient(spec, noise, selected, params, cand,
                        method=DEFAULT_GRAD_METHOD) -> float:
    """
    |d<H>/dtheta_c| at theta_c = 0 for one candidate.

    At theta_c = 0 this equals the ADAPT commutator gradient
    <psi|[H, A_c]|psi>. Two interchangeable estimators (see module docstring):
      "parameter-shift" -- PennyLane's exact analytic rule
      "central"         -- central difference on theta_c only (default, ~7x faster)
    """
    if method == "parameter-shift":
        qnode = _make_qnode(spec, noise, selected, trailing=cand,
                            diff_method="parameter-shift")
        x = pnp.array(list(params) + [0.0], requires_grad=True)
        g = np.asarray(qml.grad(qnode)(x), dtype=float)
        val = float(g[-1])
    elif method == "central":
        qnode = _make_qnode(spec, noise, selected, trailing=cand)
        h = CENTRAL_DIFF_STEP
        base = list(params)

        def at(t):
            return float(qnode(pnp.array(np.array(base + [t]),
                                         requires_grad=False)))

        val = (at(+h) - at(-h)) / (2.0 * h)
    else:
        raise ValueError(f"unknown grad method: {method}")

    # A non-finite gradient is a silent killer here: the forward energy stays
    # correct, so nothing looks wrong until the optimizer returns NaN. This is
    # exactly what diff_method="backprop" does on default.mixed. Fail loudly.
    if not np.isfinite(val):
        raise FloatingPointError(
            f"non-finite gradient for candidate {cand.label} using "
            f"method={method!r}. Note that backprop on default.mixed is known "
            "to return NaN in this environment."
        )
    return abs(val)


def _candidate_gradients(spec, noise, selected, params, pool,
                         method=DEFAULT_GRAD_METHOD):
    """Gradient magnitude for every candidate in the pool."""
    return np.array([
        _candidate_gradient(spec, noise, selected, params, c, method)
        for c in pool
    ])


_SELECTIONS = ("standard", "resource_aware", "noise_realized")


def _adapt_loop(spec, noise, selection: str, lam: float = DEFAULT_LAMBDA,
                max_operators: int = DEFAULT_MAX_OPERATORS,
                grad_tol: float = DEFAULT_GRAD_TOL,
                energy_tol: float = DEFAULT_ENERGY_TOL,
                patience: int = DEFAULT_PATIENCE,
                opt_maxiter: int = DEFAULT_OPT_MAXITER,
                grad_method: str = DEFAULT_GRAD_METHOD,
                n_candidates: int = DEFAULT_N_CANDIDATES,
                adaptive_lambda: bool = False,
                fixed_k: int | None = None,
                verbose: bool = False) -> dict:
    """
    Shared ADAPT driver. `selection` in {'standard', 'resource_aware',
    'noise_realized'} is the ONLY difference between the baseline and the
    contributions.

        standard        score(op) = |grad(op)|
        resource_aware  score(op) = |grad(op)| / (1 + lam*cnot_cost(op))
        noise_realized  gradient-screen to the top `n_candidates`, re-optimise
                        each UNDER NOISE, then
                        score(op) = max(0, dE_realised(op)) /
                                    (1 + lam*cnot_cost(op))
                        -- realised improvement per cost, measured not predicted.

    `adaptive_lambda` (noise_realized only): after each accepted operator, nudge
    lam toward penalising cost more when the realised improvement is small (the
    noise-dominated tail) and less when operators still deliver. Clamped to
    [LAMBDA_MIN, LAMBDA_MAX].

    Two stopping criteria, applied to every rule identically:
      * gradient norm below `grad_tol` (the textbook ADAPT criterion), and
      * `patience` consecutive operators that each fail to beat the best energy
        seen so far by at least `energy_tol`; the loop then rolls back to that
        best state. The second one is what actually terminates the loop under
        noise, where the gradient estimate never gets small.

    `fixed_k` (int, default None): matched-circuit-length mode. When set, BOTH
    stopping criteria are disabled and the loop builds EXACTLY `fixed_k`
    operators, appending the top-scored candidate at every step whether or not
    it lowers the energy. This isolates "better operator *choice* at the same k"
    from "different ansatz length": every rule is forced to the same operator
    count, so a remaining energy-error gap is purely the selection rule picking
    a better operator. The returned `energy`/`operators` then describe the full
    k-operator circuit, not the best sub-circuit seen along the way.
    """
    if selection not in _SELECTIONS:
        raise ValueError(f"unknown selection rule: {selection}")
    if adaptive_lambda and selection != "noise_realized":
        raise ValueError("adaptive_lambda is only defined for noise_realized")
    fixed = fixed_k is not None
    if fixed and int(fixed_k) < 1:
        raise ValueError("fixed_k must be a positive integer when set")
    n_iters = int(fixed_k) if fixed else max_operators

    _, n_qubits, _, _ = mol.pennylane_hamiltonian(spec)
    e_fci = mol.fci_energy(spec)
    pool = build_pool(spec)
    costs = np.array([op.cnot_cost for op in pool], dtype=float)

    t0 = time.time()
    selected: list[PoolOperator] = []
    params: list[float] = []
    energy = float(_make_qnode(spec, noise, [])(pnp.array([])))
    chosen_labels: list[str] = []
    converged = False

    lam_cur = float(lam)
    lam_traj = [lam_cur]

    # Best state seen so far -- what gets returned. Extra non-improving
    # operators explored past this point are rolled back.
    best = {"energy": energy, "selected": [], "params": [], "labels": []}
    banned: set[int] = set()          # tried since the last improvement

    def _optimise_trial(op_index):
        trial_ops = best["selected"] + [pool[op_index]]
        qn = _make_qnode(spec, noise, trial_ops)
        x0 = np.append(np.asarray(best["params"], dtype=float), 0.0)
        op_p, e_p, _ = _optimize(qn, x0, opt_maxiter)
        return list(op_p), float(e_p)

    for it in range(n_iters):
        grads = _candidate_gradients(spec, noise, best["selected"],
                                     best["params"], pool, method=grad_method)
        grad_norm = float(np.linalg.norm(grads))
        if not fixed and grad_norm < grad_tol:
            converged = True
            break

        if selection in ("standard", "resource_aware"):
            scores = (grads.copy() if selection == "standard"
                      else grads / (1.0 + lam_cur * costs))
            for b in banned:
                scores[b] = -np.inf
            pick = int(np.argmax(scores))
            opt_params, trial_energy = _optimise_trial(pick)
        else:  # noise_realized
            # In fixed_k mode the grad_tol screen is dropped so a step can never
            # run out of candidates -- exactly k operators must be produced.
            shortlist = [int(i) for i in np.argsort(grads)[::-1]
                         if i not in banned and (fixed or grads[i] > grad_tol)]
            shortlist = shortlist[:max(1, n_candidates)]
            if not shortlist:
                converged = True
                break
            realised, cand_opt, cand_e = [], [], []
            for i in shortlist:
                op_p, e_p = _optimise_trial(i)
                cand_opt.append(op_p)
                cand_e.append(e_p)
                realised.append(best["energy"] - e_p)
            realised = np.asarray(realised, dtype=float)
            cscore = np.maximum(realised, 0.0) / (
                1.0 + lam_cur * costs[shortlist])
            j = int(np.argmax(cscore))
            pick = shortlist[j]
            opt_params, trial_energy = cand_opt[j], cand_e[j]

        d_e = best["energy"] - trial_energy
        improved = d_e >= energy_tol
        # fixed_k mode: accept every pick unconditionally to reach exactly k.
        accept = improved or fixed
        if verbose:
            if fixed:
                tag = "keep" if improved else "force"
            else:
                tag = "keep" if improved else f"stale {len(banned) + 1}/{patience}"
            print(f"    it{it + 1:>2} +{pool[pick].label:<18} "
                  f"cx={pool[pick].cnot_cost:<3} |g|={grad_norm:.2e} "
                  f"lam={lam_cur:.2f} E={trial_energy:+.8f}  dE={d_e:+.2e}"
                  f"  {tag}")

        if accept:
            best = {"energy": trial_energy, "selected": best["selected"] + [pool[pick]],
                    "params": list(opt_params),
                    "labels": best["labels"]
                    + [f"{pool[pick].label}[cx={pool[pick].cnot_cost}]"]}
            banned = set()
            if adaptive_lambda:
                # Push lam up when the accepted operator barely helped (noise
                # tail), down when it delivered. Multiplicative, gentle, clamped.
                ratio = ADAPT_LAMBDA_TARGET_DE / max(d_e, 1e-9)
                lam_cur = float(np.clip(
                    lam_cur * ratio ** ADAPT_LAMBDA_GAIN
                    if lam_cur > 0 else ratio ** ADAPT_LAMBDA_GAIN,
                    LAMBDA_MIN, LAMBDA_MAX))
                lam_traj.append(lam_cur)
        else:
            banned.add(pick)
            if len(banned) >= patience:
                converged = True
                break

    selected = best["selected"]
    params = best["params"]
    chosen_labels = best["labels"]
    energy = best["energy"]

    res = (_resources(materialize(selected, params), n_qubits) if selected
           else {"depth": 0, "cnot_count": 0, "gate_count": 0})

    strategy = {
        "standard": "ADAPT-VQE(standard,PL)",
        "resource_aware": "ADAPT-VQE(resource-aware)",
        "noise_realized": ("ADAPT-VQE(noise-realized,adaptive-lam)"
                           if adaptive_lambda else "ADAPT-VQE(noise-realized)"),
    }[selection]
    option = {"standard": "A-baseline", "resource_aware": "A",
              "noise_realized": "A-novel"}[selection]
    return {
        "strategy": strategy,
        "framework": "pennylane",
        "option": option,
        "molecule": spec.label,
        "n_qubits": n_qubits,
        "noise_level": noise.label,
        "noise_scale": noise.scale,
        "comparable": noise.comparable,
        "energy": energy,
        "energy_error": abs(energy - e_fci),
        "fci_energy": e_fci,
        "n_parameters": len(params),
        "iterations": len(selected),
        "n_operators": len(selected),
        "converged": converged,
        "operators": " ".join(chosen_labels),
        "lambda": (None if selection == "standard" else lam_cur),
        "lambda_init": (None if selection == "standard" else float(lam)),
        "lambda_final": (None if selection == "standard" else lam_cur),
        "runtime_s": round(time.time() - t0, 2),
        **res,
    }


def standard_adapt_pennylane(spec, noise, **kw) -> dict:
    """Baseline rule: score = |gradient|. PennyLane reimplementation."""
    kw.pop("lam", None)
    kw.pop("adaptive_lambda", None)
    return _adapt_loop(spec, noise, "standard", **kw)


def resource_aware_adapt(spec, noise, lam: float = DEFAULT_LAMBDA, **kw) -> dict:
    """Prior contribution: score = |gradient| / (1 + lam * cnot_cost)."""
    kw.pop("adaptive_lambda", None)
    return _adapt_loop(spec, noise, "resource_aware", lam=lam, **kw)


def noise_realized_adapt(spec, noise, lam: float = DEFAULT_LAMBDA, **kw) -> dict:
    """
    NOVEL: gradient-screen to a shortlist, re-optimise each candidate under the
    noise channel, and select by realised improvement per unit cost,
    score = max(0, dE_realised) / (1 + lam * cnot_cost).
    """
    kw.pop("adaptive_lambda", None)
    return _adapt_loop(spec, noise, "noise_realized", lam=lam,
                       adaptive_lambda=False, **kw)


def noise_realized_adapt_adaptive_lambda(spec, noise,
                                         lam: float = DEFAULT_LAMBDA, **kw) -> dict:
    """
    NOVEL: noise_realized selection with a SELF-TUNING lam -- the resource
    penalty rises as ADAPT enters the noise-dominated diminishing-returns tail
    and relaxes while operators still deliver. `lam` is the initial value.
    """
    kw.pop("adaptive_lambda", None)
    return _adapt_loop(spec, noise, "noise_realized", lam=lam,
                       adaptive_lambda=True, **kw)


STRATEGIES = {
    "ADAPT-VQE(standard,PL)": standard_adapt_pennylane,
    "ADAPT-VQE(resource-aware)": resource_aware_adapt,
    "ADAPT-VQE(noise-realized)": noise_realized_adapt,
    "ADAPT-VQE(noise-realized,adaptive-lam)": noise_realized_adapt_adaptive_lambda,
}


# ==========================================================================
# Self-test
# ==========================================================================
def selftest(verbose: bool = True) -> bool:
    """
    Noiseless checks:
      1. Pool CNOT costs actually vary (else the new score is meaningless).
      2. Noise insertion is not a silent no-op.
      3. Both rules approach FCI with no noise.
      4. PennyLane standard ADAPT agrees with Qiskit's AdaptVQE (Option B),
         confirming both frameworks implement the same algorithm.
      5. SELECTION DIVERGENCE: at lambda=1 the resource-aware rule must pick a
         different operator sequence from standard ADAPT for at least one
         molecule -- otherwise the whole contribution is vacuous (this is the
         bug the qubit-ADAPT pool was introduced to fix).
      6. lambda=0 CONSISTENCY: resource_aware(lam=0) must reproduce standard
         ADAPT's operator sequence and energy exactly.
    """
    line = "-" * 94
    ok = True
    noiseless = nz.make_noise_levels(scales=(0.0,))[0]
    noisy = nz.make_noise_levels(scales=(2.0,))[-1]

    if verbose:
        print(line)
        print("OPTION A SELF-TEST")
        print(line)

    for spec in mol.BENCHMARK_MOLECULES:
        pool = build_pool(spec)
        costs = [op.cnot_cost for op in pool]
        spread = max(costs) - min(costs)
        good = spread > 0
        ok &= good
        if verbose:
            print(f"  {spec.label:<16} pool={len(pool):<3} "
                  f"CNOT cost min={min(costs):<4} max={max(costs):<4} "
                  f"spread={spread:<4} {'OK' if good else 'DEGENERATE'}")
    if verbose:
        print("  (zero spread would make gradient/(1+cost) a constant "
              "rescaling of gradient)")
        print()

    for spec in mol.BENCHMARK_MOLECULES:
        applied = _assert_noise_is_applied(spec, noisy)
        ok &= applied
        if verbose:
            print(f"  {spec.label:<16} noise actually applied: "
                  f"{'YES' if applied else 'NO -- SILENT NO-OP!'}")
    print()

    # The fast central-difference selection gradient must match PennyLane's
    # exact parameter-shift rule, WITH noise channels present.
    for spec in mol.BENCHMARK_MOLECULES:
        pool = build_pool(spec)
        cand = pool[-1]
        g_ps = _candidate_gradient(spec, noisy, [], [], cand, "parameter-shift")
        g_cd = _candidate_gradient(spec, noisy, [], [], cand, "central")
        agree = abs(g_ps - g_cd) < 1e-6
        ok &= agree
        if verbose:
            print(f"  {spec.label:<16} selection gradient  "
                  f"param-shift={g_ps:.10f}  central={g_cd:.10f}  "
                  f"{'AGREE' if agree else 'DISAGREE'}")
    if verbose:
        print()
        print(f"{'molecule':<16}{'strategy':<28}{'energy':>14}{'err/mHa':>10}"
              f"{'depth':>7}{'CNOT':>6}{'ops':>5}{'sec':>7}")
        print(line)

    results = {}
    for spec in mol.BENCHMARK_MOLECULES:
        for name, fn in STRATEGIES.items():
            r = fn(spec, noiseless)
            results[(spec.label, name)] = r
            err = r["energy_error"] * 1e3
            good = err < 5.0
            ok &= good
            if verbose:
                print(f"{spec.label:<16}{r['strategy']:<28}{r['energy']:>14.8f}"
                      f"{err:>10.3f}{r['depth']:>7}{r['cnot_count']:>6}"
                      f"{r['n_operators']:>5}{r['runtime_s']:>7.1f}"
                      f"  {'PASS' if good else 'HIGH'}")

    # -- check 5: selection divergence at lambda=1 --------------------------
    if verbose:
        print(line)
        print("Selection divergence  (resource-aware lam=1  vs  standard, "
              "noiseless):")
    any_diverged = False
    for spec in mol.BENCHMARK_MOLECULES:
        ops_std = results[(spec.label, "ADAPT-VQE(standard,PL)")]["operators"]
        ops_ra = results[(spec.label, "ADAPT-VQE(resource-aware)")]["operators"]
        diverged = ops_std != ops_ra
        any_diverged |= diverged
        if verbose:
            print(f"  {spec.label:<16} "
                  f"{'DIFFERENT selection' if diverged else 'identical selection'}")
            print(f"      standard : {ops_std}")
            print(f"      resrc-aw : {ops_ra}")
    ok &= any_diverged
    if verbose and not any_diverged:
        print("  FAIL: the two rules chose the same operators for every "
              "molecule -- the resource-aware score is still vacuous.")

    # -- check 6: lambda=0 reproduces standard ADAPT exactly ---------------
    if verbose:
        print(line)
        print("lambda=0 consistency  (resource_aware(lam=0) must == standard):")
    for spec in mol.BENCHMARK_MOLECULES:
        r_std = results[(spec.label, "ADAPT-VQE(standard,PL)")]
        r_l0 = resource_aware_adapt(spec, noiseless, lam=0.0)
        same_ops = r_std["operators"] == r_l0["operators"]
        same_e = abs(r_std["energy"] - r_l0["energy"]) < 1e-9
        good = same_ops and same_e
        ok &= good
        if verbose:
            print(f"  {spec.label:<16} ops match={same_ops}  "
                  f"|dE|={abs(r_std['energy'] - r_l0['energy']):.2e}  "
                  f"{'PASS' if good else 'FAIL'}")

    if verbose:
        print(line)
        print("Cross-framework agreement (PennyLane standard ADAPT vs Qiskit "
              "AdaptVQE, noiseless):")
    try:
        import qiskit_baselines as qb
        for spec in mol.BENCHMARK_MOLECULES:
            e_pl = results[(spec.label, "ADAPT-VQE(standard,PL)")]["energy"]
            e_qk = qb.run_adapt_vqe(spec, noiseless)["energy"]
            d = abs(e_pl - e_qk) * 1e3
            good = d < 5.0
            ok &= good
            if verbose:
                print(f"  {spec.label:<16} PL={e_pl:+.8f}  QK={e_qk:+.8f}  "
                      f"diff={d:7.3f} mHa  {'PASS' if good else 'MISMATCH'}")
    except Exception as exc:
        ok = False
        if verbose:
            print(f"  cross-check FAILED: {type(exc).__name__}: {exc}")

    if verbose:
        print(line)
        print("OVERALL: " + ("OPTION A OK" if ok else "CHECK FAILURES ABOVE"))
        print(line)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
