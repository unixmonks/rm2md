"""Settings, read from ~/.config/rm2md/config.toml (override with RM2MD_CONFIG)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_PATH = Path(os.environ.get("RM2MD_CONFIG") or _xdg("XDG_CONFIG_HOME", ".config") / "rm2md" / "config.toml")

TEMPLATE = """\
# rm2md settings. See README.md.

# The tablet over SSH. Wi-Fi IP from Settings > Help > Copyrights and licenses,
# or root@10.11.99.1 over USB.
host = "{host}"
# Extra ssh options, e.g. ["-i", "~/.ssh/id_remarkable"].
ssh_options = []

# The folder on the tablet to sync, by name, or a path like "Work/Inbox".
folder = "{folder}"
# Include notebooks in subfolders (written into matching subfolders of notes_dir).
recursive = true

# Where the Markdown notes go. One .md per notebook.
notes_dir = "{notes_dir}"
# Save a PNG of each page next to the notes and link it under the page text.
page_images = true

# Handwriting recognition: any OpenAI-compatible API with a vision model. Examples:
#   OpenRouter  api_base = "https://openrouter.ai/api/v1"   model = "google/gemini-3.8-flash"
#   OpenAI      api_base = "https://api.openai.com/v1"      model = "gpt-5.6-luna"
#               api_key_env = "OPENAI_API_KEY"
#   Ollama      api_base = "http://localhost:11434/v1"      model = "qwen2.5vl:7b"
#   LM Studio   api_base = "http://localhost:1234/v1"       model = "qwen3.5-9b"
# Local servers need no key; give them a longer timeout.
api_base = "https://openrouter.ai/api/v1"
model = "google/gemini-3.8-flash"
# How much the model thinks: "low" is ~$0.002 and ~4 s a page with gemini-3.8-flash; ""
# sends nothing (the model's default), "high" for very hard handwriting. Ignored by models
# without the setting.
reasoning = "low"
# The key comes from $RM2MD_API_KEY, else from the variable named here, else from the file.
api_key_env = "OPENROUTER_API_KEY"
api_key_file = "{key_file}"
# Seconds to wait for the model on each page.
timeout = 120

# Taskwarrior (optional). With tasks = false rm2md only writes notes, and Taskwarrior
# need not be installed. Turning it on later: run `rm2md sync --full` once to add the
# tasks from notes already synced.
tasks = {tasks}
task_tags = ["remarkable"]
# Project for tasks that do not name one ("" for none).
task_project = ""
# Run `task sync` after adding or completing tasks.
task_sync = false
"""


@dataclass
class Config:
    host: str = "root@10.11.99.1"
    ssh_options: list[str] = field(default_factory=list)
    folder: str = "Inbox"
    recursive: bool = True
    notes_dir: Path = Path.home() / "notes" / "remarkable"
    page_images: bool = True
    api_base: str = "https://openrouter.ai/api/v1"
    model: str = "google/gemini-3.8-flash"
    reasoning: str = "low"
    api_key_env: str = "OPENROUTER_API_KEY"
    api_key_file: Path = _xdg("XDG_CONFIG_HOME", ".config") / "rm2md" / "api_key"
    timeout: int = 120
    tasks: bool = True
    task_tags: list[str] = field(default_factory=lambda: ["remarkable"])
    task_project: str = ""
    task_sync: bool = False
    xochitl_dir: str = "/home/root/.local/share/remarkable/xochitl"
    state_dir: Path = _xdg("XDG_STATE_HOME", ".local/state") / "rm2md"
    cache_dir: Path = _xdg("XDG_CACHE_HOME", ".cache") / "rm2md"

    def api_key(self) -> str | None:
        for var in ("RM2MD_API_KEY", self.api_key_env):
            if var and (key := os.environ.get(var, "").strip()):
                return key
        try:
            return self.api_key_file.read_text().strip() or None
        except OSError:
            return None

    def provider(self):
        from .ocr import Provider
        return Provider(model=self.model, base=self.api_base, key=self.api_key(), reasoning=self.reasoning,
                        timeout=self.timeout)


def _path(v: str) -> Path:
    return Path(os.path.expanduser(v))


def load(path: Path = CONFIG_PATH) -> Config:
    cfg = Config()
    if not path.exists():
        return cfg
    data = tomllib.loads(path.read_text())
    for key, value in data.items():
        if not hasattr(cfg, key):
            raise SystemExit(f"{path}: unknown setting {key!r}")
        if isinstance(getattr(cfg, key), Path):
            value = _path(value)
        setattr(cfg, key, value)
    cfg.ssh_options = [os.path.expanduser(o) for o in cfg.ssh_options]
    return cfg


def write_template(path: Path, host: str, folder: str, notes_dir: str, key_file: Path, tasks: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(host=host, folder=folder, notes_dir=notes_dir, key_file=key_file,
                                    tasks=str(tasks).lower()))
