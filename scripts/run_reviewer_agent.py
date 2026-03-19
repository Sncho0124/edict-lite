#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"

OPENCLAW_BIN = "openclaw"
AGENT_ID = "reviewer"


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


def build_prompt(task: dict) -> str:
    task_id = task.get("id", "")
    title = task.get("title", "")
    task_input = task.get("input", "")
    result = task.get("result", "")
    previous_notes = task.get("review_notes", "")

    return f"""
你是 reviewer agent。请审核下面这个任务结果，并输出严格 JSON。

审核规则：
- review_decision 只能是 "done"、"revision_required"、"blocked"
- 如果结果可交付，返回 done
- 如果结果有价值但需要明确修改，返回 revision_required
- 如果当前无法合理继续，返回 blocked
- 不要输出 markdown 代码块
- 只输出 JSON，不要附加解释

请按这个 JSON 结构输出：
{{
  "task_id": "{task_id}",
  "review_decision": "done",
  "review_notes": "给 editor 或 user 的明确意见",
  "approval_basis": "通过依据；如果不是 done，也可以写判断依据"
}}

任务上下文：
task_id: {task_id}
title: {title}
input: {task_input}
previous_review_notes: {previous_notes}
result:
{result}
""".strip()


def extract_text_from_openclaw_payload(payload):
    if payload is None:
        return None

    if isinstance(payload, str):
        return payload.strip()

    result_obj = payload.get("result")
    if isinstance(result_obj, dict):
        payloads = result_obj.get("payloads")
        if isinstance(payloads, list):
            parts = []
            for item in payloads:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return "\n".join(parts)

    candidates = [
        payload.get("text"),
        payload.get("reply"),
        payload.get("replyText"),
        payload.get("output"),
        payload.get("message"),
        payload.get("summary"),
    ]
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("text", "reply", "replyText", "output", "message"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    messages = payload.get("messages")
    if isinstance(messages, list):
        parts = []
        for msg in messages:
            if isinstance(msg, dict):
                for key in ("text", "content", "message"):
                    val = msg.get(key)
                    if isinstance(val, str) and val.strip():
                        parts.append(val.strip())
        if parts:
            return "\n".join(parts)

    return None


def try_parse_agent_json(text: str):
    text = text.strip()
    if not text:
        return None

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return None


def call_openclaw_reviewer(prompt: str):
    cmd = [
        OPENCLAW_BIN,
        "agent",
        "--agent",
        AGENT_ID,
        "--message",
        prompt,
        "--json",
    ]

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"openclaw reviewer failed (code={result.returncode})\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise RuntimeError("openclaw reviewer returned empty stdout")

    try:
        payload = json.loads(stdout)
    except Exception:
        payload = {"raw_stdout": stdout}

    text = extract_text_from_openclaw_payload(payload)
    if not text and isinstance(payload, dict) and "raw_stdout" in payload:
        text = payload["raw_stdout"]

    if not text:
        raise RuntimeError(f"could not extract text from openclaw payload: {payload}")

    parsed = try_parse_agent_json(text)
    if not parsed:
        raise RuntimeError(f"reviewer response was not valid review JSON:\n{text}")

    return parsed


def validate_reviewer_output(task_id: str, data: dict) -> dict:
    decision = (data.get("review_decision") or "").strip()
    if decision not in {"done", "revision_required", "blocked"}:
        raise RuntimeError(f"invalid review_decision: {decision}")

    output = {
        "task_id": data.get("task_id", task_id),
        "review_decision": decision,
        "review_notes": (data.get("review_notes") or "").strip(),
        "approval_basis": (data.get("approval_basis") or "").strip(),
    }

    if not output["review_notes"]:
        output["review_notes"] = "reviewer 未提供说明"

    if output["task_id"] != task_id:
        output["task_id"] = task_id

    return output


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/run_reviewer_agent.py <task_id>")
        sys.exit(1)

    task_id = sys.argv[1]

    raw = load_json(TASKS_FILE)
    tasks_data = normalize_tasks_data(raw)
    task = find_task(tasks_data, task_id)

    if not task:
        print(json.dumps({"error": f"Task not found: {task_id}"}, ensure_ascii=False))
        sys.exit(2)

    prompt = build_prompt(task)

    try:
        parsed = call_openclaw_reviewer(prompt)
        output = validate_reviewer_output(task_id, parsed)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(3)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
