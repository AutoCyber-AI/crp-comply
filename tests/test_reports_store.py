"""Tests for ReportStore and EvidencePackBuilder — disk I/O on tmp_path."""

from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from crp_comply.api import evidence_signing as _evidence_signing
from crp_comply.api.reports import (
    EvidencePackBuilder,
    ReportStore,
    _sanitize,
)


# ── ReportStore ────────────────────────────────────────────────


class TestReportStore:
    def test_save_and_get_roundtrip(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        rec = store.save(
            user_id="user_a",
            kind="dpia",
            system_name="Hiring",
            tier="PRO",
            payload={"system_name": "Hiring", "dpia_required": True},
        )
        assert rec["id"]
        assert rec["size_bytes"] > 0

        got = store.get("user_a", rec["id"])
        assert got is not None
        assert got["payload"]["dpia_required"] is True
        assert got["kind"] == "dpia"
        assert got["tier"] == "PRO"

    def test_save_rejects_unknown_kind(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        with pytest.raises(ValueError):
            store.save(
                user_id="user_a",
                kind="bogus_kind",
                system_name="X",
                tier="FREE",
                payload={},
            )

    def test_save_with_markdown(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        rec = store.save(
            user_id="user_a",
            kind="full_report",
            system_name="Hiring",
            tier="PRO",
            payload={"system_name": "Hiring"},
            markdown="# Compliance Report\nAll good.",
        )
        got = store.get("user_a", rec["id"])
        assert got is not None
        assert got["markdown"].startswith("# Compliance Report")

    def test_list_scopes_per_user(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        r_a = store.save(
            user_id="alice",
            kind="dpia",
            system_name="X",
            tier="PRO",
            payload={},
        )
        store.save(
            user_id="bob",
            kind="dpia",
            system_name="Y",
            tier="PRO",
            payload={},
        )
        alice_list = store.list("alice")
        bob_list = store.list("bob")
        assert len(alice_list) == 1
        assert len(bob_list) == 1
        assert alice_list[0]["id"] == r_a["id"]
        assert alice_list[0]["system_name"] == "X"

    def test_list_filter_by_kind(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        store.save(user_id="u", kind="dpia", system_name="A", tier="PRO", payload={})
        store.save(user_id="u", kind="transparency", system_name="A", tier="PRO", payload={})
        store.save(user_id="u", kind="dpia", system_name="B", tier="PRO", payload={})
        only_dpia = store.list("u", kind="dpia")
        assert len(only_dpia) == 2
        assert all(r["kind"] == "dpia" for r in only_dpia)

    def test_list_strips_payload(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        store.save(
            user_id="u",
            kind="dpia",
            system_name="X",
            tier="PRO",
            payload={"giant": "x" * 10_000},
        )
        items = store.list("u")
        assert len(items) == 1
        # List responses must not leak payload bytes into listings
        assert "payload" not in items[0]

    def test_count_reports(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        store.save(user_id="u", kind="dpia", system_name="A", tier="PRO", payload={})
        store.save(user_id="u", kind="dpia", system_name="B", tier="PRO", payload={})
        store.save(user_id="u", kind="transparency", system_name="C", tier="PRO", payload={})
        counts = store.count("u")
        assert counts["_total"] == 3
        assert counts["dpia"] == 2
        assert counts["transparency"] == 1
        assert counts["_total_bytes"] > 0

    def test_delete(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        rec = store.save(
            user_id="u",
            kind="dpia",
            system_name="X",
            tier="PRO",
            payload={},
        )
        assert store.delete("u", rec["id"]) is True
        assert store.get("u", rec["id"]) is None
        # Double delete is idempotent-ish: returns False
        assert store.delete("u", rec["id"]) is False

    def test_purge_older_than(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        old = store.save(
            user_id="u",
            kind="dpia",
            system_name="Old",
            tier="PRO",
            payload={},
        )
        fresh = store.save(
            user_id="u",
            kind="dpia",
            system_name="Fresh",
            tier="PRO",
            payload={},
        )
        # Age the old record by rewinding its mtime by 10 days
        old_path = tmp_path / "reports" / "u" / f"{old['id']}.json"
        ten_days_ago = time.time() - (10 * 86400)
        os.utime(old_path, (ten_days_ago, ten_days_ago))

        removed = store.purge_older_than(days=5)
        assert removed == 1
        assert store.get("u", old["id"]) is None
        assert store.get("u", fresh["id"]) is not None

    def test_user_id_sanitisation(self, tmp_path: Path) -> None:
        store = ReportStore(data_dir=tmp_path)
        store.save(
            user_id="../../../etc/passwd",
            kind="dpia",
            system_name="X",
            tier="PRO",
            payload={},
        )
        # The on-disk directory must be sanitised — no path traversal.
        assert not (tmp_path.parent / "etc" / "passwd").exists()
        assert (tmp_path / "reports").exists()

    def test_sanitize_helper_strips_path_chars(self) -> None:
        assert "/" not in _sanitize("../../evil/user")
        assert "\\" not in _sanitize("\\evil")
        assert _sanitize("") == "anonymous"


# ── EvidencePackBuilder ────────────────────────────────────────


class TestEvidencePackBuilder:
    def _artifacts(self) -> dict[str, object]:
        return {
            "risk_assessment": {"risk_level": "HIGH"},
            "dpia": {"dpia_required": True, "mitigations": ["encryption"]},
            "transparency": {"declaration": {"user_rights": []}},
            "technical_docs": {"documentation": {"description": "Hiring AI"}},
            "compliance_report": {"overall_status": "compliant", "score": 95.0},
            "full_report_markdown": "# Full Compliance Report\n\nAll controls pass.",
            # Unknown key — should be silently dropped
            "not_a_real_kind": {"junk": True},
        }

    def test_build_produces_zip_with_manifest(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="Hiring",
            category="employment",
            tier="PRO",
            artifacts=self._artifacts(),
        )

        assert manifest["pack_id"]
        assert manifest["zip_bytes"] > 0

        zip_path = Path(manifest["zip_path"])
        assert zip_path.exists()

        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            assert "manifest.json" in names
            assert "README.txt" in names
            assert "risk_assessment.json" in names
            assert "dpia.json" in names
            assert "compliance_report.md" in names

    def test_manifest_records_sha256_for_every_file(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts=self._artifacts(),
        )
        for entry in manifest["files"]:
            assert len(entry["sha256"]) == 64  # hex SHA-256
            assert entry["size_bytes"] > 0

    def test_ed25519_manifest_signature(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"dpia_required": True}},
        )
        assert "signature" in manifest
        sig = manifest["signature"]
        assert sig["algorithm"] == "ed25519"
        assert sig["signature_b64"]
        assert sig["public_key_b64"]
        assert sig["key_fingerprint"]

        # The manifest signature must verify against the public key.
        assert _evidence_signing.verify_manifest(
            manifest,
            sig["signature_b64"],
            sig["public_key_b64"],
        )

    def test_no_hmac_field_in_manifest(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"dpia_required": True}},
        )
        for entry in manifest["files"]:
            assert "hmac_sha256" not in entry

    def test_unknown_artifact_keys_dropped(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"nonsense_kind": {"x": 1}, "dpia": {"ok": True}},
        )
        names = [f["name"] for f in manifest["files"]]
        assert "dpia.json" in names
        assert "README.txt" in names
        # Unknown keys have no registered filename
        assert "nonsense_kind.json" not in names

    def test_list_packs_per_user(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        builder.build(
            user_id="alice",
            system_name="A",
            category="y",
            tier="PRO",
            artifacts={"dpia": {}},
        )
        builder.build(
            user_id="alice",
            system_name="B",
            category="y",
            tier="PRO",
            artifacts={"dpia": {}},
        )
        builder.build(
            user_id="bob",
            system_name="C",
            category="y",
            tier="PRO",
            artifacts={"dpia": {}},
        )
        alice_packs = builder.list("alice")
        bob_packs = builder.list("bob")
        assert len(alice_packs) == 2
        assert len(bob_packs) == 1

    def test_get_zip_and_manifest_roundtrip(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        m = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"ok": True}},
        )
        pack_id = m["pack_id"]
        assert builder.get_zip("u", pack_id) is not None
        manifest = builder.get_manifest("u", pack_id)
        assert manifest is not None
        assert manifest["pack_id"] == pack_id

    def test_delete_removes_pack(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        m = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {}},
        )
        pack_id = m["pack_id"]
        assert builder.delete("u", pack_id) is True
        assert builder.get_zip("u", pack_id) is None
        assert builder.get_manifest("u", pack_id) is None

    def test_purge_older_than(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        old = builder.build(
            user_id="u",
            system_name="Old",
            category="y",
            tier="PRO",
            artifacts={"dpia": {}},
        )
        fresh = builder.build(
            user_id="u",
            system_name="Fresh",
            category="y",
            tier="PRO",
            artifacts={"dpia": {}},
        )
        # Age the old pack directory
        old_dir = tmp_path / "evidence_packs" / "u" / _sanitize(old["pack_id"])
        ten_days_ago = time.time() - (10 * 86400)
        # Age every file and the dir itself
        for p in old_dir.iterdir():
            os.utime(p, (ten_days_ago, ten_days_ago))
        os.utime(old_dir, (ten_days_ago, ten_days_ago))

        removed = builder.purge_older_than(days=5)
        assert removed == 1
        assert builder.get_zip("u", old["pack_id"]) is None
        assert builder.get_zip("u", fresh["pack_id"]) is not None

    def test_zip_is_valid_and_readable(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        m = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"value": 42}},
        )
        zip_path = Path(m["zip_path"])
        with zipfile.ZipFile(zip_path, "r") as z:
            bad = z.testzip()
            assert bad is None, f"corrupt zip entry: {bad}"
            manifest_inside = json.loads(z.read("manifest.json"))
            assert manifest_inside["pack_id"] == m["pack_id"]
            dpia_inside = json.loads(z.read("dpia.json"))
            assert dpia_inside["value"] == 42
