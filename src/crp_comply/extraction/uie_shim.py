"""UIE shim — make Stage 4 of ``crp.extraction`` available out-of-box.

The CRP SDK's ``stage4_uie.UIEExtractor`` does ``from uie import UIE``
on first use and silently disables Stage 4 if the import fails. There
is no ``uie`` package on PyPI that matches the contract, so without
this shim every CRP Comply deployment logs ``UIE not available — Stage
4 will be skipped`` and runs a degraded 5-stage pipeline.

This module synthesises a top-level ``uie`` module at import time and
populates it with a :class:`UIE` class whose :meth:`extract_triples`
honours the CRP contract:

    extract_triples(text: str) -> list[dict]
        # each dict has {subject, predicate, object, confidence}

Backends (in priority order):

1. **spaCy SVO** — default. spaCy ships transitively via
   ``crprotocol[full]`` (it is the Stage 2 statistical extractor), so
   no new dependency is added. We use the dependency parser to mine
   subject-verb-object triples from each sentence. Confidence is a
   fixed 0.65 because dep-parse SVO is structurally sound but
   semantically shallow.
2. **REBEL** (``Babelscape/rebel-large``) — opt-in via env
   ``CRP_COMPLY_UIE_BACKEND=rebel``. Higher precision relational
   extraction at the cost of ~1.6 GB of additional model weights and
   ~150 ms / chunk of latency. Only loaded if the env var is set.

Installation as ``sys.modules['uie']`` happens at module import.
``crp_comply.agent.ckf_corpus`` imports this module before
constructing :class:`crp.extraction.ExtractionPipeline`, which is
*before* the lazy import inside ``UIEExtractor._ensure_model`` runs.
"""

from __future__ import annotations

import logging
import os
import sys
import types
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backend 1 — spaCy SVO (default, zero extra deps)
# ---------------------------------------------------------------------------


class _SpacySVO:
    """Lazy spaCy-backed subject-verb-object triple extractor."""

    _nlp: Any = None
    _attempted: bool = False

    @classmethod
    def _get_nlp(cls) -> Any:
        if cls._nlp is not None or cls._attempted:
            return cls._nlp
        cls._attempted = True
        try:
            import spacy  # type: ignore[import-not-found]
        except Exception:
            logger.warning("UIE shim: spaCy not importable — Stage 4 will return []")
            return None
        # Prefer en_core_web_sm; fall back to any installed English model.
        for model in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
            try:
                cls._nlp = spacy.load(model, disable=["ner", "textcat", "lemmatizer"])
                logger.info("UIE shim: loaded spaCy model %s", model)
                return cls._nlp
            except Exception:
                continue
        logger.warning(
            "UIE shim: no spaCy English model available "
            "(install with `python -m spacy download en_core_web_sm`) "
            "— Stage 4 will return []"
        )
        return None

    @classmethod
    def extract_triples(cls, text: str) -> list[dict[str, Any]]:
        nlp = cls._get_nlp()
        if nlp is None:
            return []
        # spaCy default max_length is 1_000_000 — guard anyway.
        doc = nlp(text[:200_000])
        triples: list[dict[str, Any]] = []
        for sent in doc.sents:
            subj_tok = obj_tok = verb_tok = None
            for tok in sent:
                if tok.dep_ in ("nsubj", "nsubjpass") and subj_tok is None:
                    subj_tok = tok
                if tok.dep_ in ("dobj", "pobj", "attr", "obj") and obj_tok is None:
                    obj_tok = tok
                if tok.pos_ in ("VERB", "AUX") and verb_tok is None:
                    verb_tok = tok
            if subj_tok and verb_tok and obj_tok:
                triples.append(
                    {
                        "subject": _span_text(subj_tok),
                        "predicate": verb_tok.text.lower(),
                        "object": _span_text(obj_tok),
                        "confidence": 0.65,
                    }
                )
        return triples


