import PFERD
import asyncio
import logging
import pathlib

logging.basicConfig(level=logging.DEBUG, format=PFERD.LOG_FORMAT)

base_dir = PFERD.get_base_dir(__file__)

def hm1(old_path):
	if old_path.match("blatt*.pdf"):
		return pathlib.PurePath("Blätter", old_path.name)

	return old_path

def ana1(old_path):
	if old_path.match("*zettel*.pdf"):
		return pathlib.PurePath("Blätter", old_path.name)

	return old_path

def la1_filter(path):
	if path.match("Tutorien/*"):
		return False

	return True

async def main():
	#ffm = PFERD.FfM(base_dir)
	#await ffm.synchronize("iana2/lehre/hm1info2018w", "HM1", transform=hm1)
	#await ffm.synchronize("iana1/lehre/ana12018w", "Ana1", transform=ana1)
	#await ffm.close()

	ilias = PFERD.ILIAS(base_dir, "cookie_jar")
	await ilias.synchronize("874938", "LA1", filter=la1_filter)
	await ilias.close()

if __name__ == "__main__":
	asyncio.run(main())
