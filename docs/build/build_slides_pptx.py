"""
build_slides_pptx.py -- builds docs/SLIDES_UPDATED.pptx (a new deck; the original
docs/SLIDES.pptx is left untouched). Charts are native, editable PowerPoint charts
and every number from the 10-qubit study is read from the result CSVs.

    .venv\\Scripts\\python.exe docs\\build\\build_slides_pptx.py
"""

from __future__ import annotations

import os
import sys

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (XL_CHART_TYPE, XL_LABEL_POSITION,
                             XL_LEGEND_POSITION, XL_MARKER_STYLE,
                             XL_TICK_LABEL_POSITION)
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

sys.path.insert(0, os.path.dirname(__file__))
import common as c                                    # noqa: E402

OUT = os.path.join(c.ROOT, "docs", "SLIDES_UPDATED.pptx")
NOVEL = os.path.join(c.ROOT, "results", "novel")

NAVY, TEAL, INK, MUTED = "1B2A4A", "1C7293", "1A1A1A", "667085"
LIGHT, RULE, WHITE, PALE = "F3F5F8", "D7DDE4", "FFFFFF", "C6D2E6"
AMBER, SLATE, TINT = "C9821C", "667085", "E2EEF3"
HEAD, BODY = "Georgia", "Calibri"
RULE_CLR = {"standard": SLATE, "resource_aware": AMBER, "NR_c4": TEAL,
            "NR_c8": NAVY}

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
_state = {"n": 0}


def rgb(h):
    return RGBColor.from_string(h)


# --------------------------------------------------------------------------
# text, shapes
# --------------------------------------------------------------------------
def _bullet(p, indent=0.26):
    ppr = p._p.get_or_add_pPr()
    ppr.set("marL", str(int(Inches(indent))))
    ppr.set("indent", str(-int(Inches(indent))))
    etree.SubElement(ppr, qn("a:buChar")).set("char", "•")


def _fill_para(p, spec, size, color, bold, italic, font):
    parts = ([(spec, bold)] if isinstance(spec, str)
             else [(spec[0] + " ", True), (spec[1], bold)])
    for t, b in parts:
        r = p.add_run()
        r.text = t
        f = r.font
        f.size, f.bold, f.italic, f.name = Pt(size), b, italic, font
        f.color.rgb = rgb(color)


def text(slide, x, y, w, h, paras, size=16, color=INK, bold=False, italic=False,
         font=BODY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, bullet=False,
         after=6, spacing=1.05):
    if isinstance(paras, (str, tuple)):
        paras = [paras]
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, sp in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(after)
        p.line_spacing = spacing
        if bullet:
            _bullet(p)
        _fill_para(p, sp, size, color, bold, italic, font)
    return tb


def card(slide, x, y, w, h, fill=LIGHT, line=None, radius=0.05):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                                Inches(w), Inches(h))
    sh.adjustments[0] = radius
    sh.fill.solid()
    sh.fill.fore_color.rgb = rgb(fill)
    if line:
        sh.line.color.rgb = rgb(line)
        sh.line.width = Pt(0.75)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def badge(slide, x, y, d, label, fill=TEAL, size=16, color=WHITE):
    sh = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d),
                                Inches(d))
    sh.fill.solid()
    sh.fill.fore_color.rgb = rgb(fill)
    sh.line.fill.background()
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.size, r.font.bold, r.font.name = Pt(size), True, BODY
    r.font.color.rgb = rgb(color)
    return sh


def new_slide(dark=False, notes=None):
    s = prs.slides.add_slide(BLANK)
    _state["n"] += 1
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(NAVY if dark else WHITE)
    if not dark:
        text(s, 0.6, 7.03, 9, 0.28,
             "Noise-aware operator selection for ADAPT-VQE  ·  CIA-3",
             size=10, color=MUTED)
        text(s, 12.0, 7.03, 0.73, 0.28, str(_state["n"]), size=10, color=MUTED,
             align=PP_ALIGN.RIGHT)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def header(slide, label, title):
    text(slide, 0.6, 0.42, 12, 0.3, label.upper(), size=12, color=TEAL, bold=True)
    text(slide, 0.6, 0.74, 12.1, 1.0, title, size=28, color=NAVY, bold=True,
         font=HEAD, spacing=0.95)


def stat(slide, x, y, w, big, label, color=TEAL, big_size=38):
    text(slide, x, y, w, 0.7, big, size=big_size, color=color, bold=True,
         font=HEAD)
    text(slide, x, y + 0.72, w, 0.7, label, size=13, color=MUTED)


def picture(slide, path, x, y, w, h):
    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    pw, ph = iw * scale, ih * scale
    slide.shapes.add_picture(path, Inches(x + (w - pw) / 2), Inches(y),
                             Inches(pw), Inches(ph))
    return ph


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
def table(slide, x, y, colw, rows, size=13, row_h=0.42, bold_cells=(),
          hl_rows=(), left_cols=(0,), head_fill=NAVY):
    nr, nc = len(rows), len(rows[0])
    gf = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(sum(colw)),
                                Inches(row_h * nr))
    t = gf.table
    t._tbl.tblPr.set("bandRow", "0")
    t._tbl.tblPr.set("firstRow", "0")
    for j, wd in enumerate(colw):
        t.columns[j].width = Inches(wd)
    for i in range(nr):
        t.rows[i].height = Inches(row_h)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = t.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            fill = head_fill if i == 0 else (
                TINT if i in hl_rows else (LIGHT if i % 2 == 0 else WHITE))
            cell.fill.fore_color.rgb = rgb(fill)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j in left_cols else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(val)
            f = r.font
            f.size, f.name = Pt(size), BODY
            f.bold = (i == 0) or ((i, j) in bold_cells)
            f.color.rgb = rgb(WHITE if i == 0 else INK)
    return gf


