"""
run_experiments.py -- the full pipeline.

Runs   {Option B strategies} + {Option A strategies}
     x {H2, LiH}
     x {noise levels}
and writes one row per run to CSV.

Strategies
----------
OPTION B (baseline, no novelty claimed)     framework
    UCCSD                                   qiskit
    HEA(reps=2)                             qiskit
    ADAPT-VQE(standard)                     qiskit

OPTION A (contribution + its in-framework control)
    ADAPT-VQE(standard,PL)                  pennylane   <- control, not novel
    ADAPT-VQE(resource-aware)               pennylane   <- THE CONTRIBUTION

Validation gates run FIRST by default. The brief asked for noiseless energies
to be checked against known references before any noise work, so
--skip-validation exists but is off by default and prints a warning.

Usage
-----
    python run_experiments.py                  # full sweep
    python run_experiments.py --quick          # H2 only, 3 noise levels
    python run_experiments.py --molecules H2   # subset
    python run_experiments.py --out results/my.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import traceback
import warnings

import molecules as mol
import noise_models as nz
import pennylane_resource_aware_adapt as ra
import qiskit_baselines as qb

warnings.filterwarnings("ignore")

CSV_COLUMNS = [
    "strategy", "framework", "option", "molecule", "n_qubits",
    "noise_level", "noise_scale", "comparable",
    "energy", "energy_error", "fci_energy",
    "n_parameters", "iterations", "n_operators",
    "depth", "cnot_count", "gate_count",
    "converged", "operators", "lambda", "lambda_init", "lambda_final",
    "n_restarts", "runtime_s", "timestamp", "error",
]

ALL_STRATEGIES = {
    # Option B -- Qiskit
    "UCCSD": ("qiskit", qb.run_uccsd),
    "HEA": ("qiskit", qb.run_hardware_efficient),
    "ADAPT-VQE(standard)": ("qiskit", qb.run_adapt_vqe),
    # Option A -- PennyLane
    "ADAPT-VQE(standard,PL)": ("pennylane", ra.standard_adapt_pennylane),
    "ADAPT-VQE(resource-aware)": ("pennylane", ra.resource_aware_adapt),
    # Option A -- PennyLane, NOVEL selection rules
    "ADAPT-VQE(noise-realized)": ("pennylane", ra.noise_realized_adapt),
    "ADAPT-VQE(noise-realized,adaptive-lam)":
        ("pennylane", ra.noise_realized_adapt_adaptive_lambda),
}


def _row(result: dict) -> dict:
    row = {c: result.get(c, "") for c in CSV_COLUMNS}
    row["timestamp"] = dt.datetime.now().isoformat(timespec="seconds")
    return row


def run_sweep(molecules, noise_levels, strategies, out_path, verbose=True,
              pl_kwargs=None):
    """
    pl_kwargs -- extra keyword args forwarded ONLY to the PennyLane (Option A)
    strategies, used to scope the qubit-ADAPT run down for a tractable noisy
    sweep (e.g. max_operators, lam). The Qiskit baselines ignore it.
    """
    pl_kwargs = pl_kwargs or {}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    rows, failures = [], 0

    total = len(molecules) * len(noise_levels) * len(strategies)
    line = "-" * 104

    if verbose:
        print(line)
        print(f"SWEEP: {len(molecules)} molecules x {len(noise_levels)} noise "
              f"levels x {len(strategies)} strategies = {total} runs")
        print(line)
        print(f"{'molecule':<16}{'noise':<14}{'strategy':<28}"
              f"{'energy':>14}{'err/mHa':>10}{'depth':>7}{'CNOT':>6}{'sec':>7}")
        print(line)

    # Write the CSV incrementally: each row is flushed as soon as its run
    # finishes, so a sweep that is interrupted (this one takes hours) still
    # leaves a usable partial results.csv rather than nothing.
    fh = open(out_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    fh.flush()

    def _emit(row):
        rows.append(row)
        writer.writerow(row)
        fh.flush()

    try:
        for spec in molecules:
            for noise in noise_levels:
                for name in strategies:
                    framework, fn = ALL_STRATEGIES[name]
                    # Raw-device noise models exist only on the Qiskit side.
                    if framework == "pennylane" and not noise.comparable:
                        if verbose:
                            print(f"{spec.label:<16}{noise.label:<14}{name:<28}"
                                  f"   SKIP (device model is Qiskit-only)")
                        continue
                    try:
                        res = (fn(spec, noise, **pl_kwargs)
                               if framework == "pennylane" else fn(spec, noise))
                        _emit(_row(res))
                        if verbose:
                            print(f"{spec.label:<16}{noise.label:<14}"
                                  f"{res['strategy']:<28}{res['energy']:>14.8f}"
                                  f"{res['energy_error'] * 1e3:>10.3f}"
                                  f"{res['depth']:>7}{res['cnot_count']:>6}"
                                  f"{res['runtime_s']:>7.1f}")
                    except Exception as exc:
                        failures += 1
                        _emit(_row({
                            "strategy": name, "framework": framework,
                            "molecule": spec.label, "noise_level": noise.label,
                            "noise_scale": noise.scale,
                            "error": f"{type(exc).__name__}: {exc}",
                        }))
                        if verbose:
                            print(f"{spec.label:<16}{noise.label:<14}{name:<28}"
                                  f"  FAILED {type(exc).__name__}: {str(exc)[:40]}")
                            traceback.print_exc(limit=1)
    finally:
        fh.close()

    if verbose:
        print(line)
        print(f"wrote {len(rows)} rows -> {out_path}"
              + (f"   ({failures} FAILED)" if failures else ""))
        print(line)
    return rows, failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join("results", "results.csv"))
    ap.add_argument("--molecules", nargs="*", default=None,
                    choices=["H2", "LiH"],
                    help="subset of molecules (default: both)")
    ap.add_argument("--strategies", nargs="*", default=None,
                    help="subset of strategy names to run (default: all). "
                         f"Choices: {list(ALL_STRATEGIES)}")
    ap.add_argument("--backend", default="FakeManilaV2",
                    help="fake backend used to calibrate noise rates")
    ap.add_argument("--scales", nargs="*", type=float, default=None,
                    help="noise scale multipliers (default 0 0.25 0.5 1). "
                         "1 = real FakeManilaV2 gate-error rate; beyond ~1 "
                         "every strategy is already past the point where any "
                         "correlation energy survives, so the informative "
                         "range is [0, 1].")
    ap.add_argument("--pl-max-operators", type=int, default=10,
                    help="cap on qubit-ADAPT operators for the Option A "
                         "(PennyLane) strategies. Scopes the noisy sweep down; "
                         "the module default (16) is used elsewhere. 10 ops "
                         "already reaches FCI on both molecules noiseless.")
    ap.add_argument("--pl-opt-maxiter", type=int, default=120,
                    help="COBYLA iteration budget per ADAPT step for the "
                         "Option A strategies (module default is 200).")
    ap.add_argument("--lam", type=float, default=1.0,
                    help="lambda in the resource-aware score "
                         "grad/(1+lam*cnot_cost). lam=0 reproduces standard "
                         "ADAPT exactly.")
    ap.add_argument("--include-device-noise", action="store_true",
                    help="also run the raw FakeBackend model (Qiskit only, "
                         "NOT cross-framework comparable)")
    ap.add_argument("--quick", action="store_true",
                    help="H2 only, scales 0/1/4 -- fast pipeline check")
    ap.add_argument("--skip-validation", action="store_true",
                    help="skip the noiseless reference checks (NOT advised)")
    args = ap.parse_args(argv)

    # ---- validation gates -------------------------------------------------
    if args.skip_validation:
        print("WARNING: skipping validation. The noiseless energies have NOT "
              "been checked against known references, and the Qiskit/PennyLane "
              "noise equivalence has NOT been verified.\n")
    else:
        print("=" * 104)
        print("VALIDATION 1/2 -- molecular references")
        print("=" * 104)
        if not mol.validate():
            print("\nABORT: reference energies failed validation.")
            return 1
        print()
        print("=" * 104)
        print("VALIDATION 2/2 -- Qiskit vs PennyLane noise equivalence")
        print("=" * 104)
        if not nz.selftest():
            print("\nABORT: noise models are not on an equivalent footing; "
                  "Option A vs Option B would not be a fair comparison.")
            return 1
        print()

    # ---- sweep configuration ---------------------------------------------
    if args.quick:
        molecules = [mol.H2]
        scales = (0.0, 1.0, 4.0)
    else:
        names = args.molecules or ["H2", "LiH"]
        by_name = {"H2": mol.H2, "LiH": mol.LIH}
        molecules = [by_name[n] for n in names]
        scales = tuple(args.scales) if args.scales else (0.0, 0.25, 0.5, 1.0)

    noise_levels = nz.make_noise_levels(args.backend, scales=scales)
    if args.include_device_noise:
        noise_levels.append(nz.device_noise_spec(args.backend))

    pl_kwargs = {"max_operators": args.pl_max_operators, "lam": args.lam,
                 "opt_maxiter": args.pl_opt_maxiter}
    print(f"Option A (PennyLane) scoped to max_operators="
          f"{args.pl_max_operators}, opt_maxiter={args.pl_opt_maxiter}, "
          f"lambda={args.lam}\n")

    strategies = args.strategies or list(ALL_STRATEGIES)
    unknown = [s for s in strategies if s not in ALL_STRATEGIES]
    if unknown:
        print(f"ABORT: unknown strategy name(s): {unknown}\n"
              f"valid: {list(ALL_STRATEGIES)}")
        return 1

    rows, failures = run_sweep(molecules, noise_levels,
                               strategies, args.out,
                               pl_kwargs=pl_kwargs)

    print(f"\nNext: python analyze_results.py --csv {args.out}")
    return 1 if failures and not rows else 0


if __name__ == "__main__":
    sys.exit(main())
