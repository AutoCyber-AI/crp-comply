"""crp-comply web-search sidecar (PHASE_7 \u00a77.8).

Public surface:

* :class:`crp_comply_search.app.create_app` \u2014 factory for the
  FastAPI application; the production entry point passes its own
  configuration.
* :class:`crp_comply_search.backends.WebSearchBackend` \u2014 Protocol
  every backend conforms to.
* :class:`crp_comply_search.profiles.TrustTierProfile` \u2014 loaded
  YAML profile.
"""

from __future__ import annotations

__version__ = "0.1.1"
