"""
Synchronizing files from ILIAS instances (https://www.ilias.de/).
"""

from .authenticators import IliasAuthenticator, KitShibbolethAuthenticator
from .crawler import IliasCrawler, IliasDirectoryFilter
from .download_strategies import *
from .downloader import IliasDownloader
