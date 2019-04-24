import filecmp
import logging
import pathlib
import shutil

from . import utils

__all__ = [
    "Organizer",
]
logger = logging.getLogger(__name__)

class Organizer:
    def __init__(self, base_dir, sync_dir):
        """
        base_dir - the .tmp directory will be created here
        sync_dir - synced files will be moved here
        Both are expected to be concrete pathlib paths.
        """

        self._base_dir = base_dir
        self._sync_dir = sync_dir

        self._temp_dir = pathlib.Path(self._base_dir, ".tmp")
        self._temp_nr = 0

        # check if base/sync dir exist?

        self._added_files = set()

    def clean_temp_dir(self):
        if self._temp_dir.exists():
            shutil.rmtree(self._temp_dir)
        self._temp_dir.mkdir(exist_ok=True)
        logger.debug(f"Cleaned temp dir: {self._temp_dir}")

    def temp_dir(self):
        nr = self._temp_nr
        self._temp_nr += 1
        temp_dir = pathlib.Path(self._temp_dir, f"{nr:08}").resolve()
        logger.debug(f"Produced new temp dir: {temp_dir}")
        return temp_dir

    def temp_file(self):
        # generate the path to a new temp file in base_path/.tmp/
        # make sure no two paths are the same
        nr = self._temp_nr
        self._temp_nr += 1
        temp_file =  pathlib.Path(self._temp_dir, f"{nr:08}.tmp").resolve()
        logger.debug(f"Produced new temp file: {temp_file}")
        return temp_file

    def add_file(self, from_path, to_path):
        if not from_path.exists():
            raise utils.FileNotFoundException(f"Could not add file at {from_path}")

        # check if sync_dir/to_path is inside sync_dir?
        to_path = pathlib.Path(self._sync_dir, to_path)

        if to_path.exists() and to_path.is_dir():
            if self._prompt_yes_no(f"Overwrite folder {to_path} with file?", default=False):
                shutil.rmtree(to_path)
            else:
                logger.warn(f"Could not add file {to_path}")
                return

        if to_path.exists():
            if filecmp.cmp(from_path, to_path, shallow=False):
                logger.info(f"Ignored {to_path}")

                # remember path for later reference
                self._added_files.add(to_path.resolve())
                logger.debug(f"Added file {to_path.resolve()}")

                # No further action needed, especially not overwriting symlinks...
                return
            else:
                logger.info(f"Different file at {to_path}")
        else:
            logger.info(f"New file at {to_path}")

        # copy the file from from_path to sync_dir/to_path
        # If the file being replaced was a symlink, the link itself is overwritten,
        # not the file the link points to.
        to_path.parent.mkdir(parents=True, exist_ok=True)
        from_path.replace(to_path)
        logger.debug(f"Moved {from_path} to {to_path}")

        # remember path for later reference, after the new file was written
        # This is necessary here because otherwise, resolve() would resolve the symlink too.
        self._added_files.add(to_path.resolve())
        logger.debug(f"Added file {to_path.resolve()}")

    def clean_sync_dir(self):
        self._clean_dir(self._sync_dir, remove_parent=False)
        logger.debug(f"Cleaned sync dir: {self._sync_dir}")

    def _clean_dir(self, path, remove_parent=True):
        for child in sorted(path.iterdir()):
            logger.debug(f"Looking at {child.resolve()}")
            if child.is_dir():
                self._clean_dir(child, remove_parent=True)
            elif child.resolve() not in self._added_files:
                if self._prompt_yes_no(f"Delete {child}?", default=False):
                    child.unlink()
                    logger.debug(f"Deleted {child}")

        if remove_parent:
            try:
                path.rmdir()
            except OSError: # directory not empty
                pass

    def _prompt_yes_no(self, question, default=None):
        if default is True:
            prompt = "[Y/n]"
        elif default is False:
            prompt = "[y/N]"
        else:
            prompt = "[y/n]"

        text = f"{question} {prompt} "
        WRONG_REPLY = "Please reply with 'yes'/'y' or 'no'/'n'."

        while True:
            response = input(text).strip().lower()
            if response in {"yes", "ye", "y"}:
                return True
            elif response in {"no", "n"}:
                return False
            elif response == "":
                if default is None:
                    print(WRONG_REPLY)
                else:
                    return default
            else:
                print(WRONG_REPLY)

# How to use:
#
# 1. Before downloading any files
# orga = Organizer("/home/user/sync/", "/home/user/sync/bookstore/")
# orga.clean_temp_dir()
#
# 2. Downloading a file
# tempfile = orga.temp_file()
# download_something_to(tempfile)
# orga.add_file(tempfile, "books/douglas_adams/hhgttg"
#
# 3. After downloading all files
# orga.clean_sync_dir()
# orga.clean_temp_dir()
