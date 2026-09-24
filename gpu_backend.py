"""
gpu_backend.py -- CUDA density-matrix simulator for the noisy ADAPT-VQE loop.

Drop-in replacement for the PennyLane `default.mixed` QNode built by
`pennylane_resource_aware_adapt._make_qnode`. It returns a callable
`qnode(params) -> <H>` and reproduces the same physics:

  * circuit  = HF basis state, then each pool operator exp(-i theta/2 P),
               decomposed with PennyLane's own decomposer into {RX,RY,RZ,H,CNOT}
               (same gate list, same order as the CPU path);
  * noise    = depolarizing channel after every gate, Qiskit convention
               rho -> (1-p) rho + p I/d (x) Tr(rho), p1 on 1q gates and p2 on
               CNOT -- the channel `noise_models.depolarizing_kraus` encodes;
  * output   = Re Tr(H rho), H the same PennyLane qubit Hamiltonian.

Only forward evaluation is provided (the loop uses COBYLA and central
differences). `python gpu_backend.py` cross-checks against `default.mixed`.
"""

from __future__ import annotations

import string
from functools import lru_cache

import numpy as np
import pennylane as qml
import torch

import molecules as mol

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CDTYPE = torch.complex128

_PROBE = 0.123456789


@lru_cache(maxsize=None)
def _template(word: str, wires: tuple):
    """
    Decomposed gate list of PauliRot(theta, word, wires) as
    [(name, wires, angle)]; the single theta-dependent rotation has
    angle=None and is filled in at evaluation time.
    """
    from pennylane_resource_aware_adapt import _decompose_ops
    ops = _decompose_ops([qml.PauliRot(_PROBE, word, wires=list(wires))])
    out, n_theta = [], 0
    for op in ops:
        ws = tuple(int(w) for w in op.wires)
        if op.name in ("RX", "RY", "RZ"):
            ang = float(op.parameters[0])
            if abs(ang - _PROBE) < 1e-12:
                out.append((op.name, ws, None))
                n_theta += 1
            else:
                out.append((op.name, ws, ang))
        elif op.name in ("Hadamard", "CNOT"):
            out.append((op.name, ws, 0.0))
        else:
            raise NotImplementedError(f"gate {op.name} not in canonical set")
    if n_theta != 1:
        raise RuntimeError(f"expected 1 theta-dependent gate, got {n_theta}")
    return tuple(out)


def _rot_matrix(name: str, a: float) -> np.ndarray:
    c, s = np.cos(a / 2), np.sin(a / 2)
    if name == "RX":
        m = [[c, -1j * s], [-1j * s, c]]
    elif name == "RY":
        m = [[c, -s], [s, c]]
    else:  # RZ
        m = [[np.exp(-0.5j * a), 0], [0, np.exp(0.5j * a)]]
    return np.array(m, dtype=complex)


def _mix(x, m):
    """Apply host 2x2 matrix m along axis 1 of x[A,2,R] with scalar coefficients."""
    x0, x1 = x[:, 0], x[:, 1]
    out = torch.empty_like(x)
    torch.add(x0 * complex(m[0, 0]), x1 * complex(m[0, 1]), out=out[:, 0])
    torch.add(x0 * complex(m[1, 0]), x1 * complex(m[1, 1]), out=out[:, 1])
    return out


