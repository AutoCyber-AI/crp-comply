# Copyright © 2025-2026 Constantinos Vidiniotos / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Live Round 2 validation against LM Studio via the SDK worker relay.

This script:
1. Starts the CRP Comply backend on localhost:8400.
2. Provisions a test user and API key.
3. Sets the user's LLM provider to local_worker.
4. Starts the SDK worker, relaying to LM Studio at 192.168.0.6:1234.
5. Runs a short agent task and verifies a non-empty response.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Use the repo's data dir and a dev-only JWT secret.
ROOT = Path(__file__).resolve().parent.parent
# Use a dedicated validation data dir so old keys/processes don't collide.
DATA_DIR = ROOT / "data-round2-validation"
JWT_SECRET = "round2-validation-secret-do-not-use-in-production"
# Use a non-default port so we don't collide with a dev backend.
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
    env["CRP_COMPLY_LLM_PROVIDER"] = "local_worker"  # force local-worker path
    # Redirect to log files so the subprocess doesn't block on a full pipe.
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
    # Use the AuthManager directly to create a user + API key.
    from crp_comply.api.auth import AuthManager, Tier

    auth = AuthManager(data_dir=DATA_DIR, jwt_secret=JWT_SECRET)
    auth.upsert_oauth_user(
        provider="validation", provider_id="test-user",
        email="round2@example.com", name="Round 2 Validator",
    )
    key_obj = auth.create_api_key(USER_ID, name="round2-validation", tier=Tier.PRO, expires_in_days=1)
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


def _cleanup_previous_runs() -> None:
    import shutil

    shutil.rmtree(DATA_DIR, ignore_errors=True)


def main() -> int:
    print("=== Round 2 LM Studio validation ===")
    _cleanup_previous_runs()
    _ensure_data_dir()

    # Create the user and API key *before* starting the backend so the backend
    # loads them at startup.
    print("[1/6] Creating test user and API key...")
    api_key = _create_api_key()

    print("[2/6] Starting backend...")
    backend = _start_backend()
    try:
        if not _wait_for_backend():
            print("ERROR: backend did not start")
            return 1
        print("[3/6] Backend ready; configuring local_worker provider...")
        _set_local_worker_provider(api_key)
        print("[4/6] Starting SDK worker...")
        worker = _start_worker(api_key)
        try:
            print("[5/6] Waiting for worker to attach...")
            if not _wait_for_worker_attached(api_key):
                print("ERROR: worker did not attach or LLM not reachable")
                return 1
            print("[6/6] Running agent task via local_worker...")
            result = _run_agent_task(api_key)
            print("RESULT:", result)
            final_text = (result.get("final_text") or "").strip()
            if final_text:
                print("\n✅ SUCCESS: agent returned a non-empty response via local_worker -> LM Studio")
                return 0
            print("\n❌ FAIL: agent response was empty")
            return 1
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
