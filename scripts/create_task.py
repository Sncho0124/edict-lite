#!/usr/bin/env python3
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_tasks() -> dict:
    if not TASKS_FILE.exists():
        return {"tasks": []}

    raw = json.loads(TASKS_FILE.read_text(encoding="utf-8"))

    if isinstance(raw, list):
        return {"tasks": raw}
    if isinstance(raw, dict):
        raw.setdefault("tasks", [])
        return raw

    return {"tasks": []}


def save_tasks(data: dict) -> None:
    TASKS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 scripts/create_task.py "task title"')
        sys.exit(1)

    title = sys.argv[1]
    task_input = sys.argv[2] if len(sys.argv) >= 3 else title

    data = load_tasks()
    timestamp = now_iso()

    task_meta = {}
    if len(sys.argv) >= 4:
        try:
            parsed_meta = json.loads(sys.argv[3])
            if isinstance(parsed_meta, dict):
                task_meta = parsed_meta
        except Exception:
            task_meta = {}

    task = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "input": task_input,
        "status": "new",
        "owner": "editor",
        "result": "",
        "review_notes": "",
        "meta": task_meta,
        "created_at": timestamp,
        "updated_at": timestamp,
        "history": [
            {
                "at": timestamp,
                "action": "created",
                "by": "system",
                "from_status": None,
                "to_status": "new",
                "from_owner": None,
                "to_owner": "editor",
                "note": title
            }
        ]
    }

    data.setdefault("tasks", []).append(task)
    save_tasks(data)
    print(json.dumps(task, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()