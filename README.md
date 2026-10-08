# rmsync

Syncs one folder of reMarkable notebooks to this computer over SSH (Wi-Fi or USB):

- each notebook becomes a Markdown file, transcribed from your handwriting by a vision model
  (OpenRouter, `google/gemini-3.8-flash` by default), with a PNG of each page linked under its text;
- task lines become Taskwarrior tasks. Ticking the box later completes the task.

Only pages that changed since the last sync are sent to the model. Typed text (keyboard) is read
straight from the page file, so typed-only pages cost nothing.

## Writing tasks

A line is a task when it starts with a **hand-drawn box** (□), or with `TODO`, `todo:` or `[ ]`,
or when it is listed under a `TODO` / `Tasks` heading. Other bullet points are notes, not tasks. On a task line you can add:

| write                                | becomes                          |
|--------------------------------------|----------------------------------|
| ☑ (tick, cross, fill, strike-through) | completed                       |
| `#word` or `+word`                   | tag                              |
| `@word`, `pro:word`                  | project                          |
| `due fri`, `by 10/15`, `→ mon`       | due date (month/day)             |
| `!` · `(A)` / `(B)` / `(C)`          | priority H · H / M / L           |

Every task also gets the tags in `task_tags` (default `+remarkable`) and an annotation naming the
notebook and page. rmsync never edits or deletes tasks: a task you delete in Taskwarrior is not
created again, and editing its text on the page does not create a duplicate (similar lines match).

## Setup

1. On the tablet, find the IP and root password under *Settings → Help → Copyrights and licenses*.
   SSH over Wi-Fi must be on; on recent firmware that may need `rm-ssh-over-wlan on`, run over USB SSH.
2. Install your key: `ssh-copy-id root@<ip>`. rmsync runs ssh in batch mode, so the key must work
   without a password prompt (no passphrase, or loaded in ssh-agent).
3. Install and configure:

   ```sh
   uv tool install -e ~/projects/unixmonks/rmsync
   rmsync init --host root@<ip> --folder "Inbox"     # writes ~/.config/rmsync/config.toml, tests it
   rmsync folders                                     # if you are unsure of the folder name
   rmsync sync -n                                     # preview: transcribes, writes nothing
   rmsync sync
   ```

The OpenRouter key is read from `$OPENROUTER_API_KEY` or `~/.config/rmsync/openrouter_key`.
Give the tablet a fixed IP in your router so the host setting stays valid.

## Running it regularly

`rmsync watch` syncs every 5 minutes and stays quiet while the tablet is asleep or away.
Or with cron (`crontab -e`):

```
*/10 * * * * $HOME/.local/bin/rmsync sync -q >> $HOME/.local/state/rmsync/cron.log 2>&1
```

xochitl writes a notebook's pages when you close it, so close the notebook (or go back to the
library) to get your latest strokes into the next sync.

## Commands

```
rmsync init [--host H] [--folder F] [--notes-dir D] [--force]
rmsync check                 connection + folder
rmsync folders               folders on the tablet, with notebook counts
rmsync sync [-n] [--full] [--notebook NAME] [--no-tasks] [-q]
rmsync watch [--interval S]
rmsync status                notebooks, pages and tasks synced so far
```

Exit codes for `sync`: 0 ok, 1 some pages failed (retried next sync) or bad folder, 2 tablet unreachable.

## Files

- `~/.config/rmsync/config.toml`: settings (see the comments in it)
- `~/notes/remarkable/<Notebook>.md`, `assets/<Notebook>/<page-id>.png`: output; subfolders of
  the synced folder become subfolders. The `.md` is rewritten on each sync, so don't edit it there.
- `~/.local/state/rmsync/state.json`: page hashes, transcriptions, tasks created
- `~/.cache/rmsync/`: copy of the synced notebooks; transcriptions by page hash

Renaming or moving a notebook on the tablet moves its note. A notebook removed from the folder
keeps its note. PDFs and EPUBs in the folder are skipped.

## Tests

```sh
uv run pytest                      # units + full sync against a fake xochitl folder and a real `task`
tests/fake_tablet_ssh.sh           # over real SSH to a busybox/dropbear container (docker)
RMSYNC_LIVE=1 tests/fake_tablet_ssh.sh   # same, with the live model on synthetic handwriting
```
