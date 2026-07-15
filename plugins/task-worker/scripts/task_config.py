#!/usr/bin/env python3
"""Restricted `.task-worker.yml` reader/writer.

The worker config owns provider-neutral execution policy. Provider adapters must
consume this contract instead of copying planner, review, or evidence settings
into their own configuration files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
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
    "cleanup",
}
ORCH_KEYS = {"verify-command", "review-mode", "review-command", "gear-options", "max-workers"}
DEFINE_KEYS = {"review-tool", "review-command", "review-required"}
EVIDENCE_KEYS = {"reuse", "duplicate-guard", "token-coverage-required", "max-physical-runs"}
RECOVERY_KEYS = {"lease-ttl-seconds"}
CLEANUP_KEYS = {
    "remove-merged-worktrees",
    "delete-merged-local-branches",
    "prune-stale-worktrees",
}
GEARS = {"micro", "normal", "major"}
GEAR_OPTION_KEYS = {"plan", "verify", "pr-review"}
REVIEW_MODES = {"gear", "all", "skip"}
MODES = {"solo", "team"}
DISPATCH_MODES = {"worker", "manual"}
DELIVERY_MODES = {"local-ff", "external"}
PROVIDER_ONLY_KEYS = {"base_branch", "projection", "closeout", "repository", "labels"}
MAPPING_KEYS = {"orchestrate", "define", "evidence", "recovery", "cleanup", "gear-options", *GEARS}
PRESETS = {"local", "manual", "quality", "minimal"}
LOCAL_STATE_IGNORE = ".task-worker/local/"
COMMAND_PROFILES_PATH = ".task-worker/commands.json"
IMPACT_RULES_PATH = ".task-worker/impact-rules.json"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_command_profiles_todo() -> str:
    return _json_text({
        "schema": "task-worker.command-profile-set/v1",
        "status": "todo",
        "instructions": "Define project-specific immutable command profiles before policy execution.",
        "profiles": [],
    })


def render_impact_rules_todo() -> str:
    return _json_text({
        "schema": "impact-rule-set/v1",
        "status": "todo",
        "instructions": "Map project paths to explicit QA modes and command profile ids before policy execution.",
        "rules": [],
    })


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
    config.setdefault("cleanup", {})
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
    cleanup = _validate_mapping_keys(findings, config.get("cleanup", {}), name="cleanup", allowed=CLEANUP_KEYS)
    if cleanup is not None:
        for key in CLEANUP_KEYS:
            if cleanup.get(key) not in (None, True, False):
                findings.append(_finding(f"bad_cleanup_{key}", f"cleanup.{key} must be boolean"))
    return findings


def render_preset_config(preset: str) -> str:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset}")
    dispatch = "manual" if preset == "manual" else "worker"
    delivery = "external" if preset == "manual" else "local-ff"
    command_profiles = "" if preset == "minimal" else COMMAND_PROFILES_PATH
    impact_rules = "" if preset == "minimal" else IMPACT_RULES_PATH
    token_coverage_required = "true" if preset == "quality" else "false"
    return (
        "mode: solo\n"
        "state-root: .task-worker/local\n"
        f"dispatch: {dispatch}\n"
        f"delivery: {delivery}\n"
        "planning-tool:\n"
        "verify-tool:\n"
        "review-tool:\n"
        f"command-profiles: {command_profiles}\n"
        f"impact-rules: {impact_rules}\n"
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
        f"  token-coverage-required: {token_coverage_required}\n"
        "  max-physical-runs: 3\n"
        "recovery:\n"
        "  lease-ttl-seconds: 3600\n"
        "cleanup:\n"
        "  remove-merged-worktrees: true\n"
        "  delete-merged-local-branches: true\n"
        "  prune-stale-worktrees: true\n"
    )


def render_default_config() -> str:
    # Keep the legacy config-only scaffold free of dangling policy references.
    # The new init command owns policy skeleton creation for non-minimal presets.
    return render_preset_config("minimal")


def load_config(path: str | Path = ".task-worker.yml") -> dict[str, Any]:
    return parse_config(Path(path).read_text(encoding="utf-8"))


def _get(config: dict[str, Any], dotted: str) -> Any:
    value: Any = config
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _display_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    return relative.as_posix() or "."


def _gitignore_with_local_state(current: str) -> str:
    lines = current.splitlines()
    if LOCAL_STATE_IGNORE in lines:
        return current
    prefix = current
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + LOCAL_STATE_IGNORE + "\n"


def _file_action(path: Path, expected: str, *, force: bool) -> str:
    if not path.exists():
        return "create"
    if not path.is_file():
        return "conflict"
    if path.read_text(encoding="utf-8") == expected:
        return "skip"
    return "update" if force else "conflict"


def _path_type_conflict(path: Path, *, expected: str, root: Path) -> dict[str, str] | None:
    if path.exists():
        valid = path.is_file() if expected == "file" else path.is_dir()
        if valid:
            return None
        return {
            "path": _display_path(path, root),
            "expected": expected,
            "actual": "directory" if path.is_dir() else "non-directory",
            "reason": "wrong_path_type",
        }

    parent = path.parent
    while parent != parent.parent:
        if parent.exists():
            if not parent.is_dir():
                return {
                    "path": _display_path(path, root),
                    "blocking_path": _display_path(parent, root),
                    "expected": expected,
                    "actual": "blocked_by_non_directory_parent",
                    "reason": "wrong_path_type",
                }
            break
        parent = parent.parent
    return None


def _init_payload(root: Path, *, preset: str, force: bool, dry_run: bool) -> tuple[dict[str, Any], int]:
    root = root.expanduser().resolve()
    config_text = render_preset_config(preset)
    config = parse_config(config_text)
    config_findings = validate_config(config)
    config_errors = [item for item in config_findings if item["severity"] == "error"]
    validation = {
        "config": "fail" if config_errors else "pass",
        "command_profiles": "disabled" if preset == "minimal" else "todo",
        "impact_rules": "disabled" if preset == "minimal" else "todo",
    }
    config_path = root / ".task-worker.yml"
    state_path = root / ".task-worker" / "local"
    gitignore_path = root / ".gitignore"
    expected_files: list[tuple[Path, str]] = [(config_path, config_text)]
    if preset != "minimal":
        expected_files.extend((
            (root / COMMAND_PROFILES_PATH, render_command_profiles_todo()),
            (root / IMPACT_RULES_PATH, render_impact_rules_todo()),
        ))

    type_conflicts = [
        conflict
        for conflict in (
            *(
                _path_type_conflict(path, expected="file", root=root)
                for path, _ in expected_files
            ),
            _path_type_conflict(state_path, expected="directory", root=root),
            _path_type_conflict(gitignore_path, expected="file", root=root),
        )
        if conflict is not None
    ]
    blocked_paths = {conflict["path"] for conflict in type_conflicts}
    results = [
        {
            "path": _display_path(path, root),
            "action": (
                "conflict"
                if _display_path(path, root) in blocked_paths
                else _file_action(path, content, force=force)
            ),
        }
        for path, content in expected_files
    ]
    if _display_path(state_path, root) in blocked_paths:
        state_action = "conflict"
    else:
        state_action = "skip" if state_path.is_dir() else "create"
    results.append({"path": _display_path(state_path, root), "action": state_action})

    current_ignore = gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    desired_ignore = _gitignore_with_local_state(current_ignore)
    if _display_path(gitignore_path, root) in blocked_paths:
        ignore_action = "conflict"
    elif desired_ignore == current_ignore:
        ignore_action = "skip"
    else:
        ignore_action = "update" if gitignore_path.exists() else "create"
    results.append({"path": _display_path(gitignore_path, root), "action": ignore_action})

    conflicts = [item["path"] for item in results if item["action"] == "conflict"]
    paths = [item["path"] for item in results]
    if config_errors:
        return ({
            "ok": False,
            "plugin": "task-worker",
            "action": "init",
            "preset": preset,
            "changed": False,
            "paths": paths,
            "results": results,
            "validation": validation,
            "dry_run": dry_run,
            "error_code": "generated_config_invalid",
            "findings": config_findings,
        }, 2)
    if conflicts:
        return ({
            "ok": False,
            "plugin": "task-worker",
            "action": "init",
            "preset": preset,
            "changed": False,
            "paths": paths,
            "results": results,
            "validation": validation,
            "dry_run": dry_run,
            "error_code": "path_conflict",
            "conflicts": conflicts,
            "conflict_details": type_conflicts,
        }, 2)

    changed = any(item["action"] in {"create", "update"} for item in results)
    if not dry_run:
        for path, content in expected_files:
            if _file_action(path, content, force=force) in {"create", "update"}:
                _atomic_write(path, content)
        state_path.mkdir(parents=True, exist_ok=True)
        if desired_ignore != current_ignore:
            _atomic_write(gitignore_path, desired_ignore)
    return ({
        "ok": True,
        "plugin": "task-worker",
        "action": "init",
        "preset": preset,
        "changed": changed,
        "paths": paths,
        "results": results,
        "validation": validation,
        "dry_run": dry_run,
    }, 0)


def _load_execution_control():
    path = Path(__file__).with_name("execution_control.py")
    spec = importlib.util.spec_from_file_location("task_worker_execution_control_doctor", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery failure
        raise ImportError(f"cannot load execution control: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy_check(root: Path, configured: Any, *, kind: str) -> dict[str, Any]:
    if configured in (None, ""):
        return {"name": kind, "status": "disabled", "ready": True, "path": None}
    path = Path(str(configured))
    resolved = path if path.is_absolute() else root / path
    display = _display_path(resolved, root)
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"name": kind, "status": "missing", "ready": False, "path": display}
    except (OSError, json.JSONDecodeError) as exc:
        return {"name": kind, "status": "invalid", "ready": False, "path": display, "message": str(exc)}
    collection = raw.get("profiles" if kind == "command_profiles" else "rules") if isinstance(raw, dict) else raw
    if isinstance(raw, dict) and raw.get("status") == "todo" and collection == []:
        return {"name": kind, "status": "todo", "ready": False, "path": display}
    try:
        control = _load_execution_control()
        if kind == "command_profiles":
            control.load_command_profiles(resolved)
        else:
            control.load_impact_rules(resolved)
    except Exception as exc:  # execution_control exposes a plugin-local typed error
        return {"name": kind, "status": "invalid", "ready": False, "path": display, "message": str(exc)}
    return {"name": kind, "status": "pass", "ready": True, "path": display}


def _doctor_payload(root: Path) -> tuple[dict[str, Any], int]:
    root = root.expanduser().resolve()
    config_path = root / ".task-worker.yml"
    paths = [_display_path(config_path, root)]
    try:
        config = load_config(config_path)
    except (OSError, ValueError) as exc:
        return ({
            "ok": False,
            "plugin": "task-worker",
            "action": "doctor",
            "changed": False,
            "paths": paths,
            "validation": {"config": "fail", "state_root": "unknown", "command_profiles": "unknown", "impact_rules": "unknown"},
            "dry_run": False,
            "ready": False,
            "findings": [{"code": "config_unavailable", "severity": "error", "message": str(exc)}],
        }, 2)

    config_findings = validate_config(config)
    errors = [item for item in config_findings if item["severity"] == "error"]
    state_root = Path(config.get("state-root", ".task-worker/local"))
    state_path = state_root if state_root.is_absolute() else root / state_root
    state_ready = state_path.is_dir()
    state_status = "pass" if state_ready else "missing" if not state_path.exists() else "not_directory"
    command_check = _policy_check(root, config.get("command-profiles"), kind="command_profiles")
    impact_check = _policy_check(root, config.get("impact-rules"), kind="impact_rules")
    checks = [command_check, impact_check]
    paths.extend(
        item for item in (
            _display_path(state_path, root), command_check.get("path"), impact_check.get("path")
        ) if item is not None and item not in paths
    )
    ready = not errors and state_ready and all(item["ready"] for item in checks)
    findings = list(config_findings)
    if not state_ready:
        findings.append({"code": "state_root_not_ready", "severity": "error", "message": f"state-root is {state_status}: {_display_path(state_path, root)}"})
    for item in checks:
        if not item["ready"]:
            severity = "warning" if item["status"] == "todo" else "error"
            findings.append({
                "code": f"{item['name']}_{item['status']}",
                "severity": severity,
                "message": item.get("message") or f"{item['name']} is {item['status']}",
            })
    has_errors = any(item["severity"] == "error" for item in findings)
    payload = {
        "ok": not has_errors,
        "plugin": "task-worker",
        "action": "doctor",
        "changed": False,
        "paths": paths,
        "validation": {
            "config": "fail" if errors else "pass",
            "state_root": state_status,
            "command_profiles": command_check["status"],
            "impact_rules": impact_check["status"],
        },
        "dry_run": False,
        "ready": ready,
        "findings": findings,
    }
    return payload, 2 if has_errors else 0 if ready else 1


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    status = "ready" if payload.get("ready", payload.get("ok")) else "not ready"
    print(f"task-worker {payload['action']}: {status}")
    for result in payload.get("results", []):
        print(f"- {result['action']}: {result['path']}")
    for finding in payload.get("findings", []):
        print(f"- {finding['severity']}: {finding['code']}: {finding['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--root", default=".")
    init.add_argument("--preset", choices=sorted(PRESETS), default="local")
    init.add_argument("--force", action="store_true")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--json", action="store_true", dest="as_json")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--root", default=".")
    doctor.add_argument("--json", action="store_true", dest="as_json")
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

    if args.command == "init":
        payload, exit_code = _init_payload(
            Path(args.root), preset=args.preset, force=args.force, dry_run=args.dry_run
        )
        _print_payload(payload, as_json=args.as_json)
        return exit_code
    if args.command == "doctor":
        payload, exit_code = _doctor_payload(Path(args.root))
        _print_payload(payload, as_json=args.as_json)
        return exit_code
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
