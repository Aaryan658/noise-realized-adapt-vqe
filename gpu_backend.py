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

# Finite-shot configuration, module-level so the ADAPT loop needs no plumbing.
#   shots = 0  -> exact expectations (default)
#   shots = S  -> every Pauli term of H is estimated from S binomial shots,
#                 independently (no commuting-group sharing), which is the
#                 conservative "ungrouped" measurement model.
CFG = {"shots": 0, "gen": None, "evals": 0,
       "channels": ("depol",), "ratio": 0.5, "ro_eps": 0.0}


def set_shots(shots: int, seed: int = 0) -> None:
    CFG["shots"] = int(shots)
    CFG["evals"] = 0
    CFG["gen"] = (torch.Generator(device=DEVICE).manual_seed(int(seed))
                  if shots else None)


def shots_active() -> bool:
    return CFG["shots"] > 0


# --------------------------------------------------------------------------
# Noise-channel components (stackable; module-level like the shot config)
#   "depol"    depolarizing after every gate (the original model, default)
#   "thermal"  amplitude damping + dephasing after every gate, on the qubits it
#              touches (idle-qubit decay is not modelled)
#   "coherent" systematic over-rotation after every gate: about the gate's own
#              axis for 1q gates (H: the (X+Z)/sqrt2 axis), exp(-i d/2 ZZ) for CNOT
#   "readout"  symmetric assignment error eps on every measured qubit, so a
#              weight-w Pauli term is damped by (1-2 eps)^w
# "thermal" and "coherent" are scaled so their average gate infidelity equals
# the depolarizing model's at the same (p1, p2): only the STRUCTURE of the
# noise differs from the depolarizing baseline, not its strength. The
# amplitude-damping : dephasing ratio comes from the device's T1/T2 and the
# readout error from its measured assignment error.
# --------------------------------------------------------------------------
def set_channels(channels=("depol",), ratio: float = 0.5,
                 ro_eps: float = 0.0) -> None:
    CFG["channels"] = tuple(channels)
    CFG["ratio"] = float(ratio)
    CFG["ro_eps"] = float(ro_eps)


@lru_cache(maxsize=None)
def device_calibration(backend_name: str = "FakeManilaV2"):
    """(lambda/gamma from median T1/T2, median readout error) of a fake backend."""
    from qiskit_ibm_runtime import fake_provider as fp
    tgt = getattr(fp, backend_name)().target
    t1 = np.median([q.t1 for q in tgt.qubit_properties if q.t1])
    t2 = np.median([q.t2 for q in tgt.qubit_properties if q.t2])
    ro = np.median([p.error for p in tgt["measure"].values()
                    if p is not None and p.error is not None])
    # 1/T_phi = 1/T2 - 1/(2 T1); lambda/gamma = T1/T_phi = T1/T2 - 1/2
    return float(max(t1 / t2 - 0.5, 0.0)), float(ro)


