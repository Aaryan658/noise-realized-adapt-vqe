"""
build_report_docx.py -- builds docs/REPORT_UPDATED.docx from docs/REPORT.md.

A new file; the original docs/REPORT.docx is left untouched. Differences from the
markdown source: the author placeholder is filled from the project deck, the two
existing figures are embedded, and section V-F gains four tables (VI-IX) and four
figures (3-6) generated from the result CSVs.

    .venv\\Scripts\\python.exe docs\\build\\make_figures.py
    .venv\\Scripts\\python.exe docs\\build\\build_report_docx.py
"""

from __future__ import annotations

import math
import os
import sys

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from markdown_it import MarkdownIt

sys.path.insert(0, os.path.dirname(__file__))
import common as c                                    # noqa: E402

SRC = os.path.join(c.ROOT, "docs", "REPORT.md")
OUT = os.path.join(c.ROOT, "docs", "REPORT_UPDATED.docx")
AUTHOR = "Aaryan Dharrmik"
AFFIL = "5 BTCS B, B. Tech CSE"
BODY_FONT = "Times New Roman"
NAVY = RGBColor(0x1B, 0x2A, 0x4A)


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------
def set_font(run, size=None, bold=None, italic=None, name=None, color=None):
    run.font.name = name or BODY_FONT
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), name or BODY_FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def shade(cell, hex_fill):
    tcpr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcpr.append(shd)


def table_borders(table, color="BFC7D1"):
    tblpr = table._element.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblpr.append(borders)


def cell_margins(table, top=40, bottom=40, left=70, right=70):
    tblpr = table._element.tblPr
    mar = OxmlElement("w:tblCellMar")
    for k, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{k}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblpr.append(mar)


