"""Synthetic handwritten .rm v6 pages for tests: Hershey cursive with jitter, drawn checkboxes."""
from __future__ import annotations

import math
import random
from io import BytesIO
from pathlib import Path

from HersheyFonts import HersheyFonts
from rmscene import read_blocks, write_blocks
from rmscene.crdt_sequence import CrdtSequenceItem
from rmscene.scene_items import Line, Pen, PenColor, Point
from rmscene.scene_stream import RootTextBlock, SceneLineItemBlock
from rmscene.tagged_block_common import CrdtId

FIXTURE = Path(__file__).parent / "fixtures" / "Normal_A_stroke_2_layers_v3.3.2.rm"
_font = HersheyFonts()
_font.load_default_font("cursive")


def _densify(pts, step=3.0):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def _jitter(pts, rnd, amt=0.8):
    return [(x + rnd.uniform(-amt, amt), y + rnd.uniform(-amt, amt)) for x, y in pts]


def _text(text, x, baseline, rnd, height=40.0):
    _font.normalize_rendering(height)
    slant = rnd.uniform(-0.04, 0.08)
    out = []
    for s in _font.strokes_for_text(text):
        pts = [(x + px + py * slant, baseline - py) for px, py in s]
        if len(pts) >= 2:
            out.append(_jitter(_densify(pts), rnd))
    return out


def _box(x, baseline, rnd, done):
    s, y0 = 34, baseline - 36
    pts = [(x, y0), (x + s, y0), (x + s, y0 + s), (x, y0 + s), (x, y0 + 2)]
    out = [_jitter(_densify(pts), rnd, 1.2)]
    if done:
        out.append(_jitter(_densify([(x + 6, y0 + 18), (x + 15, y0 + 30), (x + 40, y0 - 10)]), rnd, 1.0))
    return out


def _shape(kind, cx, cy, w, h, rnd):
    if kind == "diamond":
        pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy), (cx, cy - h / 2 + 2)]
    elif kind == "circle":
        pts = [(cx + w / 2 * math.cos(a / 48 * 2 * math.pi), cy + h / 2 * math.sin(a / 48 * 2 * math.pi)) for a in range(51)]
    else:
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0 + 2)]
    return [_jitter(_densify(pts), rnd, 1.5)]


def _arrow(x0, y0, x1, y1, rnd):
    a = math.atan2(y1 - y0, x1 - x0)
    head = [(x1 - 22 * math.cos(a - 0.45), y1 - 22 * math.sin(a - 0.45)), (x1, y1),
            (x1 - 22 * math.cos(a + 0.45), y1 - 22 * math.sin(a + 0.45))]
    return [_jitter(_densify([(x0, y0), (x1, y1)]), rnd, 1.0), _jitter(_densify(head), rnd, 1.0)]


def page_strokes(lines, seed=1):
    """lines: list of ("h", text) heading (underlined), ("t", text) text, ("task", text, done), ("gap",),
    and drawn shapes at absolute positions that do not move the line cursor:
    ("node", kind, cx, cy, w, h, text) with kind box/diamond/circle, ("arrow", x0, y0, x1, y1[, label]),
    ("at", y) to move the cursor."""
    rnd = random.Random(seed)
    strokes, y = [], 160.0
    for ln in lines:
        kind = ln[0]
        if kind == "node":
            _, shape, cx, cy, w, h, text = ln
            strokes += _shape(shape, cx, cy, w, h, rnd)
            size = 34.0
            tw = len(text) * size * 0.52
            strokes += _text(text, cx - tw / 2, cy + size / 3, rnd, size)
            continue
        if kind == "arrow":
            strokes += _arrow(*ln[1:5], rnd)
            if len(ln) > 5:
                strokes += _text(ln[5], (ln[1] + ln[3]) / 2 + 12, (ln[2] + ln[4]) / 2, rnd, 30)
            continue
        if kind == "at":
            y = ln[1]
            continue
        if kind == "gap":
            y += 60
            continue
        if kind == "h":
            strokes += _text(ln[1], 120, y, rnd, 56)
            w = 120 + len(ln[1]) * 30
            strokes.append(_jitter(_densify([(110, y + 16), (w, y + 14)]), rnd))
            y += 110
        elif kind == "task":
            strokes += _box(120, y, rnd, ln[2])
            strokes += _text(ln[1], 180, y, rnd)
            y += 80
        else:
            strokes += _text(ln[1], 120, y, rnd)
            y += 80
    return strokes


def write_page(path: Path, lines, seed=1, units_w=1404.0):
    blocks = list(read_blocks(open(FIXTURE, "rb")))
    template = next(b for b in blocks if isinstance(b, SceneLineItemBlock) and b.item.value is not None)
    kept = [b for b in blocks if not isinstance(b, (SceneLineItemBlock, RootTextBlock))]
    out, prev, n = [], CrdtId(0, 0), 100
    for s in page_strokes(lines, seed):
        pts = [Point(x - units_w / 2, y, 2, 0, 10, 200) for x, y in s]
        item = CrdtSequenceItem(CrdtId(2, n), prev, CrdtId(0, 0), 0, Line(PenColor.BLACK, Pen.BALLPOINT_2, pts, 1.0, 0.0))
        out.append(SceneLineItemBlock(template.parent_id, item))
        prev, n = CrdtId(2, n), n + 1
    buf = BytesIO()
    write_blocks(buf, kept + out, options={"version": "3.3.2"})
    path.write_bytes(buf.getvalue())
