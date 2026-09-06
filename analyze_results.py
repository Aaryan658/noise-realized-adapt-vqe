"""
analyze_results.py -- plots and summary tables from results.csv.

Produces:
  1. energy_error_vs_noise.png -- energy error vs noise level, one line per
     strategy, Qiskit and PennyLane on the SAME axes (one panel per molecule).
  2. circuit_depth.png -- circuit depth and CNOT count bar charts.
  3. summary.csv -- tidy table for pasting into the writeup.

Plotting conventions chosen so the writeup reads correctly:
  * Option B (baseline) strategies are drawn dashed / hatched; Option A (the
    contribution) is solid and heavier. A reader should be able to tell
    contribution from baseline without consulting the legend.
  * Energy error is on a LOG axis, floored at 1e-6 Ha. Noiseless runs reach
    ~1e-9 Ha, which on a linear axis flattens every other point onto the
    x-axis.
  * The chemical-accuracy line (1.6 mHa) is drawn, since "below chemical
    accuracy" is the meaningful threshold rather than "small".
  * Rows with comparable=False (raw-device noise, Qiskit-only) are EXCLUDED
    from the cross-framework line plot by default -- drawing them beside
    PennyLane results would imply a comparison the noise models do not
    support. Pass --include-device-noise to show them anyway.

Usage
-----
    python analyze_results.py
    python analyze_results.py --csv results/results.csv --outdir results
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

warnings.filterwarnings("ignore")

CHEMICAL_ACCURACY_MHA = 1.6
ERROR_FLOOR_HA = 1e-6

# Consistent styling across both figures.
STYLE = {
    "UCCSD":                     dict(color="#4C72B0", marker="o", ls="--"),
    "HEA(reps=2)":               dict(color="#DD8452", marker="s", ls="--"),
    "ADAPT-VQE(standard)":       dict(color="#55A868", marker="^", ls="--"),
    "ADAPT-VQE(standard,PL)":    dict(color="#8172B3", marker="v", ls=":"),
    "ADAPT-VQE(resource-aware)": dict(color="#C44E52", marker="D", ls="-"),
}
CONTRIBUTION = "ADAPT-VQE(resource-aware)"
PL_BASELINE = "ADAPT-VQE(standard,PL)"


def load(csv_path):
    import pandas as pd

    if not os.path.exists(csv_path):
        raise SystemExit(f"No results file at {csv_path}. "
                         f"Run:  python run_experiments.py")
    df = pd.read_csv(csv_path)

    if "error" in df.columns:
        failed = df["error"].notna() & (df["error"].astype(str).str.strip() != "")
        if failed.any():
            print(f"NOTE: {int(failed.sum())} run(s) failed and are excluded:")
            for _, r in df[failed].iterrows():
                print(f"   {r['molecule']:<16}{r['noise_level']:<14}"
                      f"{r['strategy']:<28}{str(r['error'])[:60]}")
            df = df[~failed]

    for col in ("energy_error", "noise_scale", "depth", "cnot_count",
                "n_operators"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["energy_error"])


def _style(strategy):
    return STYLE.get(strategy, dict(color="grey", marker="x", ls="-"))


def plot_energy_error(df, outdir, include_device=False):
    """Energy error vs noise level, both frameworks on the same axes."""
    if not include_device and "comparable" in df.columns:
        df = df[df["comparable"].astype(str).str.lower() != "false"]

    molecules = sorted(df["molecule"].unique())
    fig, axes = plt.subplots(1, len(molecules),
                             figsize=(7.2 * len(molecules), 5.6), squeeze=False)

    for ax, m in zip(axes[0], molecules):
        sub = df[df["molecule"] == m]
        for strat in sorted(sub["strategy"].unique()):
            s = sub[sub["strategy"] == strat].sort_values("noise_scale")
            if s.empty:
                continue
            st = _style(strat)
            is_contrib = strat == CONTRIBUTION
            ax.plot(s["noise_scale"],
                    np.maximum(s["energy_error"], ERROR_FLOOR_HA) * 1e3,
                    label=f"{strat} [{s['framework'].iloc[0]}]",
                    linewidth=3.0 if is_contrib else 1.8,
                    markersize=9 if is_contrib else 6,
                    zorder=5 if is_contrib else 2,
                    **st)

        ax.axhline(CHEMICAL_ACCURACY_MHA, color="black", lw=1.0, ls="-.",
                   alpha=0.7)
        ax.text(0.99, CHEMICAL_ACCURACY_MHA * 1.15, "chemical accuracy",
                transform=ax.get_yaxis_transform(), ha="right", fontsize=8)
        ax.set_yscale("log")
        ax.set_xlabel("noise level  (multiple of FakeManilaV2 gate error)")
        ax.set_ylabel("energy error vs active-space FCI  [mHa]")
        ax.set_title(m)
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8, loc="best")

    fig.suptitle("Energy error vs noise level  "
                 "(solid/heavy = Option A contribution, dashed = Option B baseline)",
                 fontsize=11)
    fig.tight_layout()
    path = os.path.join(outdir, "energy_error_vs_noise.png")
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def plot_circuit_depth(df, outdir):
    """Circuit depth and CNOT count per strategy, grouped by molecule."""
    molecules = sorted(df["molecule"].unique())
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6))

    for ax, metric, title in (
        (axes[0], "depth", "Transpiled circuit depth"),
        (axes[1], "cnot_count", "CNOT count"),
    ):
        strategies = sorted(df["strategy"].unique())
        width = 0.8 / max(len(strategies), 1)
        x = np.arange(len(molecules))

        for i, strat in enumerate(strategies):
            vals = []
            for m in molecules:
                s = df[(df["molecule"] == m) & (df["strategy"] == strat)]
                # Depth is a property of the ansatz, not of the noise level;
                # take the median across noise levels for robustness.
                vals.append(float(s[metric].median()) if not s.empty else 0.0)
            st = _style(strat)
            is_contrib = strat == CONTRIBUTION
            pos = x + i * width - 0.4 + width / 2
            ax.bar(pos, vals, width * 0.92, label=strat, color=st["color"],
                   edgecolor="black", linewidth=1.4 if is_contrib else 0.5,
                   hatch=None if is_contrib else "//", alpha=0.95)
            for xi, v in zip(pos, vals):
                if v > 0:
                    ax.text(xi, v, f"{v:.0f}", ha="center", va="bottom",
                            fontsize=7)

        ax.set_xticks(x)
        ax.set_xticklabels(molecules)
        ax.set_ylabel(metric)
        ax.set_title(title)
        ax.grid(alpha=0.3, axis="y")
        ax.legend(fontsize=8)

    fig.suptitle("Circuit cost by ansatz strategy  "
                 "(solid = Option A contribution, hatched = Option B baseline)",
                 fontsize=11)
    fig.tight_layout()
    path = os.path.join(outdir, "circuit_depth.png")
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def write_summary(df, outdir):
    cols = ["molecule", "strategy", "framework", "option", "noise_scale",
            "energy_error", "depth", "cnot_count", "n_operators"]
    out = df[[c for c in cols if c in df.columns]].copy()
    out["energy_error_mHa"] = out.pop("energy_error") * 1e3
    out = out.sort_values(["molecule", "strategy", "noise_scale"])
    path = os.path.join(outdir, "summary.csv")
    out.to_csv(path, index=False)
    return path, out


def print_headline(df):
    """The Option A vs its in-framework baseline, in text, for the writeup."""
    line = "-" * 96
    print(line)
    print("HEADLINE: resource-aware vs standard ADAPT "
          "(both PennyLane, same code path)")
    print(line)
    print(f"{'molecule':<16}{'noise':>7}{'standard/mHa':>15}"
          f"{'resrc-aware/mHa':>18}{'delta/mHa':>12}{'depth std':>11}"
          f"{'depth RA':>10}")

    any_row = False
    for m in sorted(df["molecule"].unique()):
        sub = df[df["molecule"] == m]
        for scale in sorted(sub["noise_scale"].dropna().unique()):
            s = sub[sub["noise_scale"] == scale]
            std = s[s["strategy"] == PL_BASELINE]
            ra = s[s["strategy"] == CONTRIBUTION]
            if std.empty or ra.empty:
                continue
            any_row = True
            e_std = float(std["energy_error"].iloc[0]) * 1e3
            e_ra = float(ra["energy_error"].iloc[0]) * 1e3
            print(f"{m:<16}{scale:>7.2f}{e_std:>15.4f}{e_ra:>18.4f}"
                  f"{e_ra - e_std:>12.4f}{float(std['depth'].iloc[0]):>11.0f}"
                  f"{float(ra['depth'].iloc[0]):>10.0f}")
    if not any_row:
        print("  (no paired rows -- run the PennyLane strategies first)")
    print(line)
    print("delta < 0  =>  resource-aware is MORE accurate at that noise level.")
    print("Read this alongside the depth columns: the claim is that a shallower")
    print("circuit survives noise better, so the result to look for is a depth")
    print("reduction with comparable or better accuracy as noise increases.")
    print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=os.path.join("results", "results.csv"))
    ap.add_argument("--outdir", default="results")
    ap.add_argument("--include-device-noise", action="store_true",
                    help="include raw-device (Qiskit-only) rows in the line "
                         "plot; off by default because they are not "
                         "cross-framework comparable")
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    df = load(args.csv)
    if df.empty:
        print("No usable rows.")
        return 1

    p1 = plot_energy_error(df, args.outdir, args.include_device_noise)
    p2 = plot_circuit_depth(df, args.outdir)
    p3, _ = write_summary(df, args.outdir)

    print()
    print_headline(df)
    print()
    print(f"wrote {p1}")
    print(f"wrote {p2}")
    print(f"wrote {p3}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