def channel_params(p1: float, p2: float, ratio: float) -> dict:
    """
    Per-gate parameters of each component whose average gate infidelity matches
    a depolarizing channel (p1, p2). Small-error matching:
      1q  depol 3p/4 = AD+PD  gamma/2 + lambda/4 = coherent sin^2(d/2)
      2q  depol 15p/16 = 2 (gamma/2 + lambda/4) = coherent sin^2(d/2)
    """
    k = 0.5 + ratio / 4.0
    g1 = min(0.75 * p1 / k, 1.0)
    g2 = min((15.0 * p2 / 32.0) / k, 1.0)
    return {"g1": g1, "l1": min(ratio * g1, 1.0),
            "g2": g2, "l2": min(ratio * g2, 1.0),
            "d1": 2.0 * np.arcsin(np.sqrt(0.75 * p1)),
            "d2": 2.0 * np.arcsin(np.sqrt(15.0 * p2 / 16.0))}


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

    def __init__(self, n_qubits, hamiltonian, hf_bits, p1, p2,
                 channels=("depol",), ratio=0.5, ro_eps=0.0):
        self.n = n_qubits
        self.p1, self.p2 = float(p1), float(p2)
        self.ch = frozenset(channels)
        self.cp = channel_params(self.p1, self.p2, float(ratio))
        self.ro_eps = float(ro_eps)
        self._ro_on = "readout" in self.ch and self.ro_eps > 0.0
        self._zzph = {}
        hmat = hamiltonian.sparse_matrix(wire_order=list(range(n_qubits)))
        # Tr(H rho) = sum_ij H_ij rho_ji = sum(H^T * rho)
        self.Ht = torch.tensor(hmat.toarray().T, dtype=CDTYPE, device=DEVICE)
        idx = int("".join(str(int(b)) for b in hf_bits), 2)
        rho = torch.zeros(2 ** n_qubits, 2 ** n_qubits, dtype=CDTYPE,
                          device=DEVICE)
        rho[idx, idx] = 1.0
        self.rho0 = rho.reshape([2] * (2 * n_qubits))
        self.hf_bits = [int(b) for b in hf_bits]
        self._build_pauli_terms(hamiltonian)
        a = 1.0 - 2.0 * self.ro_eps if self._ro_on else 1.0
        self._ro = a ** self._weight
        self.had = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
        # Coherent over-rotation E = exp(-i d1/2 sigma_axis), applied after the gate.
        sx = np.array([[0, 1], [1, 0]], dtype=complex)
        sy = np.array([[0, -1j], [1j, 0]], dtype=complex)
        sz = np.array([[1, 0], [0, -1]], dtype=complex)
        axes = {"RX": sx, "RY": sy, "RZ": sz, "X": sx,
                "Hadamard": (sx + sz) / np.sqrt(2)}
        c, s = np.cos(self.cp["d1"] / 2), np.sin(self.cp["d1"] / 2)
        self._err1 = {k: c * np.eye(2, dtype=complex) - 1j * s * m
                      for k, m in axes.items()}
        self._perm = {}
        self._eye = {k: torch.eye(2 ** k, dtype=CDTYPE, device=DEVICE)
                     .reshape([2] * (2 * k)) for k in (1, 2)}

    def _build_pauli_terms(self, hamiltonian):
        """
        Tabulate H = const + sum_k c_k P_k for per-term expectation values.

        For P|k> = i^{ny} (-1)^{pop(k&z)} |k^x>, Tr(P rho) =
        sum_j i^{ny} (-1)^{pop((j^x)&z)} rho[j^x, j]  (real for Hermitian rho),
        so all terms come from one gather on the density matrix.
        """
        n, N = self.n, 2 ** self.n
        coeffs, ops = hamiltonian.terms()
        j = np.arange(N)
        idxs, signs, cs, wts = [], [], [], []
        self.const = 0.0
        for c, op in zip(np.real(np.asarray(coeffs)), ops):
            (pw, _), = qml.pauli.pauli_sentence(op).items()
            if len(pw) == 0:
                self.const += float(c)
                continue
            x = z = ny = 0
            for w, s in pw.items():
                bit = 1 << (n - 1 - int(w))
                if s in ("X", "Y"):
                    x |= bit
                if s in ("Y", "Z"):
                    z |= bit
                ny += s == "Y"
            k = j ^ x
            par = np.array([bin(v & z).count("1") & 1 for v in k])
            idxs.append(k)
            signs.append((1j ** ny) * (1 - 2 * par))
            cs.append(float(c))
            wts.append(len(pw))
        self.n_terms = len(cs)
        self._weight = torch.tensor(wts, dtype=torch.float64, device=DEVICE)
        self._idx = torch.tensor(np.array(idxs), device=DEVICE)
        self._sign = torch.tensor(np.array(signs), dtype=CDTYPE, device=DEVICE)
        self._coef = torch.tensor(cs, dtype=torch.float64, device=DEVICE)
        self._cols = torch.arange(N, device=DEVICE).expand(self.n_terms, N)

    def term_expectations(self, r):
        """Exact <P_k> for every non-identity Hamiltonian term; r is the N x N rho."""
        return (self._sign * r[self._idx, self._cols]).sum(1).real

    def _measured_energy(self, r):
        """Finite-shot estimate: each term is a +/-1 binomial average over S shots."""
        S = CFG["shots"]
        t = (self.term_expectations(r) * self._ro).clamp(-1.0, 1.0)
        p = (1.0 + t) / 2.0
        counts = torch.binomial(torch.full_like(p, float(S)), p,
                                generator=CFG["gen"])
        est = 2.0 * counts / S - 1.0
        CFG["evals"] += 1
        return float(self.const + (self._coef * est).sum())

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

    def _thermal(self, rho, q, g, lam):
        """Amplitude damping (gamma) + extra dephasing (lambda) on qubit q."""
        if g <= 0.0 and lam <= 0.0:
            return rho
        a, b = 2 ** q, 2 ** (self.n - q - 1)
        r = rho.reshape(a, 2, b, a, 2, b)
        out = torch.empty_like(r)
        s = float(np.sqrt((1.0 - g) * (1.0 - lam)))
        out[:, 0, :, :, 0, :] = r[:, 0, :, :, 0, :] + g * r[:, 1, :, :, 1, :]
        out[:, 1, :, :, 1, :] = (1.0 - g) * r[:, 1, :, :, 1, :]
        out[:, 0, :, :, 1, :] = s * r[:, 0, :, :, 1, :]
        out[:, 1, :, :, 0, :] = s * r[:, 1, :, :, 0, :]
        return out.reshape(rho.shape)

    def _zz_error(self, rho, c, t):
        """Coherent ZZ over-rotation exp(-i d2/2 Z_c Z_t): a diagonal phase on rho."""
        if (c, t) not in self._zzph:
            j = np.arange(2 ** self.n)
            zz = ((1 - 2 * ((j >> (self.n - 1 - c)) & 1))
                  * (1 - 2 * ((j >> (self.n - 1 - t)) & 1)))
            self._zzph[(c, t)] = torch.tensor(
                np.exp(-0.5j * self.cp["d2"] * zz), dtype=CDTYPE, device=DEVICE)
        ph = self._zzph[(c, t)]
        r = rho.reshape(2 ** self.n, 2 ** self.n)
        return ((r * ph[:, None]) * ph.conj()[None, :]).reshape(rho.shape)

    def _gate1(self, rho, name, u, q):
        """1q gate u (host 2x2) followed by the configured noise components."""
        if "coherent" in self.ch:
            u = self._err1[name] @ u
        rho = self._apply_1q_noisy(rho, u, q,
                                   self.p1 if "depol" in self.ch else 0.0)
        if "thermal" in self.ch:
            rho = self._thermal(rho, q, self.cp["g1"], self.cp["l1"])
        return rho

    def _gate2(self, rho, c, t):
        """CNOT followed by the configured noise components."""
        rho = self._apply_cnot(rho, c, t)
        if "coherent" in self.ch:
            rho = self._zz_error(rho, c, t)
        if "thermal" in self.ch:
            rho = self._thermal(rho, c, self.cp["g2"], self.cp["l2"])
            rho = self._thermal(rho, t, self.cp["g2"], self.cp["l2"])
        if "depol" in self.ch:
            rho = self._depolarize(rho, [c, t], self.p2)
        return rho

    def energy(self, ops, params, exact: bool = False) -> float:
        rho = self.rho0
        # default.mixed decomposes BasisState into PauliX gates, and each one
        # is noised like any other 1q gate; an identity gate through _gate1
        # applies exactly that noise to the prepared state.
        ident = np.eye(2, dtype=complex)
        for q, b in enumerate(self.hf_bits):
            if b:
                rho = self._gate1(rho, "X", ident, q)
        for (word, wires), theta in zip(ops, params):
            for name, ws, ang in _template(word, tuple(wires)):
                if name == "CNOT":
                    rho = self._gate2(rho, ws[0], ws[1])
                else:
                    u = (self.had if name == "Hadamard" else
                         _rot_matrix(name, float(theta) if ang is None else ang))
                    rho = self._gate1(rho, name, u, ws[0])
        r = rho.reshape(2 ** self.n, 2 ** self.n)
        if CFG["shots"] and not exact:
            return self._measured_energy(r)
        if self._ro_on:
            t = self.term_expectations(r) * self._ro
            return float(self.const + (self._coef * t).sum())
        return float((self.Ht * r).sum().real)


