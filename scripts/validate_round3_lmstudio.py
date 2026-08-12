# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Live Round 3 validation against LM Studio via the SDK worker relay.

This script:
1. Validates NLU extraction locally (no LLM required).
2. Starts the CRP Comply backend on localhost:18400.
3. Provisions a test user and API key.
4. Sets the user's LLM provider to local_worker.
5. Starts the SDK worker, relaying to LM Studio at 192.168.0.6:1234.
6. Runs a short agent task via /agent/start to confirm the relay works.
7. Runs the new /agent/loop/stream endpoint with a DPIA request and verifies
   that loop.nlu, loop.dialogue, and loop.clarifier.ask events are emitted
   before any LLM reasoning work.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Re-use Round 2 validation infrastructure.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data-round3-validation"
JWT_SECRET = "round3-validation-secret-do-not-use-in-production"
BACKEND_PORT = 18400
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
LMSTUDIO_URL = "http://192.168.0.6:1234"
RELAY_URL = f"ws://127.0.0.1:{BACKEND_PORT}/api/v1/agent/worker"
USER_ID = "validation:test-user"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = DATA_DIR / ".jwt_secret"
    secret_file.write_text(JWT_SECRET, encoding="utf-8")


def _start_backend() -> subprocess.Popen:
    env = os.environ.copy()
    env["CRP_COMPLY_DATA_DIR"] = str(DATA_DIR)
    env["CRP_COMPLY_JWT_SECRET"] = JWT_SECRET
    env["CRP_COMPLY_LLM_PROVIDER"] = "local_worker"
    log_out = open(DATA_DIR / "backend.out.log", "w", encoding="utf-8")
    log_err = open(DATA_DIR / "backend.err.log", "w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "crp_comply.cli", "serve", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=str(ROOT),
        env=env,
        stdout=log_out,
        stderr=log_err,
    )


def _wait_for_backend(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BACKEND_URL}/api/v1/health", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _create_api_key() -> str:
    from crp_comply.api.auth import AuthManager, Tier

    auth = AuthManager(data_dir=DATA_DIR, jwt_secret=JWT_SECRET)
    auth.upsert_oauth_user(
        provider="validation", provider_id="test-user",
        email="round3@example.com", name="Round 3 Validator",
    )
    key_obj = auth.create_api_key(USER_ID, name="round3-validation", tier=Tier.PRO, expires_in_days=1)
    return key_obj.key


