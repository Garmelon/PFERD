from pathlib import PurePath
from typing import Awaitable, Dict, List, Optional, Tuple
from datetime import datetime

from bs4 import BeautifulSoup

from ..auth import Authenticator
from ..config import Config
from .crawler import CrawlError, FileSink, ProgressBar
from ..utils import soupify
from .http_crawler import HttpCrawler, HttpCrawlerSection
from .shib_login import ShibbolethLogin

BASE_URL = "https://lt2srv.iar.kit.edu"

class LanguageTranslatorCrawlerSection(HttpCrawlerSection):
    def tfa_auth(
        self, authenticators: Dict[str, Authenticator]
    ) -> Optional[Authenticator]:
        value: Optional[str] = self.s.get("tfa_auth")
        if value is None:
            return None
        auth = authenticators.get(value)
        if auth is None:
            self.invalid_value("tfa_auth", value, "No such auth section exists")
        return auth

    def target(self) -> str:
        target = self.s.get("target")
        if not target:
            self.missing_value("target")
        return target

class LanguageTranslatorCrawler(HttpCrawler):
    def __init__(
            self, 
            name: str,
            section: LanguageTranslatorCrawlerSection, 
            config: Config, 
            authenticators: Dict[str, Authenticator]
    ):
        # Setting a main authenticator for cookie sharing
        auth = section.auth(authenticators)
        super().__init__(name, section, config, shared_auth=auth)
        self._auth = auth
        self._url = section.target()
        self._tfa_auth = section.tfa_auth(authenticators)
        self._shibboleth_login = ShibbolethLogin(self._url, self._auth, self._tfa_auth)

    async def _run(self) -> None:
        auth_id = await self._current_auth_id()
        await self.authenticate(auth_id)

        maybe_cl = await self.crawl(PurePath("."))
        if not maybe_cl:
            return

        tasks: List[Awaitable[None]] = []

        async with maybe_cl:
            page, url = await self.get_page()
            links = []
            file_names = []
            for archive_div in page.find_all('div', class_='archivesession'):
                header_div = archive_div.find('div', class_='window-header')
                title = header_div.get_text(strip=True) if header_div else "Untitled"
                
                a_tag = archive_div.find('a', href=True)
                if a_tag and '/archivesession' in a_tag['href']:
                    media_url = BASE_URL + a_tag['href'].replace('archivesession', 'archivemedia')
                    links.append(media_url)
                    
                    # Make HEAD request to get content type
                    async with self.session.get(media_url, allow_redirects=False) as resp:
                        content_type = resp.headers.get('Content-Type', '')
                        extension = ''
                        if 'video/mp4' in content_type:
                            extension = '.mp4'
                        elif 'audio/mp3' in content_type:
                            extension = '.mp3'
                        elif 'video/webm' in content_type:
                            extension = '.webm'
                        file_names.append(f"{title}{extension}")
                    
            for title, link in zip(file_names, links):
                etag, mtime = None, None # await self._request_resource_version(link)
                tasks.append(self._download_file(PurePath("."), title, link, etag, mtime))

        await self.gather(tasks)

    async def _authenticate(self) -> None:
        await self._shibboleth_login.login(self.session)

    async def _download_file(
        self,
        parent: PurePath,
        title: str,
        url: str,
        etag: Optional[str],
        mtime: Optional[datetime]
    ) -> None:
        element_path = parent / title

        prev_etag = self._get_previous_etag_from_report(element_path)
        etag_differs = None if prev_etag is None else prev_etag != etag

        maybe_dl = await self.download(element_path, etag_differs=etag_differs, mtime=mtime)
        if not maybe_dl:
            # keep storing the known file's etag
            if prev_etag:
                self._add_etag_to_report(element_path, prev_etag)
            return

        async with maybe_dl as (bar, sink):
            await self._stream_from_url(url, element_path, sink, bar)

    async def _stream_from_url(self, url: str, path: PurePath, sink: FileSink, bar: ProgressBar) -> None:
        async with self.session.get(url, allow_redirects=False) as resp:
            if resp.status == 403:
                raise CrawlError("Received a 403. Are you within the KIT network/VPN?")
            if resp.content_length:
                bar.set_total(resp.content_length)

            async for data in resp.content.iter_chunked(1024):
                sink.file.write(data)
                bar.advance(len(data))

            sink.done()

            self._add_etag_to_report(path, resp.headers.get("ETag"))


    async def get_page(self) -> Tuple[BeautifulSoup, str]:
        async with self.session.get(self._url) as request:
            content = (await request.read()).decode("utf-8")
            return soupify(content.encode("utf-8")), str(request.url)