_SIMS: dict = {}


def _sim(spec, noise):
    """Simulator for (molecule, noise level, channel components); cached."""
    ro = CFG["ro_eps"] * float(getattr(noise, "scale", 1.0))
    key = (spec, noise.p1, noise.p2, CFG["channels"], round(CFG["ratio"], 6),
           round(ro, 10))
    if key not in _SIMS:
        H, n_qubits, hf, _ = mol.pennylane_hamiltonian(spec)
        _SIMS[key] = DensityMatrixSim(n_qubits, H, hf, noise.p1, noise.p2,
                                      CFG["channels"], CFG["ratio"], ro)
    return _SIMS[key]


def make_gpu_qnode(spec, noise, selected, trailing=None, exact=False):
    """
    Callable qnode(params) -> energy, matching `_make_qnode`'s contract.
    With shots configured (set_shots) it returns a finite-shot estimate unless
    `exact=True`, which is used to score the final circuit.
    """
    sim = _sim(spec, noise)
    ops = [(o.pauli_word, tuple(o.wires))
           for o in list(selected) + ([trailing] if trailing is not None else [])]

    def qnode(params):
        return sim.energy(ops, np.asarray(params, dtype=float).ravel(),
                          exact=exact)
    return qnode


def n_terms(spec, noise) -> int:
    """Non-identity Pauli terms in H (shots per energy evaluation = n_terms * S)."""
    return _sim(spec, noise).n_terms


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
