"""Tests for crp_comply_sdk.worker n_parallel detection and wire frames."""

from __future__ import annotations

from crp_comply_sdk.worker import _detect_n_parallel_from_models


def test_detect_n_parallel_single_slot():
    items = [
        {"id": "model-a", "state": "loaded", "type": "llm"},
        {"id": "model-b", "state": "loaded", "type": "llm"},
    ]
    assert _detect_n_parallel_from_models(items) == 1


def test_detect_n_parallel_four_slots():
    items = [
        {"id": "model-a", "state": "loaded", "type": "llm"},
        {"id": "model-a:2", "state": "loaded", "type": "llm"},
        {"id": "model-a:3", "state": "loaded", "type": "llm"},
        {"id": "model-a:4", "state": "loaded", "type": "llm"},
    ]
    assert _detect_n_parallel_from_models(items) == 4


def test_detect_n_parallel_ignores_unloaded_and_embeddings():
    items = [
        {"id": "model-a", "state": "loaded", "type": "llm"},
        {"id": "model-a:2", "state": "loaded", "type": "llm"},
        {"id": "model-a:3", "state": "not-loaded", "type": "llm"},
        {"id": "embed-1", "state": "loaded", "type": "embeddings"},
    ]
    assert _detect_n_parallel_from_models(items) == 2


def test_detect_n_parallel_empty():
    assert _detect_n_parallel_from_models([]) == 1
