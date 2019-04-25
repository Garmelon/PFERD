import os
import pathlib

__all__ = [
    "get_base_dir",
    "move",
    "rename",
    "stream_to_path",
    "ContentTypeException",
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

def stream_to_path(response, to_path, chunk_size=1024**2):
    with open(to_path, 'wb') as fd:
        for chunk in response.iter_content(chunk_size=chunk_size):
            fd.write(chunk)

class ContentTypeException(Exception):
    pass

class FileNotFoundException(Exception):
    pass
