import hashlib
import re
from pathlib import Path

# Files PFERD keeps next to the downloaded files
PFERD_FILES = {".cookies", ".report"}

# Ids of ILIAS objects in generated files (links and HTML ids). They depend on how many objects the seed
# created before, so they change whenever a fixture is added.
OBJECT_ID = re.compile(
    rb"((?:ref_id|item_ref_id|obj_id)=|goto\.php/[a-z]+/|target=[a-z]+_|cont_block_id=[a-z]+_|item_row_|lg_div_)"
    rb"\d+(?:[-_]\d+)*"
)

# Media links contain a token that differs between instances
DELIVER_TOKEN = re.compile(rb"deliver\.php/[A-Za-z0-9_-]+/")


def downloaded_files(output: Path) -> list[Path]:
    return [
        path
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.relative_to(output).as_posix() not in PFERD_FILES
    ]


def manifest(output: Path, base_url: str) -> dict[str, str]:
    """
    Maps the path of every downloaded file to a hash of its content. Generated files (links, forum
    threads, ...) contain URLs of the instance, so its base URL (the port is random) and object ids are
    replaced.
    """
    result = {}
    for path in downloaded_files(output):
        content = path.read_bytes().replace(base_url.encode(), b"{ILIAS}")
        content = OBJECT_ID.sub(rb"\1{ID}", content)
        content = DELIVER_TOKEN.sub(b"deliver.php/{TOKEN}/", content)
        result[path.relative_to(output).as_posix()] = hashlib.sha256(content).hexdigest()[:16]
    return result
