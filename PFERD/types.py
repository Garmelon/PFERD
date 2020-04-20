"""Contains common types."""

from pathlib import Path
from typing import Any, Dict, Union


class CrawlerEntry():
    """A single entry a crawler produced."""

    def __init__(self, path: Path, url: str, extra_data: Dict[str, Any]):
        """Create a new crawler entry.

        Arguments:
            path {Path} -- the path of the entry the crawler built
            url {str} -- the url to crawl it from
            extra_data {Any} -- any extra data the crawler might produce
        """
        self._path = path
        self.url = url
        self.extra_data = extra_data

    def __str__(self) -> str:
        """Format the entry as a string."""
        return f"CrawlerEntry({self.path} - {self.url} - {self.extra_data})"

    @property
    def path(self) -> Path:
        """Return the path of this entry."""
        return self._path

    @property
    def name(self) -> str:
        """Return the name component of the path."""
        return self._path.name

    def rename(self, new_name: str) -> 'CrawlerEntry':
        """Change the name (and nothing more) of the path."""
        return CrawlerEntry(Path(self._path.parent, new_name), self.url, self.extra_data)

    def move(self, new_path: Union[str, Path]) -> 'CrawlerEntry':
        """Move the file to a different path."""
        return CrawlerEntry(self._to_path(new_path), self.url, self.extra_data)

    def _to_path(self, path: Union[str, Path]) -> Path:
        """Convert a str/Path union to a Path."""
        return path if isinstance(path, Path) else Path(path)
