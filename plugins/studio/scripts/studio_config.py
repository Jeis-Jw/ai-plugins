#!/usr/bin/env python3
"""Resolve Studio spawn and optional execution routing without owning a runtime.

The CLI intentionally owns only small, read-only policy contracts:

    explicit override
      > providers.<provider>.roles.<role>
      > roles.<role>
      > providers.<provider>.defaults
      > defaults
      > host session inheritance

    explicit route override
      > execute.<work|review|delivery>
      > native/disabled

Model and effort identifiers are provider-owned strings.  This helper validates
their shape, not whether a particular host currently advertises them. Execution
commands are opaque skill/plugin identifiers, never shell strings.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


CONFIG_PATH_DEFAULT = ".studio.yml"
SUPPORTED_PROVIDERS = frozenset(("claude", "codex"))
EXECUTE_KINDS = frozenset(("delivery", "review", "work"))
EXECUTE_ACTIVATIONS = frozenset(("always", "auto", "never"))
WORK_REVIEW_FALLBACKS = frozenset(("native", "stop"))
DELIVERY_FALLBACKS = frozenset(("skip", "stop"))
WORK_DECISION_SCHEMA = "studio.work-route-decision/v1"
COMMAND_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
CREW_ROLES = frozenset(
    (
        "architect",
        "creator",
        "curator",
        "dev",
        "planner",
        "product-designer",
        "qa",
        "researcher",
        "reviewer",
        "strategist",
        "visual-designer",
    )
)


class ConfigError(ValueError):
    """A parse or validation failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, problems: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.code = code
        self.problems = problems or []


def emit(value: dict[str, Any], *, exit_code: int = 0) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    raise SystemExit(exit_code)


def _strip_comment(line: str) -> str:
    output: list[str] = []
    quote: str | None = None
    for char in line:
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            break
        output.append(char)
    return "".join(output).rstrip()


def _scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("null", "~", ""):
        return None
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        return value


def parse_yaml_subset(text: str) -> dict[str, Any]:
    """Parse the mapping/scalar YAML subset used by .studio.yml."""

    rows: list[tuple[int, str, str, int]] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent_surface = line[: len(line) - len(line.lstrip(" \t"))]
        if "\t" in indent_surface:
            raise ConfigError(
                "parse_error",
                f"line {line_number}: tab indentation is not allowed",
            )
        indent = len(line) - len(line.lstrip(" "))
        if ":" not in line:
            raise ConfigError(
                "parse_error",
                f"line {line_number}: expected key: value",
            )
        key, value = line.strip().split(":", 1)
        key = key.strip()
        if not key:
            raise ConfigError("parse_error", f"line {line_number}: key must not be empty")
        rows.append((indent, key, value.strip(), line_number))

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for index, (indent, key, value, line_number) in enumerate(rows):
        while indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigError("parse_error", f"line {line_number}: indentation underflow")
        parent = stack[-1][1]
        if key in parent:
            raise ConfigError("parse_error", f"line {line_number}: duplicate key {key!r}")
        next_indent = rows[index + 1][0] if index + 1 < len(rows) else None
        if value == "" and next_indent is not None and next_indent > indent:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(value)
    return root


def render_default_config() -> str:
    return """# .studio.yml — optional native subagent spawn and execution policy.
# Studio keeps no runtime or workflow state here.
# Unconfigured commands are not discovered or probed.
# Resolution, most to least specific:
#   explicit override > provider role > common role
#   > provider defaults > common defaults > host session inheritance.
# Model and effort identifiers belong to the selected provider.

execute:
  work:
    command:
    activation:
    fallback: native
  review:
    command:
    activation:
    fallback: native
  delivery:
    command:
    enabled: false
    fallback: skip

defaults:
  model:
  effort:

roles:
  architect:
    model:
    effort:
  dev:
    model:
    effort:
  qa:
    model:
    effort:
  reviewer:
    model:
    effort:

providers:
  codex:
    defaults:
      model:
      effort:
    roles:
      architect:
        model:
        effort:
      dev:
        model:
        effort:
      qa:
        model:
        effort:
      reviewer:
        model:
        effort:
  claude:
    defaults:
      model:
      effort:
    roles:
      architect:
        model:
        effort:
      dev:
        model:
        effort:
      qa:
        model:
        effort:
      reviewer:
        model:
        effort:
"""


