"""
build_report_ieee_docx.py -- two-column IEEE layout of docs/REPORT.md ->
docs/REPORT_IEEE_UPDATED.docx. Mirrors docs/MANUSCRIPT_IEEE_v2.docx: US Letter,
one-column title block, two text columns (0.2 in gap), and wide tables / figures in
continuous one-column sections that span the page.

    .venv\\Scripts\\python.exe docs\\build\\make_figures.py
    .venv\\Scripts\\python.exe docs\\build\\build_report_ieee_docx.py
"""

from __future__ import annotations

import math
import os
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt
from markdown_it import MarkdownIt

sys.path.insert(0, os.path.dirname(__file__))
import build_report_docx as b                         # noqa: E402  (shared helpers)
import common as c                                    # noqa: E402

OUT = os.path.join(c.ROOT, "docs", "REPORT_IEEE_UPDATED.docx")
COL_IN, FULL_IN = 3.4, 7.0           # figure widths: one column / page width
COL_CM, FULL_CM = 8.8, 18.2          # table widths
CENTER, JUSTIFY, LEFT = (WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.JUSTIFY,
                         WD_ALIGN_PARAGRAPH.LEFT)


# --------------------------------------------------------------------------
# column layout: continuous sections switching between 1 and 2 columns
# --------------------------------------------------------------------------
def set_cols(section, n, space=288):
    sp = section._sectPr
    cols = sp.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sp.find(qn("w:pgMar")).addnext(cols)
    cols.set(qn("w:num"), str(n))
    cols.set(qn("w:space"), str(space))


class Layout:
    """Lazy column switching, so consecutive wide items share one 1-col section."""

    def __init__(self, doc):
        self.doc, self.n = doc, 1
        set_cols(doc.sections[0], 1)

    def to(self, n):
        if n == self.n:
            return
        sec = self.doc.add_section(WD_SECTION.CONTINUOUS)
        set_cols(sec, n)
        self.n = n
        brk = self.doc.paragraphs[-1]            # the paragraph holding the break
        brk.paragraph_format.space_after = Pt(0)
        brk.paragraph_format.line_spacing = Pt(4)


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------
def caption(doc, content, size=8):
    p = doc.add_paragraph()
    b.style_paragraph(p, before=4, after=2, line=1.0, align=CENTER, keep_next=True)
    if isinstance(content, str):
        b.set_font(p.add_run(content), size=size, bold=True)
    else:
        b.render_inline(p, content, size=size, bold=True)


def emit_table(doc, L, header, rows, cap=None, wide=True, widths=None, size=7.5):
    L.to(1 if wide else 2)
    if cap is not None:
        caption(doc, cap)
    n = len(header)
    widths = widths or ([0.8] + [1.0] * (n - 1) if n >= 7 else [1.0] * n)
    total = FULL_CM if wide else COL_CM
    ws = [total * w / sum(widths) for w in widths]
    t = doc.add_table(rows=1 + len(rows), cols=n)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    b.table_borders(t)
    b.cell_margins(t, top=25, bottom=25, left=50, right=50)
    for r_i, row in enumerate([header] + rows):
        tr = t.rows[r_i]
        b.no_split(tr)
        if r_i == 0:
            b.repeat_header(tr)
        for col, val in enumerate(row):
            cell = tr.cells[col]
            cell.width = Cm(ws[col])
            p = cell.paragraphs[0]
            b.style_paragraph(p, after=0, line=1.0,
                              align=LEFT if col == 0 else CENTER)
            if isinstance(val, list):
                b.render_inline(p, val, size=size, bold=(r_i == 0))
            else:
                b.set_font(p.add_run(str(val)), size=size, bold=(r_i == 0))
            if r_i < len(rows):
                p.paragraph_format.keep_with_next = True
            if r_i == 0:
                b.shade(cell, "DDE5EE")
    gap = doc.add_paragraph()
    b.style_paragraph(gap, after=0, line=1.0)
    gap.paragraph_format.line_spacing = Pt(5)


