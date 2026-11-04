"""
common.py -- loads the 10-qubit result CSVs for the figure and document builders,
so every number in the new Word report and PowerPoint deck is read from the data
rather than retyped.
"""

from __future__ import annotations

import csv
import math
import os
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.path.join(ROOT, "results")
FIG = os.path.join(ROOT, "docs", "figures")

FREE = os.path.join(RES, "results_10q.csv")
FIXED = {4: os.path.join(RES, "results_10q_fixedk4.csv"),
         6: os.path.join(RES, "results_10q_fixedk6.csv")}
SHOTS = os.path.join(RES, "results_10q_shots.csv")
CHANNELS = os.path.join(RES, "results_10q_channels.csv")

SCALES = (0.0, 0.05, 0.1, 0.2)


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if not r.get("error")]


def _grid(path):
    """{(rule_key, scale): row} for the free-running / fixed-k CSVs."""
    return {(r["rule_key"], round(float(r["noise_scale"]), 6)): r
            for r in _rows(path)}


def free_running():
    """{(rule, scale): (error_mHa, cnot, n_ops)}"""
    return {k: (float(r["energy_error_mHa"]), int(r["cnot_count"]),
                int(r["n_operators"])) for k, r in _grid(FREE).items()}


def fixed_k(k):
    """{(rule, scale): (error_mHa, cnot)}"""
    return {key: (float(r["energy_error_mHa"]), int(r["cnot_count"]))
            for key, r in _grid(FIXED[k]).items()}


def shots():
    """{(rule, shots_per_term): [error_mHa per seed]}"""
    out = defaultdict(list)
    for r in _rows(SHOTS):
        out[(r["rule_key"], int(r["shots_per_term"]))].append(
            float(r["energy_error_mHa"]))
    return dict(out)


def channels():
    """{(model, scale, rule): (error_mHa, cnot)}"""
    return {(r["model"], round(float(r["noise_scale"]), 6), r["rule_key"]):
            (float(r["energy_error_mHa"]), int(r["cnot_count"]))
            for r in _rows(CHANNELS)}


def mean_sem(xs):
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return m, float("nan")
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, math.sqrt(var / n)


# Presentation names for the rule keys used in the CSVs.
RULE_LABEL = {
    "standard": "standard (gradient)",
    "resource_aware": "resource-aware",
    "NR_c4": "noise-realized (4 cand.)",
    "NR_c8": "noise-realized (8 cand.)",
    "NR_adaptive_c4": "NR + adaptive lambda (4)",
    "NR_adaptive_c8": "NR + adaptive lambda (8)",
}

# Shared colour palette (hex without '#'): navy, teal, amber, slate, red.
NAVY, TEAL, AMBER, SLATE, RED, GREEN = (
    "1B2A4A", "1C7293", "C9821C", "667085", "B3412F", "3C8D5A")
RULE_COLOR = {"standard": SLATE, "resource_aware": AMBER,
              "NR_c4": TEAL, "NR_c8": NAVY}
