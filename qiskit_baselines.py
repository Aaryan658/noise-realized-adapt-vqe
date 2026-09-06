"""
qiskit_baselines.py -- OPTION B: baseline benchmark, NO NOVELTY CLAIMED.

Three published, off-the-shelf VQE ansatz strategies, run on the shared
Hamiltonians from molecules.py under the shared noise levels from
noise_models.py:

    (a) UCCSD                -- fixed, chemistry-derived ansatz
    (b) Hardware-efficient   -- EfficientSU2, hardware-native rotations
    (c) Standard ADAPT-VQE   -- qiskit_algorithms.AdaptVQE, selects operators
                                by RAW GRADIENT MAGNITUDE

(c) is the direct comparison target for Option A. Everything here is existing
published method; the contribution lives in
pennylane_resource_aware_adapt.py.

Simulation choice
-----------------
Expectation values are computed EXACTLY from the noisy density matrix
(shots=None / precision=0). There is therefore no shot noise anywhere in the
results. This is deliberate: the study is about how *coherent circuit depth
interacts with gate noise*, and shot noise would add a second, unrelated
error source scaling as 1/sqrt(shots) that would obscure the depth effect.
Stated plainly in the README so no one mistakes these for shot-limited results.

Metrics recorded per run: final energy, error vs active-space FCI, transpiled
circuit depth, CNOT count, parameter count, optimizer iterations.
"""

from __future__ import annotations

import time
import warnings

import numpy as np

import molecules as mol
import noise_models as nz

warnings.filterwarnings("ignore")

# Canonical basis for depth/CNOT accounting. All-to-all connectivity (no
# coupling map) so depth reflects the ANSATZ, not device routing -- matching
# the footing used on the PennyLane side.
CANONICAL_BASIS = ["rx", "ry", "rz", "h", "x", "sx", "cx"]

DEFAULT_MAXITER = 300
HEA_MAXITER = 600         # per restart; see run_hardware_efficient
HEA_RESTARTS = 3          # best-of-N; first restart is the HF point


# ==========================================================================
# Estimator plumbing
# ==========================================================================
class _TranspilingEstimatorV2:
    """
    Wraps Aer's EstimatorV2 and transpiles each circuit to a concrete basis
    before execution.

    Needed because UCCSD (and the ansatz AdaptVQE grows) is an
    EvolvedOperatorAnsatz containing a high-level 'EvolvedOps' instruction
    that Aer cannot execute directly -- it raises
    AerError: 'unknown instruction: EvolvedOps'.

    Pre-transpiling the ansatz once outside is not an option for ADAPT: the
    algorithm must keep appending operators to a live EvolvedOperatorAnsatz,
    so the decomposition has to happen at call time instead.

    Transpilation is cached (VQE re-runs the same circuit once per optimizer
    iteration, only rebinding parameters, so without a cache we would
    re-transpile hundreds of times).

    The cache key includes the circuit's CONTENT, not just its identity.
    AdaptVQE grows its ansatz by MUTATING the same EvolvedOperatorAnsatz
    object in place, so id() alone is stable across ADAPT iterations while
    the circuit actually changes -- an identity-keyed cache silently returns
    a stale circuit with the wrong parameter count, which surfaces much later
    as an opaque "primitive job to evaluate the energy failed". Including
    num_parameters and instruction count invalidates the entry whenever the
    ansatz grows. A reference to the circuit is retained so a
    garbage-collected id() cannot be reused for a different circuit.
    """

    def __init__(self, inner, basis):
        self._inner = inner
        self._basis = basis
        self._cache: dict[tuple, tuple] = {}

    def _prepare(self, circuit):
        key = (id(circuit), circuit.num_parameters, len(circuit.data))
        hit = self._cache.get(key)
        if hit is not None and hit[0] is circuit:
            return hit[1]
        from qiskit import transpile
        out = transpile(circuit, basis_gates=self._basis, optimization_level=1)
        self._cache[key] = (circuit, out)   # keep circuit alive
        return out

    def run(self, pubs, **kwargs):
        rebuilt = []
        for pub in pubs:
            circuit, *rest = pub
            rebuilt.append((self._prepare(circuit), *rest))
        return self._inner.run(rebuilt, **kwargs)

    def __getattr__(self, item):
        return getattr(self._inner, item)


