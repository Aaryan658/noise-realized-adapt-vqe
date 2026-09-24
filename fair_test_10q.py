"""
fair_test_10q.py -- the "fair test" from docs/NOVEL_RESULTS.md: LiH(2e,5o),
10 qubits, on the CUDA density-matrix backend (gpu_backend.py).

Grid: noise scales {0, 0.05, 0.1, 0.2} x FakeManilaV2 median gate errors,
      max_operators = 16, free-running ADAPT (both stopping rules active),
      rules: standard, resource-aware, noise-realized (4 and 8 candidates),
      noise-realized + adaptive-lambda (4 and 8 candidates).

Resumable: every finished cell is appended to results/results_10q.csv and
skipped on the next launch. Run:

    .venv\\Scripts\\python.exe fair_test_10q.py            # full grid
    .venv\\Scripts\\python.exe fair_test_10q.py --quick    # 3 operators, smoke test
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import functools
import os
import sys
import traceback
import warnings

os.environ["ADAPT_BACKEND"] = "gpu"

import molecules as mol                              # noqa: E402
import noise_models as nz                            # noqa: E402
import pennylane_resource_aware_adapt as ra          # noqa: E402

warnings.filterwarnings("ignore")
print = functools.partial(print, flush=True)         # noqa: A001

SPEC = mol.LIH_10Q
SCALES = (0.0, 0.05, 0.1, 0.2)
DEFAULT_OUT = os.path.join("results", "results_10q.csv")

# key -> (callable, extra kwargs)
CONFIGS = {
    "standard":       (ra.standard_adapt_pennylane, {}),
    "resource_aware": (ra.resource_aware_adapt, {}),
    "NR_c4":          (ra.noise_realized_adapt, {"n_candidates": 4}),
    "NR_c8":          (ra.noise_realized_adapt, {"n_candidates": 8}),
    "NR_adaptive_c4": (ra.noise_realized_adapt_adaptive_lambda,
                       {"n_candidates": 4}),
    "NR_adaptive_c8": (ra.noise_realized_adapt_adaptive_lambda,
                       {"n_candidates": 8}),
}

COLUMNS = [
    "rule_key", "strategy", "molecule", "n_qubits", "noise_level",
    "noise_scale", "n_candidates", "energy", "energy_error_mHa", "fci_energy",
    "n_operators", "n_parameters", "depth", "cnot_count", "gate_count",
    "converged", "operators", "lambda_final", "runtime_s", "timestamp", "error",
    "fixed_k",
]


def _done_cells(path) -> set[tuple[str, float]]:
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["rule_key"], float(r["noise_scale"]))
                for r in csv.DictReader(fh)
                if not r.get("error") and r.get("noise_scale")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="3 operators, opt_maxiter 40, scale 0.1 only")
    ap.add_argument("--scales", nargs="*", type=float, default=None)
    ap.add_argument("--rules", nargs="*", default=None, choices=list(CONFIGS))
    ap.add_argument("--max-operators", type=int, default=16)
    ap.add_argument("--opt-maxiter", type=int, default=ra.DEFAULT_OPT_MAXITER)
    ap.add_argument("--fixed-k", type=int, default=None,
                    help="matched-length mode: every rule builds exactly K "
                         "operators, stopping rules disabled")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    scales = args.scales if args.scales is not None else SCALES
    max_ops, maxiter = args.max_operators, args.opt_maxiter
    if args.quick:
        scales, max_ops, maxiter = (0.1,), 3, 40
    rules = args.rules or list(CONFIGS)
    out = args.out

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    done = _done_cells(out)
    new_file = not os.path.exists(out)
    e_fci = mol.fci_energy(SPEC)
    print("=" * 96)
    print(f"FAIR TEST  {SPEC.label}  10 qubits  FCI(active)={e_fci:+.8f} Ha")
    print(f"scales={tuple(scales)}  max_operators={max_ops}  "
          f"opt_maxiter={maxiter}  rules={rules}")
    print(f"already done: {len(done)} cells  ->  {out}")
    print("=" * 96)

    fh = open(out, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=COLUMNS)
    if new_file:
        w.writeheader()
        fh.flush()

    try:
        for noise in nz.make_noise_levels("FakeManilaV2", scales=tuple(scales)):
            print(f"\nNOISE {noise.label}  scale={noise.scale:g}  "
                  f"p1={noise.p1:.3e} p2={noise.p2:.3e}")
            for key in rules:
                if (key, float(noise.scale)) in done:
                    print(f"  {key:<16} skip (done)")
                    continue
                fn, extra = CONFIGS[key]
                try:
                    kw = ({"fixed_k": args.fixed_k} if args.fixed_k
                          else {"max_operators": max_ops})
                    r = fn(SPEC, noise, opt_maxiter=maxiter, **kw, **extra)
                    err = r["energy_error"] * 1e3
                    print(f"  {key:<16} err={err:9.3f} mHa  "
                          f"CNOT={r['cnot_count']:<4} ops={r['n_operators']:<3} "
                          f"{r['runtime_s']:.0f}s")
                    print(f"      {r['operators']}")
                    row = {c: r.get(c, "") for c in COLUMNS}
                    row.update(rule_key=key, energy_error_mHa=round(err, 6),
                               fixed_k=args.fixed_k or "",
                               n_candidates=extra.get("n_candidates", ""),
                               timestamp=dt.datetime.now().isoformat(
                                   timespec="seconds"))
                except Exception as exc:  # noqa: BLE001 -- log and continue
                    print(f"  {key:<16} FAILED {type(exc).__name__}: {exc}")
                    traceback.print_exc()
                    row = {"rule_key": key, "molecule": SPEC.label,
                           "noise_level": noise.label,
                           "noise_scale": noise.scale,
                           "error": f"{type(exc).__name__}: {exc}"}
                w.writerow(row)
                fh.flush()
    finally:
        fh.close()
    print(f"\nwrote -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
