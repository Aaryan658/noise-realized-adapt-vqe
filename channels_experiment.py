"""
channels_experiment.py -- does the selection result survive richer noise?

LiH(2e,5o), 10 qubits, fixed_k = 4, exact expectations. Noise models, each at
the same average gate infidelity as the depolarizing baseline at every scale
(so only the STRUCTURE of the noise changes; see gpu_backend.channel_params):

  thermal            amplitude damping + dephasing on every gate (T1/T2 ratio
                     from FakeManilaV2)
  coherent           systematic over-rotation (own axis for 1q, ZZ for CNOT)
  depol+readout      the depolarizing baseline plus symmetric readout error
                     (FakeManilaV2 median assignment error x scale)
  all                thermal + coherent + readout

Reference: the depolarizing K=4 runs in results_10q_fixedk4.csv. Rules:
standard (gradient) and noise-realized (4 candidates).

    .venv\\Scripts\\python.exe channels_experiment.py            # run (resumable)
    .venv\\Scripts\\python.exe channels_experiment.py --analyze  # tables
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

import gpu_backend                                    # noqa: E402
import molecules as mol                               # noqa: E402
import noise_models as nz                             # noqa: E402
import pennylane_resource_aware_adapt as ra           # noqa: E402

warnings.filterwarnings("ignore")
print = functools.partial(print, flush=True)          # noqa: A001

SPEC = mol.LIH_10Q
K = 4
SCALES = (0.05, 0.1, 0.2)
MODELS = {
    "thermal": ("thermal",),
    "coherent": ("coherent",),
    "depol+readout": ("depol", "readout"),
    "all": ("thermal", "coherent", "readout"),
}
RULES = {
    "standard": (ra.standard_adapt_pennylane, {}),
    "NR_c4": (ra.noise_realized_adapt, {"n_candidates": 4}),
}
OUT = os.path.join("results", "results_10q_channels.csv")
REF = os.path.join("results", "results_10q_fixedk4.csv")
COLUMNS = ["rule_key", "model", "noise_scale", "fixed_k", "energy_error_mHa",
           "cnot_count", "operators", "runtime_s", "timestamp", "error"]


def _done(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["model"], float(r["noise_scale"]), r["rule_key"])
                for r in csv.DictReader(fh)
                if not r.get("error") and r.get("noise_scale")}


def run(args) -> int:
    ratio, ro = gpu_backend.device_calibration("FakeManilaV2")
    levels = nz.make_noise_levels("FakeManilaV2", scales=tuple(args.scales))
    os.makedirs("results", exist_ok=True)
    done = _done(args.out)
    new = not os.path.exists(args.out)
    fh = open(args.out, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=COLUMNS)
    if new:
        w.writeheader()
        fh.flush()
    print("=" * 96)
    print(f"RICHER NOISE  {SPEC.label}  K={K}  exact expectations  "
          f"lambda/gamma={ratio:.3f}  readout eps={ro:.4f} (x scale)")
    print(f"models={list(args.models)} scales={list(args.scales)} done={len(done)}")
    print("=" * 96)
    try:
        for model in args.models:
            gpu_backend.set_channels(MODELS[model], ratio=ratio, ro_eps=ro)
            for noise in levels:
                print(f"\n{model}  scale={noise.scale:g}  p1={noise.p1:.2e} "
                      f"p2={noise.p2:.2e}")
                for key, (fn, extra) in RULES.items():
                    if (model, float(noise.scale), key) in done:
                        continue
                    try:
                        r = fn(SPEC, noise, fixed_k=K, opt_maxiter=args.maxiter,
                               **extra)
                        err = r["energy_error"] * 1e3
                        print(f"  {key:<9} err={err:8.3f} mHa CNOT={r['cnot_count']:<3}"
                              f" {r['runtime_s']:.0f}s")
                        row = {c: r.get(c, "") for c in COLUMNS}
                        row.update(rule_key=key, model=model,
                                   noise_scale=noise.scale, fixed_k=K,
                                   energy_error_mHa=round(err, 6),
                                   timestamp=dt.datetime.now().isoformat(
                                       timespec="seconds"))
                    except Exception as exc:  # noqa: BLE001
                        print(f"  {key} FAILED {type(exc).__name__}: {exc}")
                        traceback.print_exc()
                        row = {"rule_key": key, "model": model,
                               "noise_scale": noise.scale,
                               "error": f"{type(exc).__name__}: {exc}"}
                    w.writerow(row)
                    fh.flush()
    finally:
        fh.close()
        gpu_backend.set_channels(("depol",))
    print(f"wrote -> {args.out}")
    return 0


def _ref():
    out = {}
    with open(REF, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[(round(float(r["noise_scale"]), 6), r["rule_key"])] = (
                float(r["energy_error_mHa"]), r["operators"].split(),
                int(r["cnot_count"]))
    return out


def analyze(args) -> int:
    ref = _ref()
    with open(args.out, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not r.get("error")]
    by = {(r["model"], round(float(r["noise_scale"]), 6), r["rule_key"]): r
          for r in rows}
    print("Energy error vs FCI (mHa) and CNOTs, K=4, exact expectations; "
          "delta = NR - standard (negative = NR better)")
    hdr = (f"{'model':<14}{'scale':>6}  {'standard':>16}{'NR-4':>16}"
           f"{'delta':>9}{'std vs depol':>14}{'NR vs depol':>13}")
    print(hdr)
    print("-" * len(hdr))
    for model in ["depol"] + list(MODELS):
        for s in SCALES:
            if model == "depol":
                a = ref.get((s, "standard"))
                b = ref.get((s, "NR_c4"))
                if not a or not b:
                    continue
                ea, ca, eb, cb = a[0], a[2], b[0], b[2]
                da = db = ""
            else:
                ra_ = by.get((model, s, "standard"))
                rb = by.get((model, s, "NR_c4"))
                if not ra_ or not rb:
                    continue
                ea, ca = float(ra_["energy_error_mHa"]), int(ra_["cnot_count"])
                eb, cb = float(rb["energy_error_mHa"]), int(rb["cnot_count"])
                ra0, rb0 = ref.get((s, "standard")), ref.get((s, "NR_c4"))
                da = f"{ea - ra0[0]:+.2f}" if ra0 else ""
                db = f"{eb - rb0[0]:+.2f}" if rb0 else ""
            print(f"{model:<14}{s:>6g}  {ea:>9.2f} ({ca:>3})  {eb:>9.2f} ({cb:>3})"
                  f"{eb - ea:>+9.2f}{da:>14}{db:>13}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--models", nargs="*", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--scales", nargs="*", type=float, default=list(SCALES))
    ap.add_argument("--maxiter", type=int, default=ra.DEFAULT_OPT_MAXITER)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    return analyze(args) if args.analyze else run(args)


if __name__ == "__main__":
    sys.exit(main())