def _problem(where: str, message: str) -> dict[str, str]:
    return {"severity": "error", "where": where, "message": message}


def validate_config(config: Any) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    if not isinstance(config, dict):
        return [_problem("config", "must be a mapping")]

    for key in sorted(set(config) - {"defaults", "execute", "roles", "providers"}):
        problems.append(_problem(key, "unknown top-level key"))

    def validate_command(value: Any, where: str) -> str | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not COMMAND_RE.fullmatch(value):
            problems.append(
                _problem(
                    where,
                    "command must be a lowercase opaque identifier, not a shell string",
                )
            )
            return None
        return value

    def validate_execute(value: Any) -> None:
        if not isinstance(value, dict):
            problems.append(_problem("execute", "must be a mapping"))
            return
        for kind in sorted(set(value) - EXECUTE_KINDS):
            problems.append(_problem(f"execute.{kind}", "unknown execute route"))
        for kind in ("work", "review"):
            if kind not in value:
                continue
            block = value[kind]
            where = f"execute.{kind}"
            if not isinstance(block, dict):
                problems.append(_problem(where, "must be a mapping"))
                continue
            for key in sorted(set(block) - {"activation", "command", "fallback"}):
                problems.append(_problem(f"{where}.{key}", "unknown execute route key"))
            command = validate_command(block.get("command"), f"{where}.command")
            activation = block.get("activation")
            fallback = block.get("fallback")
            if activation not in (None, "") and activation not in EXECUTE_ACTIVATIONS:
                problems.append(
                    _problem(
                        f"{where}.activation",
                        "activation must be auto, always, never, or null",
                    )
                )
            if fallback not in (None, "") and fallback not in WORK_REVIEW_FALLBACKS:
                problems.append(
                    _problem(f"{where}.fallback", "fallback must be native, stop, or null")
                )
            if activation in {"auto", "always"} and command is None:
                problems.append(
                    _problem(f"{where}.command", "active route requires a command")
                )

        if "delivery" in value:
            block = value["delivery"]
            where = "execute.delivery"
            if not isinstance(block, dict):
                problems.append(_problem(where, "must be a mapping"))
                return
            for key in sorted(set(block) - {"command", "enabled", "fallback"}):
                problems.append(_problem(f"{where}.{key}", "unknown execute route key"))
            command = validate_command(block.get("command"), f"{where}.command")
            enabled = block.get("enabled")
            fallback = block.get("fallback")
            if enabled is not None and not isinstance(enabled, bool):
                problems.append(_problem(f"{where}.enabled", "enabled must be boolean or null"))
            if fallback not in (None, "") and fallback not in DELIVERY_FALLBACKS:
                problems.append(
                    _problem(f"{where}.fallback", "fallback must be skip, stop, or null")
                )
            if enabled is True and command is None:
                problems.append(
                    _problem(f"{where}.command", "enabled delivery requires a command")
                )

    def validate_profile(value: Any, where: str) -> None:
        if not isinstance(value, dict):
            problems.append(_problem(where, "must be a mapping"))
            return
        for key in sorted(set(value) - {"model", "effort"}):
            problems.append(_problem(f"{where}.{key}", "unknown profile key"))
        for field in ("model", "effort"):
            item = value.get(field)
            if item in (None, ""):
                continue
            if not isinstance(item, str) or not item.strip():
                problems.append(
                    _problem(
                        f"{where}.{field}",
                        f"{field} must be a non-empty provider-owned string or null",
                    )
                )

    def validate_roles(value: Any, where: str) -> None:
        if not isinstance(value, dict):
            problems.append(_problem(where, "must be a mapping"))
            return
        for role, profile in value.items():
            if role not in CREW_ROLES:
                problems.append(_problem(f"{where}.{role}", "unknown Studio crew role"))
            validate_profile(profile, f"{where}.{role}")

    if "execute" in config:
        validate_execute(config["execute"])
    if "defaults" in config:
        validate_profile(config["defaults"], "defaults")
    if "roles" in config:
        validate_roles(config["roles"], "roles")

    providers = config.get("providers", {})
    if not isinstance(providers, dict):
        problems.append(_problem("providers", "must be a mapping"))
        return problems
    for provider, policy in providers.items():
        where = f"providers.{provider}"
        if provider not in SUPPORTED_PROVIDERS:
            problems.append(_problem(where, "unsupported Studio host provider"))
        if not isinstance(policy, dict):
            problems.append(_problem(where, "must be a mapping"))
            continue
        for key in sorted(set(policy) - {"defaults", "roles"}):
            problems.append(_problem(f"{where}.{key}", "unknown provider policy key"))
        if "defaults" in policy:
            validate_profile(policy["defaults"], f"{where}.defaults")
        if "roles" in policy:
            validate_roles(policy["roles"], f"{where}.roles")
    return problems


