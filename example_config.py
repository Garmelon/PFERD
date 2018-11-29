#!/bin/env python3

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
	if path.parts[:1] == ("Tutoriumsfolien",):
		if path.parts[1:] == (): return True
		if path.parts[1:2] == ("Tutorium 15",): return True
		return False

	return True

def gbi_transform(path):
	# Übungsblätter in Blätter/blatt_xx.pdf
	new_path = PFERD.move(path, ("Übungsblätter",), ("Blätter",))
	if new_path is not None:

		match = re.match(r"(\d+).aufgaben.pdf", new_path.name)
		if match:
			number = int(match.group(1))
			return PFERD.rename(new_path, f"blatt_{number:02}.pdf")

		match = re.match(r"(\d+).loesungen.pdf", new_path.name)
		if match:
			number = int(match.group(1))
			return PFERD.rename(new_path, f"loesung_{number:02}.pdf")

		return new_path

	# Folien in Folien/*
	new_path = PFERD.move(path, ("Vorlesung: Folien",), ("Folien",))
	if new_path is not None: return new_path

	# Skripte in Skripte/*
	new_path = PFERD.move(path, ("Vorlesung: Skript",), ("Skripte",))
	if new_path is not None: return new_path

	# Übungsfolien in Übung/*
	new_path = PFERD.move(path, ("große Übung: Folien",), ("Übung",))
	if new_path is not None: return new_path

	# Tutoriumsfolien in Tutorium/*
	new_path = PFERD.move(path, ("Tutoriumsfolien","Tutorium 15"), ("Tutorium",))
	if new_path is not None:
		if new_path.name == "GBI_Tut_2 (1).pdf":
			return PFERD.rename(new_path, "GBI_Tut_2.pdf")

		return new_path

	return path

def hm1_transform(path):
	if path.match("blatt*.pdf"):
		new_path = PFERD.move(path, (), ("Blätter",))

		match = re.match(r"blatt(\d+).pdf", new_path.name)
		if match:
			number = int(match.group(1))
			return PFERD.rename(new_path, f"blatt_{number:02}.pdf")

		match = re.match(r"blatt(\d+).loesungen.pdf", new_path.name)
		if match:
			number = int(match.group(1))
			return PFERD.rename(new_path, f"loesung_{number:02}.pdf")

		return new_path

	return path

def la1_filter(path):
	# Tutorien rausfitern
	if path.parts[:1] == ("Tutorien",):
		if path.parts[1:] == (): return True
		if path.parts[1:2] == ("Tutorium 03 - Philipp Faller",): return True
		return False

	return True

def la1_transform(path):
	# Alle Übungsblätter in Blätter/blatt_xx.pdf
	# Alles andere Übungsmaterial in Blätter/*
	new_path = PFERD.move(path, ("Übungen",), ("Blätter",))
	if new_path is not None:

		match = re.match(r"Blatt(\d+).pdf", new_path.name)
		if match:
			number = int(match.group(1))
			return PFERD.rename(new_path, f"blatt_{number:02}.pdf")

		return new_path

	# Alles Tutoriengedöns in Tutorium/*
	new_path = PFERD.move(path, ("Tutorien","Tutorium 03 - Philipp Faller"), ("Tutorium",))
	if new_path is not None:
		if new_path.name == "tut2.pdf":
			return PFERD.rename(new_path, "Tut2.pdf")

		return new_path

	# Übungs-Gedöns in Übung/*
	if path.match("Informatikervorlesung/Übung_*"):
		return pathlib.PurePath("Übung", *path.parts[1:])

	# Vorlesungsfolien-Gedöns in Folien/*
	new_path = PFERD.move(path, ("Informatikervorlesung",), ("Folien",))
	if new_path is not None: return new_path

	return path

def prog_filter(path):
	# Tutorien rausfiltern
	if path.parts[:1] == ("Tutorien",): return False

	return True

def prog_transform(path):
	# Übungsblätter in Blätter/*
	new_path = PFERD.move(path, ("Übungen",), ("Blätter",))
	if new_path is not None: return new_path

	# Folien in Folien/*
	new_path = PFERD.move(path, ("Vorlesungsmaterial",), ("Folien",))
	if new_path is not None:
		if new_path.name == "00.1_Begruessung.pdf":
			return PFERD.rename(new_path, "00-01_Begruessung.pdf")
		if new_path.name == "00.2_Organisatorisches.pdf":
			return PFERD.rename(new_path, "00-02_Organisatorisches.pdf")
		if new_path.name == "01-01_ Einfache-Programme.pdf":
			return PFERD.rename(new_path, "01-01_Einfache_Programme.pdf")

		return new_path

	return path

async def main(args):
	args = [arg.lower() for arg in args]

	ffm = PFERD.FfM(base_dir)
	ilias = PFERD.ILIAS(base_dir, "cookie_jar")
	norbert = PFERD.Norbert(base_dir)

	if not args or "gbi" in args:
		await ilias.synchronize("855240", "GBI", transform=gbi_transform, filter=gbi_filter)
	if not args or "hm1" in args:
		await ffm.synchronize("iana2/lehre/hm1info2018w", "HM1", transform=hm1_transform)
	if not args or "la1" in args:
		await ilias.synchronize("874938", "LA1", transform=la1_transform, filter=la1_filter)
	if not args or "prog" in args:
		await ilias.synchronize("851237", "Prog", transform=prog_transform, filter=prog_filter)
	if not args or "norbert" in args:
		await norbert.synchronize("Prog-Tut")

	await ffm.close()
	await ilias.close()
	await norbert.close()

if __name__ == "__main__":
	args = sys.argv[1:]
	asyncio.run(main(args))
