#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = ROOT / "data" / "tasks.json"

def load_tasks():
    return json.loads(TASK_FILE.read_text())

def run(cmd):
    subprocess.run(cmd, shell=True)

def process_editor(task):
    tid = task["id"]
    status = task["status"]

    if status == "new":
        run(f"python {ROOT}/scripts/handoff_task.py {tid} in_progress editor")

    elif status in ["in_progress", "revision_required"]:
        run(f"python {ROOT}/scripts/handoff_task.py {tid} in_review reviewer")

def process_reviewer(task):
    tid = task["id"]
    status = task["status"]

    if status == "in_review":
        run(f'python {ROOT}/scripts/review_task.py {tid} done "auto review pass"')

def main():

    while True:

        tasks = load_tasks()["tasks"]

        for t in tasks:

            owner = t["owner"]

            if owner == "editor":
                process_editor(t)

            elif owner == "reviewer":
                process_reviewer(t)

        time.sleep(10)


if __name__ == "__main__":
    main()