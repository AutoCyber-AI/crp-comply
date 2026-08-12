# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for :mod:`crp_comply.backup` — export/erase/backup/restore."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from crp_comply.backup import (
    USER_SCOPED_DIRS,
    backup_all,
    delete_user,
    export_user,
    restore,
    restore_user,
)


@pytest.fixture
def populated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a realistic per-user data layout under ``tmp_path``."""
    data = tmp_path / "data"
    data.mkdir()

    # users.json — keyed by user_id.
    (data / "users.json").write_text(
        json.dumps(
            {
                "alice": {"email": "alice@example.com", "tier": "pro"},
                "bob": {"email": "bob@example.com", "tier": "free"},
            }
        ),
        encoding="utf-8",
    )

    # api_keys.json — nested.
    (data / "api_keys.json").write_text(
        json.dumps(
            {
                "api_keys": {
                    "alice": [{"id": "k1", "prefix": "crc_aaa"}],
                    "bob": [{"id": "k2", "prefix": "crc_bbb"}],
                }
            }
        ),
        encoding="utf-8",
    )

    # usage.json — flat keyed.
    (data / "usage.json").write_text(
        json.dumps({"alice": {"month": "2026-01", "calls": 42}}),
        encoding="utf-8",
    )

    # User-scoped dirs.
    for d in ("reports", "evidence_packs", "artefacts", "agent_sessions", "ckf"):
        (data / d / "alice").mkdir(parents=True)
        (data / d / "alice" / f"{d}_one.json").write_text(
            json.dumps({"owner": "alice", "kind": d}),
            encoding="utf-8",
        )
        (data / d / "bob").mkdir(parents=True)
        (data / d / "bob" / f"{d}_one.json").write_text(
            json.dumps({"owner": "bob", "kind": d}),
            encoding="utf-8",
        )

    # proxy_audit/ — record-keyed.
    (data / "proxy_audit").mkdir()
    (data / "proxy_audit" / "rec1.json").write_text(
        json.dumps({"record_id": "rec1", "user_id": "alice", "model": "x"}),
        encoding="utf-8",
    )
    (data / "proxy_audit" / "rec2.json").write_text(
        json.dumps({"record_id": "rec2", "user_id": "bob", "model": "x"}),
        encoding="utf-8",
    )

    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(data))
    return data


# ── export_user ────────────────────────────────────────────────────


def test_export_user_creates_valid_tarball(populated_data_dir: Path):
    summary = export_user("alice")
    assert summary.archive_path.exists()
    assert summary.bytes_written > 0
    assert summary.files_included >= 8  # 3 account jsons + 5 user-scoped + proxy_audit
    assert summary.sha256

    # Verify members.
    with tarfile.open(summary.archive_path, "r:gz") as tar:
        names = tar.getnames()

    assert any("MANIFEST.json" in n for n in names)
    assert any(n.endswith("/users.json") for n in names)
    assert any(n.endswith("/reports/alice/reports_one.json") for n in names)
    assert any(n.endswith("/proxy_audit/rec1.json") for n in names)
    # Bob's files must NOT appear in Alice's export.
    assert not any("/bob/" in n for n in names)
    assert not any(n.endswith("/proxy_audit/rec2.json") for n in names)


def test_export_user_filters_users_json_to_one_user(populated_data_dir: Path):
    summary = export_user("alice")
    with tarfile.open(summary.archive_path, "r:gz") as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith("/users.json"))
        f = tar.extractfile(member)
        assert f is not None
        payload = json.loads(f.read().decode("utf-8"))
    assert "alice" in payload
    assert "bob" not in payload


def test_export_user_rejects_path_traversal(populated_data_dir: Path):
    with pytest.raises(ValueError):
        export_user("../etc/passwd")
    with pytest.raises(ValueError):
        export_user("a/b")


# ── delete_user ────────────────────────────────────────────────────


def test_delete_user_cascade_removes_everything(populated_data_dir: Path):
    summary = delete_user("alice", cascade=True)
    assert summary.gdpr_art17 is True
    assert summary.items_deleted >= 8

    # Alice gone everywhere.
    users = json.loads((populated_data_dir / "users.json").read_text())
    assert "alice" not in users
    assert "bob" in users

    for d in ("reports", "evidence_packs", "artefacts", "agent_sessions", "ckf"):
        assert not (populated_data_dir / d / "alice").exists()
        assert (populated_data_dir / d / "bob").exists()  # unaffected

    assert not (populated_data_dir / "proxy_audit" / "rec1.json").exists()
    assert (populated_data_dir / "proxy_audit" / "rec2.json").exists()


def test_delete_user_no_cascade_only_strips_auth(populated_data_dir: Path):
    summary = delete_user("alice", cascade=False)
    users = json.loads((populated_data_dir / "users.json").read_text())
    assert "alice" not in users
    # Reports survive (account suspension, not erasure).
    assert (populated_data_dir / "reports" / "alice" / "reports_one.json").exists()
    assert summary.gdpr_art17 is True


def test_delete_user_idempotent(populated_data_dir: Path):
    delete_user("alice", cascade=True)
    summary = delete_user("alice", cascade=True)
    # Second call has nothing to do — must not raise and must return zero counts.
    assert summary.items_deleted == 0


# ── backup_all + restore ──────────────────────────────────────────


def test_backup_all_then_restore_round_trips(populated_data_dir: Path, tmp_path: Path):
    archive = tmp_path / "full.tar.gz"
    summary = backup_all(archive)
    assert archive.exists()
    assert summary.files_included > 0
    assert summary.sha256

    # Wipe live data dir and restore.
    import shutil

    shutil.rmtree(populated_data_dir)
    populated_data_dir.mkdir()

    restore_summary = restore(archive)
    assert restore_summary.files_restored == summary.files_included

    # Spot-check: alice's report is back.
    assert (populated_data_dir / "reports" / "alice" / "reports_one.json").exists()
    users = json.loads((populated_data_dir / "users.json").read_text())
    assert "alice" in users and "bob" in users


def test_restore_skips_existing_files_without_overwrite(populated_data_dir: Path, tmp_path: Path):
    archive = tmp_path / "full.tar.gz"
    backup_all(archive)

    # Clobber a live file with new content.
    target = populated_data_dir / "users.json"
    target.write_text(json.dumps({"new": "content"}), encoding="utf-8")

    restore(archive, overwrite=False)
    # Live content preserved because overwrite=False.
    payload = json.loads(target.read_text())
    assert payload == {"new": "content"}

    restore(archive, overwrite=True)
    payload = json.loads(target.read_text())
    assert "alice" in payload  # original restored


def test_restore_rejects_path_traversal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path / "data"))
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 4
        import io

        tar.addfile(info, io.BytesIO(b"OOPS"))

    summary = restore(bad)
    # Nothing restored, no escape file written.
    assert summary.files_restored == 0
    assert not (tmp_path / "escape.txt").exists()


# ── tar-safety: symlinks, absolute paths, oversized members ──────────


def test_restore_rejects_symlink_member(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path / "data"))
    bad = tmp_path / "bad-symlink.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="evil-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    summary = restore(bad)
    assert summary.files_restored == 0
    # Symlink must not exist on disk.
    assert not (tmp_path / "data" / "evil-link").exists()


def test_restore_rejects_absolute_path_member(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path / "data"))
    bad = tmp_path / "bad-abs.tar.gz"
    import io as _io

    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo(name="/etc/passwd")
        info.size = 5
        tar.addfile(info, _io.BytesIO(b"OOPS!"))
    summary = restore(bad)
    assert summary.files_restored == 0


# ── restore_user (single-user restore) ──────────────────────────────


def test_restore_user_only_touches_target_user(populated_data_dir: Path, tmp_path: Path):
    archive = tmp_path / "full.tar.gz"
    backup_all(archive)

    # Mutate alice's data + bob's data + the global users.json on disk.
    (populated_data_dir / "reports" / "alice" / "reports_one.json").write_text(
        json.dumps({"owner": "alice", "kind": "MUTATED"}),
        encoding="utf-8",
    )
    (populated_data_dir / "reports" / "bob" / "reports_one.json").write_text(
        json.dumps({"owner": "bob", "kind": "BOB_NEW_DATA"}),
        encoding="utf-8",
    )
    users_path = populated_data_dir / "users.json"
    users_path.write_text(
        json.dumps(
            {
                "alice": {"email": "alice@example.com", "tier": "MUTATED"},
                "bob": {"email": "bob@example.com", "tier": "enterprise"},  # bob upgraded
            }
        ),
        encoding="utf-8",
    )

    summary = restore_user(archive, "alice", overwrite=True)

    # Alice's reports rolled back.
    rolled_back = json.loads(
        (populated_data_dir / "reports" / "alice" / "reports_one.json").read_text()
    )
    assert rolled_back["kind"] == "reports"  # original

    # Bob's reports preserved.
    bob_intact = json.loads(
        (populated_data_dir / "reports" / "bob" / "reports_one.json").read_text()
    )
    assert bob_intact["kind"] == "BOB_NEW_DATA"

    # users.json: alice rolled back, bob's enterprise tier preserved.
    final_users = json.loads(users_path.read_text())
    assert final_users["alice"]["tier"] == "pro"
    assert final_users["bob"]["tier"] == "enterprise"

    assert summary.files_restored > 0


def test_restore_user_skips_other_users_dirs(populated_data_dir: Path, tmp_path: Path):
    archive = tmp_path / "full.tar.gz"
    backup_all(archive)

    # Wipe everything bob-related from disk.
    import shutil as _shutil

    for d in USER_SCOPED_DIRS:
        bob_dir = populated_data_dir / d / "bob"
        if bob_dir.exists():
            _shutil.rmtree(bob_dir)

    # Restoring alice must NOT recreate bob's directories.
    restore_user(archive, "alice", overwrite=True)
    for d in USER_SCOPED_DIRS:
        assert not (populated_data_dir / d / "bob").exists(), (
            f"bob's {d}/ should not have been restored when filtering for alice"
        )


def test_restore_user_filters_record_keyed_dirs(populated_data_dir: Path, tmp_path: Path):
    archive = tmp_path / "full.tar.gz"
    backup_all(archive)

    # Delete both proxy_audit records.
    (populated_data_dir / "proxy_audit" / "rec1.json").unlink()
    (populated_data_dir / "proxy_audit" / "rec2.json").unlink()

    restore_user(archive, "alice", overwrite=True)
    assert (populated_data_dir / "proxy_audit" / "rec1.json").exists()
    assert not (populated_data_dir / "proxy_audit" / "rec2.json").exists()
