import logging
import os
import time
from abc import ABC, abstractmethod
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from re import IGNORECASE, search, sub
from typing import cast

import serpapi
from curl_cffi import requests as curl_requests
from lxml.etree import HTML as etreeHTML
from lxml.etree import HTMLParser as etreeHTMLParser

from app import state

logger = logging.getLogger(__name__)

SERPAPI_KEY_ENV = "SERPAPI_KEY"
"""Name of the environment variable holding the SerpApi API key."""

SEARCH_PREFIXES = ("", "site:")
"""Google search prefixes the search fallback tries, in default order."""

SERPAPI_TIMEOUT_S = 300
"""Seconds to wait for a SerpApi response before timing out."""

FOLLOWERS_PATTERN = r"(\d[\d.,]*)([KMB])?\+?(?=\s*followers?\b)"
"""Matches a follower count in a search result, e.g. ``47.5K+ followers``.

Group 1 is the number with its thousands separators, group 2 the ``K``/``M``/
``B`` magnitude suffix, if present. A trailing ``+`` is matched but not
captured.
"""

SUFFIX_FACTORS = {"B": 1_000_000_000, "M": 1_000_000, "K": 1_000, "": 1}
"""Numeric value of each magnitude suffix a follower count can carry.

Ordered from the largest, so :func:`_format_followers` can pick the first
suffix a count reaches.
"""

FALLBACK_SEARCHES_PER_HOUR = 1000
"""Assumed hourly throughput when the Account API can't be read."""

MAX_THROTTLE_S = 60
"""Cap on the wait inserted between calls, so pacing never stalls a run."""

_search_interval_s: float | None = None
"""Cached minimum spacing between SerpApi calls; computed once on first use."""

_last_search_time: float | None = None
"""Monotonic timestamp of the last SerpApi call started, for throttling."""


def _parse_followers(text: str) -> Decimal | None:
    """Return the follower count found in ``text`` as a number.

    A search result states the count either in full (``437.270 Follower``) or
    abbreviated with a magnitude suffix (``47.5K+ followers``), in whichever
    notation the result's locale uses. A follower count is always a whole
    number, so every separator groups thousands and none is a decimal symbol:
    ``47.5K`` is exactly 47 500 followers, the ``5`` being the leading digit of
    the group the ``K`` cuts short.

    Args:
        text: A search result field, e.g. a snippet or a displayed link.

    Returns:
        The follower count as a number, or ``None`` if ``text`` reveals no count
        or states it unintelligibly.
    """
    followers = search(FOLLOWERS_PATTERN, text, IGNORECASE)

    if not followers:
        return None

    count, suffix = followers.group(1), (followers.group(2) or "").upper()

    if suffix:
        # An abbreviated count breaks off mid-group, which scales exactly like
        # a fraction of the suffix would ("47.5K" -> 47.5 * 1000 = 47 500), so
        # the last separator can be read as a decimal point. Separators before
        # it close whole groups ("1.234,5K") and are dropped.
        count = sub(r"[.,](?=[^.,]*[.,])", "", count)
        count = sub(r"[.,]", ".", count)
    else:
        # A count stated in full has whole groups only ("437.270" / "437,270").
        count = sub(r"[.,]", "", count)

    try:
        return Decimal(count) * SUFFIX_FACTORS[suffix]
    except InvalidOperation:
        logger.debug(
            "Could not interpret %r as a follower count in %r.",
            followers.group(0),
            text,
        )
        return None


def _format_followers(count: Decimal) -> str:
    """Render a follower count for output, e.g. ``Decimal("437270")`` -> ``437.2K``.

    Abbreviates the count with the largest magnitude suffix it reaches and keeps
    one leading digit of the group below that suffix. The remaining digits are
    cut off rather than rounded up, so the output never claims more followers
    than the platform reported.

    Args:
        count: A follower count as returned by :func:`_parse_followers`.

    Returns:
        The abbreviated count, always separated by a dot, e.g. ``"47.5K"``. A
        count that lands on a whole group keeps no separator (``"437K"``, not
        ``"437.0K"``).
    """
    suffix, factor = next(
        (suffix, factor)
        for suffix, factor in SUFFIX_FACTORS.items()
        if count >= factor or factor == 1
    )
    scaled = (count / factor).quantize(Decimal("0.1"), rounding=ROUND_DOWN)

    return f"{f'{scaled:f}'.removesuffix('.0')}{suffix}"


