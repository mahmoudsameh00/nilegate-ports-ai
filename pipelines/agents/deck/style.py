"""The NileGate deck template, as code (Agents plan §5c, P6-5): page size, colours, fonts, the slide grid.

One place for every presentation constant, so the renderer holds no magic numbers and a designed `.pptx` template
can replace this module later without touching the data path. Colours follow the dataviz method: a single series
wears categorical slot 1 (blue), the comparison (budget) a neutral grey, text never wears a series colour, and no
chart has more than two series (a bar per vessel category is one series, named on the axis — no 13-hue legend).
"""
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

# 16:9
WIDTH, HEIGHT = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.6)
CONTENT_W = WIDTH - 2 * MARGIN

FONT = "Calibri"                       # present in every Office install


def rgb(hex6: str) -> RGBColor:
    return RGBColor.from_string(hex6.lstrip("#").upper())


# brand + neutrals
NAVY = rgb("0B2545")                   # NileGate brand: title slide, slide titles
NILE = rgb("13A89E")                   # brand accent: rules, tile edges
INK = rgb("0B0B0B")                    # primary text
INK_2 = rgb("52514E")                  # secondary text
MUTED = rgb("8A8984")                  # footers, footnotes
GRID = rgb("E5E4E0")                   # recessive gridlines, table rules
TILE_BG = rgb("F5F4F0")
WHITE = rgb("FFFFFF")
LABEL_BG = rgb("EDA100")               # the "Draft for approval" badge (yellow; dark text on it)
APPROVED_BG = rgb("1BAF7A")            # the "Approved" badge
# data
SERIES_1 = rgb("2A78D6")               # dataviz categorical slot 1: billed
COMPARISON = rgb("A3A29C")             # budget (a reference, not a category)
HIGHLIGHT = rgb("EB6834")              # the report week's marker (slot 2)

# type sizes
TITLE_PT, BODY_PT, SMALL_PT, TILE_VALUE_PT, TILE_LABEL_PT, FOOT_PT = Pt(28), Pt(16), Pt(12), Pt(26), Pt(12), Pt(10)
BRAND_PT, WEEK_PT = Pt(40), Pt(22)

# the grid (EMU)
TITLE_TOP, TITLE_H = Inches(0.45), Inches(0.9)
BODY_TOP = Inches(1.55)
FOOTER_TOP, FOOTER_H = HEIGHT - Inches(0.5), Inches(0.35)
FOOTNOTE_TOP = FOOTER_TOP - Inches(0.4)
COMMENT_H = Inches(0.42)

# number formats inside the native charts (the values stay the tool's exact SDR; the axis shows millions)
AXIS_M = '#,##0.0,," M"'
AXIS_K = '#,##0,"k"'
