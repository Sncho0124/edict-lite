#!/usr/bin/env python3
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"
STATE_FILE = ROOT / "runtime" / "state.json"

HANDOFF_SCRIPT = ROOT / "scripts" / "handoff_task.py"
REVIEW_SCRIPT = ROOT / "scripts" / "review_task.py"
EDITOR_AGENT_SCRIPT = ROOT / "scripts" / "run_editor_agent.py"
REVIEWER_AGENT_SCRIPT = ROOT / "scripts" / "run_reviewer_agent.py"

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


def run_cmd(args: list[str]) -> bool:
    try:
        result = subprocess.run(args, cwd=str(ROOT), check=False)
        return result.returncode == 0
    except Exception as e:
        print(f"[ERROR] command failed: {args} | {e}")
        return False


def run_cmd_json(args: list[str]):
    try:
        result = subprocess.run(
            args,
            cwd=str(ROOT),
            check=False,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"[ERROR] command failed: {args}")
            if result.stdout:
                print(result.stdout.strip())
            if result.stderr:
                print(result.stderr.strip())
            return None

        stdout = (result.stdout or "").strip()
        if not stdout:
            print(f"[ERROR] empty stdout from command: {args}")
            return None

        return json.loads(stdout)
    except Exception as e:
        print(f"[ERROR] command json failed: {args} | {e}")
        return None


def process_editor_task(task: dict) -> None:
    task_id = task.get("id")
    status = task.get("status")

    if status == "new":
        print(f"[editor] starting task {task_id}")
        ok = run_cmd([sys.executable, str(HANDOFF_SCRIPT), task_id, "in_progress", "editor"])
        if not ok:
            return
        status = "in_progress"

    if status in {"in_progress", "revision_required"}:
        if status == "revision_required":
            print(f"[editor] resuming revised task {task_id}")
            ok = run_cmd([sys.executable, str(HANDOFF_SCRIPT), task_id, "in_progress", "editor"])
            if not ok:
                return

        print(f"[editor] generating result for task {task_id}")
        editor_output = run_cmd_json([sys.executable, str(EDITOR_AGENT_SCRIPT), task_id])
        if not editor_output:
            return

        print(f"[editor] generated summary: {editor_output.get('summary', '')}")
        print(f"[editor] handing task to reviewer {task_id}")
        run_cmd([sys.executable, str(HANDOFF_SCRIPT), task_id, "in_review", "reviewer"])


def process_reviewer_task(task: dict) -> None:
    task_id = task.get("id")
    status = task.get("status")

    if status != "in_review":
        return

    print(f"[reviewer] reviewing task {task_id}")
    review_output = run_cmd_json([sys.executable, str(REVIEWER_AGENT_SCRIPT), task_id])
    if not review_output:
        return

    decision = review_output.get("review_decision")
    notes = review_output.get("review_notes", "")

    if decision not in {"done", "revision_required", "blocked"}:
        print(f"[ERROR] invalid review_decision for task {task_id}: {decision}")
        return

    print(f"[reviewer] decision={decision} task={task_id}")
    run_cmd([
        sys.executable,
        str(REVIEW_SCRIPT),
        task_id,
        decision,
        notes
    ])


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


def scan_and_process_once() -> None:
    raw = load_json(TASKS_FILE, {"tasks": []})
    tasks_data = normalize_tasks_data(raw)
    tasks = tasks_data.get("tasks", [])

    classified = classify_tasks(tasks)

    print(f"\n[{now_iso()}] scanned {len(tasks)} tasks")
    print_section("editor_queue", classified["editor_queue"])
    print_section("reviewer_queue", classified["reviewer_queue"])
    print_section("blocked_tasks", classified["blocked_tasks"])
    print_stale_section(classified["stale_tasks"])

    for task in classified["editor_queue"]:
        process_editor_task(task)

    raw_after_editor = load_json(TASKS_FILE, {"tasks": []})
    tasks_data_after_editor = normalize_tasks_data(raw_after_editor)
    tasks_after_editor = tasks_data_after_editor.get("tasks", [])
    classified_after_editor = classify_tasks(tasks_after_editor)

    for task in classified_after_editor["reviewer_queue"]:
        if task.get("status") == "in_review":
            process_reviewer_task(task)

    raw_final = load_json(TASKS_FILE, {"tasks": []})
    tasks_data_final = normalize_tasks_data(raw_final)
    tasks_final = tasks_data_final.get("tasks", [])
    classified_final = classify_tasks(tasks_final)
    state = build_state(tasks_final, classified_final)
    save_json(STATE_FILE, state)


def main():
    print("Starting edict-lite orchestrator...")
    print(f"- tasks file: {TASKS_FILE}")
    print(f"- state file: {STATE_FILE}")
    print(f"- scan interval: {SCAN_INTERVAL_SECONDS}s")

    while True:
        try:
            scan_and_process_once()
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"\n[ERROR] orchestrator failed: {e}")

        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()