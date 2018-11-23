import PFERD
import asyncio
import logging
import pathlib
import os
import sys

logging.basicConfig(level=logging.DEBUG, format=PFERD.LOG_FORMAT)
#logging.basicConfig(level=logging.INFO, format=PFERD.LOG_FORMAT)

async def test_download():
	base_path = pathlib.Path(".")
	sync_path = pathlib.Path(base_path, "synctest")

	orga = PFERD.Organizer(base_path, sync_path)
	auth = PFERD.ShibbolethAuthenticator(cookie_path="cookie_jar")
	#soup = await auth.get_webpage("885157")

	orga.clean_temp_dir()

	filename = orga.temp_file()
	await auth.download_file("file_886544_download", filename)
	orga.add_file(filename, pathlib.Path("test.pdf"))

	filename = orga.temp_file()
	await auth.download_file("file_886544_download", filename)
	orga.add_file(filename, pathlib.Path("bla/test2.pdf"))
	
	orga.clean_sync_dir()
	orga.clean_temp_dir()
	await auth.close()

def main():
	#print(f"  os.getcwd(): {os.getcwd()}")
	#print(f"  sys.argv[0]: {sys.argv[0]}")
	#print(f"         both: {os.path.dirname(os.getcwd() + '/' + sys.argv[0])}")
	#print(f"     __file__: {__file__}")
	#print(f"stackoverflow: {os.path.dirname(os.path.abspath(__file__))}")

	#asyncio.run(test_download(), debug=True)
	asyncio.run(test_download())

if __name__ == "__main__":
	main()
