#!/usr/bin/env python3
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"
WORKFLOW_FILE = ROOT / "config" / "workflow.json"
NOTIFY_SCRIPT = ROOT / "scripts" / "notify_slack.py"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def normalize_tasks_data(data):
    if isinstance(data, list):
        return {"tasks": data}
    if isinstance(data, dict):
        data.setdefault("tasks", [])
        return data
    return {"tasks": []}


def find_task(tasks_data: dict, task_id: str):
    for task in tasks_data.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def validate_status_transition(workflow: dict, current_status: str, new_status: str) -> None:
    allowed = workflow.get("transitions", {}).get(current_status, [])
    if new_status not in allowed:
        print(f"Invalid transition: {current_status} -> {new_status}")
        sys.exit(2)


def validate_owner_handoff(workflow: dict, current_owner: str, new_owner: str) -> None:
    if current_owner == new_owner:
        return

    allowed_handoffs = workflow.get("allowed_handoffs", {})
    allowed_targets = allowed_handoffs.get(current_owner, [])
    if new_owner not in allowed_targets:
        print(f"Invalid owner handoff: {current_owner} -> {new_owner}")
        sys.exit(4)


def validate_default_owner(workflow: dict, new_status: str, new_owner: str) -> None:
    default_owner = workflow.get("default_owner_by_state", {}).get(new_status)
    if default_owner and default_owner != new_owner:
        print(
            f"Invalid owner for status '{new_status}': "
            f"expected '{default_owner}', got '{new_owner}'"
        )
        sys.exit(5)


def notify(agent: str, event: str, task_id: str, status: str, owner: str, message: str = "") -> None:
    try:
        subprocess.run(
            [
                sys.executable,
                str(NOTIFY_SCRIPT),
                agent,
                event,
                task_id,
                status,
                owner,
                message,
            ],
            check=False,
            cwd=str(ROOT),
        )
    except Exception as e:
        print(f"[WARN] slack notify failed: {e}")


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 scripts/handoff_task.py <task_id> <new_status> <new_owner>")
        sys.exit(1)

    task_id, new_status, new_owner = sys.argv[1:4]

    tasks_raw = load_json(TASKS_FILE)
    tasks_data = normalize_tasks_data(tasks_raw)
    workflow = load_json(WORKFLOW_FILE)

    task = find_task(tasks_data, task_id)
    if not task:
        print(f"Task not found: {task_id}")
        sys.exit(3)

    current_status = task.get("status")
    current_owner = task.get("owner")

    validate_status_transition(workflow, current_status, new_status)
    validate_owner_handoff(workflow, current_owner, new_owner)
    validate_default_owner(workflow, new_status, new_owner)

    timestamp = now_iso()
    action_name = "status_updated" if current_owner == new_owner else "handoff"

    history_item = {
        "at": timestamp,
        "action": action_name,
        "from_status": current_status,
        "to_status": new_status,
        "from_owner": current_owner,
        "to_owner": new_owner,
        "by": "system",
    }

    task["status"] = new_status
    task["owner"] = new_owner
    task["updated_at"] = timestamp
    task.setdefault("history", []).append(history_item)

    save_json(TASKS_FILE, tasks_data)

    if action_name == "status_updated":
        if new_owner in {"editor", "reviewer"}:
            notify(
                new_owner,
                "status_updated",
                task_id,
                new_status,
                new_owner,
                f"任务状态已更新：{current_status} -> {new_status}"
            )
    else:
        if new_owner in {"editor", "reviewer"}:
            notify(
                new_owner,
                "handoff",
                task_id,
                new_status,
                new_owner,
                f"{current_owner} 已将任务交给 {new_owner}：{current_status} -> {new_status}"
            )

    print(json.dumps(task, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()