#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    write_json(ROOT / "data" / "tasks.json", {"tasks": []})
    write_json(ROOT / "runtime" / "state.json", {
        "last_scan_at": None,
        "task_count": 0,
        "tasks_by_state": {},
        "last_notified_task_ids": []
    })
    print("Project initialized.")


if __name__ == "__main__":
    main()
