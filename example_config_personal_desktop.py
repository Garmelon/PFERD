"""
This is a small config that just crawls the ILIAS Personal Desktop.
It does not filter or rename anything, it just gobbles up everything it can find.

Note that this still includes a test-run switch, so you can see what it *would* download.
You can enable that with the "--test-run" command line switch,
i. e. "python3 example_config_minimal.py --test-run".
"""

import argparse
from pathlib import Path

from PFERD import Pferd


def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    args = parser.parse_args()

    # Create the Pferd helper instance
    pferd = Pferd(Path(__file__).parent, test_run=args.test_run)
    pferd.enable_logging()

    try:
        # Synchronize the personal desktop into the "ILIAS" directory.
        # It saves the cookies, so you only need to log in again when the ILIAS cookies expire.
        pferd.ilias_kit_personal_desktop(
            "ILIAS",
            cookies="ilias_cookies.txt",
        )

    except KeyboardInterrupt:
        print("Exiting early...")
    finally:
        # Prints a summary listing all new, modified or deleted files
        pferd.print_summary()


if __name__ == "__main__":
    main()