def _span_text(tok: Any) -> str:
    """Return the noun-phrase span anchored on *tok*, or its text."""
    try:
        # spaCy: walk up to the head of the noun chunk if available
        for chunk in tok.sent.noun_chunks:
            if chunk.start <= tok.i < chunk.end:
                return chunk.text
    except Exception:
        pass
    return tok.text


# ---------------------------------------------------------------------------
# Backend 2 — REBEL (opt-in, heavy)
# ---------------------------------------------------------------------------


class _RebelUIE:
    """Lazy REBEL-backed triple extractor (opt-in)."""

    _pipe: Any = None
    _attempted: bool = False

    @classmethod
    def _get_pipe(cls) -> Any:
        if cls._pipe is not None or cls._attempted:
            return cls._pipe
        cls._attempted = True
        try:
            from transformers import pipeline  # type: ignore[import-not-found]

            cls._pipe = pipeline(
                "text2text-generation",
                model="Babelscape/rebel-large",
                tokenizer="Babelscape/rebel-large",
            )
            logger.info("UIE shim: loaded REBEL relational extractor")
        except Exception:
            logger.warning("UIE shim: REBEL backend unavailable — falling back to spaCy")
            cls._pipe = None
        return cls._pipe

    @classmethod
    def extract_triples(cls, text: str) -> list[dict[str, Any]]:
        pipe = cls._get_pipe()
        if pipe is None:
            return _SpacySVO.extract_triples(text)
        try:
            out = pipe(
                text,
                max_length=256,
                num_beams=3,
                return_tensors=False,
                truncation=True,
            )
        except Exception:
            logger.exception("UIE shim: REBEL inference failed")
            return _SpacySVO.extract_triples(text)
        return _parse_rebel(out[0].get("generated_text", ""))


def _parse_rebel(gen: str) -> list[dict[str, Any]]:
    """Parse REBEL's ``<triplet> s <subj> o <obj> r`` output format."""
    triples: list[dict[str, Any]] = []
    subj = rel = obj = ""
    state = "x"
    for tok in gen.replace("<s>", "").replace("<pad>", "").split():
        if tok == "<triplet>":
            if subj and rel and obj:
                triples.append(
                    {
                        "subject": subj.strip(),
                        "predicate": rel.strip(),
                        "object": obj.strip(),
                        "confidence": 0.80,
                    }
                )
            subj = rel = obj = ""
            state = "subj"
        elif tok == "<subj>":
            state = "obj"
        elif tok == "<obj>":
            state = "rel"
        else:
            if state == "subj":
                subj += " " + tok
            elif state == "obj":
                obj += " " + tok
            elif state == "rel":
                rel += " " + tok
    if subj and rel and obj:
        triples.append(
            {
                "subject": subj.strip(),
                "predicate": rel.strip(),
                "object": obj.strip(),
                "confidence": 0.80,
            }
        )
    return triples


# ---------------------------------------------------------------------------
# Public ``UIE`` class — what ``crp.extraction.stage4_uie`` imports
# ---------------------------------------------------------------------------


class UIE:
    """The contract object the CRP SDK expects from ``uie.UIE``."""

    def __init__(self) -> None:
        backend = os.environ.get("CRP_COMPLY_UIE_BACKEND", "spacy").lower()
        if backend == "rebel":
            self._impl: Any = _RebelUIE
        else:
            self._impl = _SpacySVO

    def extract_triples(self, text: str) -> list[dict[str, Any]]:
        if not text or not text.strip():
            return []
        try:
            return list(self._impl.extract_triples(text))
        except Exception:
            logger.exception("UIE shim: extract_triples failed")
            return []


# ---------------------------------------------------------------------------
# Side-effect: register ourselves as the top-level ``uie`` module
# ---------------------------------------------------------------------------


def _install() -> None:
    if "uie" in sys.modules:
        # Don't clobber a real installed package.
        return
    mod = types.ModuleType("uie")
    mod.UIE = UIE  # type: ignore[attr-defined]
    mod.__doc__ = "Synthetic ``uie`` module installed by crp_comply.extraction.uie_shim."
    sys.modules["uie"] = mod


_install()
