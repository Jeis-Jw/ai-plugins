#!/usr/bin/env python3
"""Restricted task-github provider config with task-worker migration support.

`.task-github.yml` owns only GitHub projection and delivery mechanics. Generic
execution policy is read from the adjacent `.task-worker.yml`. Legacy combined
files remain readable for one compatibility window and emit deprecation
findings instead of silently becoming a second execution-policy source.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


PROVIDER_KEYS = {"base_branch", "projection", "closeout"}
PROJECTION_KEYS = {"record", "strict-deps", "state-root"}
CLOSEOUT_KEYS = {"branch-prefix", "delete-merged-branches"}
LEGACY_EXECUTION_KEYS = {
    "mode", "planning-tool", "verify-tool", "review-tool", "orchestrate", "define"
}
TOP_KEYS = PROVIDER_KEYS | LEGACY_EXECUTION_KEYS
MAPPING_KEYS = {"projection", "closeout", "orchestrate", "define", "gear-options", "micro", "normal", "major"}
RECORD_MODES = {"none", "github"}


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
    config.setdefault("projection", {})
    config.setdefault("closeout", {})
    return config


def _finding(code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _validate_mapping(
    findings: list[dict[str, str]], value: Any, *, name: str, allowed: set[str]
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
        findings.append(_finding("unknown_key", f"unknown top-level key: {key}", "warning"))
    for key in sorted(set(config) & LEGACY_EXECUTION_KEYS):
        findings.append(_finding(
            "legacy_execution_config",
            f"{key} moved to .task-worker.yml; legacy value is read only as fallback",
            "warning",
        ))

    if not isinstance(config.get("base_branch"), str) or not config.get("base_branch", "").strip():
        findings.append(_finding("base_branch_required", "base_branch is required"))

    projection = _validate_mapping(
        findings, config.get("projection", {}), name="projection", allowed=PROJECTION_KEYS
    )
    if projection is not None:
        if projection.get("record", "github") not in RECORD_MODES:
            findings.append(_finding("bad_projection_record", "projection.record must be none or github"))
        if projection.get("strict-deps") not in (None, True, False):
            findings.append(_finding("bad_projection_strict_deps", "projection.strict-deps must be boolean"))
        state_root = projection.get("state-root", ".task-github/local/projections")
        if not isinstance(state_root, str) or not state_root.strip():
            findings.append(_finding("bad_projection_state_root", "projection.state-root must be a non-empty path"))

    closeout = _validate_mapping(
        findings, config.get("closeout", {}), name="closeout", allowed=CLOSEOUT_KEYS
    )
    if closeout is not None:
        prefix = closeout.get("branch-prefix", "task/issue-")
        if not isinstance(prefix, str) or not prefix.strip():
            findings.append(_finding("bad_closeout_branch_prefix", "closeout.branch-prefix must be a non-empty string"))
        if closeout.get("delete-merged-branches") not in (None, True, False):
            findings.append(_finding("bad_closeout_delete_branches", "closeout.delete-merged-branches must be boolean"))
    return findings


def render_default_config(*, base_branch: str = "main") -> str:
    return (
        f"base_branch: {base_branch}\n"
        "projection:\n"
        "  record: github\n"
        "  strict-deps: true\n"
        "  state-root: .task-github/local/projections\n"
        "closeout:\n"
        "  branch-prefix: task/issue-\n"
        "  delete-merged-branches: true\n"
    )


def load_config(path: str | Path = ".task-github.yml") -> dict[str, Any]:
    return parse_config(Path(path).read_text(encoding="utf-8"))


def worker_config_path(github_path: str | Path, explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    environment = os.environ.get("TASK_WORKER_CONFIG")
    if environment:
        return Path(environment)
    return Path(github_path).parent / ".task-worker.yml"


def _load_worker_module():
    explicit = os.environ.get("TASK_WORKER_ROOT")
    roots = [Path(explicit)] if explicit else [Path(__file__).resolve().parents[2] / "task-worker"]
    for root in roots:
        script = root / "scripts" / "task_config.py"
        if script.is_file():
            spec = importlib.util.spec_from_file_location("task_worker_task_config", script)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError("task-worker config reader is unavailable")


def load_worker_config(
    github_path: str | Path = ".task-github.yml", worker_path: str | Path | None = None
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """Load worker policy, falling back to legacy combined keys if necessary."""
    path = worker_config_path(github_path, worker_path)
    if path.is_file():
        module = _load_worker_module()
        config = module.load_config(path)
        return config, module.validate_config(config), str(path)

    provider = load_config(github_path)
    legacy = {key: provider[key] for key in LEGACY_EXECUTION_KEYS if key in provider}
    if legacy:
        module = _load_worker_module()
        legacy.setdefault("orchestrate", {})
        legacy.setdefault("define", {})
        legacy.setdefault("evidence", {})
        legacy.setdefault("recovery", {})
        return legacy, [
            *module.validate_config(legacy),
            _finding(
                "legacy_worker_config_fallback",
                ".task-worker.yml is missing; using execution keys from .task-github.yml",
                "warning",
            ),
        ], str(github_path)
    return {}, [_finding("worker_config_missing", ".task-worker.yml is required", "error")], str(path)


def _get(value: dict[str, Any], dotted: str) -> Any:
    node: Any = value
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--path", default=".task-github.yml")
    validate.add_argument("--worker-path")
    validate.add_argument("--json", action="store_true", dest="as_json")
    scaffold = sub.add_parser("scaffold")
    scaffold.add_argument("--path", default=".task-github.yml")
    scaffold.add_argument("--base-branch", default="main")
    scaffold.add_argument("--json", action="store_true", dest="as_json")
    get = sub.add_parser("get")
    get.add_argument("key")
    get.add_argument("--path", default=".task-github.yml")
    get.add_argument("--worker-path")
    args = parser.parse_args(argv)

    if args.cmd == "scaffold":
        path = Path(args.path)
        created = not path.exists()
        if created:
            path.write_text(render_default_config(base_branch=args.base_branch), encoding="utf-8")
        payload = {"ok": True, "created": created, "path": str(path)}
        print(json.dumps(payload, ensure_ascii=False) if args.as_json else payload)
        return 0

    if args.cmd == "get":
        try:
            provider = load_config(args.path)
            try:
                value = _get(provider, args.key)
            except KeyError:
                worker, findings, _ = load_worker_config(args.path, args.worker_path)
                if any(item["severity"] == "error" for item in findings):
                    return 1
                value = _get(worker, args.key)
        except (OSError, ValueError, KeyError):
            return 1
        if value in (None, ""):
            return 1
        print(value)
        return 0

    try:
        provider = load_config(args.path)
        worker, worker_findings, worker_source = load_worker_config(args.path, args.worker_path)
        findings = [*validate_config(provider), *worker_findings]
    except (OSError, ValueError) as exc:
        provider, worker, worker_source = None, None, None
        findings = [_finding("config_read_failed", str(exc))]
    payload = {
        "ok": not any(item["severity"] == "error" for item in findings),
        "config": provider,
        "worker_config": worker,
        "worker_config_source": worker_source,
        "findings": findings,
    }
    print(json.dumps(payload, ensure_ascii=False) if args.as_json else payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
