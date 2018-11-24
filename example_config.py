import PFERD
import asyncio
import logging
import pathlib

logging.basicConfig(level=logging.INFO, format=PFERD.LOG_FORMAT)

base_dir = PFERD.get_base_dir(__file__)

def hm1(old_path):
	if old_path.match("blatt*.pdf"):
		return pathlib.PurePath("Blätter", old_path.name)

	return old_path

def ana1(old_path):
	if old_path.match("*zettel*.pdf"):
		return pathlib.PurePath("Blätter", old_path.name)

	return old_path

async def main():
	ffm = PFERD.FfM(base_dir)
	await ffm.synchronize("iana2/lehre/hm1info2018w/de", "HM1", transform=hm1)
	await ffm.synchronize("iana1/lehre/ana12018w/de", "Ana1", transform=ana1)
	await ffm.close()

if __name__ == "__main__":
	asyncio.run(main())
