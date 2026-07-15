"""Decide how often the scraper may run within the SerpApi search quota.

The CI schedule fires every day, but SerpApi only allows a limited number of
searches per billing period. This module asks the free SerpApi Account API how
many searches are left and when the period renews, then spreads the runs the
remaining budget can afford — assuming the worst case of every profile needing
the search fallback with both prefixes — evenly over the rest of the period.
On days that don't fit the budget, the run is skipped.
"""

import logging
import os
from datetime import date
from math import ceil
from typing import NamedTuple

import serpapi

from app.services.social import SERPAPI_KEY_ENV

logger = logging.getLogger(__name__)


class SerpApiQuota(NamedTuple):
    """Remaining SerpApi search budget for the current billing period."""

    searches_left: int
    """Searches left until the period renews."""
    renewal_date: date
    """Date on which the billing period renews and the budget resets."""


def serpapi_quota() -> SerpApiQuota | None:
    """Return the remaining SerpApi search budget for this billing period.

    Uses the Account API, which does not count against the search quota.

    Returns:
        The remaining searches and the period's renewal date, or ``None`` if
        ``SERPAPI_KEY`` is unset or the Account API request fails — in which
        case there is nothing to budget (no key means no fallback searches)
        or nothing reliable to budget with.
    """
    api_key = os.environ.get(SERPAPI_KEY_ENV)
    if not api_key:
        return None
    try:
        account = serpapi.Client(api_key=api_key, timeout=10).account()
        return SerpApiQuota(
            searches_left=int(account["plan_searches_left"]),
            # Truncate a possible time part, e.g. "2026-08-09T00:00:00Z".
            renewal_date=date.fromisoformat(str(account["plan_renewal_date"])[:10]),
        )
    except Exception as exc:  # noqa: BLE001 - quota info is best-effort
        logger.warning("Could not fetch SerpApi account info (%s).", exc)
        return None


def should_scrape(today: date, quota: SerpApiQuota | None, profile_count: int) -> bool:
    """Decide whether today's run fits into the remaining SerpApi budget.

    Args:
        today: The current date.
        quota: The remaining search budget, or ``None`` if unknown (then the
            run is never throttled).
        profile_count: Number of profiles this run would scrape.

    Returns:
        ``True`` if the run should go ahead today, ``False`` to skip it.
    """
    if quota is None or profile_count <= 0:
        return True

    # Worst case: every profile needs the fallback and tries some prefixes
    worst_case_per_run = profile_count * 1.5
    runs_left = quota.searches_left // worst_case_per_run
    remaining_days = max((quota.renewal_date - today).days, 1)

    if runs_left >= remaining_days:
        return True
    if runs_left <= 0:
        logger.warning(
            "SerpApi quota too low for a worst-case run (%d searches left, "
            "up to %d needed); skipping until the period renews on %s.",
            quota.searches_left,
            worst_case_per_run,
            quota.renewal_date,
        )
        return False

    # Spread the affordable runs evenly over the rest of the period.
    interval = ceil(remaining_days / runs_left)
    if remaining_days % interval == 0:
        return True
    logger.info(
        "Skipping today to stay within the SerpApi quota (%d searches left "
        "allow %d more worst-case runs over %d days; next run in %d day(s)).",
        quota.searches_left,
        runs_left,
        remaining_days,
        remaining_days % interval,
    )
    return False
