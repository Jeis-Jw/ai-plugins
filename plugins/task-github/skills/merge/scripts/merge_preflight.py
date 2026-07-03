#!/usr/bin/env python3
"""Pre-closeout PR gate evidence producer for task-github merge."""

from __future__ import annotations

import argparse
from datetime import date
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[2] / "orchestrate" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import orchestrator_ops  # type: ignore  # noqa: E402
from orchestrate_ledger import (  # type: ignore  # noqa: E402
    load_ledger,
    record_gate_evidence,
    record_github_read,
    record_preflight_evidence,
)

GATE_VERSION = "changed-path-stale:v1"
DRIFT_SURFACE_TYPES = {"observation", "runbook", "ssot", "trial_error"}
PREFLIGHT_REUSE_COVERS = ("mergeability", "ci_check", "review_decision", "head_sha")
PREFLIGHT_CLOSEOUT_VIEW_FIELDS = (
    "number",
    "headRefName",
    "headRefOid",
    "baseRefName",
    "state",
    "body",
    "labels",
)
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


def _strip_yaml_comment(value: str) -> str:
    quote = None
    out = []
    for ch in value:
        if ch in {"'", '"'}:
            quote = None if quote == ch else ch if quote is None else quote
        if ch == "#" and quote is None:
            break
        out.append(ch)
    return "".join(out).strip()


def _yaml_scalar(raw: str) -> str:
    value = _strip_yaml_comment(raw)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _yaml_value(raw: str) -> Any:
    value = _strip_yaml_comment(raw)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_yaml_scalar(part) for part in inner.split(",") if _yaml_scalar(part)]
    return _yaml_scalar(value)


def _frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw in lines[1:end]:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_key and stripped.startswith("- "):
            value = _yaml_scalar(stripped[2:])
            if value:
                data.setdefault(current_key, []).append(value)
            continue
        if ":" not in stripped:
            current_key = None
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if raw_value.strip() == "":
            data[key] = []
            current_key = key
        else:
            data[key] = _yaml_value(raw_value)
            current_key = None
    return data


def _active_wiki_doc(path: Path, vault: Path) -> bool:
    try:
        rel = path.relative_to(vault)
    except ValueError:
        return False
    parts = set(rel.parts)
    return "retired" not in parts and "done" not in parts


def _wiki_doc_type(path: Path, vault: Path) -> str:
    rel = tuple(part for part in path.relative_to(vault).parts if part not in {"retired", "done"})
    if not rel:
        return ""
    if rel[0] in {"runbook", "ssot"}:
        return rel[0]
    if rel[0] == "context" and len(rel) >= 2:
        return rel[1]
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def drift_surface_entries(wiki_vault: Path = Path("wiki")) -> list[dict[str, Any]]:
    """Return the wiki frontmatter surface that can affect changed-path-stale.

    The gate depends on active docs' type, affects_paths, verified_at and the
    current date. Body text is intentionally excluded so wording-only wiki edits
    do not invalidate child closeout evidence.
    """
    vault = Path(wiki_vault)
    if not vault.is_dir():
        return [{"wiki_vault": "missing"}]
    entries: list[dict[str, Any]] = []
    for path in sorted(vault.rglob("*.md")):
        if not _active_wiki_doc(path, vault):
            continue
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        doc_type = _wiki_doc_type(path, vault)
        affects_paths = orchestrator_ops.canonical_path_list(_string_list(fm.get("affects_paths")))
        verified_at = str(fm.get("verified_at") or "").strip()
        if doc_type not in DRIFT_SURFACE_TYPES or not affects_paths:
            continue
        entries.append({
            "path": str(path.relative_to(vault)),
            "type": doc_type,
            "affects_paths": affects_paths,
            "verified_at": verified_at,
            "superseded_by": str(fm.get("superseded_by") or "").strip(),
        })
    return entries


def compute_drift_surface_hash(wiki_vault: Path = Path("wiki")) -> str:
    return _stable_hash({
        "gate_version": GATE_VERSION,
        "as_of": date.today().isoformat(),
        "surface": drift_surface_entries(wiki_vault),
    })


def parse_linked_issue(pr_body: str) -> int | None:
    match = LINKED_ISSUE_RE.search(pr_body or "")
    return int(match.group(1)) if match else None


