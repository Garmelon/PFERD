"""
A small sample config for PFERD.
"""
from pathlib import Path

from PFERD import Pferd, enable_logging
from PFERD.ilias.download_strategies import (download_everything,
                                             download_modified_or_new)


def main() -> None:
    enable_logging()
    pferd = Pferd(Path(__file__).parent)

    # Synchronize "databases" and only download files with a more recent timestamp than
    # the local copy, if any exists.
    pferd.ilias_kit(
        Path("DB"),
        "1101554",
        cookies=Path("ilias_cookies.txt"),
        download_strategy=download_modified_or_new
    )

    # Synchronize "databases" and redownload every file (default).
    pferd.ilias_kit(
        Path("DB"),
        "1101554",
        cookies=Path("ilias_cookies.txt"),
        download_strategy=download_everything
    )


if __name__ == "__main__":
    main()
