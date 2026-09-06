"""
molecules.py -- SHARED GROUND TRUTH for Option A and Option B.

This is the "bridge point" of the project. Everything downstream (Qiskit
baselines, PennyLane resource-aware ADAPT) consumes the objects built here, so
that Option A and Option B are provably solving the *same* eigenvalue problem.

Design decision (forced by the environment, see README):
    PySCF does not build on Windows, so qiskit_nature's PySCFDriver is
    unavailable. Instead, PennyLane's built-in differentiable Hartree-Fock
    ('dhf', pure Python) is the SINGLE SOURCE OF TRUTH for molecular integrals.
    The Qiskit-side Hamiltonian is constructed from those *same* integrals via
    ElectronicEnergy.from_raw_integrals.

    Consequence: the two frameworks do not merely "agree to some tolerance",
    they are built from identical integrals, so agreement is exact (~1e-9 Ha)
    and any disagreement is a genuine convention bug, not numerical noise.
    validate() asserts this AND cross-checks full-space results against
    published FCI values.

Reference frame for error metrics
---------------------------------
IMPORTANT: when an active space is used (LiH), the reference for "energy error"
is the FCI energy *within that active space*, NOT the full-space FCI. Using the
full-space value would add a constant ~19 mHa truncation error to every method,
which has nothing to do with the ansatz being benchmarked and would swamp the
Option A vs B differences. Both are reported; `fci_energy` is the active-space
one.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

warnings.filterwarnings("ignore")

# --------------------------------------------------------------------------
# Published reference values, STO-3G, full space (no active-space truncation).
# Used only as an external sanity check on the dhf integral pipeline.
# --------------------------------------------------------------------------
LITERATURE_FCI = {
    "H2": -1.137270,    # d = 0.735 A
    "LiH": -7.882362,   # d = 1.5949 A
}
CHEMICAL_ACCURACY = 1.6e-3  # Hartree


@dataclass(frozen=True)
class MoleculeSpec:
    """A molecule + active space. Frozen so it can be an lru_cache key."""
    name: str
    symbols: tuple[str, ...]
    geometry: tuple[tuple[float, float, float], ...]  # Angstrom
    active_electrons: int | None = None
    active_orbitals: int | None = None
    basis: str = "sto-3g"
    note: str = ""

    @property
    def label(self) -> str:
        if self.active_orbitals is None:
            return f"{self.name}(full)"
        return f"{self.name}(AS:{self.active_electrons}e,{self.active_orbitals}o)"


# --------------------------------------------------------------------------
# The benchmark set.
#
# LiH full space is 12 qubits -- fine for exact diagonalisation, but a 12-qubit
# *density-matrix* noisy simulation is 2^24 amplitudes and an ADAPT loop over it
# is not tractable for a course project. We therefore benchmark LiH in a
# (2e, 3o) active space -> 6 qubits, a standard choice in the ADAPT-VQE
# literature. LIH_FULL is retained for the validation step only.
# --------------------------------------------------------------------------
H2 = MoleculeSpec(
    name="H2",
    symbols=("H", "H"),
    geometry=((0.0, 0.0, 0.0), (0.0, 0.0, 0.735)),
    note="Full space, 4 qubits.",
)

# --- Why LiH is STRETCHED to 3.0 A (state this in the writeup) --------------
# In STO-3G, LiH's correlation energy at equilibrium (1.5949 A) is concentrated
# almost entirely in the HIGHEST virtual orbital. A contiguous active space
# therefore captures almost nothing:
#
#     d = 1.5949 A   (2e,3o) 6q ->  1.05 mHa correlation   <- below chemical
#                    (2e,4o) 8q ->  1.82 mHa                  accuracy (1.6)
#                    (2e,5o) 10q -> 20.15 mHa
#     d = 3.0000 A   (2e,3o) 6q -> 16.26 mHa   <-- USED HERE
#                    (2e,5o) 10q -> 87.67 mHa
#
# With only ~1 mHa of correlation to recover, every ansatz would land on top of
# HF and noise would dominate entirely -- the benchmark could not distinguish
# any method from any other. Stretching the bond restores 16.3 mHa of
# correlation (comparable to H2's 20.3 mHa) while staying at 6 qubits, and the
# stretched geometry is more multi-reference, which is precisely the regime
# where adaptive ansatze are expected to outperform a fixed UCCSD.
# ---------------------------------------------------------------------------
LIH = MoleculeSpec(
    name="LiH",
    symbols=("Li", "H"),
    geometry=((0.0, 0.0, 0.0), (0.0, 0.0, 3.0)),
    active_electrons=2,
    active_orbitals=3,
    note="STRETCHED d=3.0A, frozen core + (2e,3o), 6 qubits, 16.3 mHa corr.",
)

LIH_FULL = MoleculeSpec(
    name="LiH",
    symbols=("Li", "H"),
    geometry=((0.0, 0.0, 0.0), (0.0, 0.0, 1.5949)),
    note="Full space, 12 qubits. Validation only -- too big for noisy ADAPT.",
)

BENCHMARK_MOLECULES = [H2, LIH]


# --------------------------------------------------------------------------
# PennyLane side (source of truth)
# --------------------------------------------------------------------------
def _pl_molecule(spec: MoleculeSpec):
    import pennylane as qml
    return qml.qchem.Molecule(
        list(spec.symbols),
        np.array(spec.geometry, dtype=float),
        unit="angstrom",
        basis_name=spec.basis,
    )


@lru_cache(maxsize=None)
def pennylane_hamiltonian(spec: MoleculeSpec):
    """Return (H, n_qubits, hf_state, n_active_electrons) for PennyLane."""
    import pennylane as qml

    mol = _pl_molecule(spec)
    kw = {}
    if spec.active_electrons is not None:
        kw["active_electrons"] = spec.active_electrons
    if spec.active_orbitals is not None:
        kw["active_orbitals"] = spec.active_orbitals

    H, n_qubits = qml.qchem.molecular_hamiltonian(mol, method="dhf", **kw)
    n_elec = (spec.active_electrons if spec.active_electrons is not None
              else mol.n_electrons)
    hf = qml.qchem.hf_state(n_elec, n_qubits)
    return H, int(n_qubits), hf, int(n_elec)


@lru_cache(maxsize=None)
def molecular_integrals(spec: MoleculeSpec):
    """(core_constant, one_body_MO, two_body_MO) from PennyLane's dhf."""
    import pennylane as qml

    mol = _pl_molecule(spec)
    if spec.active_orbitals is None:
        core, one, two = qml.qchem.electron_integrals(mol)()
    else:
        n_core = (mol.n_electrons - spec.active_electrons) // 2
        core_list = list(range(n_core))
        active = list(range(n_core, n_core + spec.active_orbitals))
        core, one, two = qml.qchem.electron_integrals(
            mol, core=core_list, active=active
        )()
    return float(np.array(core).ravel()[0]), np.asarray(one), np.asarray(two)


