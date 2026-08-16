#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Sequence


DECISION_CLI = pathlib.Path(__file__).resolve().parents[2] / "decision/scripts/decision_cli.py"


def _emit(value: dict[str, Any], *, compact: bool) -> None:
    print(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(value, ensure_ascii=False, indent=2)
    )


def _forward(completed: subprocess.CompletedProcess[str]) -> int:
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decision_init.py")
    parser.add_argument("--host", choices=("codex", "claude-code"), required=True)
    parser.add_argument("--core-inventory", required=True)
    parser.add_argument("--core-doctor", required=True)
    parser.add_argument("--core-cli", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    planned = _run(
        [
            sys.executable,
            str(DECISION_CLI),
            "init",
            "--host",
            args.host,
            "--core-inventory",
            args.core_inventory,
            "--core-doctor",
            args.core_doctor,
            "--json",
        ]
    )
    if planned.returncode != 0:
        return _forward(planned)
    try:
        plan = json.loads(planned.stdout)["result"]
    except (KeyError, TypeError, json.JSONDecodeError):
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "init_plan_invalid",
                    "message": "context-decision init plan output is invalid",
                    "details": {"write_policy": {"repository": "none", "host_configuration": "none"}},
                },
            },
            compact=args.json,
        )
        return 7

    core_cli = pathlib.Path(args.core_cli).resolve()
    if not core_cli.is_file() or core_cli.name != "context_cli.py":
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "core_surface_unavailable",
                    "message": "the active installed context-core public CLI was not supplied",
                    "details": {
                        "required_plugin": plan.get("required_plugin"),
                        "write_policy": {"repository": "none", "host_configuration": "none"},
                    },
                },
            },
            compact=args.json,
        )
        return 5

    with tempfile.TemporaryDirectory(prefix="context-decision-init-") as temp:
        temp_root = pathlib.Path(temp)
        descriptor = temp_root / "descriptor.json"
        seed = temp_root / "decision.index.md"
        descriptor.write_text(
            json.dumps(plan["owner_descriptor"], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        seed.write_text(plan["index_seed"], encoding="utf-8")
        completed = _run(
            [
                sys.executable,
                str(core_cli),
                "bootstrap",
                "--descriptor",
                f"@{descriptor}",
                "--index-seed",
                f"@{seed}",
                "--host",
                args.host,
                "--json",
            ]
        )
    if completed.returncode != 0:
        return _forward(completed)
    try:
        bootstrap = json.loads(completed.stdout)["result"]
    except (KeyError, TypeError, json.JSONDecodeError):
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "core_bootstrap_result_invalid",
                    "message": "context-core bootstrap output is invalid",
                    "details": {"write_policy": {"host_configuration": "none"}},
                },
            },
            compact=args.json,
        )
        return 7

    _emit(
        {
            "ok": True,
            "result": {
                "schema": "context-decision-init-result/v1",
                "core_repository_state_before": plan["core_repository_state"],
                "preflight": {
                    "required_plugin": plan["required_plugin"],
                    "repository_state": plan["core_repository_state"],
                },
                "phases": bootstrap["phases"],
                "changed_paths": bootstrap["changed_paths"],
                "doctor": bootstrap["doctor"],
                "policy": bootstrap["policy"],
                "bootstrap": bootstrap,
            },
        },
        compact=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