def _make_estimator(spec: nz.NoiseSpec):
    """Aer EstimatorV2 wired to the given noise level, exact expectations."""
    from qiskit_aer.primitives import EstimatorV2

    backend_options = {"method": "density_matrix"}
    nm = nz.qiskit_noise_model(spec)
    if nm is not None:
        backend_options["noise_model"] = nm

    inner = EstimatorV2(options={
        "backend_options": backend_options,
        "default_precision": 0.0,   # exact -- no shot noise
    })
    return _TranspilingEstimatorV2(inner, CANONICAL_BASIS)


def circuit_metrics(circuit, params=None) -> dict:
    """Transpile to the canonical basis and measure depth / CNOT count."""
    from qiskit import transpile

    qc = circuit
    if params is not None and qc.num_parameters:
        try:
            qc = qc.assign_parameters(np.asarray(params, dtype=float))
        except Exception:
            pass
    try:
        t = transpile(qc, basis_gates=CANONICAL_BASIS, optimization_level=1)
        ops = t.count_ops()
        return {
            "depth": int(t.depth()),
            "cnot_count": int(ops.get("cx", 0)),
            "gate_count": int(sum(ops.values())),
        }
    except Exception:
        return {"depth": -1, "cnot_count": -1, "gate_count": -1}


def _optimizer(maxiter: int):
    """
    COBYLA: gradient-free. Under a noisy density-matrix simulation the energy
    surface is smooth but biased; gradient-based methods chase the biased
    minimum and stall. COBYLA is the standard robust choice here.
    """
    from qiskit_algorithms.optimizers import COBYLA
    return COBYLA(maxiter=maxiter)


# ==========================================================================
# Ansatz builders
# ==========================================================================
def build_uccsd(spec: mol.MoleculeSpec):
    from qiskit_nature.second_q.circuit.library import UCCSD, HartreeFock
    from qiskit_nature.second_q.mappers import JordanWignerMapper

    _, _, num_particles, n_so = mol.qiskit_hamiltonian(spec)
    mapper = JordanWignerMapper()
    init = HartreeFock(n_so, num_particles, mapper)
    return UCCSD(n_so, num_particles, mapper, initial_state=init)


def build_hardware_efficient(spec: mol.MoleculeSpec, reps: int = 2):
    """
    EfficientSU2 with linear entanglement, prepended with the HF state so it
    starts from the same reference as the chemistry-derived ansatze.
    """
    from qiskit.circuit.library import EfficientSU2
    from qiskit_nature.second_q.circuit.library import HartreeFock
    from qiskit_nature.second_q.mappers import JordanWignerMapper

    op, _, num_particles, n_so = mol.qiskit_hamiltonian(spec)
    n_qubits = op.num_qubits
    init = HartreeFock(n_so, num_particles, JordanWignerMapper())
    hea = EfficientSU2(n_qubits, su2_gates=["ry", "rz"],
                       entanglement="linear", reps=reps)
    return init.compose(hea)