class DensityMatrixSim:
    """n-qubit density matrix as a [2]*2n tensor (kets 0..n-1, bras n..2n-1)."""

    def __init__(self, n_qubits, hamiltonian, hf_bits, p1, p2):
        self.n = n_qubits
        self.p1, self.p2 = float(p1), float(p2)
        hmat = hamiltonian.sparse_matrix(wire_order=list(range(n_qubits)))
        # Tr(H rho) = sum_ij H_ij rho_ji = sum(H^T * rho)
        self.Ht = torch.tensor(hmat.toarray().T, dtype=CDTYPE, device=DEVICE)
        idx = int("".join(str(int(b)) for b in hf_bits), 2)
        rho = torch.zeros(2 ** n_qubits, 2 ** n_qubits, dtype=CDTYPE,
                          device=DEVICE)
        rho[idx, idx] = 1.0
        self.rho0 = rho.reshape([2] * (2 * n_qubits))
        self.hf_bits = [int(b) for b in hf_bits]
        self.had = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
        self._perm = {}
        self._eye = {k: torch.eye(2 ** k, dtype=CDTYPE, device=DEVICE)
                     .reshape([2] * (2 * k)) for k in (1, 2)}

    def _apply_1q_noisy(self, rho, u, q, p):
        """U rho U^dag on qubit q, then 1q depolarizing -- no permute copies."""
        n = self.n
        shape = rho.shape
        # ket axis q, then bra axis n+q, as elementwise 2x2 mixes on views
        x = _mix(rho.reshape(2 ** q, 2, -1), u)
        x = _mix(x.reshape(2 ** (n + q), 2, -1), u.conj())
        if p <= 0.0:
            return x.reshape(shape)
        a, b = 2 ** q, 2 ** (n - q - 1)
        r6 = x.reshape(a, 2, b, a, 2, b)
        t = (r6[:, 0, :, :, 0, :] + r6[:, 1, :, :, 1, :]) * (p / 2.0)
        out = (x * (1.0 - p)).reshape(a, 2, b, a, 2, b)
        out[:, 0, :, :, 0, :] += t
        out[:, 1, :, :, 1, :] += t
        return out.reshape(shape)

    def _apply_cnot(self, rho, c, t):
        n = self.n
        if (c, t) not in self._perm:
            idx = np.arange(2 ** n)
            cbit = (idx >> (n - 1 - c)) & 1
            perm = np.where(cbit == 1, idx ^ (1 << (n - 1 - t)), idx)
            self._perm[(c, t)] = torch.tensor(perm, device=DEVICE)
        p = self._perm[(c, t)]
        r = rho.reshape(2 ** n, 2 ** n)
        return r[p][:, p].reshape(rho.shape)

    def _depolarize(self, rho, qubits, p):
        """rho -> (1-p) rho + p (I/d) (x) Tr_qubits(rho)."""
        if p <= 0.0:
            return rho
        n, k = self.n, len(qubits)
        L = string.ascii_letters[: 2 * n]
        tr = list(L)
        for q in qubits:
            tr[n + q] = L[q]
        keep = "".join(L[i] for i in range(2 * n)
                       if i not in qubits and i - n not in qubits)
        tvec = torch.einsum(f"{''.join(tr)}->{keep}", rho)
        e_ax = "".join(L[q] for q in qubits) + "".join(L[n + q] for q in qubits)
        add = torch.einsum(f"{keep},{e_ax}->{L}", tvec, self._eye[k])
        return (1.0 - p) * rho + (p / 2 ** k) * add

    def energy(self, ops, params) -> float:
        rho = self.rho0
        # default.mixed decomposes BasisState into PauliX gates, and each one
        # is noised like any other 1q gate; depolarizing commutes with X, so
        # noising the prepared state per flipped qubit is equivalent.
        for q, b in enumerate(self.hf_bits):
            if b:
                rho = self._depolarize(rho, [q], self.p1)
        for (word, wires), theta in zip(ops, params):
            for name, ws, ang in _template(word, tuple(wires)):
                if name == "CNOT":
                    rho = self._apply_cnot(rho, ws[0], ws[1])
                    rho = self._depolarize(rho, list(ws), self.p2)
                else:
                    u = (self.had if name == "Hadamard" else
                         _rot_matrix(name, float(theta) if ang is None else ang))
                    rho = self._apply_1q_noisy(rho, u, ws[0], self.p1)
        r = rho.reshape(2 ** self.n, 2 ** self.n)
        return float((self.Ht * r).sum().real)


_SIMS: dict = {}


def _sim(spec, p1, p2):
    key = (spec, p1, p2)
    if key not in _SIMS:
        H, n_qubits, hf, _ = mol.pennylane_hamiltonian(spec)
        _SIMS[key] = DensityMatrixSim(n_qubits, H, hf, p1, p2)
    return _SIMS[key]


def make_gpu_qnode(spec, noise, selected, trailing=None):
    """Callable qnode(params) -> energy, matching `_make_qnode`'s contract."""
    sim = _sim(spec, noise.p1, noise.p2)
    ops = [(o.pauli_word, tuple(o.wires))
           for o in list(selected) + ([trailing] if trailing is not None else [])]

    def qnode(params):
        return sim.energy(ops, np.asarray(params, dtype=float).ravel())
    return qnode


def selftest(spec=None, scales=(0.0, 0.25, 1.0), n_ops=4, seed=0) -> bool:
    """Cross-check against default.mixed on random circuits."""
    import time
    import pennylane_resource_aware_adapt as ra
    import noise_models as nz
    from pennylane import numpy as pnp

    spec = spec or mol.LIH
    pool = ra.build_pool(spec)
    rng = np.random.default_rng(seed)
    ok = True
    print(f"device={DEVICE}  spec={spec.label}  pool={len(pool)}")
    for noise in nz.make_noise_levels("FakeManilaV2", scales=scales):
        sel = [pool[i] for i in rng.choice(len(pool), n_ops, replace=False)]
        x = rng.uniform(-1, 1, n_ops)
        t0 = time.time()
        e_cpu = float(ra._make_qnode(spec, noise, sel)(
            pnp.array(x, requires_grad=False)))
        t_cpu = time.time() - t0
        q = make_gpu_qnode(spec, noise, sel)
        q(x)  # warm-up
        t0 = time.time()
        e_gpu = q(x)
        t_gpu = time.time() - t0
        diff = abs(e_cpu - e_gpu)
        good = diff < 1e-9
        ok &= good
        print(f"{noise.label:<14} cpu={e_cpu:+.10f} ({t_cpu:6.2f}s)  "
              f"gpu={e_gpu:+.10f} ({t_gpu:6.3f}s)  |diff|={diff:.2e}  "
              f"{'PASS' if good else 'FAIL'}")
    print("OVERALL:", "GPU MATCHES default.mixed" if ok else "MISMATCH")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
