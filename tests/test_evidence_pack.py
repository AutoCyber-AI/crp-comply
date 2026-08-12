# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for evidence-pack build, manifest signature, ZIP download, and verification."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


from crp_comply.api import evidence_signing as _evidence_signing
from crp_comply.api.reports import EvidencePackBuilder


class TestEvidencePack:
    def _artifacts(self) -> dict[str, object]:
        return {
            "risk_assessment": {"risk_level": "HIGH"},
            "dpia": {"dpia_required": True, "mitigations": ["encryption"]},
            "transparency": {"declaration": {"user_rights": []}},
            "technical_docs": {"documentation": {"description": "Hiring AI"}},
            "compliance_report": {"overall_status": "compliant", "score": 95.0},
            "full_report_markdown": "# Full Compliance Report\n\nAll controls pass.",
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
            assert "manifest.sig" in names
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
            assert "hmac_sha256" not in entry

    def test_manifest_signature_verifies_with_public_key(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"dpia_required": True}},
        )
        sig = manifest["signature"]
        assert sig["algorithm"] == "ed25519"

        # Verify using the public key embedded in the manifest.
        assert _evidence_signing.verify_manifest(
            manifest,
            sig["signature_b64"],
            sig["public_key_b64"],
        )

        # The published public key endpoint must match.
        pub = _evidence_signing.export_public_key(tmp_path / "evidence_packs")
        assert pub["public_key_b64"] == sig["public_key_b64"]
        assert pub["fingerprint"] == sig["key_fingerprint"]

    def test_tampered_manifest_fails_verification(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"dpia_required": True}},
        )
        sig = manifest["signature"]

        tampered = dict(manifest)
        tampered["system_name"] = "Tampered System"
        assert tampered != manifest
        assert not _evidence_signing.verify_manifest(
            tampered,
            sig["signature_b64"],
            sig["public_key_b64"],
        )

    def test_zip_download_roundtrip(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"value": 42}},
        )
        zip_path = builder.get_zip("u", manifest["pack_id"])
        assert zip_path is not None

        with zipfile.ZipFile(zip_path, "r") as z:
            assert z.testzip() is None
            inside_manifest = json.loads(z.read("manifest.json"))
            assert inside_manifest["pack_id"] == manifest["pack_id"]
            dpia_inside = json.loads(z.read("dpia.json"))
            assert dpia_inside["value"] == 42
            sig_inside = z.read("manifest.sig").decode("utf-8")
            assert sig_inside == manifest["signature"]["signature_b64"]

    def test_provenance_is_recorded(self, tmp_path: Path) -> None:
        builder = EvidencePackBuilder(data_dir=tmp_path)
        provenance = {
            "corpus_manifest_hash": "a" * 64,
            "ckf_fact_ids": ["f1", "f2"],
            "ckf_event_ids": ["e1"],
        }
        manifest = builder.build(
            user_id="u",
            system_name="X",
            category="y",
            tier="PRO",
            artifacts={"dpia": {"ok": True}},
            provenance=provenance,
        )
        assert "provenance" in manifest
        assert manifest["provenance"]["corpus_manifest_hash"] == "a" * 64
        assert manifest["provenance"]["ckf_fact_ids"] == ["f1", "f2"]