# ==========================================================================
# Runners
# ==========================================================================
def _run_fixed_ansatz(name, spec, noise, ansatz, maxiter, initial_point=None):
    """Shared VQE driver for UCCSD and the hardware-efficient ansatz."""
    from qiskit_algorithms import VQE

    op, core, _, _ = mol.qiskit_hamiltonian(spec)
    e_fci = mol.fci_energy(spec)

    t0 = time.time()
    estimator = _make_estimator(noise)
    n_params = ansatz.num_parameters

    if initial_point is None:
        initial_point = np.zeros(n_params)

    counter = {"n": 0}

    def cb(*_args, **_kw):
        counter["n"] += 1

    vqe = VQE(estimator, ansatz, _optimizer(maxiter),
              initial_point=np.asarray(initial_point, dtype=float), callback=cb)
    res = vqe.compute_minimum_eigenvalue(op)
    energy = float(np.real(res.eigenvalue)) + core

    metrics = circuit_metrics(ansatz, res.optimal_point)
    return {
        "strategy": name,
        "framework": "qiskit",
        "option": "B",
        "molecule": spec.label,
        "n_qubits": op.num_qubits,
        "noise_level": noise.label,
        "noise_scale": noise.scale,
        "comparable": noise.comparable,
        "energy": energy,
        "energy_error": abs(energy - e_fci),
        "fci_energy": e_fci,
        "n_parameters": int(n_params),
        "iterations": counter["n"],
        "n_operators": int(n_params),
        "runtime_s": round(time.time() - t0, 2),
        **metrics,
    }


def run_uccsd(spec, noise, maxiter: int = DEFAULT_MAXITER) -> dict:
    """(a) Fixed UCCSD ansatz."""
    return _run_fixed_ansatz("UCCSD", spec, noise, build_uccsd(spec), maxiter)


def run_hardware_efficient(spec, noise, reps: int = 2,
                           maxiter: int = HEA_MAXITER, seed: int = 7,
                           n_restarts: int = HEA_RESTARTS) -> dict:
    """
    (b) Hardware-efficient ansatz (EfficientSU2), best of several restarts.

    Three deviations from the UCCSD/ADAPT settings, all necessary rather than
    cosmetic:

      * MULTIPLE RESTARTS, keeping the lowest energy. EfficientSU2 is a
        generic ansatz on a rugged energy surface and a single COBYLA run
        lands in whatever local minimum is nearest. Observed directly: a
        single seeded start on LiH converged (by COBYLA's own criterion, in
        1414 iterations) to 21.6 mHa error -- ABOVE the Hartree-Fock energy
        at 16.3 mHa. Since the ansatz contains the identity, its true
        variational minimum cannot exceed HF, so that number was an optimizer
        artifact being reported as an ansatz property.

      * The FIRST restart is the all-zero point, which is exactly the HF
        state. This makes the reported HEA energy provably <= E_HF, so the
        baseline can never come out worse than doing nothing.

      * Higher iteration budget. HEA carries many more parameters than UCCSD
        (24 vs 3 for H2) and COBYLA needs O(n) evaluations per improvement,
        so the shared 300-iteration budget would not be a fair comparison.

    HEA is still expected to underperform the chemistry-derived ansatze --
    that is the honest baseline result, and it is what the literature reports
    -- but it must underperform because of the ansatz, not because the
    optimizer stalled.
    """
    ansatz = build_hardware_efficient(spec, reps)
    rng = np.random.default_rng(seed)

    best = None
    total_iters = 0
    total_time = 0.0
    for k in range(max(1, n_restarts)):
        x0 = (np.zeros(ansatz.num_parameters) if k == 0
              else rng.normal(scale=0.25, size=ansatz.num_parameters))
        r = _run_fixed_ansatz(f"HEA(reps={reps})", spec, noise,
                              ansatz, maxiter, initial_point=x0)
        total_iters += r["iterations"]
        total_time += r["runtime_s"]
        if best is None or r["energy"] < best["energy"]:
            best = r

    # Report the work actually done across all restarts, not just the winner --
    # otherwise HEA looks cheaper than it is next to the other strategies.
    best["iterations"] = total_iters
    best["runtime_s"] = round(total_time, 2)
    best["n_restarts"] = max(1, n_restarts)
    return best