def repeat_header(row):
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def no_split(row):
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def add_page_number(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for kind, text in (("begin", None), (None, " PAGE "), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)
    set_font(run, size=9)


# --------------------------------------------------------------------------
# inline markdown -> runs
# --------------------------------------------------------------------------
def render_inline(par, children, size=11, bold=False, italic=False):
    b = i = 0
    for t in children:
        if t.type == "text":
            set_font(par.add_run(t.content), size=size, bold=bold or b > 0,
                     italic=italic or i > 0)
        elif t.type == "strong_open":
            b += 1
        elif t.type == "strong_close":
            b -= 1
        elif t.type == "em_open":
            i += 1
        elif t.type == "em_close":
            i -= 1
        elif t.type == "code_inline":
            set_font(par.add_run(t.content), size=size - 1.5, name="Consolas",
                     bold=bold or b > 0, italic=italic or i > 0)
        elif t.type == "softbreak":
            set_font(par.add_run(" "), size=size)
        elif t.type == "hardbreak":
            par.add_run().add_break()


def inline_text(children):
    return "".join(t.content for t in children
                   if t.type in ("text", "code_inline"))


# --------------------------------------------------------------------------
# document pieces
# --------------------------------------------------------------------------
def style_paragraph(p, before=0, after=6, line=1.12, align=None, keep_next=False):
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = line
    pf.keep_with_next = keep_next
    if align is not None:
        p.alignment = align


def add_caption(doc, text):
    p = doc.add_paragraph()
    style_paragraph(p, before=8, after=3, align=WD_ALIGN_PARAGRAPH.CENTER,
                    keep_next=True)
    set_font(p.add_run(text), size=9.5, bold=True)
    return p


def add_table(doc, header, rows, caption=None, widths=None, size=8.5,
              align_first_left=True):
    if caption:
        add_caption(doc, caption)
    t = doc.add_table(rows=1 + len(rows), cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    table_borders(t)
    cell_margins(t)
    total = 16.0 if widths is None else sum(widths)
    widths = widths or [total / len(header)] * len(header)
    for r_i, row in enumerate([header] + rows):
        tr = t.rows[r_i]
        no_split(tr)
        if r_i == 0:
            repeat_header(tr)
        for col, val in enumerate(row):
            cell = tr.cells[col]
            cell.width = Cm(widths[col])
            p = cell.paragraphs[0]
            style_paragraph(p, after=0, line=1.0,
                            align=(WD_ALIGN_PARAGRAPH.LEFT
                                   if (col == 0 and align_first_left)
                                   else WD_ALIGN_PARAGRAPH.CENTER))
            if isinstance(val, list):
                render_inline(p, val, size=size, bold=(r_i == 0))
            else:
                set_font(p.add_run(str(val)), size=size, bold=(r_i == 0))
            if r_i < len(rows):          # keep the table on one page
                p.paragraph_format.keep_with_next = True
            if r_i == 0:
                shade(cell, "DDE5EE")
    after = doc.add_paragraph()
    style_paragraph(after, after=4)
    return t


def add_figure(doc, path, caption, width_in=5.6):
    p = doc.add_paragraph()
    style_paragraph(p, before=6, after=2, align=WD_ALIGN_PARAGRAPH.CENTER,
                    keep_next=True)
    p.add_run().add_picture(path, width=Inches(width_in))
    cp = doc.add_paragraph()
    style_paragraph(cp, after=8, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_font(cp.add_run(caption), size=9, italic=True)


# --------------------------------------------------------------------------
# generated 10-qubit tables and figures (section V-F)
# --------------------------------------------------------------------------
def tex(x, nd=2):
    return f"{x:.{nd}f}"


def tables_and_figures(doc):
    p = doc.add_paragraph()
    style_paragraph(p, before=4, after=6)
    set_font(p.add_run(
        "Tables VI to IX and Figures 3 to 6 give the full 10-qubit data. Every "
        "entry is read from results/results_10q*.csv; errors are against the "
        "active-space FCI energy, CNOT counts are in parentheses where shown, and "
        "NR denotes noise-realized selection."), size=11)

    rules = ("standard", "resource_aware", "NR_c4", "NR_c8")
    head = ["noise scale", "standard", "resource-aware", "NR (4 cand.)",
            "NR (8 cand.)"]
    free = c.free_running()
    add_table(doc, head,
              [[f"{s:g}"] + [f"{tex(free[(r, s)][0], 3 if s == 0 else 2)} "
                             f"({free[(r, s)][1]})" for r in rules]
               for s in c.SCALES],
              "TABLE VI. LiH(2e,5o), 10 qubits: free-running energy error (mHa) "
              "and CNOT count", widths=[2.6, 3.2, 3.2, 3.2, 3.2])

    rows = []
    for k in (4, 6):
        d = c.fixed_k(k)
        for s in c.SCALES:
            rows.append([f"K = {k}, {s:g}"] + [
                f"{tex(d[(r, s)][0], 3 if s == 0 else 2)} ({d[(r, s)][1]})"
                for r in rules])
    add_table(doc, ["operators, noise", "standard", "resource-aware",
                    "NR (4 cand.)", "NR (8 cand.)"], rows,
              "TABLE VII. Matched operator count (both stopping rules off): "
              "energy error (mHa) and CNOT count",
              widths=[3.0, 3.1, 3.1, 3.1, 3.1])

    sh = c.shots()
    ref = c.fixed_k(4)
    rows = []
    for s in sorted({x for (_, x) in sh}):
        a, b = sh[("standard", s)], sh[("NR_c4", s)]
        ma, ea = c.mean_sem(a)
        mb, eb = c.mean_sem(b)
        diffs = [y - x for x, y in zip(a, b)]
        md, ed = c.mean_sem(diffs)
        wins = sum(1 for d in diffs if d < 0)
        pm = "±"
        rows.append([f"1e{round(math.log10(s))}", f"{ma:.2f} {pm} {ea:.2f}",
                     f"{mb:.2f} {pm} {eb:.2f}", f"{md:+.2f} {pm} {ed:.2f}",
                     f"{wins}/{len(diffs)}"])
    rows.append(["exact (infinite)", f"{ref[('standard', 0.1)][0]:.2f}",
                 f"{ref[('NR_c4', 0.1)][0]:.2f}",
                 f"{ref[('NR_c4', 0.1)][0] - ref[('standard', 0.1)][0]:+.2f}", "-"])
    add_table(doc, ["shots per term", "standard", "NR (4 cand.)",
                    "paired NR - standard", "NR wins"], rows,
              "TABLE VIII. Finite-shot selection (K = 4, 0.1x noise, 5 seeds): "
              "energy error (mHa), mean ± standard error",
              widths=[3.0, 3.3, 3.3, 3.8, 2.0])

    ch = c.channels()
    rows = []
    for m, label in (("depolarizing", "depolarizing"), ("thermal", "thermal"),
                     ("coherent", "coherent"), ("depol+readout",
                                                "depol. + readout"),
                     ("all", "all combined")):
        for s in (0.05, 0.1, 0.2):
            if m == "depolarizing":
                a, b = ref[("standard", s)][0], ref[("NR_c4", s)][0]
            else:
                a, b = ch[(m, s, "standard")][0], ch[(m, s, "NR_c4")][0]
            rows.append([label, f"{s:g}", tex(a), tex(b), f"{b - a:+.2f}"])
    add_table(doc, ["noise model", "scale", "standard", "NR (4 cand.)",
                    "NR - standard"], rows,
              "TABLE IX. Noise structure at equal gate infidelity (K = 4, exact "
              "expectations): energy error (mHa)",
              widths=[3.6, 2.0, 3.0, 3.2, 3.2])

    fdir = c.FIG
    add_figure(doc, os.path.join(fdir, "fig_10q_free_running.png"),
               "Fig. 3. LiH(2e,5o) free-running energy error versus noise scale "
               "(log scale). The dotted line is chemical accuracy, 1.6 mHa.", 5.0)
    add_figure(doc, os.path.join(fdir, "fig_10q_matched_k.png"),
               "Fig. 4. Matched operator count: K = 4 (left) and K = 6 (right). "
               "Cost-aware selection helps only past the noise-optimal length.",
               6.0)
    add_figure(doc, os.path.join(fdir, "fig_10q_shots.png"),
               "Fig. 5. Finite-shot selection, mean ± standard error over 5 "
               "seeds (K = 4, 0.1x). Dashed lines: exact-expectation results.",
               5.0)
    add_figure(doc, os.path.join(fdir, "fig_10q_noise_structure.png"),
               "Fig. 6. Noise structure at equal gate infidelity at 0.05x (left) "
               "and 0.2x (right). Coherent errors are the most damaging and the "
               "only setting where selection changes the error substantially.",
               6.2)


# --------------------------------------------------------------------------
# main conversion
# --------------------------------------------------------------------------
def build():
    with open(SRC, encoding="utf-8") as fh:
        md = fh.read()
    tokens = MarkdownIt("commonmark").enable("table").parse(md)

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.3)
    sec.top_margin = sec.bottom_margin = Cm(2.2)
    add_page_number(sec)
    st = doc.styles["Normal"]
    st.font.name, st.font.size = BODY_FONT, Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    doc.core_properties.title = ("Noise-Realized Operator Selection for ADAPT-VQE "
                                 "(updated report)")
    doc.core_properties.author = AUTHOR

    figs_done = False
    vf_inserted = False
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        ty = t.type

        if ty == "heading_open":
            level = int(t.tag[1])
            inl = tokens[i + 1].children
            text = inline_text(inl)
            if level == 3 and text.startswith("G. Conclusion") and not vf_inserted:
                tables_and_figures(doc)
                vf_inserted = True
            p = doc.add_paragraph()
            if level == 1:
                style_paragraph(p, before=0, after=8, align=WD_ALIGN_PARAGRAPH.CENTER,
                                keep_next=True)
                render_inline(p, inl, size=17, bold=True)
                for r in p.runs:
                    r.font.color.rgb = NAVY
            elif level == 2:
                style_paragraph(p, before=16, after=6, keep_next=True)
                render_inline(p, inl, size=13, bold=True)
                for r in p.runs:
                    r.font.color.rgb = NAVY
            else:
                style_paragraph(p, before=10, after=4, keep_next=True)
                render_inline(p, inl, size=11.5, bold=True, italic=True)
            i += 3

        elif ty == "paragraph_open":
            inl = tokens[i + 1].children
            text = inline_text(inl)
            p = doc.add_paragraph()
            if text.startswith("Author Name"):
                style_paragraph(p, after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
                set_font(p.add_run(AUTHOR), size=12, bold=True)
                p2 = doc.add_paragraph()
                style_paragraph(p2, after=8, align=WD_ALIGN_PARAGRAPH.CENTER)
                set_font(p2.add_run(AFFIL), size=11, italic=True)
            elif text.startswith("TABLE "):
                style_paragraph(p, before=8, after=3, align=WD_ALIGN_PARAGRAPH.CENTER,
                                keep_next=True)
                render_inline(p, inl, size=9.5, bold=True)
            else:
                has_code = any(x.type == "code_inline" for x in inl)
                style_paragraph(p, after=6,
                                align=(WD_ALIGN_PARAGRAPH.LEFT if has_code
                                       else WD_ALIGN_PARAGRAPH.JUSTIFY))
                render_inline(p, inl, size=11)
            if text.startswith("Figure 1 (") and not figs_done:
                add_figure(doc, os.path.join(c.ROOT, "results", "novel",
                                             "energy_error_vs_noise.png"),
                           "Fig. 1. Energy error versus noise scale, one panel "
                           "per molecule, all strategies (log scale).", 6.2)
                add_figure(doc, os.path.join(c.ROOT, "results", "novel",
                                             "circuit_depth.png"),
                           "Fig. 2. Transpiled depth and CNOT count per strategy.",
                           6.2)
                figs_done = True
            i += 3

        elif ty in ("bullet_list_open", "ordered_list_open"):
            ordered = ty == "ordered_list_open"
            close = ty.replace("_open", "_close")
            j, num = i + 1, 1
            while tokens[j].type != close:
                if tokens[j].type == "list_item_open":
                    k = j + 1
                    while tokens[k].type != "list_item_close":
                        if tokens[k].type == "paragraph_open":
                            p = doc.add_paragraph()
                            pf = p.paragraph_format
                            pf.left_indent, pf.first_line_indent = Cm(0.9), Cm(-0.6)
                            style_paragraph(p, after=4, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
                            set_font(p.add_run((f"{num}.\t" if ordered else "•\t")),
                                     size=11)
                            pf.tab_stops.add_tab_stop(Cm(0.9))
                            render_inline(p, tokens[k + 1].children, size=11)
                            k += 3
                        else:
                            k += 1
                    num += 1
                    j = k
                j += 1
            i = j + 1

        elif ty == "table_open":
            rows, cur, in_head = [], None, False
            j = i + 1
            while tokens[j].type != "table_close":
                tt = tokens[j]
                if tt.type == "tr_open":
                    cur = []
                elif tt.type == "tr_close":
                    rows.append(cur)
                elif tt.type == "inline":
                    cur.append(tt.children)
                j += 1
            ncol = len(rows[0])
            widths = ([16.4 / ncol] * ncol)
            if ncol >= 7:
                widths = [1.6] + [(16.4 - 1.6) / (ncol - 1)] * (ncol - 1)
            add_table(doc, rows[0], rows[1:], widths=widths,
                      size=8 if ncol >= 6 else 8.5)
            i = j + 1

        else:  # hr, html, fences etc.: not present / not needed
            i += 1

    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
