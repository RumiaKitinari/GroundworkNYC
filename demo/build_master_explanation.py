"""Build the team-facing status document for a frozen Groundwork data export."""

import argparse
import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


INK = RGBColor(25, 39, 55)
MUTED = RGBColor(82, 99, 113)
ACCENT = RGBColor(0, 112, 115)


def shade(cell, color):
    tc_pr = cell._tc.get_or_add_tcPr()
    fill = OxmlElement("w:shd")
    fill.set(qn("w:fill"), color)
    tc_pr.append(fill)


def margins(cell, top=90, left=110, bottom=90, right=110):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    mar = tc_pr.first_child_found_in("w:tcMar")
    if mar is None:
        mar = OxmlElement("w:tcMar")
        tc_pr.append(mar)
    for side, amount in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = mar.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            mar.append(node)
        node.set(qn("w:w"), str(amount))
        node.set(qn("w:type"), "dxa")


def border_table(table):
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        item = OxmlElement(f"w:{edge}")
        item.set(qn("w:val"), "single")
        item.set(qn("w:sz"), "4")
        item.set(qn("w:color"), "D9D9D9")
        borders.append(item)
    tbl_pr.append(borders)


def set_cell(cell, text, bold=False, white=False):
    cell.text = text
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    margins(cell)
    for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_after = Pt(0)
        for run in paragraph.runs:
            run.font.size = Pt(9)
            run.font.bold = bold
            run.font.color.rgb = RGBColor(255, 255, 255) if white else INK


def add_table(doc, headers, rows, widths):
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    for index, (header, width) in enumerate(zip(headers, widths)):
        table.columns[index].width = Inches(width)
        set_cell(table.rows[0].cells[index], header, bold=True, white=True)
        shade(table.rows[0].cells[index], "263D50")
    for number, data in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(data):
            set_cell(cells[index], value)
            if number % 2:
                shade(cells[index], "F2F5F6")
    border_table(table)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width)
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def bullet(doc, label, body):
    paragraph = doc.add_paragraph(style="List Bullet")
    lead = paragraph.add_run(label + " ")
    lead.bold = True
    paragraph.add_run(body)


