from pathlib import Path

from PFERD import Pferd, enable_logging


def main() -> None:
    enable_logging()
    pferd = Pferd(Path(__file__).parent)

    pferd.ilias_kit(Path("DB"), "1101554", cookies=Path("ilias_cookies.txt"))


if __name__ == "__main__":
    main()