# --------------------------------------------------------------------------
# native charts
# --------------------------------------------------------------------------
def _style_axes(ch, y_title, x_title, size, log, ymin, ymax, fmt):
    va, ca = ch.value_axis, ch.category_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb(RULE)
    va.major_gridlines.format.line.width = Pt(0.5)
    va.format.line.fill.background()
    ca.has_major_gridlines = False
    ca.format.line.color.rgb = rgb(RULE)
    ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    for ax in (va, ca):
        ax.tick_labels.font.size = Pt(size)
        ax.tick_labels.font.color.rgb = rgb(MUTED)
    if fmt:
        va.tick_labels.number_format = fmt
        va.tick_labels.number_format_is_linked = False
    if ymin is not None:
        va.minimum_scale = ymin
    if ymax is not None:
        va.maximum_scale = ymax
    if log:
        sc = va._element.find(qn("c:scaling"))
        lb = etree.Element(qn("c:logBase"))
        lb.set("val", "10")
        sc.insert(0, lb)
    for ax, t in ((va, y_title), (ca, x_title)):
        if t:
            ax.has_title = True
            ax.axis_title.text_frame.text = t
            r = ax.axis_title.text_frame.paragraphs[0].runs[0]
            r.font.size, r.font.bold = Pt(size), False
            r.font.color.rgb = rgb(MUTED)


def _legend(ch, on, size):
    ch.has_legend = on
    if on:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(size)


def line_chart(slide, x, y, w, h, cats, series, y_title=None, x_title=None,
               log=False, ymin=None, ymax=None, size=12, legend=True, fmt=None):
    """series: [(name, values, hex colour, dashed?)]"""
    cd = CategoryChartData()
    cd.categories = cats
    for name, vals, _, _ in series:
        cd.add_series(name, vals)
    ch = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(x), Inches(y),
                                Inches(w), Inches(h), cd).chart
    ch.font.size, ch.font.name = Pt(size), BODY
    ch.has_title = False
    for s, (_, _, color, dash) in zip(ch.plots[0].series, series):
        s.smooth = False
        s.format.line.color.rgb = rgb(color)
        s.format.line.width = Pt(2.5)
        if dash:
            s.format.line.dash_style = MSO_LINE.DASH
            s.format.line.width = Pt(1.5)
            s.marker.style = XL_MARKER_STYLE.NONE
        else:
            s.marker.style = XL_MARKER_STYLE.CIRCLE
            s.marker.size = 8
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = rgb(color)
            s.marker.format.line.color.rgb = rgb(color)
    _legend(ch, legend, size)
    _style_axes(ch, y_title, x_title, size, log, ymin, ymax, fmt)
    return ch


def column_chart(slide, x, y, w, h, cats, series, y_title=None, size=12,
                 fmt="0", ymax=None, labels=True, legend=True):
    """series: [(name, values, hex colour)]"""
    cd = CategoryChartData()
    cd.categories = cats
    for name, vals, _ in series:
        cd.add_series(name, vals)
    ch = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x),
                                Inches(y), Inches(w), Inches(h), cd).chart
    ch.font.size, ch.font.name = Pt(size), BODY
    ch.has_title = False
    plot = ch.plots[0]
    plot.gap_width, plot.overlap = 70, -5
    for s, (_, _, color) in zip(plot.series, series):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = rgb(color)
    if labels:
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.number_format, dl.number_format_is_linked = fmt, False
        dl.position = XL_LABEL_POSITION.OUTSIDE_END
        dl.font.size = Pt(size - 1)
    _legend(ch, legend, size)
    _style_axes(ch, y_title, None, size, False, 0, ymax, None)
    return ch


def section(title, subtitle, label):
    s = new_slide(dark=True)
    text(s, 0.8, 2.3, 11.5, 0.4, label.upper(), size=14, color=PALE, bold=True)
    text(s, 0.8, 2.9, 11.7, 1.5, title, size=44, color=WHITE, bold=True, font=HEAD)
    text(s, 0.8, 4.6, 11.0, 1.2, subtitle, size=20, color=PALE)
    return s