def build(output, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.67)
    section.left_margin = Inches(0.82)
    section.right_margin = Inches(0.82)
    section.header_distance = Inches(0.33)
    section.footer_distance = Inches(0.32)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.12
    for name, size, before, after in (("Title", 20, 0, 12), ("Heading 1", 12.5, 14, 6),
                                       ("Heading 2", 11, 10, 4)):
        style = styles[name]
        style.font.name = "Aptos Display" if name == "Title" else "Aptos"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = INK
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
    styles["List Bullet"].paragraph_format.space_after = Pt(4)

    header = section.header.paragraphs[0]
    header.text = "GROUNDWORK NYC  |  DATA STATUS"
    header.runs[0].font.size = Pt(8)
    header.runs[0].font.bold = True
    header.runs[0].font.color.rgb = MUTED
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run("Internal team working copy  |  20 October 2026").font.size = Pt(8)

    doc.add_paragraph("Groundwork NYC Master Data and Model Readiness", style="Title")
    p = doc.add_paragraph()
    p.add_run("Purpose. ").bold = True
    p.add_run("This document accompanies the frozen team data export. It identifies what is in the current master, what must remain in separate files, and which evidence gaps prevent a defensible restaurant survival model or verified property recommendations.")

    doc.add_heading("Current Master", level=1)
    doc.add_paragraph(
        f"The active release is {manifest['active_release']}. Its master table contains "
        f"{manifest['master_rows']:,} unique 2020 NYC census tracts and {manifest['master_columns']} columns. "
        "The export includes the exact master CSV, its data dictionary, source catalog, QA files, geography, "
        "and companion entity and feature tables. Each file is indexed with a SHA-256 checksum. "
        "The release passed structural validation; this does not establish predictive accuracy."
    )
    add_table(doc, ("Data area", "Available now", "How it should be used"), (
        ("Residents and jobs", "2024 ACS population/income; 2023 LODES workplace jobs", "Current tract context, not a historical survival feature without dated vintages."),
        ("Access and market", "Subway, Citi Bike, OSM places, DOHMH restaurants, taxi-zone activity, walkability", "Location screening with source-grain and coverage caveats."),
        ("Built environment", "PLUTO lots, 2024 storefront filings and reported occupied-rent medians", "Commercial context, not live availability or asking rent."),
        ("Research inputs", "Historical tract snapshots, inspection archive, 5,999-case review packet", "Private research and manual adjudication only; no verified outcome labels."),
    ), (1.22, 2.55, 3.05))

    doc.add_heading("Why the Master Is Not One Giant Training Table", level=1)
    doc.add_paragraph(
        "The master has one row per tract. Restaurants and commercial spaces are point or property records; "
        "subway and pedestrian data are station or monitor observations; weather is citywide by day; "
        "TLC totals belong to taxi zones; historical predictors have dated releases. Flattening all of these "
        "into tract rows would repeat observations and conceal their timing. The export keeps them in their "
        "native tables and supplies a file index instead. The 2026 current master must not be joined to a "
        "2023-2025 restaurant baseline as if its values were known then."
    )

    doc.add_heading("What Is Holding Us Back", level=1)
    add_table(doc, ("Priority", "Evidence today", "Required next step"), (
        ("Survival outcomes", "All 5,999 candidate cases remain unresolved. Archive disappearance is not permanent closure.", "Obtain dated operating baselines and independent one-year operation or permanent-closure records; double-review both classes."),
        ("Business identity", "127 possible new CAMIS IDs after Queens address normalization; 18 same-CAMIS name or address changes.", "Reconcile ownership, relocation, rebranding, and permit changes before assigning a stable business identity."),
        ("Historical coverage", "Four dated tract predictors are prepared; the current tract master is not historical.", "Add only predictors available at each baseline; preserve 2025-01-01 as the predeclared temporal cutoff."),
        ("Actual properties", "1,000 synthetic scenarios and one source-reported public opportunity; no authorized live lease feed.", "Obtain licensed listing/owner data for prices, terms, availability, images, and space suitability. Do not present synthetic rows as listings."),
    ), (1.12, 2.75, 2.95))

    doc.add_heading("Other Data Limitations", level=1)
    bullet(doc, "Demographics.", "The current master has 128 tracts without published 2024 median income; 124 have a separate neighbor estimate. Eleven full ACS detailed tables now provide demographic, social, economic and housing context through a repeatable bulk route without an API key. Missing published values remain blank.")
    bullet(doc, "Property context.", "The 2025 registry extract contains vacancy-only records, so it cannot supply a defensible storefront vacancy rate. The 2024 reported median rent is for occupied storefronts, not a live asking rent.")
    bullet(doc, "Movement and geography.", "DOT counts cover 114 monitored sites, subway activity is a complete week, and Citi Bike coverage is uneven. Subway entrance proximity and station time shares are integrated. A projected taxi-zone crosswalk now records overlap fractions; original trip totals still have zone grain. ZIP Business Patterns remains at ZIP/NAICS grain.")
    bullet(doc, "Cuisine and success.", "Some OSM places lack cuisine tags. We have no validated restaurant sales, profit, customer visits, or permanent-closure registry. The archive-reobservation gradient booster is a weak pipeline proxy, not a survival model or deployable success prediction.")
    bullet(doc, "Lineage and sharing.", "The inventory contains machine-local paths; the export provides a file index and relative paths. Current ACS raw files are now retained and checksummed. Review source licensing before sharing third-party archives or map assets beyond the project team.")

    doc.add_heading("Immediate Team Decisions", level=1)
    doc.add_paragraph(
        "Use the exported master and companion tables for the dashboard and transparent location screening. "
        "Submit the drafted DOHMH permit-history request and begin the private 600-case probability-sample review. "
        "Resolve CAMIS changes, record dated baseline and outcome sources, and keep ambiguous cases censored. "
        "The guarded training command currently returns needs_verified_outcomes with zero eligible rows and writes "
        "no model. Run the historical cohort and fixed temporal/geographic holdout only after verified evidence "
        "meets the class, timing, and neighborhood requirements."
    )

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    doc.save(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output, args.manifest))


if __name__ == "__main__":
    main()
