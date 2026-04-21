__version__ = "0.1.0"

# Convenience re-exports so callers can do `from research_harness import ResearchAPI`
# instead of remembering `from research_harness.api import ResearchAPI`.
from .api import ResearchAPI  # noqa: E402

__all__ = ["ResearchAPI", "__version__"]
