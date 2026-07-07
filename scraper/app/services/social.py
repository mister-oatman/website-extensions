import logging
import os
from abc import ABC, abstractmethod
from re import IGNORECASE, search, sub

import requests
from curl_cffi import requests as curl_requests
from lxml.etree import HTML as etreeHTML
from lxml.etree import HTMLParser as etreeHTMLParser

logger = logging.getLogger(__name__)

SERPER_API_KEY_ENV = "SERPER_API_KEY"
"""Name of the environment variable holding the Serper API key."""


class SocialService(ABC):
    """Base class for scraping public follower counts from social platforms."""

    BASE_URL: str
    """Root URL of the platform, e.g. ``https://www.instagram.com``."""
    USER_URL: str
    """Profile URL template containing a ``{username}`` placeholder."""

    @classmethod
    def get_followers(cls, username: str) -> str:
        """Return the follower count for ``username`` as a display string.

        Scrapes the public profile page directly and only falls back to a
        Google (Serper) search if the direct scrape fails.

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
            logger.warning(
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
        """Return the follower count via a Google (Serper) search fallback.

        Args:
            username: The profile handle to look up.

        Returns:
            The follower count in uppercase, e.g. ``"1.2M"``.

        Raises:
            ValueError: If the search fails or the follower count cannot be
                parsed from the result snippet.
        """
        user_meta = cls.get_user_meta(username)

        followers = search(r"\d\S+(?= follower)", user_meta, IGNORECASE)

        if not followers:
            raise ValueError(
                f"Followers count not found for {username} on {cls.BASE_URL}. The page structure may have changed."
            )

        return followers.group(0).upper()

    @classmethod
    def get_user_meta(cls, username: str) -> str:
        """Fetch the search meta for a user's profile page.

        Args:
            username: The profile handle to fetch.

        Returns:
            The page's meta description as text.

        Raises:
            ValueError: If the ``SERPER_API_KEY`` environment variable is
                unset, the request returns a non-200 status code, or the meta
                description cannot be found.
        """
        api_key = os.environ.get(SERPER_API_KEY_ENV)
        if not api_key:
            raise ValueError(
                f"{SERPER_API_KEY_ENV} is not set; cannot use the search fallback."
            )

        url = sub(r"^https?://(www\.)?", "", cls.USER_URL.format(username=username))

        for search_prefix in ("site:", ""):
            r = requests.post(
                "https://google.serper.dev/search",
                json={"q": f"{search_prefix}{url} follower"},
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            if r.status_code == 200 and (
                result := next(
                    (
                        result["snippet"]
                        for result in r.json().get("organic", [])
                        if search(rf"^https?://(www\.)?{url}/?", result["link"])
                        and search(r"\S+(?= follower)", result["snippet"], IGNORECASE)
                    ),
                    None,
                )
            ):
                return result

        raise ValueError(
            f"Failed to fetch page for {username} on {cls.BASE_URL}. Status code: {r.status_code}"
        )


class InstagramService(SocialService):
    """Scrape follower counts from Instagram profiles."""

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
        meta_tag = tree.xpath('//meta[@property="og:description"]/@content')

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
