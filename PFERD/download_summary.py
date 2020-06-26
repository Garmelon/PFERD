import logging
from .logging import PrettyLogger
from .utils import PathLike


class DownloadSummary:

    def __init__(self):
        self._new_files = []
        self._changed_files = []
        self._deleted_files = []

    def merge(self, summary: 'DownloadSummary') -> None:
        self._new_files += summary._new_files
        self._changed_files += summary._changed_files
        self._deleted_files += summary._deleted_files

    def add_deleted_file(self, path: PathLike) -> None:
        self._deleted_files.append(path)

    def add_changed_file(self, path: PathLike) -> None:
        self._changed_files.append(path)

    def add_new_file(self, path: PathLike) -> None:
        self._new_files.append(path)

    def _has_no_updates(self) -> bool:
        return len(self._new_files) == 0 and len(self._changed_files) == 0 and len(self._deleted_files) == 0

    def print(self, logger: logging, pretty: PrettyLogger) -> None:
        logger.info("")
        logger.info("Summary: ")
        if self._has_no_updates():
            logger.info("nothing changed")
        else:
            if len(self._new_files) > 0:
                logger.info("New Files:")
                for file in self._new_files:
                    pretty.new_file(file)

            logger.info("")

            if len(self._changed_files) > 0:
                logger.info("Modified Files:")
                for file in self._changed_files:
                    pretty.modified_file(file)

            logger.info("")

            if len(self._deleted_files) > 0:
                logger.info("Deleted Files:")
                for file in self._deleted_files:
                    pretty.deleted_file(file)
