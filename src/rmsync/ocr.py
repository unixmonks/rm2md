"""Handwriting → Markdown + tasks, with a vision model on OpenRouter."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = os.environ.get("RMSYNC_API_URL", "https://openrouter.ai/api/v1/chat/completions")

PROMPT = """You transcribe a handwritten page from a reMarkable tablet notebook.
Today is {today} ({weekday}). Notebook: "{notebook}", page {page}.

Return JSON only, with these fields:

"markdown": the page as clean Markdown. Keep the writer's words; fix only obvious letter-level
misreads. Use headings for underlined or large titles, lists for bullet points, "- [ ]" / "- [x]"
for task lines (below). Drawings, arrows and diagrams: describe briefly in italics, e.g.
"*[sketch: box labelled API pointing to DB]*". Do not add commentary or anything not on the page.
Write a word you cannot read as [?].

"tasks": one entry per task on the page, in page order. A line is a task when it starts with a
hand-drawn checkbox (a small square or circle), or with "TODO", "todo:" or "[ ]"; also every item
listed under a heading such as "TODO", "To do" or "Tasks". A tick, cross or fill inside the box, or
a line struck through, means done. Other bullet points are NOT tasks. For each task:
  "text": the task without the checkbox and without the markers below
  "done": true if ticked
  "project": from "@word" or "pro:word" or "project:word" on the line, else null
  "tags": from "#word" or "+word" on the line (no # or +), else []
  "due": from "due fri", "by 12/3", "due:tomorrow", "→ mon" etc. as YYYY-MM-DD computed from today, else null.
         Dates like 12/3 are month/day.
  "priority": "H" for "!" or "!!" or "!!!" or "(A)" on the line, "M" for "(B)", "L" for "(C)", else null

"title": a short title for the page if it has an obvious heading, else null
"confidence": "high", "medium" or "low" for the transcription as a whole
{typed}"""

SCHEMA = {
    "name": "page",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["markdown", "tasks", "title", "confidence"],
        "properties": {
            "markdown": {"type": "string"},
            "title": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "tasks": {"type": "array", "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "done", "project", "tags", "due", "priority"],
                "properties": {
                    "text": {"type": "string"},
                    "done": {"type": "boolean"},
                    "project": {"type": ["string", "null"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "due": {"type": ["string", "null"]},
                    "priority": {"anyOf": [{"type": "string", "enum": ["H", "M", "L"]}, {"type": "null"}]},
                },
            }},
        },
    },
}


class OcrError(Exception):
    pass


@dataclass
class TaskItem:
    text: str
    done: bool = False
    project: str | None = None
    tags: list[str] = field(default_factory=list)
    due: str | None = None
    priority: str | None = None


@dataclass
class PageText:
    markdown: str
    tasks: list[TaskItem]
    title: str | None = None
    confidence: str = "high"


_WORD = re.compile(r"[^\w.\-]+")


def _clean_word(s: str | None) -> str | None:
    if not s:
        return None
    s = _WORD.sub("", s.strip().lstrip("#+@"))
    return s or None


def _clean_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s.strip()[:10]).isoformat()
    except ValueError:
        return None


def parse_reply(obj: dict) -> PageText:
    tasks = []
    for t in obj.get("tasks") or []:
        if not isinstance(t, dict) or not str(t.get("text", "")).strip():
            continue
        tasks.append(TaskItem(
            text=" ".join(str(t["text"]).split()),
            done=bool(t.get("done")),
            project=_clean_word(t.get("project")),
            tags=[w for w in (_clean_word(x) for x in t.get("tags") or [] if isinstance(x, str)) if w],
            due=_clean_date(t.get("due")),
            priority=t.get("priority") if t.get("priority") in ("H", "M", "L") else None,
        ))
    conf = obj.get("confidence")
    return PageText(
        markdown=str(obj.get("markdown") or "").strip(),
        tasks=tasks,
        title=(str(obj["title"]).strip() or None) if obj.get("title") else None,
        confidence=conf if conf in ("high", "medium", "low") else "medium",
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def transcribe(png: bytes, *, api_key: str, model: str, notebook: str, page: int, typed: str = "",
               reasoning: str = "low", today: dt.date | None = None, retries: int = 3,
               timeout: int = 120) -> PageText:
    today = today or dt.date.today()
    typed_note = (f"\nThe page also has typed text (already known, include it in the markdown where it fits):\n"
                  f"<<<\n{typed}\n>>>\n") if typed else ""
    prompt = PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"), notebook=notebook,
                           page=page, typed=typed_note)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        "temperature": 0,
    }
    if reasoning:
        body["reasoning"] = {"effort": reasoning}
    req_data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=req_data, method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            "X-Title": "rmsync",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                reply = json.load(r)
            if "error" in reply:
                raise OcrError(f"{model}: {reply['error'].get('message', reply['error'])}")
            content = reply["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            return parse_reply(_extract_json(content or ""))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            last = OcrError(f"{model}: HTTP {e.code} {detail}")
            if e.code in (400, 401, 402, 403, 404):
                raise last
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = OcrError(f"{model}: {e}")
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as e:
            last = OcrError(f"{model}: unexpected reply ({e})")
        time.sleep(2 * (attempt + 1))
    raise last or OcrError("failed")
