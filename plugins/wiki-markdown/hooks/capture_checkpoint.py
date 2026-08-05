#!/usr/bin/env python3
"""Stop-hook: gated capture-checkpoint reminder (knowledge-protocol §12.3).

Fires a single short "audit durable candidates" reminder at turn end, and only
when the session actually produced work outputs. Silent (0 bytes, 0 tokens) in
every other case. Gates, in order:

1. env kill-switch        WIKI_MARKDOWN_CHECKPOINT=off|0|false
2. stop_hook_active       loop guard — never block a continuation we caused
3. vault presence         <cwd>/wiki must exist (same resolution as wiki_cli)
4. linked git worktree    worker lanes are skipped; capture belongs to the
                          main session / closeout, not to each parallel lane
5. work threshold         >= MIN_EDITS file-edit tool uses, or >= 1 Bash
                          `git commit`, counted after the previous firing

Once fired, the transcript line count is stored per session so the hook only
re-fires after a NEW batch of work — "audit once per batch", not per turn.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

MARKER = "[wiki-markdown capture checkpoint]"
REMINDER = (
    MARKER + " Work outputs detected in this session. Do ONE audit pass from "
    "context you already have (no new recall, no file exploration): deduplicate "
    "durable candidates (decisions, rejected alternatives, lessons, design/policy "
    "changes) and either make one grouped capture proposal for user approval, or "
    "state 'no durable candidates' with a one-line reason. Then end the turn."
)

EDIT_RE = re.compile(r'"name"\s*:\s*"(?:Edit|MultiEdit|Write|NotebookEdit)"')
BASH_RE = re.compile(r'"name"\s*:\s*"Bash"')
DEFAULT_MIN_EDITS = 3


def state_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id or "unknown")
    return os.path.join(
        tempfile.gettempdir(), "wiki-markdown-checkpoint", f"{safe}.json"
    )


def load_fired_at_line(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return int(json.load(f).get("fired_at_line", 0))
    except Exception:
        return 0


def save_fired_at_line(path: str, line: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fired_at_line": line}, f)


def in_linked_worktree(cwd: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-dir", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return False
        git_dir, common_dir = out.stdout.splitlines()[:2]
        resolve = lambda p: os.path.realpath(os.path.join(cwd, p))
        return resolve(git_dir) != resolve(common_dir)
    except Exception:
        return False


def main() -> int:
    if os.environ.get("WIKI_MARKDOWN_CHECKPOINT", "").lower() in {"off", "0", "false"}:
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    if not os.path.isdir(os.path.join(cwd, "wiki")):
        return 0
    if in_linked_worktree(cwd):
        return 0
    transcript = payload.get("transcript_path")
    if not transcript or not os.path.isfile(transcript):
        return 0

    spath = state_path(payload.get("session_id", ""))
    start = load_fired_at_line(spath)
    try:
        min_edits = int(os.environ.get("WIKI_MARKDOWN_CHECKPOINT_MIN_EDITS", ""))
    except ValueError:
        min_edits = DEFAULT_MIN_EDITS
    if min_edits <= 0:
        min_edits = DEFAULT_MIN_EDITS

    edits = commits = total = 0
    try:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                total = i + 1
                if i < start:
                    continue
                if EDIT_RE.search(line):
                    edits += 1
                elif BASH_RE.search(line) and "git commit" in line:
                    commits += 1
    except OSError:
        return 0

    if edits < min_edits and commits < 1:
        return 0

    try:
        save_fired_at_line(spath, total)
    except OSError:
        return 0  # can't record the firing -> stay silent rather than risk a nag loop
    print(json.dumps({"decision": "block", "reason": REMINDER}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
