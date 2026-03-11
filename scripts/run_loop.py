#!/usr/bin/env python3
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"
STATE_FILE = ROOT / "runtime" / "state.json"

SCAN_INTERVAL_SECONDS = 10
STALE_IN_PROGRESS_SECONDS = 20 * 60
STALE_IN_REVIEW_SECONDS = 20 * 60
STALE_BLOCKED_SECONDS = 60 * 60


def now_utc():
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default
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


def parse_iso(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def age_seconds(updated_at: str):
    dt = parse_iso(updated_at)
    if not dt:
        return None
    return int((now_utc() - dt).total_seconds())


def summarize_task(task: dict) -> str:
    task_id = task.get("id", "unknown")
    status = task.get("status", "unknown")
    owner = task.get("owner", "unknown")
    title = task.get("title", "")
    age = age_seconds(task.get("updated_at"))
    age_text = f"{age}s" if age is not None else "unknown"
    return f"{task_id} | status={status} owner={owner} age={age_text} | {title}"


def classify_tasks(tasks: list[dict]) -> dict:
    editor_queue = []
    reviewer_queue = []
    blocked_tasks = []
    stale_tasks = []

    for task in tasks:
        status = task.get("status")
        owner = task.get("owner")
        age = age_seconds(task.get("updated_at"))

        if owner == "editor" and status in {"new", "in_progress", "revision_required"}:
            editor_queue.append(task)

        if owner == "reviewer" and status in {"in_review", "blocked"}:
            reviewer_queue.append(task)

        if status == "blocked":
            blocked_tasks.append(task)

        if age is not None:
            if status == "in_progress" and age > STALE_IN_PROGRESS_SECONDS:
                stale_tasks.append({
                    "id": task.get("id"),
                    "status": status,
                    "owner": owner,
                    "age_seconds": age,
                    "reason": "in_progress_timeout"
                })
            elif status == "in_review" and age > STALE_IN_REVIEW_SECONDS:
                stale_tasks.append({
                    "id": task.get("id"),
                    "status": status,
                    "owner": owner,
                    "age_seconds": age,
                    "reason": "in_review_timeout"
                })
            elif status == "blocked" and age > STALE_BLOCKED_SECONDS:
                stale_tasks.append({
                    "id": task.get("id"),
                    "status": status,
                    "owner": owner,
                    "age_seconds": age,
                    "reason": "blocked_too_long"
                })

    return {
        "editor_queue": editor_queue,
        "reviewer_queue": reviewer_queue,
        "blocked_tasks": blocked_tasks,
        "stale_tasks": stale_tasks
    }


def print_section(title: str, items: list[dict]) -> None:
    print(f"\n== {title} ({len(items)}) ==")
    if not items:
        print("- none")
        return

    for item in items:
        print(f"- {summarize_task(item)}")


def print_stale_section(stale_tasks: list[dict]) -> None:
    print(f"\n== stale_tasks ({len(stale_tasks)}) ==")
    if not stale_tasks:
        print("- none")
        return

    for item in stale_tasks:
        print(
            f"- {item['id']} | status={item['status']} owner={item['owner']} "
            f"age={item['age_seconds']}s reason={item['reason']}"
        )


def build_state(tasks: list[dict], classified: dict) -> dict:
    counts = Counter(task.get("status", "unknown") for task in tasks)

    return {
        "last_scan_at": now_iso(),
        "task_count": len(tasks),
        "tasks_by_state": dict(counts),
        "editor_queue_ids": [t.get("id") for t in classified["editor_queue"]],
        "reviewer_queue_ids": [t.get("id") for t in classified["reviewer_queue"]],
        "blocked_task_ids": [t.get("id") for t in classified["blocked_tasks"]],
        "stale_tasks": classified["stale_tasks"]
    }


def scan_once() -> None:
    raw = load_json(TASKS_FILE, {"tasks": []})
    tasks_data = normalize_tasks_data(raw)
    tasks = tasks_data.get("tasks", [])

    classified = classify_tasks(tasks)
    state = build_state(tasks, classified)
    save_json(STATE_FILE, state)

    print(f"\n[{state['last_scan_at']}] scanned {len(tasks)} tasks")
    print_section("editor_queue", classified["editor_queue"])
    print_section("reviewer_queue", classified["reviewer_queue"])
    print_section("blocked_tasks", classified["blocked_tasks"])
    print_stale_section(classified["stale_tasks"])


def main():
    print("Starting edict-lite run loop...")
    print(f"- tasks file: {TASKS_FILE}")
    print(f"- state file: {STATE_FILE}")
    print(f"- scan interval: {SCAN_INTERVAL_SECONDS}s")

    while True:
        try:
            scan_once()
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"\n[ERROR] run_loop scan failed: {e}")

        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()