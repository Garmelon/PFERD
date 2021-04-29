import asyncio
import random
from pathlib import Path
from typing import Any

from rich.markup import escape

from ..crawler import Crawler

DUMMY_TREE = {
    "Blätter": {
        "Blatt_01.pdf": (),
        "Blatt_02.pdf": (),
        "Blatt_03.pdf": (),
        "Blatt_04.pdf": (),
        "Blatt_05.pdf": (),
        "Lösungen": {
            "Blatt_01_Lösung.pdf": (),
            "Blatt_02_Lösung.pdf": (),
            "Blatt_03_Lösung.pdf": (),
            "Blatt_04_Lösung.pdf": (),
            "Blatt_05_Lösung.pdf": (),
        },
    },
    "Vorlesungsfolien": {
        "VL_01.pdf": (),
        "VL_02.pdf": (),
        "VL_03.pdf": (),
        "VL_04.pdf": (),
        "VL_05.pdf": (),
    },
    "noch_mehr.txt": (),
    "dateien.jar": (),
}


class DummyCrawler(Crawler):
    async def crawl(self) -> None:
        await self._crawl_entry(Path(), DUMMY_TREE)

    async def _crawl_entry(self, path: Path, value: Any) -> None:
        if value == ():
            n = random.randint(5, 20)
            async with self.download_bar(path, n) as bar:
                await asyncio.sleep(random.random() / 2)
                for i in range(n):
                    await asyncio.sleep(0.5)
                    bar.advance()
            self.print(f"[green]Downloaded {escape(str(path))}")
        else:
            t = random.random() * 2 + 1
            async with self.crawl_bar(path) as bar:
                await asyncio.sleep(t)
            tasks = [self._crawl_entry(path / k, v) for k, v in value.items()]
            await asyncio.gather(*tasks)