def _policy_value(block: Any, field: str) -> str | None:
    if not isinstance(block, dict):
        return None
    value = block.get(field)
    if value in (None, ""):
        return None
    return value


def resolve_profile(
    config: dict[str, Any],
    *,
    provider: str,
    role: str,
    model_override: str | None = None,
    effort_override: str | None = None,
) -> dict[str, Any]:
    provider_policy = (config.get("providers") or {}).get(provider, {})
    layers = (
        ("explicit-override", {"model": model_override, "effort": effort_override}),
        ("provider-role", (provider_policy.get("roles") or {}).get(role, {})),
        ("common-role", (config.get("roles") or {}).get(role, {})),
        ("provider-defaults", provider_policy.get("defaults") or {}),
        ("common-defaults", config.get("defaults") or {}),
    )
    resolved: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    for field in ("model", "effort"):
        for source, block in layers:
            value = _policy_value(block, field)
            if value is not None:
                resolved[field] = value
                sources[field] = source
                break
        else:
            resolved[field] = None
            sources[field] = "host-session-inherit"
    return {
        "provider": provider,
        "role": role,
        "model": resolved["model"],
        "effort": resolved["effort"],
        "sources": sources,
        "configured": any(resolved[field] is not None for field in ("model", "effort")),
    }


def resolve_execute_route(
    config: dict[str, Any],
    *,
    kind: str,
    command_override: str | None = None,
    activation_override: str | None = None,
    fallback_override: str | None = None,
    enabled_override: bool | None = None,
) -> dict[str, Any]:
    if kind not in EXECUTE_KINDS:
        raise ConfigError("invalid_route", f"unsupported execute route {kind!r}")
    block = ((config.get("execute") or {}).get(kind) or {})
    command = command_override or _policy_value(block, "command")
    source = "run-override" if any(
        value is not None
        for value in (
            command_override,
            activation_override,
            fallback_override,
            enabled_override,
        )
    ) else ("config" if block else "native")

    if command is not None and not COMMAND_RE.fullmatch(command):
        raise ConfigError("invalid_route", "command override must be an opaque identifier")

    if kind == "delivery":
        if activation_override is not None:
            raise ConfigError("invalid_route", "delivery route does not accept activation")
        enabled = enabled_override if enabled_override is not None else bool(block.get("enabled", False))
        fallback = fallback_override or _policy_value(block, "fallback") or "skip"
        if fallback not in DELIVERY_FALLBACKS:
            raise ConfigError("invalid_route", "delivery fallback must be skip or stop")
        if enabled and command is None:
            raise ConfigError("invalid_route", "enabled delivery requires a command")
        decision = "invoke-command" if enabled and command else "skip"
        return {
            "kind": kind,
            "source": source,
            "command": command,
            "enabled": enabled,
            "fallback": fallback,
            "configured": command is not None,
            "decision": decision,
            "probe": "required" if decision == "invoke-command" else "forbidden",
        }

    if enabled_override is not None:
        raise ConfigError("invalid_route", f"{kind} route does not accept enabled")
    configured_activation = _policy_value(block, "activation")
    if command_override is not None and activation_override is None:
        activation = "always"
    else:
        activation = activation_override or configured_activation or (
            "auto" if command is not None else "never"
        )
    if command_override is not None and fallback_override is None:
        fallback = "stop"
    else:
        fallback = fallback_override or _policy_value(block, "fallback") or "native"
    if activation not in EXECUTE_ACTIVATIONS:
        raise ConfigError("invalid_route", f"{kind} activation must be auto, always, or never")
    if fallback not in WORK_REVIEW_FALLBACKS:
        raise ConfigError("invalid_route", f"{kind} fallback must be native or stop")
    if activation in {"auto", "always"} and command is None:
        raise ConfigError("invalid_route", f"active {kind} route requires a command")
    if command is None or activation == "never":
        decision = "native"
        probe = "forbidden"
    elif activation == "always":
        decision = "invoke-command"
        probe = "required"
    else:
        decision = "producer-decision"
        probe = "after-producer-selection"
    return {
        "kind": kind,
        "source": source,
        "command": command,
        "activation": activation,
        "fallback": fallback,
        "configured": command is not None,
        "decision": decision,
        "probe": probe,
    }


