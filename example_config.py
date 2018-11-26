import PFERD
import asyncio
import logging
import pathlib
import re
import sys

logging.basicConfig(level=logging.INFO, format=PFERD.LOG_FORMAT)

base_dir = PFERD.get_base_dir(__file__)

def gbi_filter(path):
	# Tutorien rausfiltern
	if path.match("Tutoriumsfolien/Tutorium 15"): return True
	if path.match("Tutoriumsfolien/Tutorium 15/*"): return True
	if path.match("Tutoriumsfolien/*"): return False

	return True

def gbi_transform(path):
	# Übungsblätter in Blätter/blatt_xx.pdf
	if path.match("Übungsblätter/*"):
		new_folder = pathlib.PurePath("Blätter")

		match = re.match(r"(\d+).aufgaben.pdf", path.name)
		if match:
			number = int(match.group(1))
			name = f"blatt_{number:02}.pdf"
			return new_folder / name

		match = re.match(r"(\d+).loesungen.pdf", path.name)
		if match:
			number = int(match.group(1))
			name = f"loesung_{number:02}.pdf"
			return new_folder / name

		return pathlib.Path(new_folder, *path.parts[1:])

	# Folien in Folien/*
	if path.match("Vorlesung: Folien/*"):
		return pathlib.Path("Folien", *path.parts[1:])

	# Skripte in Skripte/*
	if path.match("Vorlesung: Skript/*"):
		return pathlib.Path("Skripte", *path.parts[1:])

	# Übungsfolien in Übung/*
	if path.match("große Übung: Folien/*"):
		return pathlib.Path("Übung", *path.parts[1:])

	# Tutoriumsfolien in Tutorium/*
	if path.match("Tutoriumsfolien/Tutorium 15/GBI_Tut_2 (1).pdf"):
		return pathlib.Path("Tutorium", "GBI_Tut_2.pdf")
	if path.match("Tutoriumsfolien/Tutorium 15/*"):
		return pathlib.Path("Tutorium", *path.parts[2:])

	return path

def hm1_transform(path):
	if path.match("blatt*.pdf"):
		new_folder = pathlib.PurePath("Blätter")

		match = re.match(r"blatt(\d+).pdf", path.name)
		if match:
			number = int(match.group(1))
			name = f"blatt_{number:02}.pdf"
			return new_folder / name

		match = re.match(r"blatt(\d+).loesungen.pdf", path.name)
		if match:
			number = int(match.group(1))
			name = f"loesung_{number:02}.pdf"
			return new_folder / name

		return pathlib.PurePath(new_folder, *path.parts[1:])

	return path

def la1_filter(path):
	# Tutorien rausfitern
	if path.match("Tutorien/Tutorium 03 - Philipp Faller"): return True
	if path.match("Tutorien/Tutorium 03 - Philipp Faller/*"): return True
	if path.match("Tutorien/*"): return False

	return True

def la1_transform(path):
	# Alle Übungsblätter in Blätter/blatt_xx.pdf
	# Alles andere Übungsmaterial in Blätter/*
	if path.match("Übungen/*"):
		new_folder = pathlib.PurePath("Blätter")

		match = re.match(r"Blatt(\d+).pdf", path.name)
		if match:
			number = int(match.group(1))
			name = f"blatt_{number:02}.pdf"
			return new_folder / name

		return pathlib.PurePath(new_folder, *path.parts[1:])

	# Alles Tutoriengedöns in Tutorium/*
	if path.match("Tutorien/Tutorium 03 - Philipp Faller/tut2.pdf"):
		return pathlib.PurePath("Tutorium", "Tut2.pdf")
	if path.match("Tutorien/Tutorium 03 - Philipp Faller/*"):
		return pathlib.PurePath("Tutorium", *path.parts[2:])

	# Übungs-Gedöns in Übung/*
	if path.match("Informatikervorlesung/Übung_*"):
		return pathlib.PurePath("Übung", *path.parts[1:])

	# Vorlesungsfolien-Gedöns in Folien/*
	if path.match("Informatikervorlesung/*"):
		return pathlib.PurePath("Folien", *path.parts[1:])

	return path

def prog_filter(path):
	# Tutorien rausfiltern
	if path.match("Tutorien"): return False

	return True

def prog_transform(path):
	# Übungsblätter in Blätter/*
	if path.match("Übungen/*"):
		return pathlib.PurePath("Blätter", *path.parts[1:])

	# Folien in Folien/*
	if path.match("Vorlesungsmaterial/*"):
		return pathlib.PurePath("Folien", *path.parts[1:])

	return path

async def main(args):
	args = [arg.lower() for arg in args]

	ffm = PFERD.FfM(base_dir)
	ilias = PFERD.ILIAS(base_dir, "cookie_jar")

	if not args or "gbi" in args:
		await ilias.synchronize("855240", "GBI", transform=gbi_transform, filter=gbi_filter)
	if not args or "hm1" in args:
		await ffm.synchronize("iana2/lehre/hm1info2018w", "HM1", transform=hm1_transform)
	if not args or "la1" in args:
		await ilias.synchronize("874938", "LA1", transform=la1_transform, filter=la1_filter)
	if not args or "prog" in args:
		await ilias.synchronize("851237", "Prog", transform=prog_transform, filter=prog_filter)

	await ffm.close()
	await ilias.close()

if __name__ == "__main__":
	args = sys.argv[1:]
	asyncio.run(main(args))
