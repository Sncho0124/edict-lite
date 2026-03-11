#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
AGENTS_FILE = ROOT / "config" / "agents.json"
SLACK_FILE = ROOT / "config" / "slack.json"
ENV_FILE = ROOT / ".env"


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_text(prefix: str, event: str, task_id: str, status: str, owner: str, message: str) -> str:
    lines = [
        f"{prefix} event={event}",
        f"task_id={task_id}",
        f"status={status}",
        f"owner={owner}",
    ]
    if message:
        lines.append(f"message={message}")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 6:
        print(
            "Usage: python3 scripts/notify_slack.py "
            "<agent> <event> <task_id> <status> <owner> [message]"
        )
        sys.exit(1)

    agent = sys.argv[1]
    event = sys.argv[2]
    task_id = sys.argv[3]
    status = sys.argv[4]
    owner = sys.argv[5]
    message = sys.argv[6] if len(sys.argv) >= 7 else ""

    load_env(ENV_FILE)

    agents = load_json(AGENTS_FILE, {})
    slack = load_json(SLACK_FILE, {})

    if not slack.get("enabled", False):
        print("slack disabled")
        return

    if agent not in agents:
        print(f"Unknown agent: {agent}")
        sys.exit(2)

    notify_map = slack.get("notify_on", {})
    if event in notify_map and not notify_map[event]:
        print(f"event disabled: {event}")
        return

    env_key = slack.get("targets", {}).get(agent)
    if not env_key:
        env_key = agents[agent].get("slack_env_key")

    if not env_key:
        print(f"No slack env key configured for agent: {agent}")
        sys.exit(3)

    webhook = os.getenv(env_key)
    if not webhook:
        print(f"Missing webhook env: {env_key}")
        sys.exit(4)

    prefix = slack.get("prefix", "[edict-lite]")
    text = build_text(prefix, event, task_id, status, owner, message)

    resp = requests.post(webhook, json={"text": text}, timeout=10)
    resp.raise_for_status()
    print("sent")


if __name__ == "__main__":
    main()