import logging
import os
from abc import ABC, abstractmethod
from re import search
from time import sleep

from curl_cffi import requests
from lxml.etree import HTML as etreeHTML
from lxml.etree import HTMLParser as etreeHTMLParser

logger = logging.getLogger(__name__)


class SocialService(ABC):
    """Base class for scraping public follower counts from social platforms."""

    BASE_URL: str
    """Root URL of the platform, e.g. ``https://www.instagram.com``."""
    USER_URL: str
    """Profile URL template containing a ``{username}`` placeholder."""

    RETRIES = 3
    """How many times to attempt a request before giving up."""
    RETRY_BACKOFF = 2.0
    """Base seconds to wait between retries (multiplied by the attempt number)."""

    @staticmethod
    def _proxy() -> str | None:
        """Return the proxy URL from the ``SCRAPER_PROXY`` env var, if set.

        Instagram (and, less often, TikTok) block requests from datacenter IP
        ranges such as CI runners. Pointing ``SCRAPER_PROXY`` at a residential
        proxy (``http://user:pass@host:port``) routes the scrape through an
        unblocked IP.

        Returns:
            The proxy URL, or ``None`` when the env var is unset.
        """
        return os.environ.get("SCRAPER_PROXY") or None

    @staticmethod
    @abstractmethod
    def get_followers(username: str) -> str:
        """Return the follower count for ``username`` as a display string.

        Args:
            username: The profile handle to look up.

        Returns:
            The follower count, e.g. ``"1.2M"``.
        """
        pass

    @classmethod
    def get_user_html(cls, username: str) -> str:
        """Fetch the raw HTML of a user's profile page.

        Args:
            username: The profile handle to fetch.

        Returns:
            The page's HTML as text.

        Raises:
            ValueError: If every attempt returns a non-200 status code.
        """
        url = cls.USER_URL.format(username=username)
        proxy = cls._proxy()
        last_status: int | None = None

        for attempt in range(1, cls.RETRIES + 1):
            r = requests.get(url, impersonate="chrome", proxy=proxy)
            if r.status_code == 200:
                return r.text

            last_status = r.status_code
            if attempt < cls.RETRIES:
                sleep(cls.RETRY_BACKOFF * attempt)

        raise ValueError(
            f"Failed to fetch page for {username} after {cls.RETRIES} attempts "
            f"(last status code: {last_status}). The platform is likely blocking "
            "this IP, which is common on CI runners; set SCRAPER_PROXY to a "
            "residential proxy to route around it."
        )


class InstagramService(SocialService):
    """Scrape follower counts from Instagram profiles."""

    BASE_URL = "https://www.instagram.com"
    USER_URL = f"{BASE_URL}/{{username}}"

    @classmethod
    def get_followers(cls, username: str) -> str:
        """Return the follower count for an Instagram ``username``.

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
        logger.info(user_html)

        tree = etreeHTML(user_html, parser=etreeHTMLParser(remove_comments=True))
        meta_tag = tree.xpath('//meta[@property="og:description"]/@content')

        if not meta_tag:
            hint = (
                " The page looks like a login wall, which Instagram serves to "
                "blocked IPs (common on CI runners); set SCRAPER_PROXY to a "
                "residential proxy to route around it."
                if "loginForm" in user_html or "/accounts/login" in user_html
                else " The page structure may have changed."
            )
            raise ValueError(f"Meta tag not found for {username}.{hint}")

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
    def get_followers(cls, username: str) -> str:
        """Return the follower count for a TikTok ``username``.

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