def _search_interval(client: serpapi.Client) -> float:
    """Return the minimum spacing (in seconds) between SerpApi search calls.

    SerpApi guarantees throughput per hour rather than per second, so calls are
    paced to stay within that budget and avoid bursts that provoke slow
    responses. The pace is taken from the account's live hourly limits via the
    free Account API (which doesn't count against the search quota): the
    searches still available this hour
    (``account_rate_limit_per_hour`` minus ``this_hour_searches``) are spread
    over an hour, so pacing tightens automatically as the account nears its
    cap. The result is fetched once and cached for the process; if the Account
    API can't be read it falls back to ``FALLBACK_SEARCHES_PER_HOUR``.
    """
    global _search_interval_s
    if _search_interval_s is not None:
        return _search_interval_s

    per_hour = FALLBACK_SEARCHES_PER_HOUR
    try:
        account = client.account()
        rate_limit = int(account["account_rate_limit_per_hour"])
        used = int(account.get("this_hour_searches", 0))
        per_hour = max(1, rate_limit - used)
        logger.debug(
            "SerpApi hourly limit %d, %d used this hour; pacing at %d/hour.",
            rate_limit,
            used,
            per_hour,
        )
    except Exception as exc:  # noqa: BLE001 - pacing is best-effort
        logger.warning(
            "Could not read SerpApi account limits (%s); pacing at %d/hour.",
            exc,
            per_hour,
        )

    _search_interval_s = min(MAX_THROTTLE_S, 3600 / per_hour) if per_hour > 0 else 0.0
    return _search_interval_s


def _throttle_search(client: serpapi.Client) -> None:
    """Sleep so consecutive SerpApi calls respect the account's hourly limit.

    Enforces at least :func:`_search_interval` seconds between the *starts* of
    consecutive calls, then records the current call's start time. Safe for the
    scraper's sequential, single-threaded run.
    """
    global _last_search_time
    interval = _search_interval(client)
    if interval > 0 and _last_search_time is not None:
        wait = interval - (time.monotonic() - _last_search_time)
        if wait > 0:
            logger.debug("Throttling SerpApi call: sleeping %.1fs.", wait)
            time.sleep(wait)
    _last_search_time = time.monotonic()


class SocialService(ABC):
    """Base class for scraping public follower counts from social platforms."""

    PLATFORM: str
    """Platform key used in output and persistent state, e.g. ``"instagram"``."""
    BASE_URL: str
    """Root URL of the platform, e.g. ``https://www.instagram.com``."""
    USER_URL: str
    """Profile URL template containing a ``{username}`` placeholder."""

    @classmethod
    def get_followers(cls, username: str) -> str:
        """Return the follower count for ``username`` as a display string.

        Scrapes the public profile page directly and only falls back to a
        Google (SerpApi) search if the direct scrape fails.

        Args:
            username: The profile handle to look up.

        Returns:
            The follower count in uppercase, e.g. ``"1.2M"``.

        Raises:
            ValueError: If both the direct scrape and the search fallback fail
                to produce a follower count.
        """
        try:
            return cls._get_followers_from_page(username)
        except Exception as exc:  # noqa: BLE001 - fall back to search on any failure
            logger.debug(
                "Direct scrape failed for %s on %s (%s); falling back to search.",
                username,
                cls.BASE_URL,
                exc,
            )
            try:
                return cls._get_followers_from_search(username)
            except Exception as fallback_exc:  # noqa: BLE001 - report both failures
                raise ValueError(
                    f"Failed to fetch followers for {username} on {cls.BASE_URL}: "
                    f"scrape failed ({exc}); search fallback failed ({fallback_exc})."
                ) from fallback_exc

    @classmethod
    @abstractmethod
    def _get_followers_from_page(cls, username: str) -> str:
        """Return the follower count by scraping the profile page directly.

        Args:
            username: The profile handle to look up.

        Returns:
            The follower count in uppercase, e.g. ``"1.2M"``.

        Raises:
            ValueError: If the page cannot be fetched or the follower count
                cannot be parsed (the page structure may have changed).
        """
        ...

    @classmethod
    def get_user_html(cls, username: str) -> str:
        """Fetch the raw HTML of a user's profile page.

        Args:
            username: The profile handle to fetch.

        Returns:
            The page's HTML as text.

        Raises:
            ValueError: If the request returns a non-200 status code.
        """
        url = cls.USER_URL.format(username=username)
        r = curl_requests.get(url, impersonate="chrome")

        if r.status_code != 200:
            raise ValueError(
                f"Failed to fetch page for {username}. Status code: {r.status_code}"
            )

        return r.text

    @classmethod
    def _get_followers_from_search(cls, username: str) -> str:
        """Return the follower count via a Google (SerpApi) search fallback.

        Args:
            username: The profile handle to look up.

        Returns:
            The follower count abbreviated with a magnitude suffix, e.g.
            ``"1.2M"``.

        Raises:
            ValueError: If the search fails or the follower count cannot be
                parsed from the result's snippet or displayed link.
        """
        snippet, displayed_link = cls.get_user_meta(username)

        # Both sources state the count in their own way, so whichever reports
        # more followers wins.
        candidates = [
            followers
            for followers in (
                _parse_followers(snippet),
                _parse_followers(displayed_link),
            )
            if followers is not None
        ]

        if not candidates:
            raise ValueError(
                f"Followers count not found for {username} on {cls.BASE_URL}. "
                "The page structure may have changed."
            )

        return _format_followers(max(candidates))

    @classmethod
    def get_user_meta(cls, username: str) -> tuple[str, str]:
        """Fetch the search meta for a user's profile page.

        Args:
            username: The profile handle to fetch.

        Returns:
            The snippet and the displayed link of the first search result that
            points at the profile and states a follower count. Either one can
            be empty, but not both.

        Raises:
            ValueError: If the ``SERPAPI_KEY`` environment variable is unset or
                no matching search result with a follower count is found.
            serpapi.HTTPError: If a SerpApi request fails.
        """
        api_key = os.environ.get(SERPAPI_KEY_ENV)
        if not api_key:
            raise ValueError(
                f"{SERPAPI_KEY_ENV} is not set; cannot use the search fallback."
            )

        url = sub(r"^https?://(www\.)?", "", cls.USER_URL.format(username=username))

        client = serpapi.Client(api_key=api_key, timeout=SERPAPI_TIMEOUT_S)

        prefixes = list(SEARCH_PREFIXES)
        # Try the prefix that worked last time first; it usually still works
        # and then the second search is never spent.
        if (preferred := state.get_search_prefix(cls.PLATFORM)) in prefixes:
            prefixes.sort(key=lambda prefix: prefix != preferred)

        for search_prefix in prefixes:
            _throttle_search(client)

            try:
                results = client.search(
                    {
                        "engine": "google",
                        "q": f"{search_prefix}{url}",
                        "gl": "de",
                        "location": "585069a5ee19ad271e9b56e3",
                    }
                )
            except serpapi.SerpApiError as exc:
                logger.warning("SerpApi request failed (%s).", exc)
                continue

            for result in results.get("organic_results", []):
                if not search(rf"^https?://(www\.)?{url}/?", result.get("link", "")):
                    continue

                meta = (result.get("snippet", ""), result.get("displayed_link", ""))

                if any(_parse_followers(text) is not None for text in meta):
                    state.set_search_prefix(cls.PLATFORM, search_prefix)
                    return meta

        raise ValueError(f"No follower count found for {username} on {cls.BASE_URL}.")


