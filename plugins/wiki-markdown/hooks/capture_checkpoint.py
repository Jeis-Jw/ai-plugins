#!/usr/bin/env python3
"""Gated capture-checkpoint reminder (knowledge-protocol §12.3).

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

Claude Code counts work from its transcript at Stop. Codex records stable
PostToolUse events first because its transcript format is explicitly unstable,
then consumes those events at Stop. Once fired, a per-session cursor ensures the
hook only re-fires after a NEW batch of work — "audit once per batch", not per
turn.
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
CODEX_EDIT_TOOLS = {"apply_patch", "Edit", "Write", "NotebookEdit"}


def state_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id or "unknown")
    return os.path.join(
        tempfile.gettempdir(), "wiki-markdown-checkpoint", f"{safe}.json"
    )


def event_path(session_id: str) -> str:
    path = state_path(session_id)
    return path[:-5] + ".events"


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
            return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def state_int(state: dict, key: str) -> int:
    try:
        return max(0, int(state.get(key, 0)))
    except (TypeError, ValueError):
        return 0


def append_codex_event(path: str, kind: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (kind + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def read_codex_events(path: str) -> list:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.strip() for line in f if line.strip() in {"edit", "commit"}]
    except OSError:
        return []


def codex_work_kind(payload: dict):
    tool_name = payload.get("tool_name")
    if tool_name in CODEX_EDIT_TOOLS:
        return "edit"
    if tool_name != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str):
        command = json.dumps(command, ensure_ascii=False)
    return "commit" if "git commit" in command else None


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

    session_id = payload.get("session_id", "")
    spath = state_path(session_id)
    if payload.get("hook_event_name") == "PostToolUse":
        kind = codex_work_kind(payload)
        if not kind:
            return 0
        try:
            append_codex_event(event_path(session_id), kind)
        except OSError:
            pass
        return 0

    state = load_state(spath)
    is_codex = bool(payload.get("turn_id"))
    edits = commits = total = 0

    if is_codex:
        events = read_codex_events(event_path(session_id))
        start = state_int(state, "codex_fired_at_event")
        batch = events[start:]
        edits = batch.count("edit")
        commits = batch.count("commit")
        total = len(events)
    else:
        transcript = payload.get("transcript_path")
        if not transcript or not os.path.isfile(transcript):
            return 0
        start = state_int(state, "fired_at_line")
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
    try:
        min_edits = int(os.environ.get("WIKI_MARKDOWN_CHECKPOINT_MIN_EDITS", ""))
    except ValueError:
        min_edits = DEFAULT_MIN_EDITS
    if min_edits <= 0:
        min_edits = DEFAULT_MIN_EDITS

    if edits < min_edits and commits < 1:
        return 0

    try:
        if is_codex:
            state["codex_fired_at_event"] = total
        else:
            state["fired_at_line"] = total
        save_state(spath, state)
    except OSError:
        return 0  # can't record the firing -> stay silent rather than risk a nag loop
    print(json.dumps({"decision": "block", "reason": REMINDER}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
