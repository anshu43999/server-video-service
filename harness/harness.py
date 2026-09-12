#!/usr/bin/env python3
"""Task and acceptance harness for the server-video-service project."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = REPO_ROOT / "harness"
DEFAULT_STATE_PATH = HARNESS_ROOT / "task-state.json"
VALID_STATUSES = {
    "pending",
    "in_progress",
    "blocked",
    "completed",
    "superseded",
}
# Terminal statuses close out a subtask: either the work was delivered, or the
# task definition itself was retired. Both allow a major task to be accepted.
TERMINAL_STATUSES = {"completed", "superseded"}
# Only work that will never be delivered may be superseded. Completed work
# stays completed so its record and evidence remain historically accurate.
SUPERSEDABLE_STATUSES = {"pending", "in_progress", "blocked"}
ID_PATTERN = re.compile(r"^M\d{2}(?:-T\d{2})?$")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class HarnessError(RuntimeError):
    """Expected command error with a concise user-facing message."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HarnessError(f"State file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Invalid JSON in {path}: {exc}") from exc


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    state["updatedAt"] = now_iso()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temp_path.replace(path)


def build_index(
    state: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    index: dict[str, dict[str, Any]] = {}
    parents: dict[str, str] = {}
    for major in state.get("majorTasks", []):
        major_id = major.get("id", "")
        if major_id in index:
            raise HarnessError(f"Duplicate task id: {major_id}")
        index[major_id] = major
        for task in major.get("subtasks", []):
            task_id = task.get("id", "")
            if task_id in index:
                raise HarnessError(f"Duplicate task id: {task_id}")
            index[task_id] = task
            parents[task_id] = major_id
    return index, parents


def find_item(
    state: dict[str, Any], item_id: str
) -> tuple[dict[str, Any], str | None]:
    index, parents = build_index(state)
    item = index.get(item_id)
    if item is None:
        raise HarnessError(f"Unknown task id: {item_id}")
    return item, parents.get(item_id)


def is_completed(item_id: str, index: dict[str, dict[str, Any]]) -> bool:
    item = index.get(item_id)
    return item is not None and item.get("status") == "completed"


def unmet_dependencies(
    item: dict[str, Any], index: dict[str, dict[str, Any]]
) -> list[str]:
    return [
        dependency
        for dependency in item.get("dependsOn", [])
        if not is_completed(dependency, index)
    ]


def safe_repo_path(relative_path: str, repo_root: Path = REPO_ROOT) -> Path:
    candidate = (repo_root / relative_path).resolve()
    root = repo_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HarnessError(f"Path escapes repository: {relative_path}") from exc
    return candidate


def acceptance_passed(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    return bool(re.search(r"(?mi)^result:\s*passed\s*$", content))


def dependency_cycles(index: dict[str, dict[str, Any]]) -> list[list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(item_id: str) -> None:
        if item_id in visited:
            return
        if item_id in visiting:
            start = stack.index(item_id)
            cycles.append(stack[start:] + [item_id])
            return
        visiting.add(item_id)
        stack.append(item_id)
        for dependency in index[item_id].get("dependsOn", []):
            if dependency in index:
                visit(dependency)
        stack.pop()
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in index:
        visit(item_id)
    return cycles


def validate_state(
    state: dict[str, Any], repo_root: Path = REPO_ROOT
) -> list[str]:
    errors: list[str] = []
    if state.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not state.get("project"):
        errors.append("project is required")

    try:
        index, parents = build_index(state)
    except HarnessError as exc:
        return [str(exc)]

    for item_id, item in index.items():
        if not ID_PATTERN.fullmatch(item_id):
            errors.append(f"Invalid task id: {item_id}")
        status = item.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"{item_id}: invalid status {status!r}")
        if not item.get("title"):
            errors.append(f"{item_id}: title is required")
        for dependency in item.get("dependsOn", []):
            if dependency not in index:
                errors.append(f"{item_id}: missing dependency {dependency}")
            elif dependency == item_id:
                errors.append(f"{item_id}: cannot depend on itself")

        if status == "superseded":
            if not item.get("supersededReason"):
                errors.append(f"{item_id}: supersededReason is required")
            if not item.get("supersededAt"):
                errors.append(f"{item_id}: supersededAt is required")
            replacement = item.get("supersededBy")
            if replacement is not None and replacement not in index:
                errors.append(
                    f"{item_id}: unknown supersededBy target {replacement}"
                )

        if item_id in parents:
            record = item.get("record")
            acceptance = item.get("acceptance")
            if not record:
                errors.append(f"{item_id}: record path is required")
            else:
                try:
                    record_path = safe_repo_path(record, repo_root)
                    if status == "completed" and not record_path.exists():
                        errors.append(
                            f"{item_id}: completed task record missing: {record}"
                        )
                except HarnessError as exc:
                    errors.append(f"{item_id}: {exc}")
            if not acceptance:
                errors.append(f"{item_id}: acceptance criterion is required")
            if status == "completed":
                for dependency in item.get("dependsOn", []):
                    dependency_item = index.get(dependency)
                    if (
                        dependency_item is not None
                        and dependency_item.get("status") != "completed"
                    ):
                        errors.append(
                            f"{item_id}: completed before dependency {dependency}"
                        )
        else:
            acceptance_document = item.get("acceptanceDocument")
            if not acceptance_document:
                errors.append(f"{item_id}: acceptanceDocument is required")
            else:
                try:
                    acceptance_path = safe_repo_path(
                        acceptance_document, repo_root
                    )
                    if status == "completed" and not acceptance_passed(
                        acceptance_path
                    ):
                        errors.append(
                            f"{item_id}: completed major task requires a passed "
                            f"acceptance document: {acceptance_document}"
                        )
                except HarnessError as exc:
                    errors.append(f"{item_id}: {exc}")
            subtasks = item.get("subtasks", [])
            if not subtasks:
                errors.append(f"{item_id}: at least one subtask is required")
            if status == "completed":
                unresolved = [
                    task.get("id", "")
                    for task in subtasks
                    if task.get("status") not in TERMINAL_STATUSES
                ]
                if unresolved:
                    errors.append(
                        f"{item_id}: completed with unresolved subtasks: "
                        + ", ".join(unresolved)
                    )
                if subtasks and all(
                    task.get("status") == "superseded" for task in subtasks
                ):
                    errors.append(
                        f"{item_id}: completed with every subtask superseded; "
                        "retire the major task definition instead"
                    )

    for cycle in dependency_cycles(index):
        errors.append("Dependency cycle: " + " -> ".join(cycle))
    return errors


def dependency_guard(
    item: dict[str, Any],
    parent_id: str | None,
    index: dict[str, dict[str, Any]],
) -> None:
    unmet = unmet_dependencies(item, index)
    if parent_id is not None:
        parent_unmet = unmet_dependencies(index[parent_id], index)
        unmet.extend(parent_unmet)
    if unmet:
        raise HarnessError(
            "Unmet dependencies: " + ", ".join(dict.fromkeys(unmet))
        )


def list_lines(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def write_completion_record(
    task: dict[str, Any],
    major: dict[str, Any],
    summary: str,
    evidence: list[str],
    tests: list[str],
    owner: str,
    repo_root: Path = REPO_ROOT,
) -> Path:
    record_path = safe_repo_path(task["record"], repo_root)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    if record_path.exists():
        raise HarnessError(f"Record already exists: {task['record']}")
    completed_at = now_iso()
    started_at = task.get("startedAt", "not-recorded")
    content = f"""---
task_id: {task['id']}
major_task_id: {major['id']}
status: completed
owner: {owner}
started_at: {started_at}
completed_at: {completed_at}
---

# {task['id']} {task['title']}

## 完成摘要

{summary}

## 完成标准

{task['acceptance']}

## 测试结果

{list_lines(tests)}

## 证据

{list_lines(evidence)}

## 遗留问题

- 无；如有遗留问题，必须在此处明确记录并创建后续任务。
"""
    record_path.write_text(content, encoding="utf-8", newline="\n")
    return record_path


def write_block_record(
    task: dict[str, Any], major: dict[str, Any], reason: str, owner: str
) -> Path:
    completion_path = safe_repo_path(task["record"])
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    record_path = completion_path.with_name(
        f"{completion_path.stem}.blocked-{timestamp}{completion_path.suffix}"
    )
    record_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""---
task_id: {task['id']}
major_task_id: {major['id']}
status: blocked
owner: {owner}
updated_at: {now_iso()}
---

# {task['id']} {task['title']}

## 阻塞原因

{reason}

## 解除条件

- 需要在继续任务前补充明确解除条件。
"""
    record_path.write_text(content, encoding="utf-8", newline="\n")
    return record_path


def write_supersede_record(
    task: dict[str, Any],
    major: dict[str, Any],
    reason: str,
    owner: str,
    superseded_by: str | None = None,
    previous_status: str = "not-recorded",
    repo_root: Path = REPO_ROOT,
) -> Path:
    completion_path = safe_repo_path(task["record"], repo_root)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    record_path = completion_path.with_name(
        f"{completion_path.stem}.superseded-{timestamp}{completion_path.suffix}"
    )
    record_path.parent.mkdir(parents=True, exist_ok=True)
    replacement = superseded_by or "无；该任务范围整体作废，没有单一替代任务。"
    content = f"""---
task_id: {task['id']}
major_task_id: {major['id']}
status: superseded
previous_status: {previous_status}
owner: {owner}
superseded_by: {superseded_by or 'none'}
superseded_at: {now_iso()}
---

# {task['id']} {task['title']}

## 终止原因

{reason}

## 原完成标准

{task.get('acceptance', '未记录')}

## 替代任务

{replacement}

## 说明

该任务因架构或范围变更而作废，不再执行，也不计入完成。本记录保留任务定义与终止决策；既有完成记录、阻塞记录和验收证据一律保留，不得删除。
"""
    record_path.write_text(content, encoding="utf-8", newline="\n")
    return record_path


def subtask_record_link(
    task: dict[str, Any], major_id: str, repo_root: Path = REPO_ROOT
) -> str:
    """Link a subtask row to a record that actually exists on disk."""
    record = task.get("record")
    if not record:
        return "待补充"
    record_path = safe_repo_path(record, repo_root)
    if record_path.exists():
        return f"[{record_path.name}](../records/{major_id}/{record_path.name})"
    variants = sorted(
        record_path.parent.glob(f"{record_path.stem}.*{record_path.suffix}")
    )
    if variants:
        name = variants[-1].name
        return f"[{name}](../records/{major_id}/{name})"
    return "待补充"


def write_major_acceptance(
    major: dict[str, Any],
    result: str,
    summary: str,
    evidence: list[str],
    tests: list[str],
    owner: str,
) -> Path:
    acceptance_path = safe_repo_path(major["acceptanceDocument"])
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    result_cn = "通过" if result == "passed" else "不通过"
    task_rows = "\n".join(
        f"| {task['id']} | {task['title']} | {task['status']} | "
        f"{subtask_record_link(task, major['id'])} |"
        for task in major.get("subtasks", [])
    )
    criteria = "\n".join(
        f"- [x] {criterion}" if result == "passed" else f"- [ ] {criterion}"
        for criterion in major.get("acceptanceCriteria", [])
    )
    content = f"""---
major_task_id: {major['id']}
result: {result}
owner: {owner}
accepted_at: {now_iso()}
---

# {major['id']} {major['title']}测试验收报告

## 验收结论

**{result_cn}**

{summary}

## 验收标准

{criteria}

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
{task_rows}

## 测试结果

{list_lines(tests)}

## 验收证据

{list_lines(evidence)}

## 遗留风险

- 无；若存在遗留风险，必须在正式通过前改写本节并给出责任人和截止日期。
"""
    acceptance_path.write_text(content, encoding="utf-8", newline="\n")
    return acceptance_path


def status_symbol(status: str) -> str:
    return {
        "pending": "[ ]",
        "in_progress": "[~]",
        "blocked": "[!]",
        "completed": "[x]",
        "superseded": "[-]",
    }.get(status, "[?]")


def render_board(
    state: dict[str, Any], output_path: Path | None = None
) -> Path:
    output = output_path or (HARNESS_ROOT / "TASK_BOARD.md")
    lines = [
        "# Harness任务板",
        "",
        "> 本文件由`python harness/harness.py render`生成，请勿手工修改。  ",
        f"> 更新时间：{state.get('updatedAt', '')}",
        "",
        "状态：`[ ] pending`、`[~] in_progress`、`[!] blocked`、`[x] completed`、"
        "`[-] superseded`。",
        "",
        "> `superseded`表示任务定义因架构或范围变更而作废：不再执行，也不计入完成。",
        "> 终止原因见`harness/records/<大任务>/<任务>.superseded-*.md`。",
        "",
    ]
    for major in state.get("majorTasks", []):
        lines.extend(
            [
                f"## {status_symbol(major['status'])} {major['id']} {major['title']}",
                "",
                f"大任务状态：`{major['status']}`  ",
                "依赖："
                + (", ".join(major.get("dependsOn", [])) or "无")
                + "  ",
                f"验收文档：`{major['acceptanceDocument']}`",
                "",
                "| 状态 | ID | 小任务 | 依赖 | 完成标准 |",
                "|---|---|---|---|---|",
            ]
        )
        for task in major.get("subtasks", []):
            dependencies = ", ".join(task.get("dependsOn", [])) or "无"
            lines.append(
                f"| {status_symbol(task['status'])} | {task['id']} | "
                f"{task['title']} | {dependencies} | {task['acceptance']} |"
            )
        lines.append("")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return output


def command_status(state: dict[str, Any], _args: argparse.Namespace) -> None:
    for major in state.get("majorTasks", []):
        tasks = major.get("subtasks", [])
        completed = sum(task.get("status") == "completed" for task in tasks)
        blocked = sum(task.get("status") == "blocked" for task in tasks)
        superseded = sum(task.get("status") == "superseded" for task in tasks)
        line = (
            f"{status_symbol(major['status'])} {major['id']} "
            f"{major['title']}: {completed}/{len(tasks)} completed, "
            f"{blocked} blocked"
        )
        if superseded:
            line += f", {superseded} superseded"
        print(line)


def command_next(state: dict[str, Any], _args: argparse.Namespace) -> None:
    index, parents = build_index(state)
    ready: list[tuple[str, str]] = []
    for task_id, parent_id in parents.items():
        task = index[task_id]
        if task.get("status") != "pending":
            continue
        if unmet_dependencies(task, index):
            continue
        if unmet_dependencies(index[parent_id], index):
            continue
        ready.append((task_id, task["title"]))
    if not ready:
        print("No ready pending tasks.")
        return
    for task_id, title in ready:
        print(f"{task_id} {title}")


def command_start(state: dict[str, Any], args: argparse.Namespace) -> None:
    item, parent_id = find_item(state, args.task_id)
    if parent_id is None:
        raise HarnessError("Start a subtask, not a major task")
    if item.get("status") not in {"pending", "blocked"}:
        raise HarnessError(
            f"{args.task_id} cannot start from status {item.get('status')}"
        )
    index, _ = build_index(state)
    dependency_guard(item, parent_id, index)
    item["status"] = "in_progress"
    item["owner"] = args.owner
    item["startedAt"] = now_iso()
    item.pop("blocker", None)
    item.pop("blockedAt", None)
    parent = index[parent_id]
    if parent.get("status") == "pending":
        parent["status"] = "in_progress"
        parent["startedAt"] = now_iso()
    save_state(state)
    render_board(state)
    print(f"Started {args.task_id}: {item['title']}")


def command_add(state: dict[str, Any], args: argparse.Namespace) -> None:
    """Add a pending subtask through the governed CLI.

    This is intentionally a planning operation: it never starts work and it
    always regenerates TASK_BOARD.md after updating the state source.
    """
    parent, parent_id = find_item(state, args.parent)
    if parent_id is not None:
        raise HarnessError("add requires a major task parent id")
    if not ID_PATTERN.fullmatch(args.task_id) or "-T" not in args.task_id:
        raise HarnessError(f"Invalid subtask id: {args.task_id}")
    index, _ = build_index(state)
    if args.task_id in index:
        raise HarnessError(f"Task id already exists: {args.task_id}")
    dependencies = list(args.depends_on or [])
    for dependency in dependencies:
        if dependency not in index:
            raise HarnessError(f"Unknown dependency: {dependency}")
        if dependency == args.task_id:
            raise HarnessError("A task cannot depend on itself")
    task = {
        "id": args.task_id,
        "title": args.title,
        "status": "pending",
        "dependsOn": dependencies,
        "acceptance": args.acceptance,
        "record": args.record or f"harness/records/{args.parent}/{args.task_id}.md",
    }
    parent.setdefault("subtasks", []).append(task)
    if parent.get("status") == "completed":
        parent["status"] = "in_progress"
        parent.pop("completedAt", None)
    save_state(state)
    render_board(state)
    print(f"Added {args.task_id} under {args.parent}: {args.title}")


def command_complete(state: dict[str, Any], args: argparse.Namespace) -> None:
    item, parent_id = find_item(state, args.task_id)
    if parent_id is None:
        raise HarnessError("Complete a subtask with this command")
    if item.get("status") != "in_progress":
        raise HarnessError(
            f"{args.task_id} must be in_progress, got {item.get('status')}"
        )
    index, _ = build_index(state)
    dependency_guard(item, parent_id, index)
    parent = index[parent_id]
    record_path = write_completion_record(
        item,
        parent,
        args.summary,
        args.evidence,
        args.test,
        args.owner or item.get("owner", "unassigned"),
    )
    item["status"] = "completed"
    item["completedAt"] = now_iso()
    item.pop("blocker", None)
    save_state(state)
    render_board(state)
    print(f"Completed {args.task_id}; record: {record_path.relative_to(REPO_ROOT)}")


def command_block(state: dict[str, Any], args: argparse.Namespace) -> None:
    item, parent_id = find_item(state, args.task_id)
    if parent_id is None:
        raise HarnessError("Block a subtask, not a major task")
    if item.get("status") == "completed":
        raise HarnessError("A completed task cannot be blocked")
    if item.get("status") == "superseded":
        raise HarnessError("A superseded task cannot be blocked")
    index, _ = build_index(state)
    parent = index[parent_id]
    item["status"] = "blocked"
    item["blocker"] = args.reason
    item["blockedAt"] = now_iso()
    owner = args.owner or item.get("owner", "unassigned")
    record_path = write_block_record(item, parent, args.reason, owner)
    if parent.get("status") == "pending":
        parent["status"] = "in_progress"
    save_state(state)
    render_board(state)
    print(f"Blocked {args.task_id}; record: {record_path.relative_to(REPO_ROOT)}")


def command_supersede(state: dict[str, Any], args: argparse.Namespace) -> None:
    item, parent_id = find_item(state, args.task_id)
    if parent_id is None:
        raise HarnessError("Supersede a subtask, not a major task")
    previous_status = item.get("status", "")
    if previous_status == "completed":
        raise HarnessError(
            f"{args.task_id} is completed; completed work keeps its record. "
            "Retire the follow-up work by revising the task definition instead."
        )
    if previous_status not in SUPERSEDABLE_STATUSES:
        raise HarnessError(
            f"{args.task_id} cannot be superseded from status {previous_status}"
        )
    index, _ = build_index(state)
    replacement = args.superseded_by
    if replacement is not None:
        if replacement not in index:
            raise HarnessError(f"Unknown supersededBy target: {replacement}")
        if replacement == args.task_id:
            raise HarnessError("A task cannot supersede itself")
    parent = index[parent_id]
    owner = args.owner or item.get("owner", "unassigned")
    record_path = write_supersede_record(
        item, parent, args.reason, owner, replacement, previous_status
    )
    item["status"] = "superseded"
    item["owner"] = owner
    item["supersededReason"] = args.reason
    item["supersededAt"] = now_iso()
    if replacement is not None:
        item["supersededBy"] = replacement
    item.pop("blocker", None)
    item.pop("blockedAt", None)
    save_state(state)
    render_board(state)
    print(
        f"Superseded {args.task_id}; record: "
        f"{record_path.relative_to(REPO_ROOT)}"
    )


def command_accept_major(state: dict[str, Any], args: argparse.Namespace) -> None:
    major, parent_id = find_item(state, args.major_id)
    if parent_id is not None:
        raise HarnessError("accept-major requires a major task id")
    subtasks = major.get("subtasks", [])
    unresolved = [
        task["id"]
        for task in subtasks
        if task.get("status") not in TERMINAL_STATUSES
    ]
    if unresolved:
        raise HarnessError(
            "Major task has unresolved subtasks: " + ", ".join(unresolved)
        )
    if subtasks and all(
        task.get("status") == "superseded" for task in subtasks
    ):
        raise HarnessError(
            "Every subtask is superseded; retire the major task definition "
            "instead of accepting it"
        )
    acceptance_path = write_major_acceptance(
        major,
        args.result,
        args.summary,
        args.evidence,
        args.test,
        args.owner,
    )
    major["status"] = "completed" if args.result == "passed" else "blocked"
    major["completedAt" if args.result == "passed" else "blockedAt"] = now_iso()
    save_state(state)
    render_board(state)
    print(
        f"Acceptance {args.result} for {args.major_id}: "
        f"{acceptance_path.relative_to(REPO_ROOT)}"
    )


def command_validate(state: dict[str, Any], _args: argparse.Namespace) -> None:
    errors = validate_state(state)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise HarnessError(f"Validation failed with {len(errors)} error(s)")
    print("Harness validation passed.")


def command_render(state: dict[str, Any], _args: argparse.Namespace) -> None:
    output = render_board(state)
    print(f"Rendered {output.relative_to(REPO_ROOT)}")


def command_show(state: dict[str, Any], args: argparse.Namespace) -> None:
    item, parent_id = find_item(state, args.item_id)
    print(json.dumps({"parent": parent_id, **item}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage small-task records and major-task acceptance gates."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show major task progress")
    subparsers.add_parser("next", help="List ready pending subtasks")
    subparsers.add_parser("validate", help="Validate state and required records")
    subparsers.add_parser("render", help="Regenerate the Markdown task board")

    show_parser = subparsers.add_parser("show", help="Show one task as JSON")
    show_parser.add_argument("item_id")

    start_parser = subparsers.add_parser("start", help="Start one subtask")
    start_parser.add_argument("task_id")
    start_parser.add_argument("--owner", required=True)

    add_parser = subparsers.add_parser(
        "add", help="Add a pending subtask to a major task"
    )
    add_parser.add_argument("task_id")
    add_parser.add_argument("--parent", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--acceptance", required=True)
    add_parser.add_argument("--depends-on", action="append", default=[])
    add_parser.add_argument("--record")

    complete_parser = subparsers.add_parser(
        "complete", help="Complete one subtask and create its record"
    )
    complete_parser.add_argument("task_id")
    complete_parser.add_argument("--summary", required=True)
    complete_parser.add_argument("--evidence", action="append", required=True)
    complete_parser.add_argument("--test", action="append", required=True)
    complete_parser.add_argument("--owner")

    block_parser = subparsers.add_parser(
        "block", help="Block one subtask and record the reason"
    )
    block_parser.add_argument("task_id")
    block_parser.add_argument("--reason", required=True)
    block_parser.add_argument("--owner")

    supersede_parser = subparsers.add_parser(
        "supersede",
        help="Retire one subtask whose definition is void after a scope change",
    )
    supersede_parser.add_argument("task_id")
    supersede_parser.add_argument("--reason", required=True)
    supersede_parser.add_argument("--owner", required=True)
    supersede_parser.add_argument(
        "--superseded-by",
        dest="superseded_by",
        help="Optional replacement task id that takes over this scope",
    )

    accept_parser = subparsers.add_parser(
        "accept-major", help="Create a major-task test acceptance report"
    )
    accept_parser.add_argument("major_id")
    accept_parser.add_argument("--result", choices=["passed", "failed"], required=True)
    accept_parser.add_argument("--summary", required=True)
    accept_parser.add_argument("--evidence", action="append", required=True)
    accept_parser.add_argument("--test", action="append", required=True)
    accept_parser.add_argument("--owner", required=True)
    return parser


COMMANDS = {
    "add": command_add,
    "status": command_status,
    "next": command_next,
    "start": command_start,
    "complete": command_complete,
    "block": command_block,
    "supersede": command_supersede,
    "accept-major": command_accept_major,
    "validate": command_validate,
    "render": command_render,
    "show": command_show,
}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        state = load_state()
        COMMANDS[args.command](state, args)
        return 0
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