# @@HELPERS_DONE@@
def build_intro():
    # 1 -- title
    s = new_slide(dark=True)
    text(s, 0.8, 1.45, 11, 0.4, "CIA-3 RESEARCH PROJECT", size=14, color=PALE,
         bold=True)
    text(s, 0.8, 2.0, 11.7, 1.7, "Noise-realized operator selection for ADAPT-VQE",
         size=44, color=WHITE, bold=True, font=HEAD, spacing=0.95)
    text(s, 0.8, 3.9, 11.0, 1.1,
         "From a 6-qubit null result to a 10-qubit GPU test: finite shots, "
         "noise structure, and what actually drives accuracy", size=20, color=PALE)
    text(s, 0.8, 5.5, 11, 0.4, "Aaryan Dharrmik  ·  5 BTCS B, B. Tech CSE",
         size=18, color=WHITE, bold=True)
    text(s, 0.8, 5.95, 11.5, 0.35,
         "Qiskit + PennyLane  ·  STO-3G active-space simulation  ·  "
         "CUDA density-matrix backend", size=14, color=PALE)
    text(s, 0.8, 6.35, 11, 0.35, "github.com/Aaryan658/noise-realized-adapt-vqe",
         size=14, color=PALE)

    # 2 -- agenda
    s = new_slide()
    header(s, "Overview", "What this talk covers")
    items = [
        ("Background", "the ansatz problem in noisy VQE; how ADAPT-VQE builds a circuit"),
        ("Research question", "is the energy gradient the right thing to select on under noise?"),
        ("Methodology", "molecules, a framework-matched noise model, four selection rules"),
        ("Implementation", "one shared ADAPT driver, self-tests, and a GPU backend"),
        ("Part 1: 6-qubit study", "baseline, cost penalty, realised energy, matched-length control"),
        ("Part 2: 10-qubit test", "circuit length, finite shots, noise structure"),
        ("Assessment", "limitations, what holds up, and what is still open"),
        ("Conclusions", "and how to reproduce every number"),
    ]
    for k, (a, b) in enumerate(items):
        col, row = divmod(k, 4)
        x, y = 0.6 + col * 6.15, 1.95 + row * 1.2
        badge(s, x, y + 0.05, 0.5, str(k + 1))
        text(s, x + 0.75, y, 5.2, 0.35, a, size=18, color=NAVY, bold=True)
        text(s, x + 0.75, y + 0.4, 5.2, 0.7, b, size=14, color=MUTED)

    # 3 -- background
    s = new_slide()
    header(s, "Background", "The variational eigensolver hinges on the ansatz")
    text(s, 0.6, 1.95, 7.3, 4.8, [
        "VQE minimises ⟨ψ(θ)|H|ψ(θ)⟩ over the parameters of a quantum circuit; the reachable accuracy is set by that circuit.",
        "A shallow ansatz (hardware-efficient, HEA) cannot represent the correlated wavefunction.",
        "A chemically complete ansatz (UCCSD) needs hundreds of two-qubit gates: the state decoheres before it is measured.",
        "ADAPT-VQE builds the circuit adaptively: add pool operators one at a time, largest energy gradient first, re-optimise after each.",
        "Result: compact, problem-specific circuits with far fewer parameters than fixed UCCSD."],
        size=17, bullet=True, after=10)
    for k, (h, b, fill) in enumerate([
            ("shallow", "low gate error, high representation error", LIGHT),
            ("deep", "low representation error, high gate error", LIGHT),
            ("adaptive", "grow only what the molecule needs", TEAL)]):
        y = 1.95 + k * 1.55
        card(s, 8.3, y, 4.4, 1.35, fill)
        text(s, 8.55, y + 0.17, 3.9, 0.4, h, size=18, bold=True,
             color=WHITE if fill == TEAL else TEAL)
        text(s, 8.55, y + 0.62, 3.9, 0.65, b, size=14,
             color=WHITE if fill == TEAL else INK)

    # 4 -- one iteration
    s = new_slide()
    header(s, "Background", "One ADAPT-VQE iteration")
    steps = [("Screen the pool", "compute |dE/dθ| for every candidate operator on the current state"),
             ("Select", "standard ADAPT keeps the single largest-gradient operator"),
             ("Append and re-optimise", "add the operator, re-optimise all θ (here: COBYLA, gradient-free)"),
             ("Test for convergence", "stop on gradient norm or, under noise, on an energy plateau")]
    for k, (h, b) in enumerate(steps):
        x = 0.6 + k * 3.08
        card(s, x, 2.0, 2.85, 3.3)
        badge(s, x + 0.25, 2.25, 0.55, str(k + 1))
        text(s, x + 0.25, 3.05, 2.4, 0.7, h, size=18, color=NAVY, bold=True)
        text(s, x + 0.25, 3.85, 2.4, 1.4, b, size=14, color=MUTED)
    text(s, 0.6, 5.85, 12.1, 0.5,
         "The selection quantity in step 2 is the lever this project examines.",
         size=20, color=TEAL, bold=True)

    # 5 -- research questions
    s = new_slide()
    header(s, "Research question", "Is the gradient the right thing to select on under noise?")
    text(s, 0.6, 1.95, 12.1, 1.4, [
        "The gradient is noise-blind: it does not know the operator's contribution will be corrupted by decoherence.",
        "Estimated on a noisy device it is also floored near the gate-error rate, so it barely ranks operators; with finite shots it is noisier still."],
        size=16, bullet=True, after=8)
    qs = [("Q1", "Realised vs predicted benefit", "score an operator by the energy it actually reaches after re-optimisation with the noise channel on"),
          ("Q2", "A circuit-cost penalty", "divide the score by (1 + λ · added CNOT count); untested in the ADAPT literature"),
          ("Q3", "A self-tuning penalty", "make λ a feedback controller that rises in the noise-dominated tail"),
          ("Q4", "Does it survive reality?", "finite shots and realistic noise structure (thermal, coherent, readout) on a 10-qubit active space")]
    for k, (q, h, b) in enumerate(qs):
        x = 0.6 + k * 3.08
        card(s, x, 3.65, 2.85, 3.05, TEAL if k == 3 else LIGHT)
        badge(s, x + 0.25, 3.9, 0.55, q, fill=WHITE if k == 3 else TEAL,
              color=TEAL if k == 3 else WHITE, size=15)
        text(s, x + 0.25, 4.65, 2.4, 0.7, h, size=17, bold=True,
             color=WHITE if k == 3 else NAVY)
        text(s, x + 0.25, 5.3, 2.4, 1.3, b, size=13,
             color=WHITE if k == 3 else MUTED)

    # 6 -- related work
    s = new_slide()
    header(s, "Related work", "Selection criteria beyond the gradient, and the open gap")
    rows = [["Method", "Selection quantity", "Under noise?"],
            ["Standard ADAPT (Grimsley 2019)", "energy gradient |dE/dθ|", "no"],
            ["QEB-ADAPT (Yordanov 2021)", "energy reduction of the top-n candidates", "no"],
            ["Overlap-ADAPT (Feniou 2023)", "overlap with a classical target state", "no"],
            ["Rotoselect (Ostaszewski 2021)", "closed-form noiseless energy landscape", "no"],
            ["Rossi et al. (2026)", "exact energy-based selection", "no"],
            ["GGA-VQE (Feniou 2025)", "gradient-free energy-curve fit", "shot noise; QPU run"],
            ["Haravu et al. (2026)", "study of gradient distortion, with mitigation", "yes"],
            ["This work: noise-realized", "realised energy under the noise channel, per CNOT", "yes"],
            ["This work: resource-aware", "|g| / (1 + λ · CNOT cost)", "yes"]]
    table(s, 0.6, 1.85, [3.9, 5.6, 2.6], rows, size=13, row_h=0.41,
          hl_rows=(8, 9), left_cols=(0, 1))
    text(s, 0.6, 6.15, 12.1, 0.7,
         "No prior ADAPT variant re-optimises each candidate with the device noise applied and selects on the energy it delivers there; a CNOT-cost penalty on the score is likewise unstudied.",
         size=14, color=MUTED)

    # 7 -- molecules
    s = new_slide()
    header(s, "Methodology 1/4", "Molecular systems and reference energies")
    text(s, 0.6, 1.95, 7.6, 4.9, [
        ("H₂ (d = 0.735 Å):", "full space, 4 spin-orbitals, 4 qubits."),
        ("LiH stretched to d = 3.0 Å,", "frozen core: (2e, 3o), 6 qubits in Part 1; (2e, 5o), 10 qubits, a 144-operator pool and 87.7 mHa of correlation in Part 2."),
        "Why stretched: at equilibrium the (2e,3o) space holds ~1 mHa of correlation, below chemical accuracy. Stretching restores 16.3 mHa and a multireference state.",
        "Integrals: PennyLane differentiable Hartree-Fock; the Qiskit Hamiltonian is built from the same integrals.",
        "Error is measured against the active-space FCI, not full-space FCI."],
        size=17, bullet=True, after=11)
    card(s, 8.6, 1.95, 4.1, 3.0)
    text(s, 8.85, 2.15, 3.6, 0.4, "Validation (noiseless)", size=16, bold=True, color=NAVY)
    text(s, 8.85, 2.75, 3.6, 3.5, [
        ("0.036 / 0.041 mHa", "dhf vs literature FCI (H₂ / LiH)"),
        ("≤ 5×10⁻¹⁴ Ha", "Qiskit vs PennyLane spectrum"),
        ("HF ≥ FCI", "holds in every case")], size=14, after=14)

    # 8 -- noise footing
    s = new_slide()
    header(s, "Methodology 2/4", "Noise on an equivalent footing for both frameworks")
    text(s, 0.6, 1.95, 8.0, 4.9, [
        "Feeding a raw FakeBackend model to Qiskit while PennyLane runs default.mixed is not comparable: different native gates, routing SWAPs, and readout error that does not transfer.",
        "Instead: framework-independent depolarizing channels with rates read from FakeManilaV2 calibration: p₁ = 3.54×10⁻⁴, p₂ = 1.01×10⁻².",
        "The PennyLane channels are the exact 16-Kraus form of Qiskit-Aer's convention, not an approximation.",
        "Noise is applied after decomposition to {RX, RY, RZ, H, CNOT}; a runtime guard rejects a silent no-op.",
        ("Part 2 adds", "thermal, coherent and readout channels scaled to the same gate infidelity, so only the noise structure changes.")],
        size=16, bullet=True, after=10)
    card(s, 9.0, 1.95, 3.7, 3.3, TEAL)
    text(s, 9.3, 2.25, 3.1, 0.9, "6.7×10⁻¹⁶", size=40, color=WHITE,
         bold=True, font=HEAD)
    text(s, 9.3, 3.25, 3.1, 2.2,
         "probe-observable agreement between the two stacks across noise scales 0×, 1×, 4×, 20× (spread 0.42, so the test is not vacuous)",
         size=14, color=WHITE)

    # 9 -- rules
    s = new_slide()
    header(s, "Methodology 3/4", "Four selection rules, one shared ADAPT driver")
    rows = [["Rule", "Score for a candidate operator", "Role"],
            ["standard", "|g|  (gradient magnitude)", "textbook baseline"],
            ["noise-realized", "max(0, ΔE_realised) / (1 + λ · CNOT cost)", "proposed: measured benefit"],
            ["resource-aware", "|g| / (1 + λ · CNOT cost)", "proposed: cost penalty"],
            ["noise-realized + adaptive λ", "as above; λ is a clamped multiplicative controller", "proposed: self-tuning"]]
    table(s, 0.6, 1.95, [3.3, 5.9, 2.9], rows, size=14, row_h=0.5,
          left_cols=(0, 1, 2))
    text(s, 0.6, 4.8, 12.1, 1.9, [
        "noise-realized: gradient-screen to the top 4 (or 8), append each, re-optimise with the noise channel on, keep the best realised ΔE per CNOT; the winner's parameters are carried forward.",
        "λ = 0 reproduces standard ADAPT exactly (checked). Cost of noise-realized: about 2 to 2.5× gradient selection."],
        size=17, bullet=True, after=10)

    # 10 -- gradients, optimiser, stopping
    s = new_slide()
    header(s, "Methodology 4/4", "Gradients, optimiser, stopping, and the matched-count control")
    text(s, 0.6, 1.95, 12.1, 4.9, [
        ("Selection gradient:", "central difference on the trailing parameter at θ = 0, checked against exact parameter-shift to ~10⁻⁸ with noise present. backprop on default.mixed silently returns NaN in this stack, so it is not used. With finite shots the exact two-term shift rule is used instead."),
        ("Re-optimisation:", "COBYLA, gradient-free, the same optimiser as the Qiskit baselines."),
        ("Stopping:", "two rules for every selection rule: gradient norm < 10⁻³, and an energy-plateau rollback (ΔE < 10⁻⁵ Ha, patience 2). The plateau rule is what actually fires under noise."),
        ("fixed_k mode:", "disables both stops, forces exactly k operators, and accepts every top-scored pick. It isolates operator choice from circuit length.")],
        size=18, bullet=True, after=15)

    # 11 -- implementation
    s = new_slide()
    header(s, "Implementation", "Pipeline and safeguards")
    text(s, 0.6, 1.95, 7.5, 4.9, [
        "Strict dependency order: molecules → noise_models → {qiskit_baselines, pennylane_resource_aware_adapt} → run_experiments → analyze_results.",
        "One _adapt_loop holds all four selection rules and fixed_k; the novel rules do not touch the standard / λ = 0 paths.",
        "Every module is its own self-test: pool-cost spread, noise actually applied, gradient-method agreement, noiseless convergence to FCI, λ = 1 divergence, λ = 0 ≡ standard.",
        "Result CSVs are written row by row, so an interrupted multi-hour run leaves usable data and resumes where it stopped."],
        size=17, bullet=True, after=12)
    card(s, 8.5, 1.95, 4.2, 3.0)
    text(s, 8.75, 2.15, 3.7, 0.4, "Vacuous-selection diagnostic", size=16, bold=True, color=NAVY)
    text(s, 8.75, 2.75, 3.7, 3.3,
         "Before any sweep it checks that the cost penalty can in principle change a pick, and shows analytically that on the 6-qubit molecules it cannot (Result 2).",
         size=14, color=INK)

    # 12 -- GPU backend
    s = new_slide(notes="gpu_backend.py: CUDA density-matrix simulator validated against "
                        "default.mixed (selftest) and, for the extra channels, against "
                        "PennyLane's AmplitudeDamping, PhaseDamping, IsingZZ and unitary gates.")
    header(s, "Implementation", "A GPU density-matrix backend made the 10-qubit test feasible")
    text(s, 0.6, 1.95, 7.6, 4.9, [
        "CUDA density-matrix simulator on an RTX 4060 (8 GB); same PennyLane gate decomposition and Qiskit-convention depolarizing channels as the CPU path.",
        "Reproduces the noisy X gates that prepare the Hartree-Fock state, a detail the first version missed.",
        "Opt-in (ADAPT_BACKEND=gpu): the CPU path and every 6-qubit result are unchanged.",
        "Adds what the CPU path could not afford: finite-shot sampling (binomial per Pauli term, exact shift-rule gradients) and stackable thermal, coherent and readout channels.",
        "The result: 120 ten-qubit runs where the CPU estimate was GPU-days."],
        size=16, bullet=True, after=10)
    stat(s, 8.8, 1.95, 3.9, "≈4000×", "faster per 10-qubit energy than default.mixed (0.02 to 0.04 s vs 50 to 140 s)")
    stat(s, 8.8, 3.6, 3.9, "10⁻¹⁴", "agreement with default.mixed at 6 and 10 qubits")
    stat(s, 8.8, 5.25, 3.9, "≤ 10⁻¹¹", "agreement with PennyLane's thermal, coherent and readout channels")