class InstagramService(SocialService):
    """Scrape follower counts from Instagram profiles."""

    PLATFORM = "instagram"
    BASE_URL = "https://www.instagram.com"
    USER_URL = f"{BASE_URL}/{{username}}"

    @classmethod
    def _get_followers_from_page(cls, username: str) -> str:
        """Return the Instagram follower count by parsing the profile page.

        Args:
            username: The Instagram handle to look up.

        Returns:
            The follower count in uppercase, e.g. ``"1.2M"``.

        Raises:
            ValueError: If the page cannot be fetched, the meta tag is missing,
                or the follower count cannot be parsed (the page structure may
                have changed).
        """
        user_html = cls.get_user_html(username)

        tree = etreeHTML(user_html, parser=etreeHTMLParser(remove_comments=True))
        # This XPath selects an attribute value, so it always yields a list of
        # strings; xpath()'s static return type is broader (it can also be a
        # scalar), hence the cast.
        meta_tag = cast(
            list[str], tree.xpath('//meta[@property="og:description"]/@content')
        )

        if not meta_tag:
            raise ValueError(
                f"Meta tag not found for {username}. The page structure may have changed."
            )

        followers = search(r"\S+(?= Followers)", meta_tag[0])

        if not followers:
            raise ValueError(
                f"Followers count not found for {username}. The page structure may have changed."
            )

        return followers.group(0).upper()


class TikTokService(SocialService):
    """Scrape follower counts from TikTok profiles."""

    PLATFORM = "tiktok"
    BASE_URL = "https://tiktok.com"
    USER_URL = f"{BASE_URL}/@{{username}}"

    @classmethod
    def _get_followers_from_page(cls, username: str) -> str:
        """Return the TikTok follower count by parsing the profile page.

        Args:
            username: The TikTok handle to look up (without the leading ``@``).

        Returns:
            The follower count in uppercase, e.g. ``"1.2M"``.

        Raises:
            ValueError: If the page cannot be fetched or the follower count
                cannot be parsed (the page structure may have changed).
        """
        user_html = cls.get_user_html(username)

        followers = search(rf"(?<=@{username}\s)\S+(?= Follower)", user_html)

        if not followers:
            raise ValueError(
                f"Followers count not found for {username}. The page structure may have changed."
            )

        return followers.group(0).upper()
