#!/usr/bin/env python3
import json
import os
import re
import subprocess
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


ROOT = Path(__file__).resolve().parents[1]

app = App(token=os.environ["SLACK_BOT_TOKEN"])

MULTI_AGENT_PREFIX = "/ma"


def run_cmd(cmd: list[str]) -> str:
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
    return result.stdout.strip()


def strip_mention(text: str) -> str:
    return re.sub(r"^\s*<@[\w]+>\s*", "", text).strip()


def should_use_multi_agent(text: str) -> bool:
    return text.strip().startswith(MULTI_AGENT_PREFIX)


def extract_multi_agent_task(text: str) -> str:
    text = text.strip()
    if text.startswith(MULTI_AGENT_PREFIX):
        return text[len(MULTI_AGENT_PREFIX):].strip()
    return text


def create_task(text: str, event: dict) -> dict:
    text = text.strip()
    if not text:
        raise RuntimeError("empty task text")

    title = text[:60]
    meta = {
        "source": "slack",
        "channel": event.get("channel"),
        "thread_ts": event.get("thread_ts") or event.get("ts"),
        "user": event.get("user"),
    }

    out = run_cmd([
        "python",
        "scripts/create_task.py",
        title,
        text,
        json.dumps(meta, ensure_ascii=False)
    ])

    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"create_task.py returned invalid JSON: {out}") from e

    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError(f"create_task.py returned unexpected payload: {out}")

    return data


def normal_reply(text: str) -> str:
    text = text.strip()

    if text in ["你好", "您好", "hi", "hello"]:
        return "你好～我在。想让我帮你做什么？"

    if text in ["在吗", "在吗？", "在么", "在？"]:
        return "在，我在。"

    return (
        "我在。\n"
        f"普通聊天我会直接回复；如果你要进入多 agent 流程，请用：`{MULTI_AGENT_PREFIX} 你的任务`"
    )


def process_message(text: str, event: dict, say, thread_ts: str) -> None:
    if not text:
        say("请直接输入内容。", thread_ts=thread_ts)
        return

    if not should_use_multi_agent(text):
        say(normal_reply(text), thread_ts=thread_ts)
        return

    task_text = extract_multi_agent_task(text)
    if not task_text:
        say(
            f"请在 `{MULTI_AGENT_PREFIX}` 后面写具体任务，例如：`{MULTI_AGENT_PREFIX} 写一份产品发布稿`",
            thread_ts=thread_ts,
        )
        return

    say("已收到，任务正在入队。", thread_ts=thread_ts)

    try:
        task = create_task(task_text, event)
        task_id = task["id"]

        say(
            f"任务已创建：`{task_id}`\n"
            f"标题：{task.get('title', '')}\n"
            f"已进入多 agent 队列，等待 orchestrator 处理。",
            thread_ts=thread_ts,
        )

    except Exception as e:
        say(
            f"执行失败：```{type(e).__name__}: {str(e)}```",
            thread_ts=thread_ts,
        )


@app.event("app_mention")
def on_app_mention(event, say):
    text = strip_mention(event.get("text", ""))
    thread_ts = event.get("thread_ts") or event["ts"]
    process_message(text, event, say, thread_ts)


@app.event("message")
def on_dm_message(event, say):
    if event.get("channel_type") != "im":
        return
    if event.get("subtype"):
        return
    if event.get("bot_id"):
        return

    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts") or event["ts"]
    process_message(text, event, say, thread_ts)


def start_slack_listener() -> None:
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()