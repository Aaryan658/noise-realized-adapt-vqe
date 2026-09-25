"""
shots_experiment.py -- finite-shot operator selection on LiH(2e,5o), 10 qubits.

Question: does gradient-based ADAPT selection survive a realistic shot budget,
and how does it compare with the energy-based noise-realized rule at the same
budget? Every energy evaluation (optimizer steps, shift-rule gradients, candidate
scoring) is a finite-shot estimate: each Pauli term of H is a +/-1 binomial
average over S shots (no commuting-group sharing, i.e. the conservative
ungrouped model). Gradients use the exact two-term shift rule. The circuit each
run builds is scored by its EXACT noisy energy, so the reported error is about
the choices made, not about measurement noise in the final number.

Design: fixed_k = 4 (removes the stopping-rule confound), noise 0.1x, rules
standard and noise-realized (4 candidates), S in {1e4,1e5,1e6,1e7} per term,
5 seeds. Reference: the exact-expectation K=4 run in results_10q_fixedk4.csv.

    .venv\\Scripts\\python.exe shots_experiment.py            # run (resumable)
    .venv\\Scripts\\python.exe shots_experiment.py --analyze  # summary tables
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import functools
import math
import os
import sys
import traceback
import warnings

os.environ["ADAPT_BACKEND"] = "gpu"

import numpy as np                                    # noqa: E402

import gpu_backend                                    # noqa: E402
import molecules as mol                               # noqa: E402
import noise_models as nz                             # noqa: E402
import pennylane_resource_aware_adapt as ra           # noqa: E402

warnings.filterwarnings("ignore")
print = functools.partial(print, flush=True)          # noqa: A001

SPEC = mol.LIH_10Q
K = 4
SCALE = 0.1
SHOTS = (10 ** 4, 10 ** 5, 10 ** 6, 10 ** 7)
SEEDS = (0, 1, 2, 3, 4)
RULES = {
    "standard": (ra.standard_adapt_pennylane, {}),
    "NR_c4": (ra.noise_realized_adapt, {"n_candidates": 4}),
}
OUT = os.path.join("results", "results_10q_shots.csv")
REF = os.path.join("results", "results_10q_fixedk4.csv")
COLUMNS = [
    "rule_key", "shots_per_term", "seed", "noise_scale", "fixed_k",
    "energy_error_mHa", "energy_measured", "cnot_count", "operators",
    "n_energy_evals", "n_terms", "total_term_shots", "runtime_s",
    "timestamp", "error",
]


def _done(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["rule_key"], int(r["shots_per_term"]), int(r["seed"]))
                for r in csv.DictReader(fh)
                if not r.get("error") and r.get("seed")}


def run(args) -> int:
    noise = nz.make_noise_levels("FakeManilaV2", scales=(SCALE,))[0]
    os.makedirs("results", exist_ok=True)
    done = _done(args.out)
    new = not os.path.exists(args.out)
    fh = open(args.out, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=COLUMNS)
    if new:
        w.writeheader()
        fh.flush()
    print("=" * 96)
    print(f"FINITE-SHOT SELECTION  {SPEC.label}  K={K}  noise={SCALE}x  "
          f"exact FCI={mol.fci_energy(SPEC):+.8f}")
    print(f"shots/term={list(args.shots)} seeds={list(args.seeds)} "
          f"rules={list(RULES)}  done={len(done)}")
    print("=" * 96)
    try:
        for S in args.shots:
            for seed in args.seeds:
                for key, (fn, extra) in RULES.items():
                    if (key, S, seed) in done:
                        continue
                    gpu_backend.set_shots(S, seed=1000 * seed + 7)
                    try:
                        r = fn(SPEC, noise, fixed_k=K, opt_maxiter=args.maxiter,
                               **extra)
                        err = r["energy_error"] * 1e3
                        tot = r["n_energy_evals"] * r["n_terms"] * S
                        print(f"S={S:>8} seed={seed} {key:<9} err={err:8.3f} mHa "
                              f"CNOT={r['cnot_count']:<3} evals={r['n_energy_evals']:<6}"
                              f" {r['runtime_s']:.0f}s")
                        row = {c: r.get(c, "") for c in COLUMNS}
                        row.update(rule_key=key, shots_per_term=S, seed=seed,
                                   noise_scale=SCALE, fixed_k=K,
                                   energy_error_mHa=round(err, 6),
                                   total_term_shots=tot,
                                   timestamp=dt.datetime.now().isoformat(
                                       timespec="seconds"))
                    except Exception as exc:  # noqa: BLE001
                        print(f"S={S} seed={seed} {key} FAILED "
                              f"{type(exc).__name__}: {exc}")
                        traceback.print_exc()
                        row = {"rule_key": key, "shots_per_term": S, "seed": seed,
                               "error": f"{type(exc).__name__}: {exc}"}
                    w.writerow(row)
                    fh.flush()
    finally:
        fh.close()
        gpu_backend.set_shots(0)
    print(f"wrote -> {args.out}")
    return 0


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def _wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def _ref_sequence(rule):
    with open(REF, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["rule_key"] == rule and abs(float(r["noise_scale"]) - SCALE) < 1e-9:
                return r["operators"].split(), float(r["energy_error_mHa"])
    return [], float("nan")


def analyze(args) -> int:
    with open(args.out, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not r.get("error")]
    ref = {k: _ref_sequence(k) for k in RULES}
    by = {}
    for r in rows:
        by.setdefault((r["rule_key"], int(r["shots_per_term"])), {})[
            int(r["seed"])] = r
    print(f"exact-expectation reference (K={K}, {SCALE}x): "
          + ", ".join(f"{k}={v[1]:.3f} mHa" for k, v in ref.items()))
    print()
    hdr = (f"{'shots/term':>10} {'rule':<9} {'n':>2} {'err mean+-sem (mHa)':>22} "
           f"{'pick agree w/ exact':>20} {'term-shots/run':>15}")
    print(hdr)
    print("-" * len(hdr))
    for S in sorted({s for (_, s) in by}):
        for key in RULES:
            d = by.get((key, S), {})
            if not d:
                continue
            e = np.array([float(r["energy_error_mHa"]) for r in d.values()])
            sem = e.std(ddof=1) / math.sqrt(len(e)) if len(e) > 1 else float("nan")
            seq = ref[key][0]
            agree = np.mean([
                np.mean([a == b for a, b in zip(r["operators"].split(), seq)])
                for r in d.values()])
            tot = np.mean([float(r["total_term_shots"]) for r in d.values()])
            print(f"{S:>10.0e} {key:<9} {len(e):>2} "
                  f"{e.mean():>12.3f} +- {sem:<7.3f} {agree:>19.0%} {tot:>15.2e}")
    print()
    print("Paired NR_c4 - standard (same seed), negative = NR better:")
    print(f"{'shots/term':>10} {'n':>2} {'mean diff (mHa)':>18} {'NR wins':>9} "
          f"{'95% Wilson CI':>16}")
    for S in sorted({s for (_, s) in by}):
        a, b = by.get(("standard", S), {}), by.get(("NR_c4", S), {})
        seeds = sorted(set(a) & set(b))
        if not seeds:
            continue
        diff = np.array([float(b[s]["energy_error_mHa"])
                         - float(a[s]["energy_error_mHa"]) for s in seeds])
        wins = int((diff < 0).sum())
        lo, hi = _wilson(wins, len(diff))
        sem = diff.std(ddof=1) / math.sqrt(len(diff)) if len(diff) > 1 else float("nan")
        print(f"{S:>10.0e} {len(diff):>2} {diff.mean():>+10.3f} +- {sem:<6.3f} "
              f"{wins:>4}/{len(diff):<3} [{lo:.2f}, {hi:.2f}]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--shots", nargs="*", type=int, default=list(SHOTS))
    ap.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    ap.add_argument("--maxiter", type=int, default=ra.DEFAULT_OPT_MAXITER)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    return analyze(args) if args.analyze else run(args)


if __name__ == "__main__":
    sys.exit(main())