def run_adapt_vqe(spec, noise, maxiter: int = DEFAULT_MAXITER,
                  max_adapt_iter: int = 10,
                  gradient_threshold: float = 1e-3) -> dict:
    """
    (c) Standard ADAPT-VQE via qiskit_algorithms.AdaptVQE.

    Operator selection is by RAW GRADIENT MAGNITUDE -- this is the published
    baseline that Option A's resource-aware scoring is compared against.
    """
    from qiskit_algorithms import VQE, AdaptVQE

    op, core, _, _ = mol.qiskit_hamiltonian(spec)
    e_fci = mol.fci_energy(spec)

    t0 = time.time()
    ansatz = build_uccsd(spec)     # UCCSD provides the operator pool
    estimator = _make_estimator(noise)

    vqe = VQE(estimator, ansatz, _optimizer(maxiter),
              initial_point=np.zeros(ansatz.num_parameters))
    adapt = AdaptVQE(vqe,
                     gradient_threshold=gradient_threshold,
                     max_iterations=max_adapt_iter)
    res = adapt.compute_minimum_eigenvalue(op)
    energy = float(np.real(res.eigenvalue)) + core

    # The adaptively grown circuit, not the full UCCSD pool.
    final_ansatz = getattr(res, "optimal_circuit", None) or ansatz
    opt_point = getattr(res, "optimal_point", None)
    metrics = circuit_metrics(final_ansatz, opt_point)

    hist = getattr(res, "eigenvalue_history", None) or []
    n_ops = len(hist)
    return {
        "strategy": "ADAPT-VQE(standard)",
        "framework": "qiskit",
        "option": "B",
        "molecule": spec.label,
        "n_qubits": op.num_qubits,
        "noise_level": noise.label,
        "noise_scale": noise.scale,
        "comparable": noise.comparable,
        "energy": energy,
        "energy_error": abs(energy - e_fci),
        "fci_energy": e_fci,
        "n_parameters": int(getattr(final_ansatz, "num_parameters", 0)),
        "iterations": n_ops,
        "n_operators": n_ops,
        "runtime_s": round(time.time() - t0, 2),
        **metrics,
    }


STRATEGIES = {
    "UCCSD": run_uccsd,
    "HEA": run_hardware_efficient,
    "ADAPT-VQE(standard)": run_adapt_vqe,
}


# ==========================================================================
# Smoke test: noiseless runs must land close to FCI
# ==========================================================================
def smoke_test(verbose: bool = True) -> bool:
    """Noiseless sanity check -- every baseline should approach FCI."""
    noiseless = nz.make_noise_levels(scales=(0.0,))[0]
    line = "-" * 92
    ok = True

    if verbose:
        print(line)
        print("OPTION B SMOKE TEST (noiseless) -- baselines should approach FCI")
        print(line)
        print(f"{'molecule':<16}{'strategy':<22}{'energy':>14}{'err/mHa':>10}"
              f"{'depth':>7}{'CNOT':>6}{'iters':>7}{'sec':>7}")

    for spec in mol.BENCHMARK_MOLECULES:
        for name, fn in STRATEGIES.items():
            try:
                r = fn(spec, noiseless)
                err = r["energy_error"] * 1e3
                # HEA is not expected to be chemically accurate; UCCSD/ADAPT are.
                limit = 50.0 if r["strategy"].startswith("HEA") else 5.0
                good = err < limit
                ok &= good
                if verbose:
                    print(f"{spec.label:<16}{r['strategy']:<22}"
                          f"{r['energy']:>14.8f}{err:>10.3f}{r['depth']:>7}"
                          f"{r['cnot_count']:>6}{r['iterations']:>7}"
                          f"{r['runtime_s']:>7.1f}  {'PASS' if good else 'HIGH'}")
            except Exception as exc:
                ok = False
                if verbose:
                    print(f"{spec.label:<16}{name:<22}  FAIL "
                          f"{type(exc).__name__}: {str(exc)[:70]}")

    if verbose:
        print(line)
        print("OVERALL: " + ("OPTION B BASELINES OK" if ok
                             else "CHECK FAILURES ABOVE"))
        print(line)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if smoke_test() else 1)
