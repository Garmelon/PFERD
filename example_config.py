from pathlib import Path

from PFERD import Pferd, enable_logging


def main():
    enable_logging()
    pferd = Pferd(Path(__file__).parent)

    pferd.ilias_kit("DB", "1101554", cookies="ilias_cookies.txt")


if __name__ == "__main__":
    main()
