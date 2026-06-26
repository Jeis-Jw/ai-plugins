#!/usr/bin/env python3
"""Small `.task-github.yml` reader/writer for task-github.

This intentionally supports only the config shape task-github owns. It is not a
general YAML parser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOP_KEYS = {"mode", "base_branch", "planning-tool", "verify-tool", "review-tool", "orchestrate"}
ORCH_KEYS = {"verify-command", "review-mode", "review-command"}
REVIEW_MODES = {"gear", "all", "skip"}
MODES = {"solo", "team"}


def _strip_comment(line: str) -> str:
    quote = None
    out = []
    for ch in line:
        if ch in {"'", '"'}:
            quote = None if quote == ch else ch if quote is None else quote
        if ch == "#" and quote is None:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_value(raw: str) -> str | None:
    value = raw.strip()
    if value == "":
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_config(text: str) -> dict[str, Any]:
    config: dict[str, Any] = {"orchestrate": {}}
    section: str | None = None
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if ":" not in line:
            raise ValueError(f"invalid config line: {raw_line}")
        key, raw_value = line.strip().split(":", 1)
        if indent == 0:
            section = key if key == "orchestrate" and raw_value.strip() == "" else None
            config[key] = {} if section == key else _parse_value(raw_value)
        elif section == "orchestrate" and indent >= 2:
            config.setdefault("orchestrate", {})[key] = _parse_value(raw_value)
        else:
            raise ValueError(f"invalid indentation: {raw_line}")
    config.setdefault("orchestrate", {})
    return config


def _finding(code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def validate_config(config: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    unknown = sorted(set(config) - TOP_KEYS)
    for key in unknown:
        findings.append(_finding("unknown_key", f"unknown top-level key: {key}", "warning"))

    if config.get("mode") not in MODES:
        findings.append(_finding("bad_mode", "mode must be solo or team"))
    if not isinstance(config.get("base_branch"), str) or not config.get("base_branch", "").strip():
        findings.append(_finding("base_branch_required", "base_branch is required"))

    orchestrate = config.get("orchestrate")
    if not isinstance(orchestrate, dict):
        findings.append(_finding("bad_orchestrate", "orchestrate must be a mapping"))
        return findings
    for key in sorted(set(orchestrate) - ORCH_KEYS):
        findings.append(_finding("unknown_orchestrate_key", f"unknown orchestrate key: {key}", "warning"))
    if orchestrate.get("review-mode", "gear") not in REVIEW_MODES:
        findings.append(_finding("bad_orchestrate_review_mode", "orchestrate.review-mode must be gear, all, or skip"))
    if orchestrate.get("verify-command") and not config.get("verify-tool"):
        findings.append(_finding("verify_tool_required", "orchestrate.verify-command requires verify-tool"))
    if orchestrate.get("review-command") and not config.get("review-tool"):
        findings.append(_finding("review_tool_required", "orchestrate.review-command requires review-tool"))
    return findings


def render_default_config(*, base_branch: str = "main") -> str:
    return (
        "mode: solo\n"
        f"base_branch: {base_branch}\n"
        "planning-tool:\n"
        "verify-tool:\n"
        "review-tool:\n"
        "orchestrate:\n"
        "  verify-command:\n"
        "  review-mode: gear\n"
        "  review-command:\n"
    )


def load_config(path: str | Path = ".task-github.yml") -> dict[str, Any]:
    return parse_config(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--path", default=".task-github.yml")
    p_validate.add_argument("--json", action="store_true", dest="as_json")
    p_scaffold = sub.add_parser("scaffold")
    p_scaffold.add_argument("--path", default=".task-github.yml")
    p_scaffold.add_argument("--base-branch", default="main")
    p_scaffold.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.cmd == "scaffold":
        path = Path(args.path)
        if path.exists():
            payload = {"ok": True, "created": False, "path": str(path)}
        else:
            path.write_text(render_default_config(base_branch=args.base_branch), encoding="utf-8")
            payload = {"ok": True, "created": True, "path": str(path)}
        print(json.dumps(payload, ensure_ascii=False) if args.as_json else payload)
        return 0

    try:
        config = load_config(args.path)
        findings = validate_config(config)
    except (OSError, ValueError) as exc:
        findings = [_finding("config_read_failed", str(exc))]
        config = None
    payload = {"ok": not any(f["severity"] == "error" for f in findings), "config": config, "findings": findings}
    print(json.dumps(payload, ensure_ascii=False) if args.as_json else payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
