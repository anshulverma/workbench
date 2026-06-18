"""Domain package — the entity vocabulary of Workbench.

This package replaces the former single models module. It holds the pydantic
models and enums that make up the shared domain language, split by concern
across submodules. This ``__init__`` re-exports the full public surface
so callers always import ``from workbench.domain import X`` and never depend on
submodule locations.
"""

from __future__ import annotations

from workbench.domain.diff import *  # noqa: F401,F403
from workbench.domain.diff import __all__ as _diff_all
from workbench.domain.enrichment import *  # noqa: F401,F403
from workbench.domain.enrichment import __all__ as _enrichment_all
from workbench.domain.enums import *  # noqa: F401,F403
from workbench.domain.enums import __all__ as _enums_all
from workbench.domain.feedback import *  # noqa: F401,F403
from workbench.domain.feedback import __all__ as _feedback_all
from workbench.domain.filters import *  # noqa: F401,F403
from workbench.domain.filters import __all__ as _filters_all
from workbench.domain.items import *  # noqa: F401,F403
from workbench.domain.items import __all__ as _items_all
from workbench.domain.llm_calls import *  # noqa: F401,F403
from workbench.domain.llm_calls import __all__ as _llm_calls_all
from workbench.domain.pipeline import *  # noqa: F401,F403
from workbench.domain.pipeline import __all__ as _pipeline_all
from workbench.domain.plans import *  # noqa: F401,F403
from workbench.domain.plans import __all__ as _plans_all
from workbench.domain.preferences import *  # noqa: F401,F403
from workbench.domain.preferences import __all__ as _preferences_all
from workbench.domain.sources import *  # noqa: F401,F403
from workbench.domain.sources import __all__ as _sources_all
from workbench.domain.triage import *  # noqa: F401,F403
from workbench.domain.triage import __all__ as _triage_all

__all__ = [
    *_enums_all,
    *_items_all,
    *_llm_calls_all,
    *_pipeline_all,
    *_triage_all,
    *_diff_all,
    *_feedback_all,
    *_filters_all,
    *_preferences_all,
    *_enrichment_all,
    *_sources_all,
    *_plans_all,
]
