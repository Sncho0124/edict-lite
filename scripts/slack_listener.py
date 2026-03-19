#!/usr/bin/env python3
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "runtime" / "slack-listener-events.log"

app = App(token=os.environ["SLACK_BOT_TOKEN"])

DEFAULT_TRIGGER_BOT_USER_ID = "U0AKCGJ00A3"
MULTI_AGENT_PREFIX = "/ma"


def trigger_bot_user_id() -> str:
    return os.getenv("SLACK_TRIGGER_BOT_USER_ID", DEFAULT_TRIGGER_BOT_USER_ID).strip()


def trigger_mention() -> str:
    return f"<@{trigger_bot_user_id()}>"


def log_event(kind: str, payload: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "payload": payload,
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")



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


def strip_bot_mention(text: str) -> str:
    mention = re.escape(trigger_mention())
    return re.sub(rf"^\s*{mention}\s*", "", text).strip()


def contains_trigger_mention(text: str) -> bool:
    return trigger_mention() in (text or "")


def extract_task_text(text: str) -> str:
    text = strip_bot_mention(text).strip()
    if text.startswith(MULTI_AGENT_PREFIX):
        text = text[len(MULTI_AGENT_PREFIX):].strip()
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
        "trigger_bot_user_id": trigger_bot_user_id(),
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


def process_triggered_message(text: str, event: dict, say, thread_ts: str) -> None:
    log_event("process_triggered_message", {
        "channel": event.get("channel"),
        "channel_type": event.get("channel_type"),
        "user": event.get("user"),
        "thread_ts": thread_ts,
        "text": text,
        "trigger_mention": trigger_mention(),
        "contains_trigger": contains_trigger_mention(text),
    })
    if not contains_trigger_mention(text):
        return

    task_text = extract_task_text(text)
    if not task_text:
        say(
            f"请在 {trigger_mention()} 后面直接写任务内容。",
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
    log_event("app_mention", {
        "channel": event.get("channel"),
        "channel_type": event.get("channel_type"),
        "user": event.get("user"),
        "ts": event.get("ts"),
        "thread_ts": event.get("thread_ts"),
        "text": event.get("text", ""),
    })
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event["ts"]
    process_triggered_message(text, event, say, thread_ts)


@app.event("message")
def on_dm_message(event, say):
    log_event("message_event", {
        "channel": event.get("channel"),
        "channel_type": event.get("channel_type"),
        "user": event.get("user"),
        "ts": event.get("ts"),
        "thread_ts": event.get("thread_ts"),
        "subtype": event.get("subtype"),
        "bot_id": event.get("bot_id"),
        "text": event.get("text", ""),
    })
    if event.get("channel_type") != "im":
        return
    if event.get("subtype"):
        return
    if event.get("bot_id"):
        return

    # Safety guard: do not consume normal Slack DMs.
    # OpenClaw is the primary direct-message path for Rui.
    # edict-lite should only react in shared spaces via explicit mention.
    return


def start_slack_listener() -> None:
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
