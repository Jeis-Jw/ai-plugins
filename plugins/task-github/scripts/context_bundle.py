#!/usr/bin/env python3
"""Shared task-github context-bundle resolver.

The resolver is intentionally IO-light: skills may fetch GitHub/wiki data in
their own flow, then pass those JSON objects here to get one common read-model.
It never calls wiki-markdown and therefore preserves plugin independence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


TASK_ID_RE = re.compile(r"TASK-\d{4}-\d{2}-\d{2}-\d{6}-[^\s)\],.]+")
INTEGRATION_FIELDS = ("topology", "gate", "parent_branch")


def extract_task_ids(body: str | None) -> list[str]:
    seen = set()
    out: list[str] = []
    for match in TASK_ID_RE.finditer(body or ""):
        task_id = match.group(0)
        if task_id not in seen:
            out.append(task_id)
            seen.add(task_id)
    return out


def _labels(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    labels = []
    for label in raw:
        if isinstance(label, str):
            labels.append(label)
        elif isinstance(label, Mapping) and isinstance(label.get("name"), str):
            labels.append(label["name"])
    return labels


def _normalize_issue(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    number = raw.get("number")
    return {
        "number": int(number) if isinstance(number, (int, str)) and str(number).isdigit() else number,
        "title": raw.get("title"),
        "state": raw.get("state"),
        "body": raw.get("body") or "",
        "labels": _labels(raw.get("labels")),
    }


def _normalize_dependency_items(items: Iterable[Any] | None) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        if isinstance(item, Mapping):
            normalized = {
                "number": item.get("number"),
                "title": item.get("title"),
                "state": item.get("state"),
            }
            for key in ("id", "reason"):
                if key in item:
                    normalized[key] = item[key]
            out.append(normalized)
        else:
            out.append({"number": None, "title": str(item), "state": None})
    return out


def _task_record_id(record: Mapping[str, Any] | None) -> str | None:
    if not record:
        return None
    for key in ("id", "basename", "name"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith("TASK-"):
            return value
    path = record.get("path")
    if isinstance(path, str):
        return Path(path).stem
    return None


def _task_done(record: Mapping[str, Any]) -> bool:
    status = record.get("status")
    if isinstance(status, str) and status.lower() in {"done", "closed", "complete", "completed"}:
        return True
    path = record.get("path")
    return isinstance(path, str) and "/done/" in path.replace("\\", "/")


def _task_relations(record: Mapping[str, Any] | None) -> list[str]:
    if not record:
        return []
    relations = record.get("relations")
    if isinstance(relations, Mapping) and isinstance(relations.get("tasks"), list):
        return [str(v) for v in relations["tasks"]]
    tasks = record.get("tasks")
    if isinstance(tasks, list):
        return [str(v) for v in tasks]
    return []


def _root_refs(owner: str | None, repo: str | None, root_number: Any) -> set[str]:
    if owner and repo and root_number is not None:
        ref = f"{owner}/{repo}#{root_number}"
        return {ref, f"github:{ref}"}
    return {f"#{root_number}"} if root_number is not None else set()


def _link_integrity(
    *,
    root: dict[str, Any] | None,
    owner: str | None,
    repo: str | None,
    wiki_task_record: Mapping[str, Any] | None,
) -> tuple[str | None, list[dict[str, str]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not root:
        errors.append({"code": "missing_root_issue", "message": "root issue data is required"})
        return None, errors, warnings

    task_ids = extract_task_ids(root.get("body"))
    task_id = task_ids[0] if task_ids else None
    if not task_id:
        errors.append({
            "code": "missing_root_wiki_task",
            "message": "root issue body has no TASK id in Wiki Context",
        })
    if len(task_ids) > 1:
        errors.append({
            "code": "multiple_root_wiki_tasks",
            "message": "root issue body links more than one TASK id",
        })

    record_id = _task_record_id(wiki_task_record)
    if task_id and record_id and task_id != record_id:
        errors.append({
            "code": "task_record_id_mismatch",
            "message": f"root links {task_id}, but wiki record is {record_id}",
        })

    if task_id and wiki_task_record:
        relations = _task_relations(wiki_task_record)
        refs = _root_refs(owner, repo, root.get("number"))
        if refs and not any(ref in refs for ref in relations):
            errors.append({
                "code": "task_relation_missing_root",
                "message": "wiki task relations.tasks does not point to the root issue",
            })

        root_closed = str(root.get("state") or "").upper() == "CLOSED"
        task_done = _task_done(wiki_task_record)
        if root_closed and not task_done:
            errors.append({
                "code": "root_closed_task_active",
                "message": "root issue is closed but wiki task is not done",
            })
        elif not root_closed and task_done:
            errors.append({
                "code": "root_open_task_done",
                "message": "root issue is open but wiki task is done",
            })
    elif task_id and not wiki_task_record:
        warnings.append({
            "code": "wiki_task_record_unavailable",
            "message": "root links a TASK id but no wiki task record was supplied",
        })

    return task_id, errors, warnings


def build_context_bundle(
    *,
    issue: Mapping[str, Any],
    root: Mapping[str, Any] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    wiki_task_record: Mapping[str, Any] | None = None,
    blockers: Iterable[Any] | None = None,
    downstream: Iterable[Any] | None = None,
    worktree_path: str | None = None,
    integration_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the shared read-model consumed by open/start/done/merge/status."""
    issue_out = _normalize_issue(issue)
    root_out = _normalize_issue(root or issue)
    task_id, errors, warnings = _link_integrity(
        root=root_out,
        owner=owner,
        repo=repo,
        wiki_task_record=wiki_task_record,
    )

    contract = dict(integration_contract or {})
    bundle = {
        "ok": not errors,
        "issue": issue_out,
        "root": root_out,
        "wiki_task": {"id": task_id, "record": dict(wiki_task_record)} if task_id and wiki_task_record else (
            {"id": task_id, "record": None} if task_id else None
        ),
        "blockers": _normalize_dependency_items(blockers),
        "downstream": _normalize_dependency_items(downstream),
        "worktree_path": worktree_path,
        "integrity": {"errors": errors, "warnings": warnings},
    }
    if contract:
        for field in INTEGRATION_FIELDS:
            bundle[field] = contract.get(field)
        bundle["default_source"] = None
    else:
        for field in INTEGRATION_FIELDS:
            bundle[field] = None
        bundle["default_source"] = "profile+gear"
    return bundle


def _read_snapshot(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON snapshot path, or '-' for stdin")
    args = parser.parse_args(argv)
    data = _read_snapshot(args.input)
    bundle = build_context_bundle(
        issue=data["issue"],
        root=data.get("root"),
        owner=data.get("owner"),
        repo=data.get("repo"),
        wiki_task_record=data.get("wiki_task_record"),
        blockers=data.get("blockers"),
        downstream=data.get("downstream"),
        worktree_path=data.get("worktree_path"),
        integration_contract=data.get("integration_contract"),
    )
    print(json.dumps(bundle, ensure_ascii=False))
    return 0 if bundle["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