def figure(doc, L, path, cap, wide):
    L.to(1 if wide else 2)
    p = doc.add_paragraph()
    b.style_paragraph(p, before=3, after=1, line=1.0, align=CENTER, keep_next=True)
    p.add_run().add_picture(path, width=Inches(FULL_IN if wide else COL_IN))
    cp = doc.add_paragraph()
    b.style_paragraph(cp, after=5, line=1.0, align=CENTER)
    b.set_font(cp.add_run(cap), size=8)


def body_par(doc, L, inl, size=10, indent=True):
    L.to(2)
    has_code = any(x.type == "code_inline" for x in inl)
    p = doc.add_paragraph()
    b.style_paragraph(p, after=3, line=1.0, align=LEFT if has_code else JUSTIFY)
    if indent:
        p.paragraph_format.first_line_indent = Inches(0.17)
    b.render_inline(p, inl, size=size)
    return p


# --------------------------------------------------------------------------
# generated 10-qubit tables and figures (section V-F)
# --------------------------------------------------------------------------
def vf_content(doc, L):
    L.to(2)
    p = doc.add_paragraph()
    b.style_paragraph(p, after=3, line=1.0, align=JUSTIFY)
    p.paragraph_format.first_line_indent = Inches(0.17)
    b.set_font(p.add_run(
        "Tables VI to IX and Figures 3 to 6 give the full 10-qubit data. Every "
        "entry is read from results/results_10q*.csv; errors are against the "
        "active-space FCI energy, CNOT counts are in parentheses where shown, and "
        "NR denotes noise-realized selection."), size=10)
    rules = ("standard", "resource_aware", "NR_c4", "NR_c8")
    free = c.free_running()
    emit_table(doc, L, ["noise scale", "standard", "resource-aware", "NR (4 cand.)",
                        "NR (8 cand.)"],
               [[f"{s:g}"] + [f"{free[(r, s)][0]:.{3 if s == 0 else 2}f} "
                              f"({free[(r, s)][1]})" for r in rules]
                for s in c.SCALES],
               "TABLE VI. LiH(2e,5o), 10 qubits: free-running energy error (mHa) "
               "and CNOT count")
    rows = []
    for k in (4, 6):
        d = c.fixed_k(k)
        for s in c.SCALES:
            rows.append([f"K = {k}, {s:g}"] + [
                f"{d[(r, s)][0]:.{3 if s == 0 else 2}f} ({d[(r, s)][1]})"
                for r in rules])
    emit_table(doc, L, ["operators, noise", "standard", "resource-aware",
                        "NR (4 cand.)", "NR (8 cand.)"], rows,
               "TABLE VII. Matched operator count (both stopping rules off): "
               "energy error (mHa) and CNOT count")
    sh, ref, pm = c.shots(), c.fixed_k(4), "±"
    rows = []
    for s in sorted({x for (_, x) in sh}):
        a, bb = sh[("standard", s)], sh[("NR_c4", s)]
        ma, ea = c.mean_sem(a)
        mb, eb = c.mean_sem(bb)
        diffs = [y - x for x, y in zip(a, bb)]
        md, ed = c.mean_sem(diffs)
        rows.append([f"1e{round(math.log10(s))}", f"{ma:.2f} {pm} {ea:.2f}",
                     f"{mb:.2f} {pm} {eb:.2f}", f"{md:+.2f} {pm} {ed:.2f}",
                     f"{sum(1 for d in diffs if d < 0)}/{len(diffs)}"])
    rows.append(["exact (infinite)", f"{ref[('standard', 0.1)][0]:.2f}",
                 f"{ref[('NR_c4', 0.1)][0]:.2f}",
                 f"{ref[('NR_c4', 0.1)][0] - ref[('standard', 0.1)][0]:+.2f}", "-"])
    emit_table(doc, L, ["shots per term", "standard", "NR (4 cand.)",
                        "paired NR - standard", "NR wins"], rows,
               "TABLE VIII. Finite-shot selection (K = 4, 0.1x noise, 5 seeds): "
               "energy error (mHa), mean ± standard error")
    ch, rows = c.channels(), []
    for m, label in (("depolarizing", "depolarizing"), ("thermal", "thermal"),
                     ("coherent", "coherent"), ("depol+readout", "depol. + readout"),
                     ("all", "all combined")):
        for s in (0.05, 0.1, 0.2):
            if m == "depolarizing":
                a, bb = ref[("standard", s)][0], ref[("NR_c4", s)][0]
            else:
                a, bb = ch[(m, s, "standard")][0], ch[(m, s, "NR_c4")][0]
            rows.append([label, f"{s:g}", f"{a:.2f}", f"{bb:.2f}", f"{bb - a:+.2f}"])
    emit_table(doc, L, ["noise model", "scale", "standard", "NR (4 cand.)",
                        "NR - standard"], rows,
               "TABLE IX. Noise structure at equal gate infidelity (K = 4, exact "
               "expectations): energy error (mHa)")
    f = c.FIG
    figure(doc, L, os.path.join(f, "fig_10q_matched_k.png"),
           "Fig. 3. Matched operator count: K = 4 (left) and K = 6 (right).", True)
    figure(doc, L, os.path.join(f, "fig_10q_noise_structure.png"),
           "Fig. 4. Noise structure at equal gate infidelity, 0.05x (left) and 0.2x "
           "(right): coherent errors hurt most and are where selection matters.", True)
    figure(doc, L, os.path.join(f, "fig_10q_free_running.png"),
           "Fig. 5. LiH(2e,5o) free-running error vs noise scale (log scale); dotted "
           "line: chemical accuracy.", False)
    figure(doc, L, os.path.join(f, "fig_10q_shots.png"),
           "Fig. 6. Finite-shot selection, mean ± s.e. over 5 seeds (K = 4, "
           "0.1x); dashed: exact expectations.", False)


