#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from slack_sdk import WebClient


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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


def build_reply_text(task: dict) -> str:
    task_id = task.get("id", "unknown")
    status = task.get("status", "unknown")
    title = (task.get("title") or "").strip()
    result = (task.get("result") or "").strip()
    review_notes = (task.get("review_notes") or "").strip()

    if status == "done":
        parts = [
            f"多 agent 任务已完成：`{task_id}`",
        ]
        if title:
            parts.append(f"标题：{title}")
        if result:
            parts.extend(["", "结果：", result])
        if review_notes:
            parts.extend(["", "reviewer 意见：", review_notes])
        return "\n".join(parts)

    if status == "blocked":
        if review_notes:
            return f"多 agent 任务已 blocked：`{task_id}`\n原因：{review_notes}"
        return f"多 agent 任务已 blocked：`{task_id}`"

    return f"任务状态更新：`{task_id}` status={status}"


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/slack_thread_reply.py <task_id>")
        sys.exit(1)

    load_dotenv(ROOT / ".env")

    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        print("Missing SLACK_BOT_TOKEN")
        sys.exit(2)

    task_id = sys.argv[1]
    raw = load_json(TASKS_FILE)
    tasks_data = normalize_tasks_data(raw)
    task = find_task(tasks_data, task_id)
    if not task:
        print(f"Task not found: {task_id}")
        sys.exit(3)

    meta = task.get("meta") or {}
    if meta.get("source") != "slack":
        print("skip: non-slack task")
        return

    channel = meta.get("channel")
    thread_ts = meta.get("thread_ts")
    if not channel or not thread_ts:
        print("skip: missing channel/thread_ts")
        return

    client = WebClient(token=token)
    text = build_reply_text(task)
    client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
    print("sent")


if __name__ == "__main__":
    main()
