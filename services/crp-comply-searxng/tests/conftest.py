"""Test scaffolding for the SearXNG-host CRP plugins.

The plugin modules import ``searx.*`` and ``flask`` at the top level, neither
of which is installed in the main monorepo test environment. This conftest
injects lightweight fake modules so the plugin logic can be imported and
unit-tested without a running SearXNG instance.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# ── Fake SearXNG settings / plugin base classes ──────────────────────────


def _install_fakes() -> None:
    if "searx" in sys.modules:
        return

    settings = types.ModuleType("searx.settings")
    settings._data = {
        "crp_agent": {
            "router": {
                "intents": {
                    "regulation_text": ["eur-lex", "curia", "bing"],
                    "case_law": ["curia", "bailii", "bing"],
                    "guidance": ["edpb", "eur-lex", "bing"],
                    "enforcement": ["edpb", "bing", "duckduckgo"],
                    "news": ["bing", "duckduckgo", "brave"],
                    "vendor": ["bing", "duckduckgo", "github"],
                    "general": ["bing", "duckduckgo", "wikipedia"],
                },
                "max_engines_per_query": 3,
            },
            "reranker": {
                "feedback_db": ":memory:",
                "decay_half_life_days": 14,
                "min_observations": 2,
            },
        }
    }

    def _get(key: str, default: object = None) -> object:
        keys = key.split(".")
        value: object = settings._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    settings.get = _get
    sys.modules["searx.settings"] = settings

    plugins = types.ModuleType("searx.plugins")

    class Plugin:
        def __init__(self, plg_cfg: object = None) -> None:
            pass

    class PluginInfo:
        def __init__(self, **kwargs: object) -> None:
            pass

    plugins.Plugin = Plugin
    plugins.PluginInfo = PluginInfo
    sys.modules["searx.plugins"] = plugins

    _crp = types.ModuleType("searx.plugins._crp")
    _crp.learning_reranker = types.ModuleType("searx.plugins._crp.learning_reranker")
    _crp.learning_reranker.engine_scores = lambda intent: {}
    sys.modules["searx.plugins._crp"] = _crp
    sys.modules["searx.plugins._crp.learning_reranker"] = _crp.learning_reranker

    searx_pkg = types.ModuleType("searx")
    searx_pkg.settings = settings
    sys.modules["searx"] = searx_pkg

    # Flask is only needed for the endpoint registration helpers.
    flask = types.ModuleType("flask")

    def jsonify(*args: object, **kwargs: object) -> tuple[object, ...]:
        return args if args else kwargs

    class _Request:
        is_json = True

        @staticmethod
        def get_json(silent: bool = False) -> dict:
            return {}

    flask.jsonify = jsonify
    flask.request = _Request()
    sys.modules["flask"] = flask

    # Make the plugin source directory importable as plain modules.
    plugins_dir = Path(__file__).parent.parent / "plugins"
    if str(plugins_dir) not in sys.path:
        sys.path.insert(0, str(plugins_dir))


_install_fakes()


@pytest.fixture
def query_router_module():
    import query_router

    return query_router


@pytest.fixture
def learning_reranker_module():
    import learning_reranker

    return learning_reranker
