#!/usr/bin/env python3
"""Pre-closeout PR gate evidence producer for task-github merge."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[2] / "orchestrate" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import orchestrator_ops  # type: ignore  # noqa: E402
from orchestrate_ledger import record_gate_evidence, record_github_read  # type: ignore  # noqa: E402

GATE_VERSION = "changed-path-stale:v1"
REQUIRED_GATE_FIELDS = (
    "changed_paths",
    "changed_paths_hash",
    "checked_paths",
    "checked_paths_hash",
    "drift_surface_hash",
    "tool_versions",
    "gate_version",
    "changed_path_stale_issues",
    "pr_head_sha",
)
LINKED_ISSUE_RE = re.compile(r"(?i)\b(?:closes|fixes|resolves)\s+#(\d+)")


class PreflightError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_linked_issue(pr_body: str) -> int | None:
    match = LINKED_ISSUE_RE.search(pr_body or "")
    return int(match.group(1)) if match else None


def plugin_tool_versions(plugin_root: Path | None = None) -> tuple[dict[str, str], str | None]:
    root = plugin_root or Path(__file__).resolve().parents[3]
    for rel in (".codex-plugin/plugin.json", ".claude-plugin/plugin.json"):
        path = root / rel
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            version = data.get("version")
            if version:
                return {"task-github": str(version)}, None
    return {"task-github": "unknown"}, "plugin-version-unavailable:v1"


def build_gate_evidence(
    *,
    changed_paths: list[str],
    checked_paths: list[str],
    drift_report: dict[str, Any],
    pr_head_sha: str,
    tool_versions: dict[str, str],
    gate_version: str = GATE_VERSION,
    tool_version_policy_token: str | None = None,
) -> dict[str, Any]:
    changed = orchestrator_ops.canonical_path_list(changed_paths)
    checked = orchestrator_ops.canonical_path_list(checked_paths)
    stale_issues = list((drift_report or {}).get("issues") or [])
    evidence = {
        "changed_paths": changed,
        "changed_paths_hash": orchestrator_ops.path_list_hash(changed),
        "checked_paths": checked,
        "checked_paths_hash": orchestrator_ops.path_list_hash(checked),
        "drift_surface_hash": _stable_hash({
            "gate_version": gate_version,
            "changed_paths": changed,
            "checked_paths": checked,
            "changed_path_stale_issues": stale_issues,
        }),
        "tool_versions": dict(tool_versions),
        "gate_version": gate_version,
        "changed_path_stale_issues": stale_issues,
        "pr_head_sha": pr_head_sha,
    }
    if tool_version_policy_token:
        evidence["tool_version_policy_token"] = tool_version_policy_token
    return evidence


def validate_required_gate_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_GATE_FIELDS if evidence.get(field) is None]
    if missing:
        return {"ok": False, "stop_reason": "missing_gate_evidence_field", "missing": missing}
    changed = evidence["changed_paths"]
    checked = evidence["checked_paths"]
    if changed != orchestrator_ops.canonical_path_list(changed):
        return {"ok": False, "stop_reason": "noncanonical_changed_paths"}
    if checked != orchestrator_ops.canonical_path_list(checked):
        return {"ok": False, "stop_reason": "noncanonical_checked_paths"}
    if evidence["changed_paths_hash"] != orchestrator_ops.path_list_hash(changed):
        return {"ok": False, "stop_reason": "changed_paths_hash_mismatch"}
    if evidence["checked_paths_hash"] != orchestrator_ops.path_list_hash(checked):
        return {"ok": False, "stop_reason": "checked_paths_hash_mismatch"}
    if evidence.get("changed_path_stale_issues"):
        return {"ok": False, "stop_reason": "changed_path_stale"}
    return {"ok": True}


def _check_conclusion(item: dict[str, Any]) -> str:
    return str(item.get("conclusion") or item.get("state") or item.get("status") or "").upper()


def validate_pr_status(view: dict[str, Any], *, expected_head_oid: str | None = None) -> dict[str, Any]:
    head_oid = view.get("headRefOid")
    if expected_head_oid and head_oid != expected_head_oid:
        return {"ok": False, "stop_reason": "pr_head_mismatch"}
    if view.get("isDraft"):
        return {"ok": False, "stop_reason": "draft_pr"}
    if view.get("mergeStateStatus") not in (None, "CLEAN", "HAS_HOOKS"):
        return {"ok": False, "stop_reason": "mergeability_not_clean", "mergeStateStatus": view.get("mergeStateStatus")}
    if view.get("reviewDecision") == "CHANGES_REQUESTED":
        return {"ok": False, "stop_reason": "review_changes_requested"}
    for item in view.get("statusCheckRollup") or []:
        conclusion = _check_conclusion(item)
        if conclusion in {"", "SUCCESS", "SKIPPED", "NEUTRAL"}:
            continue
        if conclusion in {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED"}:
            return {"ok": False, "stop_reason": "ci_check_pending", "check": item.get("name")}
        return {"ok": False, "stop_reason": "ci_check_failed", "check": item.get("name")}
    return {"ok": True, "headRefOid": head_oid}


def _run(cmd: list[str], *, code: str) -> str:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise PreflightError(code, result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def gh(args: list[str], *, code: str = "gh_failed") -> str:
    return _run(["gh", *args], code=code)


def _wiki(args: list[str], *, code: str) -> dict[str, Any]:
    out = _run(["python3", "plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py", *args], code=code)
    return json.loads(out or "{}")


def run_preflight(
    pr: int,
    *,
    orchestrate_ledger: str | None = None,
    expected_head_oid: str | None = None,
) -> dict[str, Any]:
    view = json.loads(gh([
        "pr",
        "view",
        str(pr),
        "--json",
        "number,title,headRefName,headRefOid,baseRefName,state,isDraft,mergeStateStatus,reviewDecision,statusCheckRollup,body",
    ], code="pr_view_failed"))
    if orchestrate_ledger:
        record_github_read(
            orchestrate_ledger,
            reason="pre_merge",
            operation="merge_preflight",
            detail={"pr": pr, "covers": ["mergeability", "ci_check", "review_decision"]},
        )

    status = validate_pr_status(view, expected_head_oid=expected_head_oid)
    if not status.get("ok"):
        return {"ok": False, **status, "pr": pr}

    integrity = _wiki(["refresh", "--level", "integrity", "--strict", "--json"], code="wiki_integrity_failed")
    if integrity.get("issues") or integrity.get("ok") is False:
        return {"ok": False, "stop_reason": "wiki_integrity_failed", "integrity": integrity, "pr": pr}

    changed_paths = [line for line in gh(["pr", "diff", str(pr), "--name-only"], code="pr_diff_failed").splitlines() if line]
    drift = _wiki([
        "refresh",
        "--check",
        "changed-path-stale",
        "--changed-path",
        ",".join(orchestrator_ops.canonical_path_list(changed_paths)),
        "--json",
    ], code="wiki_drift_failed")
    tools, policy_token = plugin_tool_versions()
    evidence = build_gate_evidence(
        changed_paths=changed_paths,
        checked_paths=changed_paths,
        drift_report=drift,
        pr_head_sha=view["headRefOid"],
        tool_versions=tools,
        tool_version_policy_token=policy_token,
    )
    required = validate_required_gate_evidence(evidence)
    if not required.get("ok"):
        return {"ok": False, **required, "pr": pr}

    issue = parse_linked_issue(view.get("body") or "")
    if orchestrate_ledger and issue is not None:
        record_gate_evidence(orchestrate_ledger, issue, evidence)
    return {"ok": True, "pr": pr, "issue": issue, "headRefOid": view["headRefOid"], "gate_evidence": evidence}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--orchestrate-ledger")
    parser.add_argument("--expected-head-oid")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = run_preflight(
            args.pr,
            orchestrate_ledger=args.orchestrate_ledger,
            expected_head_oid=args.expected_head_oid,
        )
    except PreflightError as exc:
        result = {"ok": False, "stop_reason": exc.code, "message": exc.message}
    print(json.dumps(result, ensure_ascii=False) if args.as_json else json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
