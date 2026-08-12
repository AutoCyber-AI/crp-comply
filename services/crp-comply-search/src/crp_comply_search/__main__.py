"""Convenience entry point: ``python -m crp_comply_search``.

Boots :func:`crp_comply_search.app.create_app` under uvicorn,
honouring ``PORT`` (Railway-style) with a default of 8081.
"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", "8081"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
