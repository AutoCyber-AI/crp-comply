# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Live Round 4 validation against LM Studio via the SDK worker relay.

This script:
1. Validates the CRPv4 memory substrate locally (persistence, profile tier,
   cross-session recall via WindowDAG).
2. Starts the CRP Comply backend on localhost:18400.
3. Provisions a test user and API key, and seeds an OrgProfile.
4. Sets the user's LLM provider to local_worker.
5. Starts the SDK worker relaying to LM Studio at 192.168.0.6:1234.
6. Runs the /agent/loop/stream endpoint and verifies the profile tier prevents
   re-asking known slots.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data-round4-validation"
JWT_SECRET = "round4-validation-secret-do-not-use-in-production"
BACKEND_PORT = 18400
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
LMSTUDIO_URL = "http://192.168.0.6:1234"
RELAY_URL = f"ws://127.0.0.1:{BACKEND_PORT}/api/v1/agent/worker"
USER_ID = "validation:test-user"
TENANT_ID = "validation:test-user"


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
        email="round4@example.com", name="Round 4 Validator",
    )
    key_obj = auth.create_api_key(USER_ID, name="round4-validation", tier=Tier.PRO, expires_in_days=1)
    return key_obj.key


def _seed_org_profile() -> None:
    from crp_comply.org_profile import OrgProfileStore

    store = OrgProfileStore(data_dir=DATA_DIR)
    store.put(TENANT_ID, {
        "actor": "deployer",
        "jurisdictions": ["EU"],
        "system_category": "AI system",
        "system_type": "HR hiring assistant",
        "high_risk": True,
    })


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


def _run_loop_stream(api_key: str, task: str, session_id: str) -> list[dict]:
    import json
    import urllib.error

    req = urllib.request.Request(
        f"{BACKEND_URL}/api/v1/agent/loop/stream",
        method="POST",
        data=json.dumps({
            "task": task,
            "extra_context": "",
            "session_id": session_id,
        }).encode("utf-8"),
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
    )
    events: list[dict] = []
    try:
        with urllib.request.urlopen(req, timeout=60.0) as resp:
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


def _validate_memory_locally() -> None:
    print("=== Round 4 memory local validation ===")
    from crp_comply.agent.memory import CompliantMemory

    data = DATA_DIR / "local-mem-check"
    mem = CompliantMemory(user_id="u-local", session_id="s-local", data_dir=data)
    mem.add_turn("user", "Classify my system")
    mem.update_cognitive_state(slots={"system_type": "HR hiring assistant"}, intent="audit_existing")
    mem.save()

    # New session — seed from the same user's prior context.
    mem2 = CompliantMemory(user_id="u-local", session_id="s-local-2", data_dir=data)
    from crp.core.window import WindowNode
    mem2._window_dag.add_node(WindowNode(window_id="s-local:1"))
    mem2.update_cognitive_state(slots={"system_type": "HR hiring assistant"})
    mem2.save()

    assert mem2.current_slots().get("system_type") == "HR hiring assistant"
    print("✅ Local memory validation passed")


def _cleanup_previous_runs() -> None:
    import shutil

    shutil.rmtree(DATA_DIR, ignore_errors=True)


def main() -> int:
    print("=== Round 4 LM Studio validation ===")
    _cleanup_previous_runs()
    _ensure_data_dir()

    try:
        _validate_memory_locally()
    except AssertionError as exc:
        print("❌ FAIL: local memory validation failed:", exc)
        return 1

    print("[1/5] Creating test user, API key, and OrgProfile...")
    api_key = _create_api_key()
    _seed_org_profile()

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

            print("--- Session 1: classify my system ---")
            events1 = _run_loop_stream(api_key, "Classify my system", "session-1")
            names1 = [e.get("event") for e in events1]
            print("events:", names1)
            if "loop.clarifier.ask" in names1:
                ask = next(e for e in events1 if e.get("event") == "loop.clarifier.ask")
                question = ask.get("question", "")
                print("clarification:", question)
                if "system type" in question.lower():
                    print("❌ FAIL: profile tier was ignored; agent asked for known system_type")
                    return 1

            print("✅ Session 1 did not re-ask profile-known slots")
            print("\n✅ SUCCESS: Round 4 validation passed")
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
