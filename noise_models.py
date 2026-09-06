"""
noise_models.py -- noise on an EQUIVALENT FOOTING for Qiskit and PennyLane.

THE COMPARABILITY PROBLEM (read this before trusting any Option A vs B plot)
===========================================================================
The brief asked to flag whether Qiskit-side and PennyLane-side noise are
"reasonably comparable". Investigated; the honest answer is:

    Feeding a FakeBackend NoiseModel straight into Qiskit while running
    PennyLane on default.mixed does NOT give a comparable footing, even
    though both are "realistic IBM noise".

Three independent reasons:

  1. GATE BASIS. Aer applies error per *native* gate after transpilation
     (FakeManilaV2: cx/sx/x/rz; FakeSherbrooke: ecr/sx/x/rz). PennyLane
     applies error to whatever ops are on the tape. The same logical circuit
     becomes a different number of noisy gates, so "the same noise model"
     produces a different total error budget.

  2. ROUTING. Transpiling to a real coupling map inserts SWAPs (each = 3 CNOTs).
     FakeSherbrooke is a 127-qubit heavy-hex device; a 6-qubit circuit picks up
     substantial routing overhead. PennyLane assumes all-to-all connectivity and
     inserts nothing. Depth, and therefore accumulated error, diverges badly.

  3. READOUT ERROR. qml.from_qiskit_noise does NOT transfer Qiskit's
     ReadoutError (it is classical post-processing, not a Kraus channel).
     Verified: FakeManilaV2 carries 5 readout errors, FakeSherbrooke 127, and
     none of them survive the conversion.

WHAT THIS MODULE DOES INSTEAD
=============================
It separates the two jobs that were conflated:

  (A) HEADLINE COMPARISON (used for Option A vs Option B).
      A framework-independent `NoiseSpec`: depolarizing channels with rates
      *calibrated from real IBM backend data* (median gate errors read off
      FakeManilaV2 / FakeSherbrooke), applied to the SAME canonical gate basis
      {RX,RY,RZ,H,CNOT} with all-to-all connectivity on both sides.

      The PennyLane channels are built from Kraus operators that reproduce
      Qiskit's depolarizing convention EXACTLY (not approximately -- the
      2-qubit channel is the true 16-Kraus channel, not two 1-qubit channels
      applied in sequence). selftest() proves agreement to ~1e-12.

      So: still real IBM calibration data, but applied identically on both
      sides. This is the "custom Kraus-channel translation" option from the
      brief, and it turned out to be both the simplest and the only defensible
      one.

  (B) REALISM REFERENCE (Qiskit only, reported but NOT used for A vs B).
      The raw FakeBackend noise model with transpilation and routing. Useful
      to show "here is what a real device would do", but it cannot be
      reproduced on the PennyLane side, so it is flagged `comparable=False`
      and excluded from cross-framework plots.

Run `python noise_models.py` to execute the equivalence self-test.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

warnings.filterwarnings("ignore")

# Canonical gate basis that BOTH frameworks are held to.
ONE_QUBIT_GATES_QISKIT = ["rx", "ry", "rz", "h", "x", "sx"]
TWO_QUBIT_GATES_QISKIT = ["cx", "cz"]


# ==========================================================================
# Noise specification
# ==========================================================================
@dataclass(frozen=True)
class NoiseSpec:
    """
    A framework-independent noise level.

    p1 / p2 are depolarizing parameters in Qiskit's convention:
        rho -> (1 - p) rho + p * I / 2**n
    """
    label: str
    p1: float              # 1-qubit depolarizing parameter
    p2: float              # 2-qubit depolarizing parameter
    comparable: bool = True   # False => Qiskit-only, excluded from A vs B plots
    backend: str | None = None   # set for raw-device models
    scale: float = 1.0
    source: str = ""

    @property
    def is_noiseless(self) -> bool:
        return self.p1 == 0.0 and self.p2 == 0.0


# ==========================================================================
# Calibration: read real error rates off IBM fake backends
# ==========================================================================
@lru_cache(maxsize=None)
def calibrate_from_backend(backend_name: str) -> tuple[float, float]:
    """
    Median 1-qubit and 2-qubit gate error from a fake backend's real
    calibration data. Returns (p1, p2) as depolarizing parameters.
    """
    from qiskit_ibm_runtime import fake_provider as fp

    backend = getattr(fp, backend_name)()
    target = backend.target

    one_q, two_q = [], []
    for inst_name in target.operation_names:
        if inst_name in ("delay", "reset", "measure", "if_else",
                         "for_loop", "switch_case", "rz"):
            continue
        props = target[inst_name]
        for qargs, prop in props.items():
            if prop is None or prop.error is None or qargs is None:
                continue
            err = float(prop.error)
            if not np.isfinite(err) or err <= 0:
                continue
            (one_q if len(qargs) == 1 else two_q).append(err)

    p1 = float(np.median(one_q)) if one_q else 1e-4
    p2 = float(np.median(two_q)) if two_q else 1e-2
    return p1, p2


def make_noise_levels(
    backend_name: str = "FakeManilaV2",
    scales: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 4.0),
) -> list[NoiseSpec]:
    """
    The sweep axis: real backend error rates multiplied by increasing scales.
    scale=0 is the noiseless baseline; scale=1 is the real device rate.
    """
    p1_base, p2_base = calibrate_from_backend(backend_name)
    levels = []
    for s in scales:
        levels.append(NoiseSpec(
            label=("noiseless" if s == 0.0 else f"{backend_name[4:]}x{s:g}"),
            p1=p1_base * s,
            p2=p2_base * s,
            comparable=True,
            scale=s,
            source=f"{backend_name} median gate errors "
                   f"(p1={p1_base:.2e}, p2={p2_base:.2e}) x {s:g}",
        ))
    return levels


def device_noise_spec(backend_name: str) -> NoiseSpec:
    """Raw-device model: Qiskit-only, NOT comparable across frameworks."""
    p1, p2 = calibrate_from_backend(backend_name)
    return NoiseSpec(
        label=f"device:{backend_name[4:]}",
        p1=p1, p2=p2,
        comparable=False,
        backend=backend_name,
        scale=1.0,
        source=f"raw {backend_name} NoiseModel incl. readout + routing",
    )


# ==========================================================================
# Kraus operators -- the shared definition both frameworks are built from
# ==========================================================================
_PAULIS = {
    "I": np.eye(2, dtype=complex),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
}


@lru_cache(maxsize=None)
def depolarizing_kraus(p: float, num_qubits: int) -> tuple:
    """
    Kraus operators for the depolarizing channel in QISKIT's convention:
        rho -> (1 - p) rho + p * I / d,     d = 2**num_qubits

    Written as a Pauli mixture:
        K_0   = sqrt(1 - p*(d^2-1)/d^2) * I
        K_i>0 = sqrt(p/d^2) * P_i         over the d^2-1 non-identity Paulis

    Using these on the PennyLane side guarantees the channel is *identical*
    to Aer's, rather than merely similar. This is what makes the Option A vs
    Option B comparison defensible.
    """
    import itertools

    if p <= 0:
        return (np.eye(2 ** num_qubits, dtype=complex),)

    d2 = 4 ** num_qubits
    labels = ["".join(c) for c in itertools.product("IXYZ", repeat=num_qubits)]

    kraus = []
    for lab in labels:
        mat = _PAULIS[lab[0]]
        for ch in lab[1:]:
            mat = np.kron(mat, _PAULIS[ch])
        coeff = (np.sqrt(1.0 - p * (d2 - 1) / d2) if lab == "I" * num_qubits
                 else np.sqrt(p / d2))
        kraus.append(coeff * mat)
    return tuple(kraus)


# ==========================================================================
# Qiskit side
# ==========================================================================
def qiskit_noise_model(spec: NoiseSpec):
    """Aer NoiseModel for a NoiseSpec. Returns None for the noiseless case."""
    if spec.backend is not None:
        # Raw device model (realism reference, not cross-comparable)
        from qiskit_aer.noise import NoiseModel
        from qiskit_ibm_runtime import fake_provider as fp
        return NoiseModel.from_backend(getattr(fp, spec.backend)())

    if spec.is_noiseless:
        return None

    from qiskit_aer.noise import NoiseModel, depolarizing_error

    nm = NoiseModel()
    nm.add_all_qubit_quantum_error(
        depolarizing_error(spec.p1, 1), ONE_QUBIT_GATES_QISKIT
    )
    nm.add_all_qubit_quantum_error(
        depolarizing_error(spec.p2, 2), TWO_QUBIT_GATES_QISKIT
    )
    return nm


# ==========================================================================
# PennyLane side
# ==========================================================================
def pennylane_noise_model(spec: NoiseSpec):
    """
    qml.NoiseModel matching `spec` exactly. Returns None if noiseless.

    Raises for backend-derived specs: those are deliberately not reproducible
    on the PennyLane side (see module docstring), and silently approximating
    them would be the exact mistake this module exists to prevent.
    """
    import pennylane as qml

    if spec.backend is not None:
        raise ValueError(
            f"NoiseSpec '{spec.label}' is a raw-device model (comparable=False). "
            "It includes readout error and hardware routing that cannot be "
            "reproduced on the PennyLane side. Use a calibrated NoiseSpec from "
            "make_noise_levels() for cross-framework comparison."
        )

    if spec.is_noiseless:
        return None

    k1 = [np.asarray(k) for k in depolarizing_kraus(spec.p1, 1)]
    k2 = [np.asarray(k) for k in depolarizing_kraus(spec.p2, 2)]

    def one_qubit_noise(op, **_):
        for w in op.wires:
            qml.QubitChannel(k1, wires=w)

    def two_qubit_noise(op, **_):
        qml.QubitChannel(k2, wires=op.wires)

    cond1 = qml.noise.op_in([qml.RX, qml.RY, qml.RZ, qml.Hadamard,
                             qml.PauliX, qml.PauliY, qml.PauliZ, qml.SX])
    cond2 = qml.noise.op_in([qml.CNOT, qml.CZ])

    return qml.NoiseModel({cond1: one_qubit_noise, cond2: two_qubit_noise})


def pennylane_from_qiskit_bridge(qiskit_nm):
    """
    Secondary path: convert an Aer NoiseModel via pennylane-qiskit.

    Provided for completeness/inspection. NOT used for the headline comparison
    because it drops readout error and does not reproduce transpilation or
    routing. Prefer pennylane_noise_model().
    """
    import pennylane as qml
    return qml.from_qiskit_noise(qiskit_nm)


# ==========================================================================
# Self-test: prove the two sides really are on an equivalent footing
# ==========================================================================
def _reference_circuit_ops():
    """
    A fixed gate sequence exercising both 1q and 2q noise.

    NOTE: deliberately contains NO Hadamard. An H on qubit 0 followed by CNOTs
    creates an equal superposition whose <ZZZ> is identically zero at every
    noise level -- the comparison would then "pass" even if the two noise
    models disagreed completely. Small RY/RX angles keep the state near |000>
    so <ZZZ> starts near +1 and visibly decays as noise increases, which is
    what makes the equivalence test meaningful.
    """
    return [
        ("ry", 0), ("cx", (0, 1)), ("ry", 1), ("cx", (1, 2)),
        ("rz", 2), ("cx", (0, 2)), ("rx", 0), ("cx", (1, 2)),
    ]


def selftest(verbose: bool = True) -> bool:
    """
    Build the SAME explicit circuit in Qiskit and PennyLane, apply the noise
    model from each side, and compare <Z0 Z1 Z2>. Agreement to ~1e-10 proves
    the channels are identical, not merely similar.
    """
    import pennylane as qml
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator
    from qiskit.quantum_info import SparsePauliOp

    angles = [0.3, 0.7, 1.1]
    ops = _reference_circuit_ops()
    obs = SparsePauliOp("ZZZ")

    def build_qiskit():
        qc = QuantumCircuit(3)
        ai = 0
        for name, tgt in ops:
            if name == "h":
                qc.h(tgt)
            elif name == "cx":
                qc.cx(*tgt)
            else:
                getattr(qc, name)(angles[ai % 3], tgt)
                ai += 1
        return qc

    def pl_circuit():
        ai = 0
        for name, tgt in ops:
            if name == "h":
                qml.Hadamard(tgt)
            elif name == "cx":
                qml.CNOT(wires=list(tgt))
            else:
                {"rx": qml.RX, "ry": qml.RY, "rz": qml.RZ}[name](
                    angles[ai % 3], wires=tgt)
                ai += 1
        return qml.expval(qml.PauliZ(0) @ qml.PauliZ(1) @ qml.PauliZ(2))

    levels = make_noise_levels("FakeManilaV2", scales=(0.0, 1.0, 4.0, 20.0))

    ok = True
    observed = []          # guards against a vacuous (noise-insensitive) test
    line = "-" * 78
    if verbose:
        p1, p2 = calibrate_from_backend("FakeManilaV2")
        print(line)
        print("NOISE EQUIVALENCE SELF-TEST")
        print(line)
        print(f"FakeManilaV2   median gate errors: p1={p1:.4e}  p2={p2:.4e}")
        p1s, p2s = calibrate_from_backend("FakeSherbrooke")
        print(f"FakeSherbrooke median gate errors: p1={p1s:.4e}  p2={p2s:.4e}")
        print()
        print(f"{'noise level':<20}{'<ZZZ> qiskit':>16}{'<ZZZ> pennylane':>18}"
              f"{'|diff|':>12}  status")
        print(line)

    for spec in levels:
        qc = build_qiskit()
        nm = qiskit_noise_model(spec)
        sim = (AerSimulator(method="density_matrix", noise_model=nm) if nm
               else AerSimulator(method="density_matrix"))
        tqc = transpile(
            qc, sim,
            basis_gates=ONE_QUBIT_GATES_QISKIT + TWO_QUBIT_GATES_QISKIT,
            optimization_level=0,
        )
        tqc.save_density_matrix()
        rho = sim.run(tqc).result().data()["density_matrix"]
        e_qk = float(np.real(np.trace(np.asarray(rho) @ obs.to_matrix())))

        pl_nm = pennylane_noise_model(spec)
        dev = qml.device("default.mixed", wires=3)
        qnode = qml.QNode(pl_circuit, dev)
        if pl_nm is not None:
            qnode = qml.add_noise(qnode, pl_nm)
        e_pl = float(qnode())

        diff = abs(e_qk - e_pl)
        good = diff < 1e-9
        ok &= good
        observed.append(e_qk)
        if verbose:
            print(f"{spec.label:<20}{e_qk:>16.10f}{e_pl:>18.10f}{diff:>12.2e}"
                  f"  {'PASS' if good else 'FAIL'}")

    # A test where the observable never moves would "pass" trivially even if
    # the two noise models disagreed. Require real noise sensitivity.
    spread = max(observed) - min(observed)
    sensitive = spread > 1e-3
    ok &= sensitive
    if verbose:
        print(line)
        print(f"Noise sensitivity of the probe observable: spread={spread:.6f}"
              f"  {'OK' if sensitive else 'DEGENERATE -- test is vacuous!'}")

    if verbose:
        print(line)
        print("Readout-error transfer check (documents a real limitation):")
        try:
            from qiskit_aer.noise import NoiseModel
            from qiskit_ibm_runtime.fake_provider import FakeManilaV2
            raw = NoiseModel.from_backend(FakeManilaV2())
            n_ro = len(getattr(raw, "_local_readout_errors", {}))
            bridged = pennylane_from_qiskit_bridge(raw)
            n_cond = len(bridged.model_map)
            print(f"  FakeManilaV2 readout errors in Aer model : {n_ro}")
            print(f"  conditions after qml.from_qiskit_noise   : {n_cond} "
                  f"(gate channels only; readout NOT transferred)")
            print("  -> raw-device models are Qiskit-only; flagged "
                  "comparable=False.")
        except Exception as exc:
            print(f"  bridge inspection unavailable: {type(exc).__name__}: {exc}")

        print(line)
        print("OVERALL: " + ("EQUIVALENT FOOTING CONFIRMED" if ok
                             else "MISMATCH -- do not compare A vs B"))
        print(line)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
