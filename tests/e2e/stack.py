"""
The ILIAS instance the end-to-end tests run against, started with docker compose.

All pytest-xdist workers share a single instance. The first worker that needs it starts and seeds it,
the others wait for that and attach to it. The controller process removes it at the end of the session
(see tests/conftest.py), as no worker knows whether it is the last one using it.

By default, every test session starts a fresh ILIAS instance. Set PFERD_E2E_KEEP=1 to keep the instance
running (on PFERD_E2E_PORT, default 8080) and reuse it in the next session, which saves the ~1.5 minutes
ILIAS needs to install itself and seed the fixtures.
"""

import fcntl
import json
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

COMPOSE_FILE = Path(__file__).parent / "compose.yml"
SEED_RESULT_PATH = "/var/iliasdata/ilias/seed-result.json"
KEEP = os.environ.get("PFERD_E2E_KEEP") == "1"

# Directory shared by the controller and all workers, which inherit the environment of the controller
STATE_DIR_ENV = "PFERD_E2E_STATE_DIR"
STATE_FILE = "ilias.json"


class Compose:
    def __init__(self, project: str, port: int):
        self.project = project
        self.port = port

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", str(COMPOSE_FILE), *args],
            env={**os.environ, "ILIAS_PORT": str(self.port)},
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return result

    def exec_ilias(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run("exec", "-T", "-u", "www-data", "ilias", *args, check=check)


@dataclass(frozen=True)
class Ilias:
    base_url: str
    # The JSON printed by seed/seed.php
    seed: dict[str, Any]
    compose: Compose

    def course(self, name: str) -> int:
        return self.seed["courses"][name]

    def run_php(self, script: str, *args: str) -> Any:
        """
        Runs a script from the seed directory and returns the JSON it prints as its last line.
        """
        output = self.compose.exec_ilias("php", f"/seed/{script}", *args).stdout
        return json.loads(output.strip().splitlines()[-1])


def create_state_dir() -> None:
    """
    Called once by the controller, before any worker starts.
    """
    os.environ[STATE_DIR_ENV] = tempfile.mkdtemp(prefix="pferd-e2e-")


def _state_dir() -> Path:
    return Path(os.environ[STATE_DIR_ENV])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _start() -> Ilias:
    if KEEP:
        compose = Compose("pferd-e2e", int(os.environ.get("PFERD_E2E_PORT", "8080")))
    else:
        compose = Compose(f"pferd-e2e-{uuid.uuid4().hex[:8]}", _free_port())
    # Written before starting, so the controller also removes a stack that failed to start
    (_state_dir() / STATE_FILE).write_text(json.dumps({"project": compose.project, "port": compose.port}))

    try:
        compose.run("up", "-d", "--wait", "--wait-timeout", "600")
    except RuntimeError as e:
        logs = compose.run("logs", "ilias", check=False).stdout
        raise RuntimeError(f"{e}\nILIAS logs:\n{logs}") from e

    seed_result = compose.exec_ilias("cat", SEED_RESULT_PATH, check=False)
    if seed_result.returncode != 0:
        compose.exec_ilias("php", "/seed/seed.php")
        seed_result = compose.exec_ilias("cat", SEED_RESULT_PATH)
    seed = json.loads(seed_result.stdout)

    (_state_dir() / STATE_FILE).write_text(
        json.dumps({"project": compose.project, "port": compose.port, "seed": seed})
    )
    return Ilias(base_url=f"http://localhost:{compose.port}", seed=seed, compose=compose)


def get_or_start() -> Ilias:
    """
    Returns the instance of this session, starting it if no other worker did so yet.
    """
    with open(_state_dir() / "ilias.lock", "w") as lock:
        # Blocks while another worker starts the instance
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read_state()
        if state is None:
            return _start()
        if "seed" not in state:
            raise RuntimeError("Another worker failed to start ILIAS, see its error")
        compose = Compose(state["project"], state["port"])
        return Ilias(base_url=f"http://localhost:{compose.port}", seed=state["seed"], compose=compose)


def _read_state() -> Optional[dict[str, Any]]:
    path = _state_dir() / STATE_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text())


def stop() -> None:
    """
    Called once by the controller, after all workers are done.
    """
    state = _read_state()
    if state is not None and not KEEP:
        Compose(state["project"], state["port"]).run("down", "-v", check=False)
    shutil.rmtree(_state_dir(), ignore_errors=True)