def select_work_route(
    route: dict[str, Any],
    *,
    work_units: int,
    dependency_graph: bool = False,
    parallel_graph: bool = False,
    integration_gate: bool = False,
    cross_session_resume: bool = False,
    external_handoff: bool = False,
) -> dict[str, Any]:
    """Resolve an auto work route from topology and execution lifecycle only.

    Risk, reviewer independence, a preferred worktree, or generic evidence needs
    belong to separate Studio decisions. They must not turn a bounded standalone
    task into a task-worker graph.
    """
    if route.get("kind") != "work":
        raise ConfigError("invalid_route", "work selection requires a work route")
    if not isinstance(work_units, int) or isinstance(work_units, bool) or work_units < 1:
        raise ConfigError("invalid_work_shape", "work_units must be a positive integer")

    shape = {
        "work_units": work_units,
        "dependency_graph": bool(dependency_graph),
        "parallel_graph": bool(parallel_graph),
        "integration_gate": bool(integration_gate),
        "cross_session_resume": bool(cross_session_resume),
        "external_handoff": bool(external_handoff),
    }
    route_decision = route.get("decision")
    if route_decision == "invoke-command":
        decision = "invoke-command"
        reasons = ["explicit-command-route"]
    elif route_decision != "producer-decision":
        decision = "native"
        reasons = ["route-disabled-or-unconfigured"]
    else:
        reasons: list[str] = []
        if work_units >= 2 and dependency_graph:
            reasons.append("dependency-graph")
        if work_units >= 2 and parallel_graph:
            reasons.append("parallel-work-graph")
        if integration_gate:
            reasons.append("integration-gate")
        if cross_session_resume:
            reasons.append("cross-session-resume")
        if external_handoff:
            reasons.append("external-handoff")
        decision = "invoke-command" if reasons else "native"
        if not reasons:
            reasons = ["bounded-direct-work"]

    return {
        "schema": WORK_DECISION_SCHEMA,
        "decision": decision,
        "probe": "required" if decision == "invoke-command" else "forbidden",
        "command": route.get("command") if decision == "invoke-command" else None,
        "fallback": route.get("fallback"),
        "reason_codes": reasons,
        "work_shape": shape,
    }