def build_part1():
    section("Part 1: the 6-qubit study",
            "2 molecules  ·  4 noise scales  ·  7 strategies  ·  56 free-running runs plus a matched-length control",
            "Results")

    # 14 -- result 1 figure
    s = new_slide()
    header(s, "Result 1: the robust finding", "Adaptive qubit-ADAPT beats every fixed or routed baseline")
    h = picture(s, os.path.join(NOVEL, "energy_error_vs_noise.png"), 1.3, 1.85, 10.7, 3.9)
    text(s, 0.6, 1.85 + h + 0.1, 12.1, 0.4,
         "Energy error vs noise (log scale). Solid = PennyLane qubit-ADAPT rules; dashed = UCCSD, HEA and routed Qiskit ADAPT.",
         size=12, color=MUTED)
    text(s, 0.6, 6.2, 12.1, 0.6,
         "10 to 20× more accurate than UCCSD / HEA at every noise level, at a fraction of the two-qubit-gate count: depolarizing error tracks CNOT count, not depth.",
         size=15, color=NAVY, bold=True)

    # 15 -- routing
    s = new_slide()
    header(s, "Result 1: why the routed baseline collapses", "Routing overhead, not the algorithm, breaks Qiskit ADAPT")
    h = picture(s, os.path.join(NOVEL, "circuit_depth.png"), 1.9, 1.8, 9.5, 3.2)
    text(s, 0.6, 1.8 + h + 0.1, 12.1, 0.4,
         "Transpiled depth (left) and CNOT count (right). Qubit-ADAPT rules: 10 CNOTs, depth 16 on LiH. UCCSD and Qiskit ADAPT: 272 to 390 CNOTs.",
         size=12, color=MUTED)
    table(s, 1.5, 5.6, [3.6, 2.4, 2.4, 2.9], [
        ["LiH, 0.25× noise", "qubit-ADAPT", "UCCSD", "Qiskit ADAPT (routed)"],
        ["energy error / mHa", "5.7", "124.7", "171.3"],
        ["CNOT count", "10", "272", "388"]], size=14, row_h=0.4)

    # 16 -- result 2
    s = new_slide()
    header(s, "Result 2: the cost penalty", "Resource-aware selection is inert, with an analytic cause")
    text(s, 0.6, 1.95, 7.2, 4.9, [
        "At λ = 1 it gives a byte-identical ansatz to standard ADAPT at every non-zero noise level, for both molecules; λ = 0 reproduces standard exactly.",
        "The rules do diverge for noiseless LiH from operator 6, but under noise the plateau stop truncates the ansatz at 1 to 2 operators, before that point.",
        ("On 10 qubits it does act:", "the pool has a real cost spread (4 to 18 CNOTs per operator) and the rule changes the circuit (Part 2).")],
        size=16, bullet=True, after=12)
    card(s, 8.2, 1.95, 4.5, 3.7)
    text(s, 8.45, 2.15, 4.0, 0.4, "Why it cannot act on 6 qubits", size=16, bold=True, color=NAVY)
    text(s, 8.45, 2.7, 4.0, 3.8,
         "Single excitations have zero gradient at Hartree-Fock, so the first operator is a double. The gradient-carrying doubles (8 of 12 for H₂, 8 of 40 for LiH) all have weight 4 and cost 6 CNOTs. With a constant denominator, |g| / (1 + λc) is a monotone rescaling of |g|: the arg-max never moves, for any λ.",
         size=14, color=INK)

    # 17 -- result 3
    s = new_slide()
    header(s, "Result 3: the realised-energy score", "Noise-realized: a small gain in the free-running sweep")
    table(s, 0.6, 1.95, [2.3, 1.3, 1.6, 1.5, 1.6], [
        ["Energy error / mHa", "standard", "noise-realized", "resource-aware", "NR + adaptive λ"],
        ["H₂ 0.25×", "15.262", "13.831", "15.262", "13.831"],
        ["LiH 0.25×", "5.695", "5.237", "5.695", "5.237"],
        ["LiH 0.50×", "10.191", "9.294", "10.191", "9.294"],
        ["LiH 0.00 (CNOTs)", "36", "26", "34", "26"]], size=13, row_h=0.55,
        bold_cells={(1, 2), (2, 2), (3, 2), (4, 2)})
    text(s, 9.4, 1.95, 3.3, 4.2, [
        "0.5 to 1.4 mHa more accurate than standard at 0.25× / 0.50×, at the same operator and CNOT count: a different Pauli string of the same excitation survives decoherence better.",
        "Noiselessly it reaches chemical accuracy with 26 CNOTs vs 36."],
        size=14, bullet=True, after=10)
    text(s, 0.6, 5.3, 8.5, 0.9,
         "But does the different choice cause the gain, or does the stopping rule? That is Result 4.",
         size=18, color=TEAL, bold=True)

    # 18 -- result 4
    s = new_slide()
    header(s, "Result 4: the honest control", "Matched operator count: the gain does not survive")
    text(s, 0.6, 1.8, 12.1, 0.4,
         "All four rules forced to k = 6 operators on LiH(2e,3o); both stopping rules disabled. Energy error in mHa vs active-space FCI.",
         size=15, color=MUTED)
    table(s, 0.6, 2.35, [1.9, 1.5, 1.9, 2.3, 1.9], [
        ["noise scale", "standard", "noise-realized", "Δ (NR − standard)", "CNOT std / NR"],
        ["0.00", "0.022", "0.033", "+0.011", "30 / 32"],
        ["0.05×", "3.946", "3.980", "+0.034", "32 / 32"],
        ["0.10×", "7.788", "7.554", "−0.235", "32 / 32"],
        ["0.20×", "15.302", "16.190", "+0.888", "32 / 34"]], size=14, row_h=0.5)
    text(s, 0.6, 5.1, 12.1, 1.7, [
        "The rules do pick different operators (the guardrail did not trip), but Δ is inconsistent in sign and ≤ 0.9 mHa.",
        "The free-running advantage was mainly a circuit-length effect of the stopping rule, not a better operator choice. On LiH(2e,3o) any selection-quality advantage is below what the system can resolve."],
        size=15, bullet=True, after=8)

    # 19 -- result 5
    s = new_slide()
    header(s, "Result 5: the self-tuning penalty", "The λ controller tracks the regime but never acts")
    table(s, 0.6, 1.95, [2.0, 1.4, 1.4, 1.4, 1.4, 3.2], [
        ["LiH noise", "0.00", "0.25×", "0.50×", "1.00×", "matched-k 0.05× / 0.20×"],
        ["λ_final", "0.91", "0.37", "0.49", "2.53", "8.0 (ceiling)"]], size=14, row_h=0.5)
    text(s, 0.6, 3.5, 12.1, 3.3, [
        "Adaptive λ reproduces fixed-λ noise-realized in every cell: identical operators and energies.",
        "λ climbs when operators stop paying and relaxes while they deliver: the controller itself works.",
        "It never changes a selection: the minimal-basis pool has no cheaper, gradient-competitive operator to switch to.",
        ("On 10 qubits the result repeats:", "adaptive λ matched fixed λ exactly in all 24 free-running cells, even with a cost-varied pool.")],
        size=18, bullet=True, after=15)