# --------------------------------------------------------------------------
# main conversion
# --------------------------------------------------------------------------
def build():
    with open(b.SRC, encoding="utf-8") as fh:
        toks = MarkdownIt("commonmark").enable("table").parse(fh.read())
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(0.625)
    sec.top_margin = sec.bottom_margin = Inches(0.75)
    b.add_page_number(sec)
    st = doc.styles["Normal"]
    st.font.name, st.font.size = b.BODY_FONT, Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), b.BODY_FONT)
    doc.core_properties.title = ("Noise-Realized Operator Selection for ADAPT-VQE "
                                 "(IEEE two-column, updated)")
    doc.core_properties.author = b.AUTHOR
    L = Layout(doc)

    pending, in_title, abstract, refs = None, True, False, False
    figs_done = vf_done = False
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        ty = t.type

        if ty == "heading_open":
            level = int(t.tag[1])
            inl = toks[i + 1].children
            text = b.inline_text(inl)
            if level == 3 and text.startswith("G. Conclusion") and not vf_done:
                vf_content(doc, L)
                vf_done = True
            if level == 1:
                L.to(1)
                p = doc.add_paragraph()
                b.style_paragraph(p, after=6, line=1.0, align=CENTER, keep_next=True)
                b.render_inline(p, inl, size=19, bold=True)
            elif level == 2 and text.strip() == "Abstract":
                in_title, abstract = False, True
            elif level == 2:
                in_title, abstract = False, False
                refs = "References" in text
                L.to(2)
                p = doc.add_paragraph()
                b.style_paragraph(p, before=9, after=3, line=1.0, align=CENTER,
                                  keep_next=True)
                b.render_inline(p, inl, size=10)
                for r in p.runs:
                    r.font.small_caps = True
            else:
                L.to(2)
                p = doc.add_paragraph()
                b.style_paragraph(p, before=5, after=2, line=1.0, keep_next=True)
                b.render_inline(p, inl, size=10, italic=True)
            i += 3

        elif ty == "paragraph_open":
            inl = toks[i + 1].children
            text = b.inline_text(inl)
            if text.startswith("Author Name"):
                L.to(1)
                p = doc.add_paragraph()
                b.style_paragraph(p, after=1, line=1.0, align=CENTER)
                b.set_font(p.add_run(b.AUTHOR), size=11, bold=True)
                p2 = doc.add_paragraph()
                b.style_paragraph(p2, after=4, line=1.0, align=CENTER)
                b.set_font(p2.add_run(b.AFFIL), size=10, italic=True)
            elif text.startswith("Before submission"):
                pass                      # author to-do note; kept in REPORT.md only
            elif text.startswith("TABLE "):
                pending = inl
            elif in_title:
                L.to(1)
                p = doc.add_paragraph()
                b.style_paragraph(p, after=6, line=1.0, align=CENTER)
                b.render_inline(p, inl, size=9, italic=True)
            elif abstract:
                L.to(2)
                p = doc.add_paragraph()
                b.style_paragraph(p, after=3, line=1.0, align=JUSTIFY)
                if text.startswith("Index Terms"):
                    b.render_inline(p, inl, size=9, bold=True, italic=True)
                    abstract = False
                else:
                    b.set_font(p.add_run("Abstract—"), size=9, bold=True,
                               italic=True)
                    b.render_inline(p, inl, size=9, bold=True)
            elif refs:
                L.to(2)
                p = doc.add_paragraph()
                b.style_paragraph(p, after=2, line=1.0, align=LEFT)
                p.paragraph_format.left_indent = Inches(0.3)
                p.paragraph_format.first_line_indent = Inches(-0.3)
                b.render_inline(p, inl, size=8)
            else:
                body_par(doc, L, inl)
                if text.startswith("Figure 1 (") and not figs_done:
                    figure(doc, L, os.path.join(c.ROOT, "results", "novel",
                                                "energy_error_vs_noise.png"),
                           "Fig. 1. Energy error vs noise scale, one panel per "
                           "molecule, all strategies (log scale).", True)
                    figure(doc, L, os.path.join(c.ROOT, "results", "novel",
                                                "circuit_depth.png"),
                           "Fig. 2. Transpiled depth and CNOT count per strategy.",
                           True)
                    figs_done = True
            i += 3

        elif ty in ("bullet_list_open", "ordered_list_open"):
            ordered = ty == "ordered_list_open"
            close = ty.replace("_open", "_close")
            j, num = i + 1, 1
            while toks[j].type != close:
                if toks[j].type == "list_item_open":
                    k = j + 1
                    while toks[k].type != "list_item_close":
                        if toks[k].type == "paragraph_open":
                            L.to(2)
                            p = doc.add_paragraph()
                            pf = p.paragraph_format
                            pf.left_indent, pf.first_line_indent = Inches(0.25), Inches(-0.2)
                            pf.tab_stops.add_tab_stop(Inches(0.25))
                            b.style_paragraph(p, after=2, line=1.0, align=JUSTIFY)
                            b.set_font(p.add_run(f"{num}.\t" if ordered else "•\t"),
                                       size=10)
                            b.render_inline(p, toks[k + 1].children, size=10)
                            k += 3
                        else:
                            k += 1
                    num += 1
                    j = k
                j += 1
            i = j + 1

        elif ty == "table_open":
            rows, cur, j = [], None, i + 1
            while toks[j].type != "table_close":
                tt = toks[j]
                if tt.type == "tr_open":
                    cur = []
                elif tt.type == "tr_close":
                    rows.append(cur)
                elif tt.type == "inline":
                    cur.append(tt.children)
                j += 1
            ncol = len(rows[0])
            emit_table(doc, L, rows[0], rows[1:], pending, wide=ncol >= 5)
            pending = None
            i = j + 1

        else:
            i += 1

    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