def load_config(path: Path, *, missing_ok: bool) -> tuple[bool, dict[str, Any]]:
    if not path.is_file():
        if missing_ok:
            return False, {}
        raise ConfigError("config_not_found", f"no config at {path}")
    try:
        config = parse_yaml_subset(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError("config_read_failed", f"cannot read {path}: {error}") from error
    problems = validate_config(config)
    if problems:
        raise ConfigError("invalid_config", "config has errors", problems=problems)
    return True, config


def command_scaffold(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if path.exists() and not args.force:
        raise ConfigError("config_exists", f"{path} already exists")
    path.write_text(render_default_config(), encoding="utf-8")
    emit({"ok": True, "path": str(path), "created": True})


def command_validate(args: argparse.Namespace) -> None:
    path = Path(args.path)
    present, _ = load_config(path, missing_ok=False)
    emit({"ok": True, "path": str(path), "present": present, "problems": []})


def command_resolve(args: argparse.Namespace) -> None:
    path = Path(args.path)
    present, config = load_config(path, missing_ok=True)
    profile = resolve_profile(
        config,
        provider=args.provider,
        role=args.role,
        model_override=args.model,
        effort_override=args.effort,
    )
    emit({"ok": True, "path": str(path), "present": present, "profile": profile})


def command_route(args: argparse.Namespace) -> None:
    path = Path(args.path)
    present, config = load_config(path, missing_ok=True)
    enabled = None if args.enabled is None else args.enabled == "true"
    route = resolve_execute_route(
        config,
        kind=args.kind,
        command_override=args.route_command,
        activation_override=args.activation,
        fallback_override=args.fallback,
        enabled_override=enabled,
    )
    emit({"ok": True, "path": str(path), "present": present, "route": route})


def command_select_work(args: argparse.Namespace) -> None:
    path = Path(args.path)
    present, config = load_config(path, missing_ok=True)
    route = resolve_execute_route(
        config,
        kind="work",
        command_override=args.route_command,
        activation_override=args.activation,
        fallback_override=args.fallback,
    )
    decision = select_work_route(
        route,
        work_units=args.work_units,
        dependency_graph=args.dependency_graph,
        parallel_graph=args.parallel_graph,
        integration_gate=args.integration_gate,
        cross_session_resume=args.cross_session_resume,
        external_handoff=args.external_handoff,
    )
    emit({"ok": True, "path": str(path), "present": present, "route": route, "work": decision})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    scaffold = subcommands.add_parser("scaffold", help="create a spawn-policy config")
    scaffold.add_argument("--path", default=CONFIG_PATH_DEFAULT)
    scaffold.add_argument("--force", action="store_true")
    scaffold.set_defaults(handler=command_scaffold)

    validate = subcommands.add_parser("validate", help="validate a spawn-policy config")
    validate.add_argument("--path", default=CONFIG_PATH_DEFAULT)
    validate.set_defaults(handler=command_validate)

    resolve = subcommands.add_parser("resolve", help="resolve model/effort for one crew role")
    resolve.add_argument("--path", default=CONFIG_PATH_DEFAULT)
    resolve.add_argument("--provider", choices=sorted(SUPPORTED_PROVIDERS), required=True)
    resolve.add_argument("--role", choices=sorted(CREW_ROLES), required=True)
    resolve.add_argument("--model")
    resolve.add_argument("--effort")
    resolve.set_defaults(handler=command_resolve)

    route = subcommands.add_parser("route", help="resolve one optional execution command")
    route.add_argument("--path", default=CONFIG_PATH_DEFAULT)
    route.add_argument("--kind", choices=sorted(EXECUTE_KINDS), required=True)
    route.add_argument("--command", dest="route_command")
    route.add_argument("--activation", choices=sorted(EXECUTE_ACTIVATIONS))
    route.add_argument("--fallback", choices=sorted(WORK_REVIEW_FALLBACKS | DELIVERY_FALLBACKS))
    route.add_argument("--enabled", choices=("false", "true"))
    route.set_defaults(handler=command_route)

    select_work = subcommands.add_parser(
        "select-work", help="select native or configured work execution from work shape"
    )
    select_work.add_argument("--path", default=CONFIG_PATH_DEFAULT)
    select_work.add_argument("--work-units", type=int, required=True)
    select_work.add_argument("--dependency-graph", action="store_true")
    select_work.add_argument("--parallel-graph", action="store_true")
    select_work.add_argument("--integration-gate", action="store_true")
    select_work.add_argument("--cross-session-resume", action="store_true")
    select_work.add_argument("--external-handoff", action="store_true")
    select_work.add_argument("--command", dest="route_command")
    select_work.add_argument("--activation", choices=sorted(EXECUTE_ACTIVATIONS))
    select_work.add_argument("--fallback", choices=sorted(WORK_REVIEW_FALLBACKS))
    select_work.set_defaults(handler=command_select_work)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except ConfigError as error:
        exit_code = {
            "config_exists": 2,
            "config_not_found": 3,
            "parse_error": 4,
            "config_read_failed": 4,
            "invalid_config": 6,
            "invalid_route": 6,
            "invalid_work_shape": 6,
        }.get(error.code, 6)
        emit(
            {
                "ok": False,
                "error_code": error.code,
                "message": str(error),
                "problems": error.problems,
            },
            exit_code=exit_code,
        )


if __name__ == "__main__":
    main()