def decode_diff_path(raw: str) -> str:
    """Decode git-style quoted path lines from `gh pr diff --name-only`."""
    if not (len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"'):
        return raw
    text = raw[1:-1]
    out = bytearray()
    i = 0
    escapes = {
        "a": 7,
        "b": 8,
        "t": 9,
        "n": 10,
        "v": 11,
        "f": 12,
        "r": 13,
        '"': ord('"'),
        "\\": ord("\\"),
    }
    while i < len(text):
        ch = text[i]
        if ch != "\\":
            out.extend(ch.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(text):
            out.append(ord("\\"))
            break
        esc = text[i]
        if esc in "01234567":
            digits = [esc]
            i += 1
            while i < len(text) and len(digits) < 3 and text[i] in "01234567":
                digits.append(text[i])
                i += 1
            out.append(int("".join(digits), 8))
            continue
        out.append(escapes.get(esc, ord(esc)))
        i += 1
    return out.decode("utf-8")


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
    drift_surface_hash: str | None = None,
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
        "drift_surface_hash": drift_surface_hash or _stable_hash({
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


def build_preflight_evidence(view: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    reusable_view = {field: view.get(field) for field in PREFLIGHT_CLOSEOUT_VIEW_FIELDS}
    return {
        "pr": int(view["number"]),
        "covers": list(PREFLIGHT_REUSE_COVERS),
        "status": dict(status),
        "view": reusable_view,
        "mergeStateStatus": view.get("mergeStateStatus"),
        "reviewDecision": view.get("reviewDecision"),
        "isDraft": view.get("isDraft"),
        "statusCheckRollup": list(view.get("statusCheckRollup") or []),
    }


def _ledger_issue(ledger: dict[str, Any], number: int) -> dict[str, Any]:
    return dict((ledger.get("issues") or {}).get(str(number)) or {})


def _ledger_evidence(ledger: dict[str, Any], block: str, number: int) -> dict[str, Any] | None:
    value = (ledger.get(block) or {}).get(str(number))
    return dict(value) if isinstance(value, dict) else None


def scoped_gate_plan_from_ledger(
    *,
    parent_issue: int,
    expected_base: str,
    changed_paths: list[str],
    ledger: dict[str, Any],
    current_gate_version: str,
    current_tool_versions: dict[str, str],
    current_drift_surface_hashes: dict[int, str] | None = None,
    current_drift_surface_hash: str | None = None,
    expected_pr_heads: dict[int, str] | None = None,
    current_tool_version_policy_token: str | None = None,
) -> dict[str, Any]:
    parent = _ledger_issue(ledger, parent_issue)
    child_numbers = [int(child) for child in parent.get("children") or []]
    if not child_numbers:
        paths = orchestrator_ops.canonical_path_list(changed_paths)
        return {"target_paths": paths, "reused": [], "fallback": [], "full_fallback": False}

    children = []
    child_path_set: set[str] = set()
    for number in child_numbers:
        gate = _ledger_evidence(ledger, "gate_evidence", number)
        merge = _ledger_evidence(ledger, "merge_evidence", number)
        issue = _ledger_issue(ledger, number)
        paths = orchestrator_ops.canonical_path_list((gate or {}).get("changed_paths") or issue.get("changed_paths"))
        child_path_set.update(paths)
        child = {"number": number, "changed_paths": paths}
        if gate:
            child["gate_evidence"] = gate
        if merge:
            child["merge_evidence"] = merge
        children.append(child)

    parent_paths = [
        path for path in orchestrator_ops.canonical_path_list(changed_paths)
        if path not in child_path_set
    ]
    target_paths: set[str] = set(parent_paths)
    reused: list[int] = []
    fallback: list[dict[str, Any]] = []
    hash_by_child = current_drift_surface_hashes or {}
    heads_by_child = expected_pr_heads or {}
    child_expected_base = f"task/issue-{parent_issue}"

    for child in children:
        number = int(child["number"])
        gate = child.get("gate_evidence") or {}
        merge = child.get("merge_evidence") or {}
        current_hash = hash_by_child.get(number) or current_drift_surface_hash or ""
        expected_head = heads_by_child.get(number) or merge.get("head_sha") or gate.get("pr_head_sha")
        plan = orchestrator_ops.scoped_changed_path_stale_targets(
            parent_paths=parent_paths,
            children=[child],
            expected_base=child_expected_base,
            current_gate_version=current_gate_version,
            current_tool_versions=current_tool_versions,
            current_drift_surface_hash=current_hash,
            expected_pr_heads={number: expected_head} if expected_head else None,
            current_tool_version_policy_token=current_tool_version_policy_token,
        )
        reused.extend(plan["reused"])
        fallback.extend(plan["fallback"])
        target_paths.update(plan["target_paths"])

    return {
        "target_paths": sorted(target_paths),
        "reused": reused,
        "fallback": fallback,
        "full_fallback": bool(fallback),
        "parent_paths": parent_paths,
    }


def _run(cmd: list[str], *, code: str) -> str:
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise PreflightError(code, result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def gh(args: list[str], *, code: str = "gh_failed") -> str:
    return _run(["gh", *args], code=code)


def wiki_cli_path() -> Path:
    candidates = [
        Path("plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py"),
        Path(__file__).resolve().parents[4] / "wiki-markdown" / "skills" / "wiki" / "scripts" / "wiki_cli.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _wiki(args: list[str], *, code: str) -> dict[str, Any]:
    path = wiki_cli_path()
    if not path.exists():
        raise PreflightError("wiki_cli_missing", f"wiki CLI not found: {path}")
    out = _run(["python3", str(path), *args], code=code)
    return json.loads(out or "{}")


def collect_wiki_gate_reports(
    checked_paths: list[str],
    *,
    wiki_vault: Path = Path("wiki"),
    drift_surface_hash: str | None = None,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vault = Path(wiki_vault)
    surface_hash = drift_surface_hash or compute_drift_surface_hash(vault)
    checked = orchestrator_ops.canonical_path_list(checked_paths)
    if not vault.is_dir():
        skipped = {"ok": True, "issues": [], "skipped": True, "reason": "wiki_vault_missing"}
        return {
            "wiki_available": False,
            "integrity": dict(skipped),
            "drift": dict(skipped),
            "drift_surface_hash": surface_hash,
        }

    integrity_report = integrity or _wiki(
        ["refresh", "--vault", str(vault), "--level", "integrity", "--strict", "--json"],
        code="wiki_integrity_failed",
    )
    if checked:
        drift = _wiki([
            "refresh",
            "--vault",
            str(vault),
            "--check",
            "changed-path-stale",
            "--changed-path",
            ",".join(checked),
            "--json",
        ], code="wiki_drift_failed")
    else:
        drift = {"ok": True, "issues": [], "skipped": True, "reason": "valid_child_evidence_reused"}
    return {
        "wiki_available": True,
        "integrity": integrity_report,
        "drift": drift,
        "drift_surface_hash": surface_hash,
    }


def run_ff_gate(
    *,
    issue: int,
    changed_paths: list[str],
    head_sha: str,
    orchestrate_ledger: str | None = None,
    wiki_vault: Path = Path("wiki"),
) -> dict[str, Any]:
    tools, policy_token = plugin_tool_versions()
    checked_paths = orchestrator_ops.canonical_path_list(changed_paths)
    reports = collect_wiki_gate_reports(checked_paths, wiki_vault=wiki_vault)
    integrity = reports["integrity"]
    if integrity.get("issues") or integrity.get("ok") is False:
        return {"ok": False, "stop_reason": "wiki_integrity_failed", "integrity": integrity, "issue": issue}

    evidence = build_gate_evidence(
        changed_paths=changed_paths,
        checked_paths=checked_paths,
        drift_report=reports["drift"],
        pr_head_sha=head_sha,
        tool_versions=tools,
        drift_surface_hash=reports["drift_surface_hash"],
        tool_version_policy_token=policy_token,
    )
    required = validate_required_gate_evidence(evidence)
    if not required.get("ok"):
        return {"ok": False, **required, "issue": issue}
    if orchestrate_ledger:
        record_gate_evidence(orchestrate_ledger, issue, evidence)
    return {
        "ok": True,
        "issue": issue,
        "head_sha": head_sha,
        "gate_evidence": evidence,
        "wiki_reports": reports,
    }


def run_preflight(
    pr: int,
    *,
    orchestrate_ledger: str | None = None,
    expected_head_oid: str | None = None,
) -> dict[str, Any]:
    wiki_vault = Path("wiki")
    view = json.loads(gh([
        "pr",
        "view",
        str(pr),
        "--json",
        "number,title,headRefName,headRefOid,baseRefName,state,isDraft,mergeStateStatus,reviewDecision,statusCheckRollup,body,labels",
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

    drift_surface_hash = compute_drift_surface_hash(wiki_vault)
    wiki_reports = collect_wiki_gate_reports([], wiki_vault=wiki_vault, drift_surface_hash=drift_surface_hash)
    integrity = wiki_reports["integrity"]
    if integrity.get("issues") or integrity.get("ok") is False:
        return {"ok": False, "stop_reason": "wiki_integrity_failed", "integrity": integrity, "pr": pr}

    tools, policy_token = plugin_tool_versions()
    issue = parse_linked_issue(view.get("body") or "")
    changed_paths = [
        decode_diff_path(line)
        for line in gh(["pr", "diff", str(pr), "--name-only"], code="pr_diff_failed").splitlines()
        if line
    ]
    scoped_plan = None
    checked_paths = orchestrator_ops.canonical_path_list(changed_paths)
    if orchestrate_ledger and issue is not None:
        ledger = load_ledger(orchestrate_ledger)
        scoped_plan = scoped_gate_plan_from_ledger(
            parent_issue=issue,
            expected_base=view["baseRefName"],
            changed_paths=changed_paths,
            ledger=ledger,
            current_gate_version=GATE_VERSION,
            current_tool_versions=tools,
            current_drift_surface_hash=drift_surface_hash,
            current_tool_version_policy_token=policy_token,
        )
        checked_paths = scoped_plan["target_paths"]
    wiki_reports = collect_wiki_gate_reports(
        checked_paths,
        wiki_vault=wiki_vault,
        drift_surface_hash=drift_surface_hash,
        integrity=integrity,
    )
    drift = wiki_reports["drift"]
    evidence = build_gate_evidence(
        changed_paths=changed_paths,
        checked_paths=checked_paths,
        drift_report=drift,
        pr_head_sha=view["headRefOid"],
        tool_versions=tools,
        drift_surface_hash=drift_surface_hash,
        tool_version_policy_token=policy_token,
    )
    required = validate_required_gate_evidence(evidence)
    if not required.get("ok"):
        return {"ok": False, **required, "pr": pr}

    if orchestrate_ledger and issue is not None:
        record_gate_evidence(orchestrate_ledger, issue, evidence)
        record_preflight_evidence(orchestrate_ledger, pr, build_preflight_evidence(view, status))
    return {
        "ok": True,
        "pr": pr,
        "issue": issue,
        "headRefOid": view["headRefOid"],
        "gate_evidence": evidence,
        "preflight_evidence": build_preflight_evidence(view, status),
        "scoped_gate_plan": scoped_plan,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--ff-gate", action="store_true", help="record gate_evidence for a micro/normal FF closeout")
    parser.add_argument("--issue", type=int, help="issue number for --ff-gate")
    parser.add_argument("--changed-path", action="append", default=[], dest="changed_paths",
                        help="changed path for --ff-gate; repeat or comma-separate")
    parser.add_argument("--head-sha", help="HEAD SHA for --ff-gate")
    parser.add_argument("--wiki-vault", default="wiki")
    parser.add_argument("--orchestrate-ledger")
    parser.add_argument("--expected-head-oid")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.ff_gate:
            if args.issue is None:
                parser.error("--issue is required with --ff-gate")
            if not args.head_sha:
                parser.error("--head-sha is required with --ff-gate")
            changed_paths = [
                part.strip()
                for raw in args.changed_paths
                for part in raw.split(",")
                if part.strip()
            ]
            result = run_ff_gate(
                issue=args.issue,
                changed_paths=changed_paths,
                head_sha=args.head_sha,
                orchestrate_ledger=args.orchestrate_ledger,
                wiki_vault=Path(args.wiki_vault),
            )
        else:
            if args.pr is None:
                parser.error("--pr is required unless --ff-gate is used")
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
