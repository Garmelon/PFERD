from .config import Config
from .crawlers import CRAWLERS


class Pferd:
    def __init__(self, config: Config):
        self._config = config

    async def run(self) -> None:
        print("Bleep bloop 1")
        await CRAWLERS["dummy"]("dummy", self._config._parser["dummy"]).run()
        print("Bleep bloop 2")
