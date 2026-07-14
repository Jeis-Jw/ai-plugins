#!/usr/bin/env python3
"""Restricted `.task-worker.yml` reader/writer.

The worker config owns provider-neutral execution policy. Provider adapters must
consume this contract instead of copying planner, review, or evidence settings
into their own configuration files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TOP_KEYS = {
    "mode",
    "state-root",
    "dispatch",
    "delivery",
    "planning-tool",
    "verify-tool",
    "review-tool",
    "command-profiles",
    "impact-rules",
    "orchestrate",
    "define",
    "evidence",
    "recovery",
}
ORCH_KEYS = {"verify-command", "review-mode", "review-command", "gear-options", "max-workers"}
DEFINE_KEYS = {"review-tool", "review-command", "review-required"}
EVIDENCE_KEYS = {"reuse", "duplicate-guard", "token-coverage-required", "max-physical-runs"}
RECOVERY_KEYS = {"lease-ttl-seconds"}
GEARS = {"micro", "normal", "major"}
GEAR_OPTION_KEYS = {"plan", "verify", "pr-review"}
REVIEW_MODES = {"gear", "all", "skip"}
MODES = {"solo", "team"}
DISPATCH_MODES = {"worker", "manual"}
DELIVERY_MODES = {"local-ff", "external"}
PROVIDER_ONLY_KEYS = {"base_branch", "projection", "closeout", "repository", "labels"}
MAPPING_KEYS = {"orchestrate", "define", "evidence", "recovery", "gear-options", *GEARS}


def _strip_comment(line: str) -> str:
    quote = None
    out = []
    for char in line:
        if char in {"'", '"'}:
            quote = None if quote == char else char if quote is None else quote
        if char == "#" and quote is None:
            break
        out.append(char)
    return "".join(out).rstrip()


def _parse_value(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return None
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
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
    config.setdefault("define", {})
    config.setdefault("evidence", {})
    config.setdefault("recovery", {})
    return config


def _finding(code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _positive_int(value: Any, *, allow_none: bool = True) -> bool:
    if value in (None, ""):
        return allow_none
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_mapping_keys(
    findings: list[dict[str, str]],
    value: Any,
    *,
    name: str,
    allowed: set[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        findings.append(_finding(f"bad_{name}", f"{name} must be a mapping"))
        return None
    for key in sorted(set(value) - allowed):
        findings.append(_finding(f"unknown_{name}_key", f"unknown {name} key: {key}", "warning"))
    return value


def validate_config(config: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for key in sorted(set(config) - TOP_KEYS):
        if key in PROVIDER_ONLY_KEYS:
            findings.append(_finding("provider_key_forbidden", f"provider key belongs outside .task-worker.yml: {key}"))
        else:
            findings.append(_finding("unknown_key", f"unknown top-level key: {key}", "warning"))

    if config.get("mode", "solo") not in MODES:
        findings.append(_finding("bad_mode", "mode must be solo or team"))
    if config.get("dispatch", "worker") not in DISPATCH_MODES:
        findings.append(_finding("bad_dispatch", "dispatch must be worker or manual"))
    if config.get("delivery", "local-ff") not in DELIVERY_MODES:
        findings.append(_finding("bad_delivery", "delivery must be local-ff or external"))
    state_root = config.get("state-root", ".task-worker/local")
    if not isinstance(state_root, str) or not state_root.strip():
        findings.append(_finding("bad_state_root", "state-root must be a non-empty path"))
    for key in ("command-profiles", "impact-rules"):
        value = config.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            findings.append(_finding(f"bad_{key}", f"{key} must be a non-empty file path"))

    orchestrate = _validate_mapping_keys(
        findings, config.get("orchestrate", {}), name="orchestrate", allowed=ORCH_KEYS
    )
    if orchestrate is not None:
        if orchestrate.get("review-mode", "gear") not in REVIEW_MODES:
            findings.append(_finding("bad_orchestrate_review_mode", "orchestrate.review-mode must be gear, all, or skip"))
        if not _positive_int(orchestrate.get("max-workers")):
            findings.append(_finding("bad_orchestrate_max_workers", "orchestrate.max-workers must be a positive integer"))
        if orchestrate.get("verify-command") and not config.get("verify-tool"):
            findings.append(_finding("verify_tool_required", "orchestrate.verify-command requires verify-tool"))
        if orchestrate.get("review-command") and not config.get("review-tool"):
            findings.append(_finding("review_tool_required", "orchestrate.review-command requires review-tool"))
        gear_options = orchestrate.get("gear-options", {})
        if not isinstance(gear_options, dict):
            findings.append(_finding("bad_orchestrate_gear_options", "orchestrate.gear-options must be a mapping"))
        else:
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
                    elif not isinstance(value, bool):
                        findings.append(_finding("bad_orchestrate_gear_option", f"{gear}.{option} must be boolean"))

    define = _validate_mapping_keys(findings, config.get("define", {}), name="define", allowed=DEFINE_KEYS)
    if define is not None:
        if define.get("review-command") and not define.get("review-tool"):
            findings.append(_finding("define_review_tool_required", "define.review-command requires define.review-tool"))
        if define.get("review-required") not in (None, True, False):
            findings.append(_finding("bad_define_review_required", "define.review-required must be boolean"))

    evidence = _validate_mapping_keys(findings, config.get("evidence", {}), name="evidence", allowed=EVIDENCE_KEYS)
    if evidence is not None:
        for key in ("reuse", "duplicate-guard", "token-coverage-required"):
            if evidence.get(key) not in (None, True, False):
                findings.append(_finding(f"bad_evidence_{key}", f"evidence.{key} must be boolean"))
        if not _positive_int(evidence.get("max-physical-runs")):
            findings.append(_finding("bad_evidence_max_physical_runs", "evidence.max-physical-runs must be a positive integer"))

    recovery = _validate_mapping_keys(findings, config.get("recovery", {}), name="recovery", allowed=RECOVERY_KEYS)
    if recovery is not None and not _positive_int(recovery.get("lease-ttl-seconds")):
        findings.append(_finding("bad_recovery_lease_ttl", "recovery.lease-ttl-seconds must be a positive integer"))
    return findings


def render_default_config() -> str:
    return (
        "mode: solo\n"
        "state-root: .task-worker/local\n"
        "dispatch: worker\n"
        "delivery: local-ff\n"
        "planning-tool:\n"
        "verify-tool:\n"
        "review-tool:\n"
        "command-profiles:\n"
        "impact-rules:\n"
        "orchestrate:\n"
        "  verify-command:\n"
        "  review-mode: gear\n"
        "  review-command:\n"
        "  max-workers: 3\n"
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
        "  review-tool:\n"
        "  review-command:\n"
        "  review-required: false\n"
        "evidence:\n"
        "  reuse: true\n"
        "  duplicate-guard: true\n"
        "  token-coverage-required: false\n"
        "  max-physical-runs: 3\n"
        "recovery:\n"
        "  lease-ttl-seconds: 3600\n"
    )


def load_config(path: str | Path = ".task-worker.yml") -> dict[str, Any]:
    return parse_config(Path(path).read_text(encoding="utf-8"))


def _get(config: dict[str, Any], dotted: str) -> Any:
    value: Any = config
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--path", default=".task-worker.yml")
    validate.add_argument("--json", action="store_true", dest="as_json")
    scaffold = sub.add_parser("scaffold")
    scaffold.add_argument("--path", default=".task-worker.yml")
    scaffold.add_argument("--json", action="store_true", dest="as_json")
    get = sub.add_parser("get")
    get.add_argument("key")
    get.add_argument("--path", default=".task-worker.yml")
    args = parser.parse_args(argv)

    if args.command == "scaffold":
        path = Path(args.path)
        created = not path.exists()
        if created:
            path.write_text(render_default_config(), encoding="utf-8")
        payload = {"ok": True, "created": created, "path": str(path)}
    else:
        try:
            config = load_config(args.path)
        except (OSError, ValueError) as exc:
            payload = {"ok": False, "error_code": "config_invalid", "message": str(exc)}
            if args.command == "get":
                return 1
            print(json.dumps(payload, ensure_ascii=False))
            return 2
        if args.command == "get":
            try:
                value = _get(config, args.key)
            except KeyError:
                return 1
            if value in (None, ""):
                return 1
            if isinstance(value, bool):
                print("true" if value else "false")
            elif isinstance(value, (dict, list)):
                print(json.dumps(value, ensure_ascii=False))
            else:
                print(value)
            return 0
        findings = validate_config(config)
        payload = {
            "ok": not any(item["severity"] == "error" for item in findings),
            "path": str(args.path),
            "config": config,
            "findings": findings,
        }
        if not payload["ok"]:
            print(json.dumps(payload, ensure_ascii=False))
            return 2
    print(json.dumps(payload, ensure_ascii=False) if getattr(args, "as_json", False) else payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
