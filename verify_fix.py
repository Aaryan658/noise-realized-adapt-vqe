"""
verify_fix.py -- pre-sweep verification that the qubit-ADAPT pool actually
fixes the vacuous-selection problem.

Checks, noiseless only (fast), for H2 and LiH(2e,3o):

  1. Pool size and the spectrum of CNOT costs (must span several values).
  2. SELECTION DIVERGENCE at lambda=1: standard ADAPT and the resource-aware
     rule must choose different operator sequences for at least one molecule.
     This is the whole point -- if they still agree, Option A is vacuous.
  3. lambda=0 CONSISTENCY: resource_aware(lam=0) must reproduce standard
     ADAPT's operator sequence and energy exactly.

Run:  python -u verify_fix.py
It prints as it goes; nothing here touches the noisy path or Qiskit.
"""
from __future__ import annotations

import numpy as np

import molecules as mol
import noise_models as nz
import pennylane_resource_aware_adapt as ra

MAX_OPS = 10
OPT_MAXITER = 120


def main() -> int:
    noiseless = nz.make_noise_levels(scales=(0.0,))[0]
    line = "=" * 96
    all_ok = True
    diverged_somewhere = False

    for spec in mol.BENCHMARK_MOLECULES:
        print(line, flush=True)
        print(f"{spec.label}", flush=True)
        print(line, flush=True)

        pool = ra.build_pool(spec)
        costs = sorted({op.cnot_cost for op in pool})
        by_kind = {}
        for op in pool:
            by_kind.setdefault(op.kind, []).append(op.cnot_cost)
        print(f"  pool size            : {len(pool)}", flush=True)
        print(f"  distinct CNOT costs  : {costs}", flush=True)
        for k, v in by_kind.items():
            print(f"    {k:<7} n={len(v):<3} cost {min(v)}..{max(v)}", flush=True)
        spread_ok = len(costs) > 1
        all_ok &= spread_ok
        print(f"  cost spectrum non-trivial: {spread_ok}", flush=True)
        print(flush=True)

        print(f"  running standard ADAPT (<= {MAX_OPS} ops, noiseless) ...",
              flush=True)
        r_std = ra.standard_adapt_pennylane(
            spec, noiseless, max_operators=MAX_OPS, opt_maxiter=OPT_MAXITER)
        print(f"    E={r_std['energy']:+.8f}  "
              f"err={r_std['energy_error']*1e3:.3f} mHa  "
              f"ops={r_std['n_operators']}  depth={r_std['depth']}  "
              f"cnot={r_std['cnot_count']}  {r_std['runtime_s']}s", flush=True)
        print(f"    seq: {r_std['operators']}", flush=True)

        print(f"  running resource-aware ADAPT lam=1 (<= {MAX_OPS} ops) ...",
              flush=True)
        r_ra = ra.resource_aware_adapt(
            spec, noiseless, lam=1.0, max_operators=MAX_OPS,
            opt_maxiter=OPT_MAXITER)
        print(f"    E={r_ra['energy']:+.8f}  "
              f"err={r_ra['energy_error']*1e3:.3f} mHa  "
              f"ops={r_ra['n_operators']}  depth={r_ra['depth']}  "
              f"cnot={r_ra['cnot_count']}  {r_ra['runtime_s']}s", flush=True)
        print(f"    seq: {r_ra['operators']}", flush=True)

        diverged = r_std["operators"] != r_ra["operators"]
        diverged_somewhere |= diverged
        print(f"  --> SELECTION {'DIFFERS' if diverged else 'IDENTICAL'} "
              f"(std vs resource-aware, lam=1)", flush=True)
        d_cnot = r_ra["cnot_count"] - r_std["cnot_count"]
        d_depth = r_ra["depth"] - r_std["depth"]
        d_err = (r_ra["energy_error"] - r_std["energy_error"]) * 1e3
        print(f"      dCNOT={d_cnot:+d}  ddepth={d_depth:+d}  "
              f"dE_err={d_err:+.3f} mHa", flush=True)
        print(flush=True)

        print("  lambda=0 consistency check ...", flush=True)
        r_l0 = ra.resource_aware_adapt(
            spec, noiseless, lam=0.0, max_operators=MAX_OPS,
            opt_maxiter=OPT_MAXITER)
        same_ops = r_l0["operators"] == r_std["operators"]
        same_e = abs(r_l0["energy"] - r_std["energy"]) < 1e-9
        ok0 = same_ops and same_e
        all_ok &= ok0
        print(f"    ops match={same_ops}  "
              f"|dE|={abs(r_l0['energy']-r_std['energy']):.2e}  "
              f"{'PASS' if ok0 else 'FAIL'}", flush=True)
        print(flush=True)

    print(line, flush=True)
    all_ok &= diverged_somewhere
    print(f"selection diverges at lam=1 for >=1 molecule : {diverged_somewhere}",
          flush=True)
    print("OVERALL: " + ("FIX VERIFIED -- safe to run the sweep"
                         if all_ok else "NOT VERIFIED -- do not sweep yet"),
          flush=True)
    print(line, flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
