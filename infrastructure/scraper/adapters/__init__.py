# infrastructure.scraper.adapters package
"""
Site-specific crawling adapters.

- BaseSiteAdapter: Abstract interface.
- OJSSiteAdapter: Open Journal Systems.
- GenericSiteAdapter: Fallback BFS crawler.
"""
from infrastructure.scraper.adapters.base import BaseSiteAdapter, ArticleInfo
from infrastructure.scraper.adapters.ojs import OJSSiteAdapter
from infrastructure.scraper.adapters.generic import GenericSiteAdapter

__all__ = [
    "BaseSiteAdapter",
    "ArticleInfo",
    "OJSSiteAdapter",
    "GenericSiteAdapter",
]