def _set_local_worker_provider(api_key: str) -> None:
    import json
    import urllib.error

    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/llm/configure",
        method="POST",
        data=json.dumps({
            "provider": "local_worker",
            "api_key": "local",
            "base_url": "",
            "model": "meta-llama-3.1-8b-instruct",
        }).encode("utf-8"),
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            print("provider config:", resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("provider config failed:", exc.code, exc.read().decode("utf-8"))
        raise


def _start_worker(api_key: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["CRP_COMPLY_DATA_DIR"] = str(DATA_DIR)
    env["CRP_COMPLY_JWT_SECRET"] = JWT_SECRET
    log_out = open(DATA_DIR / "worker.out.log", "w", encoding="utf-8")
    log_err = open(DATA_DIR / "worker.err.log", "w", encoding="utf-8")
    return subprocess.Popen(
        [
            sys.executable, "-m", "crp_comply_sdk.worker", "worker",
            "--lmstudio", LMSTUDIO_URL,
            "--allow-lan",
            "--api-key", api_key,
            "--relay-url", RELAY_URL,
            "-v",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_out,
        stderr=log_err,
    )


def _wait_for_worker_attached(api_key: str, timeout: float = 60.0) -> bool:
    import json
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(
            f"{BACKEND_URL}/api/v1/agent/worker/status",
            headers={"X-API-Key": api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("attached") and data.get("llm_reachable"):
                    print("worker attached and LLM reachable:", data)
                    return True
                if data.get("attached"):
                    print("worker attached, waiting for LLM probe:", data)
        except urllib.error.HTTPError as exc:
            print("worker status error:", exc.code, exc.read().decode("utf-8"))
        except Exception as exc:
            print("worker status exception:", exc)
        time.sleep(1.0)
    return False


def _run_agent_task(api_key: str) -> dict:
    import json
    import urllib.error

    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/agent/start",
        method="POST",
        data=json.dumps({
            "task": "List one risk of a high-risk AI system under the EU AI Act.",
            "recipe_id": "",
        }).encode("utf-8"),
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("agent task failed:", exc.code, exc.read().decode("utf-8"))
        raise


def _run_loop_stream(api_key: str, task: str) -> list[dict]:
    """Call /agent/loop/stream and parse SSE events."""
    import json
    import urllib.error

    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/agent/loop/stream",
        method="POST",
        data=json.dumps({
            "task": task,
            "extra_context": "",
        }).encode("utf-8"),
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
    )
    events: list[dict] = []
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            buffer = b""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n\n" in buffer:
                    frame, _, buffer = buffer.partition(b"\n\n")
                    data = b""
                    for line in frame.splitlines():
                        if line.startswith(b"data: "):
                            data = line[6:]
                    if data:
                        try:
                            events.append(json.loads(data.decode("utf-8")))
                        except json.JSONDecodeError:
                            pass
    except urllib.error.HTTPError as exc:
        print("loop stream failed:", exc.code, exc.read().decode("utf-8"))
        raise
    return events


def _validate_nlu_locally() -> None:
    print("=== Round 3 NLU local validation ===")
    from crp_comply.agent.nlu import NluEngine
    from crp_comply.agent.dialogue import DialogueStateTracker

    engine = NluEngine()
    turn1 = engine.parse("Draft a DPIA for my HR hiring assistant")
    assert turn1.intent == "produce_artefact", turn1.intent
    assert turn1.slots.get("task_type") == "dpia", turn1.slots
    assert turn1.slots.get("system_type") == "hiring assistant", turn1.slots

    tracker = DialogueStateTracker(user_id="validation")
    _, decision1 = tracker.process_utterance("Draft a DPIA for my HR hiring assistant")
    assert decision1.action == "clarify", decision1.action
    assert "regulation" in decision1.args.get("missing", []), decision1.args

    _, decision2 = tracker.process_utterance("It processes CVs and scores candidates in the EU")
    assert decision2.action == "clarify", decision2.action
    slots = tracker.state.slots.to_dict()
    assert slots.get("data_type") == "cv", slots
    assert slots.get("jurisdiction") == "eu", slots
    assert slots.get("purpose") == "scoring candidates", slots

    _, decision3 = tracker.process_utterance("Under GDPR")
    assert decision3.action == "produce_artefact", decision3.action

    print("✅ Local NLU/dialogue validation passed")


def _cleanup_previous_runs() -> None:
    import shutil

    shutil.rmtree(DATA_DIR, ignore_errors=True)


def main() -> int:
    print("=== Round 3 LM Studio validation ===")
    _cleanup_previous_runs()
    _ensure_data_dir()

    # 1. Local NLU checks (no LLM).
    try:
        _validate_nlu_locally()
    except AssertionError as exc:
        print("❌ FAIL: local NLU validation failed:", exc)
        return 1

    # 2. End-to-end via backend + SDK worker + LM Studio.
    print("[1/5] Creating test user and API key...")
    api_key = _create_api_key()

    print("[2/5] Starting backend...")
    backend = _start_backend()
    try:
        if not _wait_for_backend():
            print("ERROR: backend did not start")
            return 1
        print("[3/5] Backend ready; configuring local_worker provider...")
        _set_local_worker_provider(api_key)
        print("[4/5] Starting SDK worker...")
        worker = _start_worker(api_key)
        try:
            print("[5/5] Waiting for worker to attach...")
            if not _wait_for_worker_attached(api_key):
                print("ERROR: worker did not attach or LLM not reachable")
                return 1

            print("--- Running baseline agent task via local_worker ---")
            result = _run_agent_task(api_key)
            final_text = (result.get("final_text") or "").strip()
            if not final_text:
                print("❌ FAIL: baseline agent response was empty")
                return 1
            print("✅ Baseline agent task returned a non-empty response")

            print("--- Running loop/stream dialogue short-circuit ---")
            events = _run_loop_stream(api_key, "Draft a DPIA for my HR hiring assistant")
            names = [e.get("event") for e in events]
            if "loop.nlu" not in names:
                print("❌ FAIL: loop.nlu event missing; events:", names)
                return 1
            if "loop.dialogue" not in names:
                print("❌ FAIL: loop.dialogue event missing; events:", names)
                return 1
            if "loop.clarifier.ask" not in names:
                print("❌ FAIL: loop.clarifier.ask event missing; events:", names)
                return 1
            if "loop.step.start" in names or "loop.plan" in names:
                print("❌ FAIL: clarification did not short-circuit reasoning; events:", names)
                return 1
            nlu = next(e for e in events if e.get("event") == "loop.nlu")
            print("loop.nlu:", nlu)
            print("✅ Loop stream dialogue short-circuit worked")
            print("\n✅ SUCCESS: Round 3 validation passed")
            return 0
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=5.0)
            except Exception:
                worker.kill()
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5.0)
        except Exception:
            backend.kill()


if __name__ == "__main__":
    raise SystemExit(main())
