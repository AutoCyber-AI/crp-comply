"""CRP Comply extraction shims.

Side-effects on import:

1. Registers a synthetic ``uie`` top-level module in ``sys.modules`` so
   that ``crp.extraction.stage4_uie`` finds a ``UIE`` class to
   instantiate. See :mod:`crp_comply.extraction.uie_shim`.
2. Installs ``warnings.filterwarnings`` rules for known-harmless
   upstream warnings emitted by ``transformers``, ``huggingface_hub``,
   ``sentencepiece`` and ``gliner`` during fact extraction. These are
   informational and cannot be silenced at the source without re-pinning
   the upstream library.
"""

from __future__ import annotations

import warnings

from . import uie_shim as _uie_shim  # noqa: F401  (registers ``uie`` module)


def _install_warning_filters() -> None:
    # GLiNER processor: "Sentence of length N has been truncated to 384"
    # — we already pre-chunk in ``ckf_corpus._split_for_extraction`` to
    # keep this from firing, but a long single word can still trigger it.
    warnings.filterwarnings(
        "ignore",
        message=r"Sentence of length \d+ has been truncated.*",
        category=UserWarning,
    )
    # huggingface_hub: ``resume_download`` deprecation. Emitted by older
    # transformers; resume always happens now.
    warnings.filterwarnings(
        "ignore",
        message=r".*resume_download.*deprecated.*",
        category=FutureWarning,
    )
    # transformers: tokenizer conversion warning about sentencepiece
    # byte-fallback. Cannot be fixed without retraining the tokenizer.
    warnings.filterwarnings(
        "ignore",
        message=r"The sentencepiece tokenizer that you are converting.*",
        category=UserWarning,
    )
    # transformers: "Asking to truncate to max_length but no maximum
    # length is provided" — fired from internal calls we do not own.
    warnings.filterwarnings(
        "ignore",
        message=r"Asking to truncate to max_length but no maximum length.*",
        category=UserWarning,
    )


_install_warning_filters()
