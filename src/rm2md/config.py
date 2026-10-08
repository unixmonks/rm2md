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

# Handwriting recognition through OpenRouter.
model = "google/gemini-3.8-flash"
# How much the model thinks: "low" is ~$0.002 and ~4 s a page; "" uses the model's default
# (~$0.008 and ~20 s with gemini-3.8-flash), "high" for very hard handwriting.
reasoning = "low"
# The key is read from $OPENROUTER_API_KEY, or else from this file.
api_key_file = "{key_file}"

# Taskwarrior
tasks = true
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
    model: str = "google/gemini-3.8-flash"
    reasoning: str = "low"
    api_key_file: Path = _xdg("XDG_CONFIG_HOME", ".config") / "rm2md" / "openrouter_key"
    tasks: bool = True
    task_tags: list[str] = field(default_factory=lambda: ["remarkable"])
    task_project: str = ""
    task_sync: bool = False
    xochitl_dir: str = "/home/root/.local/share/remarkable/xochitl"
    state_dir: Path = _xdg("XDG_STATE_HOME", ".local/state") / "rm2md"
    cache_dir: Path = _xdg("XDG_CACHE_HOME", ".cache") / "rm2md"

    def api_key(self) -> str | None:
        if key := os.environ.get("OPENROUTER_API_KEY"):
            return key.strip()
        try:
            return self.api_key_file.read_text().strip() or None
        except OSError:
            return None


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


def write_template(path: Path, host: str, folder: str, notes_dir: str, key_file: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(host=host, folder=folder, notes_dir=notes_dir, key_file=key_file))
