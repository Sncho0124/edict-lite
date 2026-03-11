#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_json(cmd: list[str]) -> dict:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON from command: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}"
        ) from e


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_pipeline_for_task.py <task_id>")
        sys.exit(1)

    task_id = sys.argv[1]

    editor_result = run_json(["python", "scripts/run_editor_agent.py", task_id])
    reviewer_result = run_json(["python", "scripts/run_reviewer_agent.py", task_id])

    final = {
        "task_id": task_id,
        "editor": editor_result,
        "reviewer": reviewer_result,
        "status": "done",
    }

    print(json.dumps(final, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()