#!/usr/bin/env python3
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"
NOTIFY_SCRIPT = ROOT / "scripts" / "notify_slack.py"
SLACK_THREAD_REPLY_SCRIPT = ROOT / "scripts" / "slack_thread_reply.py"

VALID = {
    "approved": "done",
    "done": "done",
    "revision_required": "revision_required",
    "blocked": "blocked"
}


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


def reply_to_task_origin(task_id: str) -> None:
    try:
        subprocess.run(
            [sys.executable, str(SLACK_THREAD_REPLY_SCRIPT), task_id],
            check=False,
            cwd=str(ROOT),
        )
    except Exception as e:
        print(f"[WARN] slack thread reply failed: {e}")


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 scripts/review_task.py <task_id> <approved|done|revision_required|blocked> <comment>")
        sys.exit(1)

    task_id = sys.argv[1]
    decision = sys.argv[2]
    comment = sys.argv[3]

    if decision not in VALID:
        print("Decision must be one of: approved, done, revision_required, blocked")
        sys.exit(2)

    new_status = VALID[decision]

    if new_status == "revision_required":
        new_owner = "editor"
    elif new_status == "done":
        new_owner = "user"
    else:
        new_owner = "reviewer"

    raw = load_json(TASKS_FILE)
    data = normalize_tasks_data(raw)

    for task in data.get("tasks", []):
        if task.get("id") != task_id:
            continue

        current_status = task.get("status")
        current_owner = task.get("owner")

        if current_status != "in_review":
            print(f"Task {task_id} is not in review state: current_status={current_status}")
            sys.exit(4)

        if current_owner != "reviewer":
            print(f"Task {task_id} is not owned by reviewer: current_owner={current_owner}")
            sys.exit(5)

        timestamp = now_iso()

        task["status"] = new_status
        task["owner"] = new_owner
        task["review_notes"] = comment
        task["updated_at"] = timestamp

        task.setdefault("history", []).append({
            "at": timestamp,
            "action": "reviewed",
            "by": "reviewer",
            "from_status": current_status,
            "to_status": new_status,
            "from_owner": current_owner,
            "to_owner": new_owner,
            "note": comment
        })

        save_json(TASKS_FILE, data)

        if new_status == "revision_required":
            notify(
                "editor",
                "reviewed",
                task_id,
                new_status,
                new_owner,
                f"reviewer 打回：{comment}"
            )
        elif new_status == "done":
            notify(
                "reviewer",
                "done",
                task_id,
                new_status,
                new_owner,
                f"任务已审核通过：{comment}"
            )
        elif new_status == "blocked":
            notify(
                "reviewer",
                "blocked",
                task_id,
                new_status,
                new_owner,
                f"任务阻塞：{comment}"
            )

        if new_status in {"done", "revision_required", "blocked"}:
            reply_to_task_origin(task_id)

        print(json.dumps(task, ensure_ascii=False, indent=2))
        return

    print(f"Task not found: {task_id}")
    sys.exit(3)


if __name__ == "__main__":
    main()