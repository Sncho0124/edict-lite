#!/usr/bin/env python3
import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv(ROOT / ".env")

orchestrator_process = None


def slack_listener_enabled() -> bool:
    return os.getenv("EDICTLITE_ENABLE_SLACK_LISTENER", "false").strip().lower() in {"1", "true", "yes", "on"}


def validate_env() -> None:
    if not slack_listener_enabled():
        return

    required = [
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def start_orchestrator() -> subprocess.Popen:
    print("Starting orchestrator...")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "orchestrator.py")],
        cwd=str(ROOT),
    )
    print(f"Orchestrator started with pid={proc.pid}")
    return proc


def stop_orchestrator() -> None:
    global orchestrator_process
    if orchestrator_process and orchestrator_process.poll() is None:
        print("Stopping orchestrator...")
        orchestrator_process.terminate()
        try:
            orchestrator_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            orchestrator_process.kill()
        print("Orchestrator stopped.")


def handle_exit(*_args):
    stop_orchestrator()
    sys.exit(0)


def main() -> None:
    global orchestrator_process

    validate_env()

    atexit.register(stop_orchestrator)
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    orchestrator_process = start_orchestrator()

    print("Starting edict-lite...")
    print("Mode: orchestrator-only")

    if slack_listener_enabled():
        from slack_listener import start_slack_listener
        print("Slack listener: enabled by EDICTLITE_ENABLE_SLACK_LISTENER=true")
        start_slack_listener()
    else:
        print("Slack listener: disabled (default)")
        print("This avoids Slack route conflicts with OpenClaw.")
        orchestrator_process.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        handle_exit()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        stop_orchestrator()
        sys.exit(1)
