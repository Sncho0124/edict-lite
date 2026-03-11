#!/usr/bin/env python3
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "data" / "tasks.json"

OPENCLAW_BIN = "openclaw"
AGENT_ID = "editor"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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


def append_history(task: dict, note: str, raw: dict | None = None) -> None:
    item = {
        "at": now_iso(),
        "action": "editor_generated",
        "by": "editor",
        "note": note,
    }
    if raw is not None:
        item["meta"] = {"openclaw_agent": AGENT_ID}
    task.setdefault("history", []).append(item)


def build_prompt(task: dict) -> str:
    task_id = task.get("id", "")
    title = task.get("title", "")
    task_input = task.get("input", "")
    review_notes = task.get("review_notes", "")
    current_result = task.get("result", "")

    return f"""
你是 editor agent。请只完成这一个任务，并输出严格 JSON。

任务要求：
- 你的职责是根据任务输入生成或修改 result
- 如果 review_notes 非空，优先根据 review_notes 修改
- 不要输出 markdown 代码块
- 只输出 JSON，不要附加解释

请按这个 JSON 结构输出：
{{
  "task_id": "{task_id}",
  "summary": "一句话总结你做了什么",
  "result": "给 reviewer 审核的完整结果文本",
  "assumptions": "你的关键假设，若无则写空字符串",
  "risks": "风险或待确认点，若无则写空字符串"
}}

任务上下文：
task_id: {task_id}
title: {title}
input: {task_input}
review_notes: {review_notes}
current_result: {current_result}
""".strip()


def extract_text_from_openclaw_payload(payload):
    """
    兼容 OpenClaw 2026.3.8 的 --json 输出。
    优先读取:
    payload["result"]["payloads"][0]["text"]
    """

    if payload is None:
        return None

    if isinstance(payload, str):
        return payload.strip()

    # 1) 最新观察到的 OpenClaw 结构：
    # {
    #   "runId": "...",
    #   "status": "ok",
    #   "result": {
    #       "payloads": [
    #           {"text": "..."}
    #       ]
    #   }
    # }
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

    # 2) 兼容旧/其他可能字段
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

    # 直接就是 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 兼容模型偶尔返回 ```json ... ```
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

    # 尝试截取首尾大括号
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


def call_openclaw_editor(prompt: str):
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
            f"openclaw editor failed (code={result.returncode})\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise RuntimeError("openclaw editor returned empty stdout")

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
        raise RuntimeError(f"editor response was not valid task JSON:\n{text}")

    return parsed, payload


def validate_editor_output(task_id: str, data: dict) -> dict:
    output = {
        "task_id": data.get("task_id", task_id),
        "summary": data.get("summary", "").strip(),
        "result": data.get("result", "").strip(),
        "assumptions": data.get("assumptions", "").strip(),
        "risks": data.get("risks", "").strip(),
    }

    if not output["result"]:
        raise RuntimeError("editor returned empty result")

    if not output["summary"]:
        output["summary"] = "已生成结果"

    if output["task_id"] != task_id:
        output["task_id"] = task_id

    return output


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/run_editor_agent.py <task_id>")
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
        parsed, raw_payload = call_openclaw_editor(prompt)
        output = validate_editor_output(task_id, parsed)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(3)

    task["result"] = output["result"]
    task["updated_at"] = now_iso()
    append_history(task, output["summary"], raw_payload)
    save_json(TASKS_FILE, tasks_data)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()