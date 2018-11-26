import os
import pathlib

__all__ = [
	"get_base_dir",
	"stream_to_path",
	"OutOfTriesException",
	"UnknownFileTypeException",
	"FileNotFoundException",
]

def get_base_dir(script_file):
	return pathlib.Path(os.path.dirname(os.path.abspath(script_file)))

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
