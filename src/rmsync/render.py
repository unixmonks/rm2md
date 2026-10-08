"""A .rm v6 page as a PNG (pen strokes) plus its typed text as Markdown."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw
from rmscene import read_tree, scene_items as si
from rmscene.text import TextDocument

# Page sizes in .rm units; x is centred on 0.
RM2 = (1404, 1872)
PAPER_PRO = (1620, 2160)

COLORS = {
    si.PenColor.BLACK: (0, 0, 0), si.PenColor.GRAY: (125, 125, 125), si.PenColor.WHITE: (255, 255, 255),
    si.PenColor.YELLOW: (240, 200, 0), si.PenColor.GREEN: (0, 150, 0), si.PenColor.PINK: (230, 80, 160),
    si.PenColor.BLUE: (0, 70, 200), si.PenColor.RED: (200, 0, 0), si.PenColor.GRAY_OVERLAP: (125, 125, 125),
    si.PenColor.HIGHLIGHT: (255, 235, 60), si.PenColor.GREEN_2: (100, 200, 80), si.PenColor.CYAN: (0, 180, 210),
    si.PenColor.MAGENTA: (200, 0, 200), si.PenColor.YELLOW_2: (240, 220, 0),
}
HIGHLIGHT_TOOLS = {si.Pen.HIGHLIGHTER_1, si.Pen.HIGHLIGHTER_2, si.Pen.SHADER}
SKIP_TOOLS = {si.Pen.ERASER, si.Pen.ERASER_AREA}

STYLE_PREFIX = {
    si.ParagraphStyle.HEADING: "## ", si.ParagraphStyle.BOLD: "**", si.ParagraphStyle.BULLET: "- ",
    si.ParagraphStyle.BULLET2: "  - ", si.ParagraphStyle.CHECKBOX: "- [ ] ",
    si.ParagraphStyle.CHECKBOX_CHECKED: "- [x] ",
}


@dataclass
class Page:
    png: bytes | None  # None when the page has no strokes
    typed: str  # typed text as Markdown ("" if none)
    strokes: int


def _typed_markdown(tree) -> str:
    if tree.root_text is None:
        return ""
    try:
        doc = TextDocument.from_scene_item(tree.root_text)
    except Exception:
        return ""
    lines = []
    for para in doc.contents:
        text = str(para).rstrip()
        if not text:
            lines.append("")
            continue
        prefix = STYLE_PREFIX.get(para.style.value, "")
        lines.append(f"**{text}**" if prefix == "**" else prefix + text)
    return "\n".join(lines).strip()


def render(data: bytes, scale: float = 1.0) -> Page:
    tree = read_tree(io.BytesIO(data))
    lines = [i for i in tree.walk() if isinstance(i, si.Line) and i.tool not in SKIP_TOOLS and len(i.points) > 0]
    typed = _typed_markdown(tree)
    if not lines:
        return Page(None, typed, 0)

    xs = [p.x for ln in lines for p in ln.points]
    ys = [p.y for ln in lines for p in ln.points]
    w, h = RM2
    if max(abs(min(xs)), abs(max(xs))) > RM2[0] / 2 + 20:
        w, h = PAPER_PRO
    w = max(w, int(2 * max(abs(min(xs)), abs(max(xs)))) + 40)
    h = max(h, int(max(ys)) + 60)
    top = min(0, int(min(ys)) - 40)
    W, H = int(w * scale), int((h - top) * scale)

    def xy(p):
        return ((p.x + w / 2) * scale, (p.y - top) * scale)

    ink = Image.new("RGB", (W, H), "white")
    marks = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d_ink, d_marks = ImageDraw.Draw(ink), ImageDraw.Draw(marks)
    for ln in sorted(lines, key=lambda ln: ln.tool not in HIGHLIGHT_TOOLS):
        hi = ln.tool in HIGHLIGHT_TOOLS
        color = COLORS.get(ln.color, (0, 0, 0))
        draw = d_marks if hi else d_ink
        fill = (*color, 110) if hi else color
        pts = ln.points
        for a, b in zip(pts, pts[1:] or pts):
            width = max(1.5, (a.width / 4.0)) * scale
            draw.line([xy(a), xy(b)], fill=fill, width=max(1, round(width)))
            if width > 3 and not hi:
                r = width / 2
                x, y = xy(b)
                draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)
    out = Image.alpha_composite(ink.convert("RGBA"), marks).convert("L")
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return Page(buf.getvalue(), typed, len(lines))
