"""Tests for BATCH 3 — MMR rerank + signed provenance in evidence pack."""

from __future__ import annotations


# ── MMR rerank ────────────────────────────────────────────────


def test_mmr_rerank_promotes_diversity():
    from crp_comply.agent.crp_integration import mmr_rerank

    hits = [
        {"chunk_id": "a", "score": 0.95, "text": "high risk ai system annex iii"},
        {"chunk_id": "b", "score": 0.94, "text": "high risk ai system annex iii"},
        {"chunk_id": "c", "score": 0.93, "text": "high risk ai system annex iii"},
        {"chunk_id": "d", "score": 0.80, "text": "gdpr article 35 dpia personal data"},
        {"chunk_id": "e", "score": 0.75, "text": "iso 42001 governance management"},
    ]
    out = mmr_rerank(hits, top_k=3, lambda_mult=0.3)
    ids = [h["chunk_id"] for h in out]
    assert ids[0] == "a"  # top-relevance still first
    assert "d" in ids or "e" in ids  # a diverse clause wins over duplicate
    assert len(set(ids)) == 3


def test_mmr_rerank_lambda_one_is_pure_relevance():
    from crp_comply.agent.crp_integration import mmr_rerank

    hits = [
        {"chunk_id": "a", "score": 0.9, "text": "alpha beta"},
        {"chunk_id": "b", "score": 0.8, "text": "alpha beta"},
        {"chunk_id": "c", "score": 0.7, "text": "gamma delta"},
    ]
    out = mmr_rerank(hits, top_k=3, lambda_mult=1.0)
    assert [h["chunk_id"] for h in out] == ["a", "b", "c"]


# ── Evidence pack provenance ──────────────────────────────────


def test_evidence_pack_includes_signed_provenance(tmp_path):
    from crp_comply.api.reports import EvidencePackBuilder

    corpus_manifest = {
        "version": "2026-04-23",
        "sources": [{"source_id": "eu_ai_act", "content_hash": "abc123"}],
    }
    pb = EvidencePackBuilder(tmp_path)
    manifest = pb.build(
        user_id="tenant-1",
        system_name="claims-triage",
        category="high-risk",
        tier="pro",
        artifacts={},
        provenance={
            "corpus_manifest": corpus_manifest,
            "ckf_fact_ids": ["f_1", "f_2"],
            "ckf_event_ids": ["e_1"],
            "verdict_rules": [{"clause": "EU-AI-Act Art 9(3)", "rule": "risk_register_present"}],
        },
    )

    assert "provenance" in manifest
    prov = manifest["provenance"]
    assert prov["corpus_manifest"]["version"] == "2026-04-23"
    assert "corpus_manifest_hash" in prov
    assert prov["ckf_fact_ids"] == ["f_1", "f_2"]
    assert prov["ckf_event_ids"] == ["e_1"]
    assert prov["verdict_rules"][0]["clause"] == "EU-AI-Act Art 9(3)"

    # Signature covers the provenance (signing happens over the canonical
    # manifest JSON that includes provenance).
    sig = manifest["signature"]
    assert sig["algorithm"] in ("ed25519", "hmac-sha256-fallback")
    assert sig["signature_b64"]


def test_evidence_pack_provenance_optional(tmp_path):
    from crp_comply.api.reports import EvidencePackBuilder

    pb = EvidencePackBuilder(tmp_path)
    manifest = pb.build(
        user_id="t2",
        system_name="s",
        category="limited-risk",
        tier="free",
        artifacts={},
    )
    assert "provenance" not in manifest
