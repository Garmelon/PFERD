"""
Runs PFERD in the current process, so a test can serve the pages it crawls from the same event loop.
"""

import configparser
import json
from pathlib import Path
from typing import Any, Optional

from PFERD.config import Config
from PFERD.pferd import Pferd


async def run_pferd(
    working_dir: Path,
    crawler: dict[str, str],
    other_sections: Optional[dict[str, dict[str, str]]] = None,
) -> dict[str, Any]:
    """
    Runs a single crawler, whose output directory is "<working_dir>/output", and returns its report.
    Other sections (like authenticators) are added to the config as they are.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser["DEFAULT"] = {"working_dir": str(working_dir)}
    parser["crawl:test"] = {"output_dir": "output", **crawler}
    for name, section in (other_sections or {}).items():
        parser[name] = section

    pferd = Pferd(Config(parser), None, None)
    await pferd.run(debug_transforms=False)
    assert not pferd.failed

    return json.loads((working_dir / "output" / ".report").read_text())
