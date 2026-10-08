"""Builds the README pictures: a handwritten page next to the note rm2md made from it.

Saves images/before-after.png (the page as rm2md sees it beside the note rendered as Markdown,
Mermaid diagram included), images/after.md (the note) and images/tasks.txt (Taskwarrior output).
The source is either a note rm2md already wrote, or docs/demo_page.py synced from a fake tablet
folder with the live model (about $0.002).

usage: uv run python docs/make_images.py                 demo page, synced with the live model
       uv run python docs/make_images.py --note FILE.md  a note rm2md already wrote, with its
                                                         page image and its +remarkable tasks
needs chromium and mmdc (and the OpenRouter key for the demo).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "tests"), str(HERE)]

from demo_page import DEMO  # noqa: E402
from fakexochitl import FakeXochitl  # noqa: E402
from PIL import Image, ImageChops, ImageDraw, ImageOps  # noqa: E402

from rm2md.config import Config, load  # noqa: E402
from rm2md.sync import Syncer  # noqa: E402

OUT = HERE / "images"
CSS = """
body { margin: 0; background: #fff; }
.markdown-body { box-sizing: border-box; width: 860px; padding: 36px 44px;
  font: 16px/1.5 -apple-system, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; color: #1f2328; }
h1 { font-size: 2em; border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; margin: 0 0 16px; }
h2 { font-size: 1.5em; border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; margin: 24px 0 16px; }
h3 { font-size: 1.25em; margin: 24px 0 16px; }
p, ul { margin: 0 0 16px; }
ul { padding-left: 2em; }
li.task { list-style: none; margin-left: -1.4em; }
li.task input { margin: 0 .5em 0 0; vertical-align: middle; }
img.diagram { display: block; max-width: 520px; margin: 8px 0 16px; }
.meta { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: #59636e; background: #f6f8fa;
  border: 1px solid #d1d9e0; border-radius: 6px; padding: 10px 14px; margin-bottom: 20px; white-space: pre; }
"""


def trim(img: Image.Image, pad: int = 40) -> Image.Image:
    bg = Image.new(img.mode, img.size, (255,) * len(img.getbands()) if len(img.getbands()) > 1 else 255)
    box = ImageChops.difference(img, bg).getbbox()
    if not box:
        return img
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def md_to_html(md: str, work: Path) -> str:
    """Just enough Markdown for one rm2md note: front matter, headings, lists, tasks, Mermaid."""
    front, _, body = md.partition("\n---\n")
    meta = "\n".join(front.strip("-\n").splitlines())
    body = re.sub(r"<!--.*?-->\n?", "", body)
    html, n = [], 0
    blocks = []
    for block in re.split(r"\n{2,}", body.strip()):
        if block.startswith("```mermaid") and not block.rstrip().endswith("```"):
            code, rest = block.split("\n```\n", 1)
            blocks += [code + "\n```", rest]
        else:
            blocks.append(block)
    for block in blocks:
        if block.startswith("```mermaid"):
            n += 1
            src, svg = work / f"d{n}.mmd", work / f"d{n}.png"
            src.write_text(block.split("\n", 1)[1].rsplit("```", 1)[0])
            subprocess.run(["mmdc", "-q", "-i", str(src), "-o", str(svg), "-b", "white", "-s", "2"], check=True)
            html.append(f'<img class="diagram" src="{svg}">')
            continue
        if block.startswith("![") :
            continue  # the page image is the "before" picture
        lines, out, in_list = block.splitlines(), [], False
        for ln in lines:
            if m := re.match(r"(#{1,4}) (.*)", ln):
                out.append(f"<h{len(m.group(1))}>{m.group(2)}</h{len(m.group(1))}>")
            elif m := re.match(r"- \[( |x)\] (.*)", ln):
                if not in_list:
                    out.append("<ul>"); in_list = True
                text = re.sub(r"~~(.*?)~~", r"<del>\1</del>", m.group(2))
                checked = " checked" if m.group(1) == "x" else ""
                out.append(f'<li class="task"><input type="checkbox" disabled{checked}>{text}</li>')
            elif ln.startswith("- "):
                if not in_list:
                    out.append("<ul>"); in_list = True
                out.append(f"<li>{ln[2:]}</li>")
            else:
                if in_list:
                    out.append("</ul>"); in_list = False
                out.append(f"<p>{re.sub(r'[*]([^*]+)[*]', r'<em>\\1</em>', ln)}</p>")
        if in_list:
            out.append("</ul>")
        html.append("\n".join(out))
    return (f"<!doctype html><meta charset=utf-8><style>{CSS}</style><div class=markdown-body>"
            f"<div class=meta>{meta}</div>{''.join(html)}</div>")


def screenshot(html_file: Path, png: Path) -> None:
    subprocess.run(["chromium", "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=860,2400", f"--screenshot={png}", f"file://{html_file}"],
                   check=True, capture_output=True)


def from_demo(work: Path) -> tuple[Path, Path, str]:
    key = load().api_key()
    if not key:
        raise SystemExit("no OpenRouter key")
    x = FakeXochitl(work / "xochitl")
    folder = x.folder("Notes")
    x.notebook("Relaunch meeting", folder, [DEMO], seed=21)
    rc = work / "taskrc"
    rc.write_text(f"data.location={work / 'tasks'}\nhooks=off\nnews.version=3.4.2\n")
    os.environ["TASKRC"] = str(rc)
    cfg = Config(host=f"dir:{x.root}", folder="Notes", notes_dir=work / "notes", state_dir=work / "state",
                 cache_dir=work / "cache", api_key_file=load().api_key_file)
    rep = Syncer(cfg).run()
    assert not rep.pages_failed, rep.pages_failed
    note = work / "notes" / "Relaunch meeting.md"
    page = next((work / "notes" / "assets" / "Relaunch meeting").glob("*.png"))
    return note, page, "all"


def from_note(note: Path) -> tuple[Path, Path, str]:
    m = re.search(r"!\[Page 1\]\((.*?)\)", note.read_text())
    if not m:
        raise SystemExit(f"{note}: no page image link")
    return note, note.parent / m.group(1).replace("%20", " "), "+remarkable all"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="rm2md-demo-"))
    if len(sys.argv) == 3 and sys.argv[1] == "--note":
        note, page_png, task_filter = from_note(Path(sys.argv[2]).expanduser())
    else:
        note, page_png, task_filter = from_demo(work)
    md = note.read_text()
    shutil.copy(note, OUT / "after.md")

    before = trim(Image.open(page_png).convert("RGB"))
    before = ImageOps.expand(before, border=2, fill=(208, 215, 222))
    before.save(work / "before.png")

    html = work / "note.html"
    html.write_text(md_to_html(md, work))
    shot = work / "note.png"
    screenshot(html, shot)
    after = trim(Image.open(shot).convert("RGB"), pad=24)
    after = ImageOps.expand(after, border=2, fill=(208, 215, 222))
    after.save(work / "after.png")

    # Side by side, same height, with an arrow between.
    h = 1100
    b = before.resize((round(before.width * h / before.height), h), Image.LANCZOS)
    a = after.resize((round(after.width * h / after.height), h), Image.LANCZOS)
    gap = 140
    combo = Image.new("RGB", (b.width + gap + a.width + 80, h + 80), "white")
    combo.paste(b, (40, 40))
    combo.paste(a, (40 + b.width + gap, 40))
    d = ImageDraw.Draw(combo)
    y, x0, x1 = 40 + h // 2, 40 + b.width + 30, 40 + b.width + gap - 30
    d.line([(x0, y), (x1, y)], fill=(89, 99, 110), width=8)
    d.polygon([(x1 + 6, y), (x1 - 26, y - 22), (x1 - 26, y + 22)], fill=(89, 99, 110))
    combo.save(OUT / "before-after.png", optimize=True)

    tasks = subprocess.run(["task", "rc.verbose=label", "rc.defaultwidth=100", "rc._forcecolor=off",
                            "rc.context=none", *task_filter.split()],
                           capture_output=True, text=True, check=True).stdout
    (OUT / "tasks.txt").write_text(re.sub(r"[ \t]+\n", "\n", tasks))
    print(md)
    print(tasks)
    shutil.rmtree(work)


if __name__ == "__main__":
    main()
