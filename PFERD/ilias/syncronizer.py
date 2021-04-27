from typing import Callable, Awaitable, List, Optional

from .authenticators import IliasAuthenticator
from .crawler import (
    IliasCrawler,
    IliasDirectoryFilter,
    IliasCrawlerEntry,
    ResultContainer,
)

from ..utils import PathLike, to_path
from ..cookie_jar import CookieJar


class IliasSycronizer:
    """
    This class is used to manage a ILIAS Crawler
    """

    def __init__(
        self,
        base_url: str,
        authenticator: IliasAuthenticator,
        cookies: Optional[PathLike],
        dir_filter: IliasDirectoryFilter,
    ):
        self._cookie_jar = CookieJar(to_path(cookies) if cookies else None)
        self._cookie_jar.load_cookies()
        self._authenticator = authenticator

        self._client = self._cookie_jar.create_async_client()

        self._crawler = IliasCrawler(
            base_url, self._client, self._authenticator, dir_filter
        )
        self._targets = []

    def add_target(
        self,
        crawl_function: Callable[[IliasCrawler], Awaitable[List[IliasCrawlerEntry]]],
    ) -> ResultContainer:
        """
        Adds a crawl target and returns the ResultContainer, in which DownloadInfos will be saved

        Arguments:
            crawl_function {Callable[[IliasCrawler], Awaitable[List[IliasCrawlerEntry]]]} -- a callback which should return an awaitable list of IliasCrawlerEntrys
        """
        results = ResultContainer()
        self._targets.append((crawl_function, results))
        return results

    def get_authenticator(self):
        """
        Returns the associated authenticator
        """
        return self._authenticator

    def get_cookie_jar(self):
        """
        Returns the associated cookie jar
        """
        return self._cookie_jar

    async def close_client(self):
        """
        Closes the async client
        """
        await self._client.aclose()

    async def syncronize(self):
        """
        Syncronizes all registered targets
        """
        # Populate initial targets
        entries = []
        for (crawl_function, results) in self._targets:
            entries.append((await crawl_function(self._crawler), results))

        await self._crawler.iterate_entries_to_download_infos(entries)
        self._cookie_jar.save_cookies()
