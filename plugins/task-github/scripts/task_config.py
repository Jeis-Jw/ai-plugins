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

TOP_KEYS = {"mode", "base_branch", "planning-tool", "verify-tool", "review-tool", "orchestrate", "define"}
ORCH_KEYS = {"verify-command", "review-mode", "review-command", "gear-options", "max-workers"}
DEFINE_KEYS = {"review-tool", "review-command", "review-required"}
GEARS = {"micro", "normal", "major"}
GEAR_OPTION_KEYS = {"plan", "verify", "pr-review"}
REVIEW_MODES = {"gear", "all", "skip"}
MODES = {"solo", "team"}
MAPPING_KEYS = {"orchestrate", "define", "gear-options", *GEARS}


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
    if value.lower() in {"true", "yes", "on"}:
        return True
    if value.lower() in {"false", "no", "off"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_config(text: str) -> dict[str, Any]:
    config: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, config)]
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if ":" not in line:
            raise ValueError(f"invalid config line: {raw_line}")
        key, raw_value = line.strip().split(":", 1)
        while indent <= stack[-1][0]:
            stack.pop()
        if indent > 0 and stack[-1][0] < 0:
            raise ValueError(f"invalid indentation: {raw_line}")
        parent = stack[-1][1]
        if raw_value.strip() == "" and key in MAPPING_KEYS:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_value(raw_value)
    config.setdefault("orchestrate", {})
    return config


def _finding(code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _valid_bool(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return True
    return str(value).strip().lower() in {"1", "0", "true", "false", "yes", "no", "on", "off", "o", "x"}


def _valid_positive_int(value: Any) -> bool:
    if value is None or value == "":
        return True
    try:
        return int(str(value).strip()) > 0
    except ValueError:
        return False


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
    gear_options = orchestrate.get("gear-options", {})
    if gear_options is not None and not isinstance(gear_options, dict):
        findings.append(_finding("bad_orchestrate_gear_options", "orchestrate.gear-options must be a mapping"))
    elif isinstance(gear_options, dict):
        for gear, options in gear_options.items():
            if gear not in GEARS:
                findings.append(_finding("unknown_orchestrate_gear", f"unknown orchestrate gear: {gear}", "warning"))
                continue
            if not isinstance(options, dict):
                findings.append(_finding("bad_orchestrate_gear", f"orchestrate.gear-options.{gear} must be a mapping"))
                continue
            for option, value in options.items():
                if option not in GEAR_OPTION_KEYS:
                    findings.append(_finding("unknown_orchestrate_gear_option", f"unknown gear option: {gear}.{option}", "warning"))
                elif not _valid_bool(value):
                    findings.append(_finding("bad_orchestrate_gear_option", f"{gear}.{option} must be boolean/o/x"))
    if not _valid_positive_int(orchestrate.get("max-workers")):
        findings.append(_finding("bad_orchestrate_max_workers", "orchestrate.max-workers must be a positive integer"))
    if orchestrate.get("verify-command") and not config.get("verify-tool"):
        findings.append(_finding("verify_tool_required", "orchestrate.verify-command requires verify-tool"))
    if orchestrate.get("review-command") and not config.get("review-tool"):
        findings.append(_finding("review_tool_required", "orchestrate.review-command requires review-tool"))

    define = config.get("define")
    if define is not None:
        if not isinstance(define, dict):
            findings.append(_finding("bad_define", "define must be a mapping"))
        else:
            for key in sorted(set(define) - DEFINE_KEYS):
                findings.append(_finding("unknown_define_key", f"unknown define key: {key}", "warning"))
            if define.get("review-command") and not define.get("review-tool"):
                findings.append(_finding("define_review_tool_required", "define.review-command requires define.review-tool"))
            if not _valid_bool(define.get("review-required")):
                findings.append(_finding("bad_define_review_required", "define.review-required must be a boolean"))
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
        "  max-workers:\n"
        "  gear-options:\n"
        "    micro:\n"
        "      plan: false\n"
        "      verify: true\n"
        "      pr-review: false\n"
        "    normal:\n"
        "      plan: true\n"
        "      verify: true\n"
        "      pr-review: false\n"
        "    major:\n"
        "      plan: true\n"
        "      verify: true\n"
        "      pr-review: true\n"
        "define:\n"
        "  review-tool:\n"       # 비면 --review 시 내장 challenge(harness). 지정하면 그 도구로 relay.
        "  review-command:\n"
        "  review-required: false\n"  # true면 create_issue_tree.py가 challenge_review.verdict==approved 없이는 이슈 생성을 거부한다.
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
    p_get = sub.add_parser("get")
    p_get.add_argument("key", help="top-level or dotted key, e.g. base_branch / orchestrate.review-mode")
    p_get.add_argument("--path", default=".task-github.yml")
    args = parser.parse_args(argv)

    if args.cmd == "get":
        # Prints the value (exit 0) or nothing (exit 1 — absent file/key/empty).
        # Lets shell snippets prefer config base_branch without inferring the repo default.
        try:
            node: Any = load_config(args.path)
        except OSError:
            return 1
        for part in args.key.split("."):
            if not isinstance(node, dict) or part not in node:
                return 1
            node = node[part]
        if node is None or node == "":
            return 1
        print(node)
        return 0

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