# --------------------------------------------------------------------------
# Qiskit side (built from the SAME integrals)
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def qiskit_hamiltonian(spec: MoleculeSpec):
    """
    Return (SparsePauliOp, nuclear_offset, num_particles, num_spatial_orbitals).

    The operator does NOT include the constant `nuclear_offset`; callers must
    add it to any expectation value. Keeping it separate avoids a large
    identity term that would distort circuit-level error analysis.
    """
    from qiskit_nature.second_q.hamiltonians import ElectronicEnergy
    from qiskit_nature.second_q.mappers import JordanWignerMapper

    core, one, two = molecular_integrals(spec)

    # PennyLane returns the MO two-electron tensor with full 8-fold
    # permutational symmetry; from_raw_integrals expects chemist notation.
    # The equivalence is verified numerically in validate() STEP 2.
    ee = ElectronicEnergy.from_raw_integrals(one, two)
    op = JordanWignerMapper().map(ee.second_q_op())

    n_so = one.shape[0]
    n_elec = (spec.active_electrons if spec.active_electrons is not None
              else _pl_molecule(spec).n_electrons)
    num_particles = (n_elec // 2, n_elec // 2)
    return op, core, num_particles, int(n_so)


# --------------------------------------------------------------------------
# Exact reference
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def fci_energy(spec: MoleculeSpec) -> float:
    """
    Exact ground-state energy of the *active-space* qubit Hamiltonian.
    This is the reference against which all energy errors are measured.
    """
    from scipy.sparse.linalg import eigsh

    H, _, _, _ = pennylane_hamiltonian(spec)
    M = H.sparse_matrix().astype(complex)
    if M.shape[0] <= 4:
        return float(np.linalg.eigvalsh(M.toarray())[0].real)
    vals = eigsh(M, k=1, which="SA", maxiter=10_000, tol=0.0)[0]
    return float(vals[0].real)


@lru_cache(maxsize=None)
def hartree_fock_energy(spec: MoleculeSpec) -> float:
    """Energy of the HF product state under the active-space Hamiltonian."""
    H, _, hf, _ = pennylane_hamiltonian(spec)
    idx = int("".join(str(int(b)) for b in hf), 2)
    M = H.sparse_matrix()
    return float(np.real(M[idx, idx]))


# --------------------------------------------------------------------------
# Validation -- the sanity check that must pass before any noise is added
# --------------------------------------------------------------------------
def validate(verbose: bool = True) -> bool:
    """
    Confirm, before any noise work:
      1. dhf integrals reproduce published full-space FCI (external check).
      2. Qiskit and PennyLane Hamiltonians share a spectrum (bridge check).
      3. HF energy sits above FCI (variational ordering sanity).
    Returns True if every check passes.
    """
    import scipy.sparse.linalg as sla

    ok = True
    line = "-" * 78

    if verbose:
        print(line)
        print("STEP 1  dhf integrals vs published full-space FCI (STO-3G)")
        print(line)
        print(f"{'molecule':<16}{'qubits':>7}{'E_dhf':>16}{'E_lit':>16}"
              f"{'err/mHa':>11}  status")

    for spec in (H2, LIH_FULL):
        _, nq, _, _ = pennylane_hamiltonian(spec)
        e = fci_energy(spec)
        lit = LITERATURE_FCI[spec.name]
        err = abs(e - lit) * 1e3
        good = err < CHEMICAL_ACCURACY * 1e3
        ok &= good
        if verbose:
            print(f"{spec.name:<16}{nq:>7}{e:>16.8f}{lit:>16.8f}{err:>11.4f}"
                  f"  {'PASS' if good else 'FAIL'}")

    if verbose:
        print()
        print(line)
        print("STEP 2  Qiskit <-> PennyLane Hamiltonian bridge (must be exact)")
        print(line)
        print(f"{'molecule':<16}{'qubits':>7}{'E_pennylane':>16}{'E_qiskit':>16}"
              f"{'diff/Ha':>11}  status")

    for spec in BENCHMARK_MOLECULES:
        e_pl = fci_energy(spec)
        op, core, _, _ = qiskit_hamiltonian(spec)
        M = op.to_matrix(sparse=True).astype(complex)
        if M.shape[0] <= 4:
            e_qk = float(np.linalg.eigvalsh(M.toarray())[0].real) + core
        else:
            e_qk = float(sla.eigsh(M, k=1, which="SA", maxiter=10_000)[0][0].real) + core
        diff = abs(e_qk - e_pl)
        good = diff < 1e-7
        ok &= good
        _, nq, _, _ = pennylane_hamiltonian(spec)
        if verbose:
            print(f"{spec.label:<16}{nq:>7}{e_pl:>16.8f}{e_qk:>16.8f}"
                  f"{diff:>11.2e}  {'PASS' if good else 'FAIL'}")

    if verbose:
        print()
        print(line)
        print("STEP 3  Reference energies used for the benchmark")
        print(line)
        print(f"{'molecule':<16}{'qubits':>7}{'E_HF':>16}{'E_FCI(active)':>16}"
              f"{'corr/mHa':>11}")

    for spec in BENCHMARK_MOLECULES:
        _, nq, _, _ = pennylane_hamiltonian(spec)
        e_hf, e_fci = hartree_fock_energy(spec), fci_energy(spec)
        good = e_hf >= e_fci - 1e-9
        ok &= good
        if verbose:
            print(f"{spec.label:<16}{nq:>7}{e_hf:>16.8f}{e_fci:>16.8f}"
                  f"{(e_hf - e_fci) * 1e3:>11.4f}")

    if verbose:
        print()
        print(line)
        print(f"OVERALL: "
              f"{'ALL CHECKS PASSED' if ok else 'FAILURES PRESENT -- do not proceed'}")
        print(line)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if validate() else 1)
