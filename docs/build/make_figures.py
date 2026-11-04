"""
make_figures.py -- draws the four 10-qubit figures used by the new report
(docs/REPORT_UPDATED.docx) from the result CSVs into docs/figures/.

    .venv\\Scripts\\python.exe docs\\build\\make_figures.py
"""

from __future__ import annotations

import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
import common as c                                    # noqa: E402

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25,
    "figure.dpi": 200, "savefig.bbox": "tight",
})
col = {k: "#" + v for k, v in c.RULE_COLOR.items()}
os.makedirs(c.FIG, exist_ok=True)


def fig_free():
    free = c.free_running()
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    for rule in ("standard", "resource_aware", "NR_c4", "NR_c8"):
        ys = [free[(rule, s)][0] for s in c.SCALES]
        ax.plot(c.SCALES, ys, marker="o", color=col[rule],
                label=c.RULE_LABEL[rule], lw=1.6, ms=4)
    ax.axhline(1.6, color="k", ls=":", lw=0.8)
    ax.text(0.201, 1.9, "chemical accuracy", fontsize=7, ha="right")
    ax.set_yscale("log")
    ax.set_xlabel("noise scale (x FakeManilaV2 median gate error)")
    ax.set_ylabel("energy error vs FCI (mHa)")
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(os.path.join(c.FIG, "fig_10q_free_running.png"))
    plt.close(fig)


def fig_matched():
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.0), sharey=True)
    for ax, k in zip(axes, (4, 6)):
        d = c.fixed_k(k)
        for rule in ("standard", "resource_aware", "NR_c4", "NR_c8"):
            ys = [d[(rule, s)][0] for s in c.SCALES]
            ax.plot(c.SCALES, ys, marker="o", color=col[rule], lw=1.5, ms=3.5,
                    label=c.RULE_LABEL[rule])
        ax.set_title(f"K = {k} operators", fontsize=9)
        ax.set_xlabel("noise scale")
    axes[0].set_ylabel("energy error vs FCI (mHa)")
    axes[0].legend(fontsize=6.5, frameon=False)
    fig.savefig(os.path.join(c.FIG, "fig_10q_matched_k.png"))
    plt.close(fig)


def fig_shots():
    sh = c.shots()
    ref4 = c.fixed_k(4)
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    xs = sorted({s for (_, s) in sh})
    for rule, name in (("standard", "standard (gradient)"),
                       ("NR_c4", "noise-realized (4 cand.)")):
        ms = [c.mean_sem(sh[(rule, s)]) for s in xs]
        ax.errorbar(xs, [m for m, _ in ms], yerr=[e for _, e in ms],
                    marker="o", capsize=3, color=col[rule], label=name, lw=1.6,
                    ms=4)
        ax.axhline(ref4[(rule, 0.1)][0], color=col[rule], ls="--", lw=0.8,
                   alpha=0.7)
    ax.set_xscale("log")
    ax.set_xlabel("shots per Pauli term")
    ax.set_ylabel("energy error vs FCI (mHa)")
    ax.text(xs[0] * 1.15, ref4[("standard", 0.1)][0] + 1.0,
            "dashed: exact expectations", fontsize=7, ha="left")
    ax.legend(fontsize=7, frameon=False)
    fig.savefig(os.path.join(c.FIG, "fig_10q_shots.png"))
    plt.close(fig)


def fig_noise_structure():
    ch = c.channels()
    ref = c.fixed_k(4)
    models = ["depolarizing", "thermal", "coherent", "depol+readout", "all"]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.0), sharey=True)
    w = 0.38
    for ax, s in zip(axes, (0.05, 0.2)):
        for j, (rule, name) in enumerate((("standard", "standard"),
                                          ("NR_c4", "noise-realized"))):
            ys = [ref[(rule, s)][0] if m == "depolarizing"
                  else ch[(m, s, rule)][0] for m in models]
            ax.bar([i + (j - 0.5) * w for i in range(len(models))], ys, w,
                   color=col[rule], label=name)
        ax.set_xticks(range(len(models)))
        ax.set_xticklabels(["depol.", "thermal", "coherent", "depol.\n+readout",
                            "all"], fontsize=7)
        ax.set_title(f"noise scale {s}x", fontsize=9)
    axes[0].set_ylabel("energy error vs FCI (mHa)")
    axes[0].legend(fontsize=7, frameon=False)
    fig.savefig(os.path.join(c.FIG, "fig_10q_noise_structure.png"))
    plt.close(fig)


if __name__ == "__main__":
    for f in (fig_free, fig_matched, fig_shots, fig_noise_structure):
        f()
    print("wrote", sorted(os.listdir(c.FIG)))
