from abc import ABC, abstractmethod
from re import search

from curl_cffi import requests
from lxml.etree import HTML as etreeHTML
from lxml.etree import HTMLParser as etreeHTMLParser


class SocialService(ABC):
    """Base class for scraping public follower counts from social platforms."""

    BASE_URL: str
    """Root URL of the platform, e.g. ``https://www.instagram.com``."""
    USER_URL: str
    """Profile URL template containing a ``{username}`` placeholder."""

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
            ValueError: If the request returns a non-200 status code.
        """
        url = cls.USER_URL.format(username=username)
        r = requests.get(url, impersonate="chrome")

        if r.status_code != 200:
            raise ValueError(
                f"Failed to fetch page for {username}. Status code: {r.status_code}"
            )

        return r.text


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
