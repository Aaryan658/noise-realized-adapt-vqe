"""
fixed_k_experiment.py -- matched-operator-count comparison of the four
selection rules on stretched LiH(2e,3o).

WHY THIS EXPERIMENT EXISTS
-------------------------
`results/results_novel.csv` shows `noise_realized` beating standard ADAPT by
0.5-1.4 mHa at 0.25x / 0.5x device noise -- but the energy-plateau stopping
rule terminates different rules at different operator counts, so part of that
gap could be "one rule simply built a longer circuit" rather than "one rule
chose a better operator". This script removes that confound: every rule is
forced (via `_adapt_loop(..., fixed_k=K)`) to build EXACTLY K operators, both
ADAPT stopping criteria disabled, accepting the top-scored operator at every
step whether or not it lowers the energy. Any energy-error gap that survives
is then purely a better *choice* of operator at the same circuit length.

Config: spec = LiH(2e,3o) stretched 3.0 A, K = 6, lam_init = 1.0,
opt_maxiter = 100, n_candidates = 4 (module default), noise scales
{0, 0.05, 0.1, 0.2} x FakeManilaV2 median gate errors.

Output: prints per-noise-scale tables (energy error / CNOTs / operator
sequence / delta vs standard) and writes results/results_fixed_k.csv.
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
import os
import sys
import traceback
import warnings

import molecules as mol
import noise_models as nz
import pennylane_resource_aware_adapt as ra

warnings.filterwarnings("ignore")

print = functools.partial(print, flush=True)  # noqa: A001 -- unbuffered logging

SPEC = mol.LIH
K = 6
LAM = 1.0
OPT_MAXITER = 100
SCALES = (0.0, 0.05, 0.1, 0.2)
OUT_CSV = os.path.join("results", "results_fixed_k.csv")

# name -> (callable, short tag used in the printed tables)
RULES = {
    "standard":                  (ra.standard_adapt_pennylane, "standard"),
    "resource_aware":            (ra.resource_aware_adapt, "resource-aware"),
    "noise_realized":            (ra.noise_realized_adapt, "noise-realized"),
    "noise_realized_adaptive_lambda":
        (ra.noise_realized_adapt_adaptive_lambda, "NR+adaptive-lam"),
}

CSV_COLUMNS = [
    "strategy", "rule_key", "framework", "option", "molecule", "n_qubits",
    "noise_level", "noise_scale", "comparable", "fixed_k",
    "energy", "energy_error", "energy_error_mHa", "fci_energy",
    "delta_vs_standard_mHa",
    "n_parameters", "iterations", "n_operators",
    "depth", "cnot_count", "gate_count",
    "converged", "operators", "lambda", "lambda_init", "lambda_final",
    "runtime_s", "timestamp", "error",
]


def _run_one(fn, noise):
    return fn(SPEC, noise, fixed_k=K, lam=LAM, opt_maxiter=OPT_MAXITER)


def _all_identical(all_results, noise_levels) -> bool:
    """True iff every rule produced the same operator string at every scale."""
    for noise in noise_levels:
        seqs = {
            all_results[(noise.scale, key)]["operators"]
            for key in RULES
            if (noise.scale, key) in all_results
        }
        if len(seqs) != 1:
            return False
    return len(all_results) > 0


def main() -> int:
    os.makedirs(os.path.dirname(OUT_CSV) or ".", exist_ok=True)
    e_fci = mol.fci_energy(SPEC)
    _, n_qubits, _, _ = mol.pennylane_hamiltonian(SPEC)

    print("=" * 100)
    print("FIXED-OPERATOR-COUNT COMPARISON")
    print("=" * 100)
    print(f"molecule      : {SPEC.label}  ({n_qubits} qubits, stretched 3.0 A)")
    print(f"fixed_k       : {K} operators, both ADAPT stopping criteria disabled")
    print(f"lambda_init   : {LAM}")
    print(f"opt_maxiter   : {OPT_MAXITER}  (COBYLA per ADAPT step)")
    print(f"noise scales  : {SCALES}  x FakeManilaV2 median gate errors")
    print(f"FCI(active)   : {e_fci:+.8f} Ha")
    print("=" * 100)
    print()

    noise_levels = nz.make_noise_levels("FakeManilaV2", scales=SCALES)

    fh = open(OUT_CSV, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    fh.flush()

    all_results: dict[tuple[float, str], dict] = {}

    try:
        for noise in noise_levels:
            print("-" * 100)
            print(f"NOISE {noise.label}  (scale={noise.scale:g}, "
                  f"p1={noise.p1:.3e}, p2={noise.p2:.3e})")
            print("-" * 100)

            std_err_mHa = None
            for key, (fn, tag) in RULES.items():
                try:
                    r = _run_one(fn, noise)
                    err_mHa = r["energy_error"] * 1e3
                    if key == "standard":
                        std_err_mHa = err_mHa
                    delta = (None if std_err_mHa is None
                             else err_mHa - std_err_mHa)
                    all_results[(noise.scale, key)] = r

                    print(f"  {tag:<16} "
                          f"err={err_mHa:8.3f} mHa   "
                          f"CNOT={r['cnot_count']:<4} depth={r['depth']:<4} "
                          f"ops={r['n_operators']}  "
                          f"lam_f={r.get('lambda_final')}  "
                          f"{r['runtime_s']:.0f}s")
                    print(f"      seq: {r['operators']}")
                    if delta is not None:
                        sign = "+" if delta >= 0 else ""
                        verdict = ("worse" if delta > 0
                                   else "better" if delta < 0 else "equal")
                        print(f"      delta vs standard: {sign}{delta:.3f} mHa "
                              f"({verdict})")

                    row = {c: r.get(c, "") for c in CSV_COLUMNS}
                    row.update({
                        "rule_key": key,
                        "fixed_k": K,
                        "energy_error_mHa": round(err_mHa, 6),
                        "delta_vs_standard_mHa":
                            ("" if delta is None else round(delta, 6)),
                        "timestamp":
                            dt.datetime.now().isoformat(timespec="seconds"),
                    })
                    writer.writerow(row)
                    fh.flush()
                except Exception as exc:  # noqa: BLE001 -- log and continue
                    print(f"  {tag:<16} FAILED  {type(exc).__name__}: {exc}")
                    traceback.print_exc()
                    writer.writerow({
                        "strategy": key, "rule_key": key,
                        "framework": "pennylane", "molecule": SPEC.label,
                        "noise_level": noise.label, "noise_scale": noise.scale,
                        "fixed_k": K,
                        "timestamp":
                            dt.datetime.now().isoformat(timespec="seconds"),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    fh.flush()
            print()
    finally:
        fh.close()

    # ---- summary tables -----------------------------------------------------
    hdr = f"{'noise':<10}" + "".join(f"{tag:>18}" for _, tag in RULES.values())

    print("=" * 100)
    print(f"SUMMARY  --  energy error vs active-space FCI (mHa), fixed_k = {K}")
    print("=" * 100)
    print(hdr)
    for noise in noise_levels:
        cells = [f"{noise.label:<10}"]
        for key in RULES:
            r = all_results.get((noise.scale, key))
            cells.append(f"{r['energy_error'] * 1e3:>18.3f}" if r
                         else f"{'--':>18}")
        print("".join(cells))

    print()
    print("SUMMARY  --  delta vs standard (mHa); negative = novel rule "
          "more accurate at matched k")
    print(hdr)
    for noise in noise_levels:
        std = all_results.get((noise.scale, "standard"))
        cells = [f"{noise.label:<10}"]
        for key in RULES:
            r = all_results.get((noise.scale, key))
            if r is None or std is None:
                cells.append(f"{'--':>18}")
            else:
                d = (r["energy_error"] - std["energy_error"]) * 1e3
                cells.append(f"{d:>+18.3f}")
        print("".join(cells))

    print()
    print("SUMMARY  --  CNOT count")
    print(hdr)
    for noise in noise_levels:
        cells = [f"{noise.label:<10}"]
        for key in RULES:
            r = all_results.get((noise.scale, key))
            cells.append(f"{r['cnot_count']:>18}" if r else f"{'--':>18}")
        print("".join(cells))

    print()
    print("SUMMARY  --  operator sequence per rule per noise scale")
    for noise in noise_levels:
        print(f"  [{noise.label}]")
        for key, (_, tag) in RULES.items():
            r = all_results.get((noise.scale, key))
            print(f"    {tag:<16} {r['operators'] if r else '--'}")

    identical = _all_identical(all_results, noise_levels)
    print()
    print("=" * 100)
    if identical:
        print("GUARDRAIL TRIPPED: all four rules selected IDENTICAL operator "
              "sequences at every noise scale.")
        print("Matched-k cannot separate the rules on LiH(2e,3o) -- a larger "
              "(10-qubit) active space is required.")
    else:
        print("Rules diverge in operator choice at matched k -- see the delta "
              "table above for the size of the effect.")
    print(f"wrote -> {OUT_CSV}")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