# @@SLIDES1_DONE@@
def build_part2():
    free, k4, k6 = c.free_running(), c.fixed_k(4), c.fixed_k(6)
    sh, ch = c.shots(), c.channels()
    rules = ("standard", "resource_aware", "NR_c4", "NR_c8")
    scale_cats = ["0", "0.05×", "0.1×", "0.2×"]

    section("Part 2: the 10-qubit fair test",
            "LiH(2e,5o)  ·  GPU density-matrix backend  ·  24 free-running, 32 matched-length, "
            "40 finite-shot and 24 richer-noise runs", "Results")

    # 21 -- free-running
    s = new_slide(notes="Source: results/results_10q.csv. Free-running, both stopping rules on, "
                        "up to 16 operators, exact expectations, depolarizing noise.")
    header(s, "Result 6: 10-qubit free-running",
           "At 0.05× device noise, no rule gets below 13 mHa")

    def cell(r, sc):
        e, cn, _ = free[(r, sc)]
        return f"{e:.3f} ({cn})" if sc == 0 else f"{e:.2f} ({cn})"
    rows = [["noise", "standard", "resource-aware", "NR (4)", "NR (8)"]]
    for sc in c.SCALES:
        rows.append([scale_cats[c.SCALES.index(sc)]] + [cell(r, sc) for r in rules])
    table(s, 0.6, 1.95, [1.0, 1.45, 1.6, 1.4, 1.4], rows, size=12, row_h=0.5)
    text(s, 0.6, 4.65, 6.85, 1.4, [
        "Error in mHa vs FCI, with the CNOT count in brackets. Up to 16 operators; both stopping rules on.",
        "Noiseless: every rule reaches chemical accuracy (1.6 mHa). Adaptive λ matched fixed λ in all 24 cells."],
        size=13, color=MUTED, bullet=True, after=6)
    line_chart(s, 7.7, 1.85, 5.0, 4.2, scale_cats,
               [(c.RULE_LABEL[r], [free[(r, sc)][0] for sc in c.SCALES],
                 RULE_CLR[r], False) for r in rules],
               y_title="energy error (mHa)", log=True, ymin=0.01, ymax=100,
               size=11, fmt="General")
    text(s, 0.6, 6.3, 12.1, 0.6,
         "Circuit length, not operator choice, is the bottleneck: noise stops every ansatz at 5 to 7 operators.",
         size=16, color=NAVY, bold=True)

    # 22 -- matched length
    s = new_slide(notes="Sources: results/results_10q_fixedk4.csv and results_10q_fixedk6.csv. "
                        "Both stopping rules disabled; every rule builds exactly K operators.")
    header(s, "Result 7: matched operator count",
           "Held to equal length, the free-running lead mostly disappears")
    for k, d, x in ((4, k4, 0.6), (6, k6, 6.75)):
        text(s, x, 1.8, 5.9, 0.3, f"K = {k} operators", size=14, color=NAVY, bold=True)
        line_chart(s, x, 2.1, 5.95, 3.25, scale_cats,
                   [(c.RULE_LABEL[r], [d[(r, sc)][0] for sc in c.SCALES],
                     RULE_CLR[r], False) for r in rules],
                   y_title="energy error (mHa)", ymin=0, ymax=60, size=11, fmt="0")
    lead_free = free[("standard", 0.2)][0] - free[("NR_c8", 0.2)][0]
    lead_k4 = k4[("standard", 0.2)][0] - k4[("NR_c8", 0.2)][0]
    nr8_gain = k6[("standard", 0.1)][0] - k6[("NR_c8", 0.1)][0]
    ra_lo = k6[("standard", 0.1)][0] - k6[("resource_aware", 0.1)][0]
    ra_hi = k6[("standard", 0.2)][0] - k6[("resource_aware", 0.2)][0]
    text(s, 0.6, 5.5, 12.1, 1.5, [
        ("At 0.2×,", f"noise-realized's free-running lead over standard ({lead_free:.1f} mHa) shrinks to {lead_k4:.1f} mHa at a matched K = 4: the plateau rule had stopped standard at 2 operators."),
        ("At K = 6, 0.1× to 0.2×,", f"cost-aware selection wins by {ra_lo:.0f} to {ra_hi:.0f} mHa by choosing cheaper circuits (54 vs 64 CNOTs); at K = 4 it is worse."),
        ("Noise-realized", f"is marginal and not reliably signed (8 candidates: {nr8_gain:.1f} mHa better at 0.1×, tied at 0.2×).")],
        size=14, bullet=True, after=6)

    # 23 -- finite shots
    s = new_slide(notes="Source: results/results_10q_shots.csv. K = 4, 0.1x, 5 seeds. Ungrouped "
                        "per-term shots; exact shift-rule gradients; final circuits scored by "
                        "their exact noisy energy. Dashed lines: exact-expectation results.")
    header(s, "Result 8: finite-shot selection",
           "Gradient selection is fragile when shots are scarce")
    xs = sorted({sv for (_, sv) in sh})
    cats = ["10⁴", "10⁵", "10⁶", "10⁷"]
    m_std = [c.mean_sem(sh[("standard", v)])[0] for v in xs]
    m_nr = [c.mean_sem(sh[("NR_c4", v)])[0] for v in xs]
    ex_std, ex_nr = k4[("standard", 0.1)][0], k4[("NR_c4", 0.1)][0]
    line_chart(s, 0.6, 1.85, 7.7, 4.6, cats,
               [("standard (gradient)", m_std, SLATE, False),
                ("noise-realized (4 cand.)", m_nr, TEAL, False),
                ("standard, exact", [ex_std] * 4, SLATE, True),
                ("noise-realized, exact", [ex_nr] * 4, TEAL, True)],
               y_title="energy error (mHa)", x_title="shots per Pauli term",
               ymin=20, ymax=65, size=12, fmt="0")
    text(s, 0.6, 6.55, 7.7, 0.4,
         "Mean over 5 seeds; K = 4, 0.1×. Per-term shots are ungrouped, so absolute counts are pessimistic.",
         size=11, color=MUTED)
    wins = sum(1 for a, b in zip(sh[("standard", xs[0])], sh[("NR_c4", xs[0])]) if b < a)
    stat(s, 8.8, 1.75, 3.9, f"{m_std[0] / ex_std:.1f}×",
         f"worse than its exact result at 10⁴ shots per term ({m_std[0]:.1f} vs {ex_std:.1f} mHa)", big_size=34)
    stat(s, 8.8, 3.0, 3.9, f"{wins} / 5",
         f"seeds won by noise-realized at 10⁴ shots ({m_nr[0]:.1f} vs {m_std[0]:.1f} mHa)", big_size=34)
    stat(s, 8.8, 4.25, 3.9, "≈8×",
         "fewer shots for the same accuracy: noise-realized at 10⁴ matches standard at 10⁵", big_size=34)
    stat(s, 8.8, 5.5, 3.9, "~10⁶",
         "shots per term before gradient selection nears its exact accuracy", big_size=34)

    # 24 -- richer noise
    s = new_slide(notes="Source: results/results_10q_channels.csv and the depolarizing K = 4 run. "
                        "Thermal and coherent are scaled to the depolarizing model's average gate "
                        "infidelity; readout is 2.19% x scale. Exact expectations, K = 4.")
    header(s, "Result 9: noise structure",
           "At equal gate infidelity, coherent errors hurt most and selection matters")
    models = [("depolarizing", "depolarizing"), ("thermal", "thermal"),
              ("coherent", "coherent"), ("depol+readout", "depol. + readout"),
              ("all", "all combined")]

    def val(m, sc, r):
        return (k4[(r, sc)][0] if m == "depolarizing" else ch[(m, sc, r)][0])
    for sc, x in ((0.05, 0.6), (0.2, 6.75)):
        text(s, x, 1.8, 5.9, 0.3, f"noise scale {sc:g}×", size=14, color=NAVY, bold=True)
        column_chart(s, x, 2.1, 5.95, 3.3, [lab for _, lab in models],
                     [("standard", [val(m, sc, "standard") for m, _ in models], SLATE),
                      ("noise-realized", [val(m, sc, "NR_c4") for m, _ in models], TEAL)],
                     y_title="energy error (mHa)", size=11, fmt="0", ymax=135)
    d05 = ch[("coherent", 0.05, "standard")][0] - ch[("coherent", 0.05, "NR_c4")][0]
    d10 = ch[("coherent", 0.1, "standard")][0] - ch[("coherent", 0.1, "NR_c4")][0]
    d20 = ch[("coherent", 0.2, "standard")][0] - ch[("coherent", 0.2, "NR_c4")][0]
    text(s, 0.6, 5.55, 12.1, 1.4, [
        ("Coherent over-rotation doubles the error", f"(standard {ch[('coherent', 0.2, 'standard')][0]:.0f} vs {k4[('standard', 0.2)][0]:.0f} mHa at 0.2×) and is the one setting where selection matters: noise-realized is {d05:.1f} and {d20:.1f} mHa ahead at 0.05× and 0.2×, but only {d10:.1f} at 0.1×."),
        ("Thermal noise is milder", "than depolarizing (2 to 7 mHa lower); readout error adds 4 to 14 mHa to both rules equally.")],
        size=14, bullet=True, after=6)

    # 25 -- what holds up
    s = new_slide()
    header(s, "Synthesis", "What holds up, and what does not")
    cards = [("Established", TEAL,
              "Compact qubit-ADAPT is 10 to 20× more accurate than UCCSD, HEA and routed Qiskit ADAPT under noise. At exact expectations, circuit length dominates operator choice."),
             ("Conditional", AMBER,
              "Gradient selection needs ~10⁶ shots per Pauli term. Below that, and under coherent noise, realised-energy selection is clearly better."),
             ("Context-dependent", NAVY,
              "Cost-aware selection pays off only when the ansatz would otherwise grow past the noise-optimal length (K = 6); at K = 4 it is worse."),
             ("Not established", SLATE,
              "A noise-realized advantage under depolarizing noise at adequate shots (≤ 1 mHa, single runs). The self-tuning λ, which never changed a selection.")]
    for k, (h, col, b) in enumerate(cards):
        x, y = 0.6 + (k % 2) * 6.15, 1.95 + (k // 2) * 2.5
        card(s, x, y, 5.95, 2.3)
        text(s, x + 0.3, y + 0.22, 5.4, 0.4, h, size=19, color=col, bold=True)
        text(s, x + 0.3, y + 0.75, 5.4, 1.5, b, size=15, color=INK)


def build_close():
    # 26 -- limitations
    s = new_slide()
    header(s, "Assessment", "Limitations")
    text(s, 0.6, 1.95, 12.1, 4.9, [
        "The proposed rules are not shown to work in general: under depolarizing noise at adequate shots the best case is a sub-1 mHa edge from single deterministic runs.",
        "One molecule (LiH, one stretched geometry) and one basis. The finite-shot study has 5 seeds, so a 5/5 record only bounds the win rate at ≥ 0.57 (Wilson 95%).",
        "The shot model is ungrouped (every Pauli term measured independently), so absolute shot counts are pessimistic; commuting-group measurement could change the cost ratio between rules.",
        "Noise models are idealised: a fixed-sign coherent over-rotation (a worst case), no idle-qubit decay, symmetric readout, and no error mitigation.",
        "At ≥ 1× the device error rate no method recovers correlation energy."],
        size=18, bullet=True, after=16)

    # 27 -- next steps
    s = new_slide()
    header(s, "Assessment", "What a stronger test needs next")
    nxt = [("Mitigation on the selection step", "dynamical decoupling and ZNE (Haravu 2026) and readout mitigation: do mitigated gradients restore gradient selection under coherent noise?"),
           ("A grouped-measurement shot model", "commuting-group measurement and shot reuse, for realistic absolute shot costs."),
           ("More instances and seeds", "bond-length sweep, other molecules, at least 5 repeats with paired tests and Wilson intervals."),
           ("TETRIS layering under non-depolarizing noise", "where depth reduction is known to help."),
           ("Emulator, then hardware", "a FakeBackend with routing and readout, then a small real-device run.")]
    for k, (h, b) in enumerate(nxt):
        y = 1.95 + k * 0.97
        badge(s, 0.6, y + 0.05, 0.5, str(k + 1))
        text(s, 1.35, y, 11.3, 0.4, h, size=18, color=NAVY, bold=True)
        text(s, 1.35, y + 0.4, 11.3, 0.5, b, size=14, color=MUTED)

    # 28 -- conclusions
    s = new_slide()
    header(s, "Conclusions", "What this project established")
    concl = [("The comparative result is robust",
              "Compact all-to-all qubit-ADAPT is 10 to 20× more accurate than UCCSD, HEA and routed Qiskit ADAPT under noise: depolarizing error tracks CNOT count."),
             ("Circuit length beats selection rule",
              "On 10 qubits at exact expectations, matched-length gaps are ≤ 1 mHa under depolarizing noise; cost-aware rules help only past the noise-optimal length."),
             ("Gradient selection is fragile on few shots",
              "At 10⁴ shots per term it is 2.5× worse than its exact result while noise-realized holds at 33.6 vs 60.7 mHa; both converge by 10⁶ to 10⁷."),
             ("Noise structure changes the ranking",
              "Coherent errors double the error and are where realised-energy selection clearly wins (8.5 to 11.2 mHa); the self-tuning λ never acted.")]
    for k, (h, b) in enumerate(concl):
        x, y = 0.6 + (k % 2) * 6.15, 1.95 + (k // 2) * 2.5
        card(s, x, y, 5.95, 2.3)
        badge(s, x + 0.3, y + 0.25, 0.5, str(k + 1))
        text(s, x + 1.0, y + 0.27, 4.7, 0.5, h, size=17, color=NAVY, bold=True)
        text(s, x + 0.3, y + 0.95, 5.4, 1.3, b, size=14, color=INK)

    # 29 -- reproducibility
    s = new_slide()
    header(s, "Reproducibility", "Everything is in the repository")
    text(s, 0.6, 1.95, 6.3, 4.9, [
        "github.com/Aaryan658/noise-realized-adapt-vqe: MIT licence, CITATION.cff.",
        "make validate / selftest / baseline / selection / fixed-k / figures for Part 1.",
        "Every number on these slides is a cell in results/*.csv (results.csv, results_novel.csv, results_fixed_k.csv, results_10q*.csv).",
        "Environment: CPython 3.14, qiskit 2.3, qiskit-aer 0.17, pennylane 0.45, numpy 2.5, scipy 1.16, torch 2.11 (CUDA 12.8).",
        "Write-ups: docs/REPORT.md, MANUSCRIPT.md, NOVEL_RESULTS.md."],
        size=16, bullet=True, after=12)
    card(s, 7.2, 1.95, 5.5, 3.9, NAVY)
    text(s, 7.45, 2.15, 5.0, 0.4, "Part 2 commands", size=15, color=PALE, bold=True)
    text(s, 7.45, 2.7, 5.1, 3.8, [
        "python gpu_backend.py",
        "python fair_test_10q.py",
        "python fair_test_10q.py --fixed-k 4",
        "python shots_experiment.py",
        "python channels_experiment.py",
        "python docs/build/make_figures.py"],
        size=13, color=WHITE, font="Consolas", after=11)

    # 30 -- references
    s = new_slide()
    header(s, "References", "Key references")
    left = ["[5] Grimsley et al. An adaptive variational algorithm for exact molecular simulations. Nat. Commun. 10, 3007 (2019).",
            "[6] Tang et al. Qubit-ADAPT-VQE. PRX Quantum 2, 020310 (2021).",
            "[7] Yordanov et al. Qubit-excitation-based adaptive VQE. Commun. Phys. 4, 228 (2021).",
            "[10] Long et al. Layering and subpool exploration for adaptive VQE. Phys. Rev. A 109, 042413 (2024).",
            "[13] Feniou et al. Overlap-ADAPT-VQE. Commun. Phys. 6, 192 (2023).",
            "[14] Ostaszewski et al. Structure optimization for parameterized quantum circuits (Rotoselect). Quantum 5, 391 (2021).",
            "[15] Rossi et al. Resource-efficient energy-based operator selection. arXiv:2606.04786 (2026)."]
    right = ["[19] Wang et al. Noise-induced barren plateaus in variational quantum algorithms. Nat. Commun. 12, 6961 (2021).",
             "[20] Dalton et al. Quantifying the effect of gate errors on variational quantum eigensolvers for quantum chemistry. npj Quantum Inf. 10 (2024), doi:10.1038/s41534-024-00808-x.",
             "[21] Bergholm et al. PennyLane. arXiv:1811.04968.   [22] Qiskit contributors (2024).",
             "[A] Haravu, Ramoa, Sambasivam. A case study on noise resilient operator selection in adaptive variational quantum algorithms. arXiv:2609.17501 (2026).",
             "[B] Feniou et al. Greedy gradient-free adaptive variational quantum algorithms on a noisy intermediate-scale quantum computer (GGA-VQE). 2025.",
             "[C] Strategies for overcoming gradient troughs in the ADAPT-VQE algorithm. arXiv:2512.25004.",
             "[D] Grimsley et al. Adaptive, problem-tailored VQE mitigates rough parameter landscapes and barren plateaus. npj Quantum Inf. (2023), doi:10.1038/s41534-023-00681-0."]
    text(s, 0.6, 1.9, 5.9, 4.9, left, size=12, color=INK, after=8)
    text(s, 6.85, 1.9, 5.9, 4.9, right, size=12, color=INK, after=8)
    text(s, 0.6, 6.55, 12, 0.35, "Full 22-entry list in docs/REPORT.md, section VI.",
         size=11, color=MUTED)
def main():
    build_intro()
    build_part1()
    build_part2()
    build_close()
    prs.core_properties.title = "Noise-realized operator selection for ADAPT-VQE (updated deck)"
    prs.core_properties.author = "Aaryan Dharrmik"
    prs.save(OUT)
    print("wrote", OUT, f"({_state['n']} slides)")


if __name__ == "__main__":
    main()
