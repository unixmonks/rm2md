"""One Markdown file per notebook."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_name(name: str) -> str:
    s = _UNSAFE.sub("-", name).strip(" .-")
    return s[:120] or "Untitled"


def note_path(notes_dir: Path, subpath: list[str] | tuple[str, ...], name: str) -> Path:
    return notes_dir.joinpath(*(safe_name(p) for p in subpath), safe_name(name) + ".md")


def assets_dir(md: Path) -> Path:
    return md.parent / "assets" / md.stem


def demote(md: str) -> str:
    """Shift the page's headings so its top level is ### (under "## Page N"), keeping their order."""
    lines, fence, heads = md.splitlines(), False, []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and (m := re.match(r"(#{1,6}) ", line)):
            heads.append((i, len(m.group(1))))
    if heads:
        shift = 3 - min(n for _, n in heads)
        for i, n in heads:
            lines[i] = "#" * min(4, n + shift) + lines[i][n:]  # deeper levels read as body text
    return "\n".join(lines)


def _iso_ms(ms: str) -> str:
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000).astimezone().isoformat(timespec="seconds")
    except (ValueError, OSError, OverflowError):
        return ""


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_note(*, name: str, uuid: str, source: str, last_modified: str, pages: list[dict],
                image_names: dict[str, str] | None = None) -> str:
    """pages: [{"id", "markdown", "title", "confidence", "error", "empty"}] in order."""
    head = [
        "---",
        f"title: {_yaml_str(name)}",
        f"source: {_yaml_str(source)}",
        f"remarkable_id: {uuid}",
        f"modified: {_iso_ms(last_modified)}",
        f"pages: {len(pages)}",
        "tags: [remarkable]",
        "---",
        "<!-- Written by rmsync from the reMarkable notebook. Edits here are overwritten on the next sync. -->",
        "",
        f"# {name}",
    ]
    body = []
    for n, p in enumerate(pages, 1):
        if p.get("empty"):
            continue
        starts_with_heading = re.match(r"#{1,4} ", p.get("markdown", ""))
        title = f" · {p['title']}" if p.get("title") and not starts_with_heading else ""
        part = [f"## Page {n}{title}", ""]
        if p.get("error"):
            part.append(f"*Not transcribed yet: {p['error']}*")
        else:
            part.append(demote(p.get("markdown", "")) or "*(no text)*")
            if p.get("confidence") == "low":
                part += ["", "*Transcription uncertain; check the page image.*"]
        if image_names and p["id"] in image_names:
            part += ["", f"![Page {n}]({image_names[p['id']]})"]
        body.append("\n".join(part))
    return "\n".join(head) + "\n\n" + "\n\n".join(body).rstrip() + "\n"
