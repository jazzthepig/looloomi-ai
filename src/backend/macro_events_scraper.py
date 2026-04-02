"""
Macro events scraper stub.
Placeholder — macro events feature is planned but not yet implemented.
Currently returns empty list so signal feed gracefully degrades.
"""
import logging

logger = logging.getLogger(__name__)


async def fetch_all_macro_events() -> list:
    """
    Fetch macro events from RSS feeds.
    TO DO: Implement with feedparser + async HTTP.
    """
    logger.warning("[macro_events] fetch_all_macro_events not implemented — returning []")
    return []
