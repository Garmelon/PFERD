import os
import pathlib

__all__ = [
    "get_base_dir",
    "move",
    "rename",
    "stream_to_path",
    "OutOfTriesException",
    "UnknownFileTypeException",
    "FileNotFoundException",
]

def get_base_dir(script_file):
    return pathlib.Path(os.path.dirname(os.path.abspath(script_file)))

def move(path, from_folders, to_folders):
    l = len(from_folders)
    if path.parts[:l] == from_folders:
        return pathlib.PurePath(*to_folders, *path.parts[l:])

def rename(path, to_name):
    return pathlib.PurePath(*path.parts[:-1], to_name)

async def stream_to_path(resp, to_path, chunk_size=1024**2):
    with open(to_path, 'wb') as fd:
        while True:
            chunk = await resp.content.read(chunk_size)
            if not chunk:
                break
            fd.write(chunk)

class OutOfTriesException(Exception):
    pass

class UnknownFileTypeException(Exception):
    pass

class FileNotFoundException(Exception):
    pass
