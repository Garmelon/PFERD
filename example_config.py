#!/bin/env python3

import re
import sys

import PFERD
from PFERD.utils import get_base_dir, move, rename

#PFERD.enable_logging(logging.DEBUG)
PFERD.enable_logging()

base_dir = get_base_dir(__file__)

# Semester 1

def gbi_filter(path):
    # Tutorien rausfiltern
    if path.parts[:1] == ("Tutoriumsfolien",):
        if path.parts[1:] == (): return True
        if path.parts[1:2] == ("Tutorium 15",): return True
        return False

    return True

def gbi_transform(path):
    # Übungsblätter in Blätter/blatt_xx.pdf
    new_path = move(path, ("Übungsblätter",), ("Blätter",))
    if new_path is not None:

        match = re.match(r"(\d+).aufgaben.pdf", new_path.name)
        if match:
            number = int(match.group(1))
            return rename(new_path, f"blatt_{number:02}.pdf")

        match = re.match(r"(\d+).loesungen.pdf", new_path.name)
        if match:
            number = int(match.group(1))
            return rename(new_path, f"loesung_{number:02}.pdf")

        return new_path

    # Folien in Folien/*
    new_path = move(path, ("Vorlesung: Folien",), ("Folien",))
    if new_path is not None: return new_path

    # Skripte in Skripte/*
    new_path = move(path, ("Vorlesung: Skript",), ("Skripte",))
    if new_path is not None:
        if new_path.name == "k-21-relationen-skript.pdf":
            return rename(new_path, "21-relationen-skript.pdf")

        return new_path

    # Übungsfolien in Übung/*
    new_path = move(path, ("große Übung: Folien",), ("Übung",))
    if new_path is not None: return new_path

    # Tutoriumsfolien in Tutorium/*
    new_path = move(path, ("Tutoriumsfolien","Tutorium 15"), ("Tutorium",))
    if new_path is not None:
        if new_path.name == "GBI_Tut_2 (1).pdf":
            return rename(new_path, "GBI_Tut_2.pdf")
        if new_path.name == "GBI_Tut_7 (1).pdf":
            return rename(new_path, "GBI_Tut_7.pdf")

        return new_path

    return path

def hm1_transform(path):
    match = re.match(r"blatt(\d+).pdf", path.name)
    if match:
        new_path = move(path, (), ("Blätter",))
        number = int(match.group(1))
        return rename(new_path, f"blatt_{number:02}.pdf")

    match = re.match(r"blatt(\d+).loesungen.pdf", path.name)
    if match:
        new_path = move(path, (), ("Blätter",))
        number = int(match.group(1))
        return rename(new_path, f"loesung_{number:02}.pdf")

    return path

def la1_filter(path):
    # Tutorien rausfitern
    if path.parts[:1] == ("Tutorien",):
        if path.parts[1:] == (): return True
        if path.parts[1:2] == ("Tutorium 03 - Philipp Faller",): return True
        if path.parts[1:2] == ("Tutorium 23 - Sebastian Faller",): return True
        return False

    return True

def la1_transform(path):
    # Alle Übungsblätter in Blätter/blatt_xx.pdf
    # Alles andere Übungsmaterial in Blätter/*
    new_path = move(path, ("Übungen",), ("Blätter",))
    if new_path is not None:

        match = re.match(r"Blatt(\d+).pdf", new_path.name)
        if match:
            number = int(match.group(1))
            return rename(new_path, f"blatt_{number:02}.pdf")

        if new_path.name == "Lösungen zu Blatt 1, Aufgabe 1 und Blatt 2, Aufgabe 4..pdf":
            return rename(new_path, "Lösungen zu Blatt 1, Aufgabe 1 und Blatt 2, Aufgabe 4.pdf")

        return new_path

    # Alles Tutoriengedöns von Philipp in Tutorium/Philipp/*
    new_path = move(path, ("Tutorien","Tutorium 03 - Philipp Faller"), ("Tutorium","Philipp"))
    if new_path is not None:
        if new_path.name == "tut2.pdf":
            return rename(new_path, "Tut2.pdf")

        return new_path

    # Alles Tutoriengedöns von Sebastian in Tutorium/Sebastian/*
    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 1"), ("Tutorium","Sebastian", "tut01"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 2", "aufgaben.pdf"), ("Tutorium","Sebastian", "tut02.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 3", "aufgaben.pdf"), ("Tutorium","Sebastian", "tut03.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 4", "aufgaben.pdf"), ("Tutorium","Sebastian", "tut04.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 5", "aufgaben.pdf"), ("Tutorium","Sebastian", "tut05.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 6", "aufgaben.pdf"), ("Tutorium","Sebastian", "tut06.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 7", "tut7.pdf"), ("Tutorium","Sebastian", "tut07.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 8", "tut8.pdf"), ("Tutorium","Sebastian", "tut08.pdf"))
    if new_path is not None: return new_path

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 9", "tut9.pdf"), ("Tutorium","Sebastian", "tut09.pdf"))
    if new_path is not None: return new_path

    if path.parts == ("Tutorien","Tutorium 23 - Sebastian Faller", "Tutorium 10", "tut10.pdf"): return None

    new_path = move(path, ("Tutorien","Tutorium 23 - Sebastian Faller"), ("Tutorium","Sebastian"))
    if new_path is not None:
        return new_path

    # Übungs-Gedöns in Übung/*
    new_path = move(path, ("Informatikervorlesung", "Übungsfolien"), ("Übung",))
    if new_path is not None:
        if new_path.name == "Übung_06_ausgewählte Folien.pdf":
            return rename(new_path, "Übung_06_ausgewählte_Folien.pdf")

        return new_path

    # Vorlesungsfolien-Gedöns in Folien/*
    new_path = move(path, ("Informatikervorlesung", "Folien.Notizen"), ("Folien",))
    if new_path is not None:
        return new_path

    # Rest in Hauptverzeichnis
    new_path = move(path, ("Informatikervorlesung",), ())
    if new_path is not None:
        # Rename filenames that are invalid on FAT systems
        if new_path.name == "Evaluationsergebnisse: Übung.pdf":
            return rename(new_path, "Evaluationsergebnisse_Übung.pdf")
        if new_path.name == "Skript \"Lineare Algebra\" von Stefan Kühnlein.pdf":
            return rename(new_path, "Skript Lineare Algebra von Stefan kühnlein.pdf")

        return new_path

    return path

def prog_filter(path):
    # Tutorien rausfiltern
    if path.parts[:1] == ("Tutorien",): return False

    return True

def prog_transform(path):
    # Übungsblätter in Blätter/*
    new_path = move(path, ("Übungen",), ("Blätter",))
    if new_path is not None:
        if new_path.name == "assignmen04.pdf":
            return rename(new_path, "assignment04.pdf")

        return new_path

    # Folien in Folien/*
    new_path = move(path, ("Vorlesungsmaterial",), ("Folien",))
    if new_path is not None:
        if new_path.name == "00.1_Begruessung.pdf":
            return rename(new_path, "00-01_Begruessung.pdf")
        if new_path.name == "00.2_Organisatorisches.pdf":
            return rename(new_path, "00-02_Organisatorisches.pdf")
        if new_path.name == "01-01_ Einfache-Programme.pdf":
            return rename(new_path, "01-01_Einfache_Programme.pdf")
        if new_path.name == "13_Finden_und_ Beheben_von_Fehlern.pdf":
            return rename(new_path, "13_Finden_und_Beheben_von_Fehlern.pdf")

        return new_path

    return path

# Semester 2

def algo1_filter(path):
    # Tutorien rausfiltern
    if path.parts[:1] == ("Tutorien",):
        if path.parts[1:] == (): return True
        #if path.parts[1:2] == ("Tutorium 15",): return True
        return False

    return True

def algo1_transform(path):
    # Folien in Folien/*
    new_path = move(path, ("Vorlesungsfolien",), ("Folien",))
    if new_path is not None:
        return new_path

    return path

def hm2_transform(path):
    match = re.match(r"blatt(\d+).pdf", path.name)
    if match:
        new_path = move(path, (), ("Blätter",))
        number = int(match.group(1))
        return rename(new_path, f"blatt_{number:02}.pdf")

    match = re.match(r"blatt(\d+).loesungen.pdf", path.name)
    if match:
        new_path = move(path, (), ("Blätter",))
        number = int(match.group(1))
        return rename(new_path, f"loesung_{number:02}.pdf")

    return path

def la2_filter(path):
    # Tutorien rausfiltern
    if path.parts[:1] == ("Tutorien",):
        if path.parts[1:] == (): return True
        #if path.parts[1:2] == ("Tutorium 15",): return True
        return False

    return True

def la2_transform(path):
    # Folien in Folien/*
    new_path = move(path, ("Vorlesungsmaterial",), ("Folien",))
    if new_path is not None: return new_path

    # Alle Übungsblätter in Blätter/blatt_xx.pdf
    # Alles andere Übungsmaterial in Blätter/*
    new_path = move(path, ("Übungen",), ("Blätter",))
    if new_path is not None:

        match = re.match(r"Blatt(\d+).pdf", new_path.name)
        if match:
            number = int(match.group(1))
            return rename(new_path, f"blatt_{number:02}.pdf")

        return new_path

    return path

def swt1_filter(path):
    # Tutorien rausfiltern
    if path.parts[:1] == ("Tutorien",):
        if path.parts[1:] == (): return True
        #if path.parts[1:2] == ("Tutorium 15",): return True
        return False

    return True

def swt1_transform(path):
    # Folien in Folien/*
    new_path = move(path, ("Vorlesungsmaterial",), ("Folien",))
    if new_path is not None: return new_path

    # Übungsblätter in Blätter/*
    new_path = move(path, ("Übungen",), ("Blätter",))
    if new_path is not None: return new_path

    return path

# Main part of the config

def main(args):
    args = [arg.lower() for arg in args]

    ffm = PFERD.FfM(base_dir)
    ilias = PFERD.ILIAS(base_dir, "cookie_jar")
    norbert = PFERD.Norbert(base_dir)

    # Semester 1

    if not args or "gbi" in args:
        ilias.synchronize("855240", "GBI",
                transform=gbi_transform, filter=gbi_filter)

    if not args or "hm1" in args:
        ffm.synchronize("iana2/lehre/hm1info2018w", "HM1",
                transform=hm1_transform)

    if not args or "la1" in args:
        ilias.synchronize("874938", "LA1",
                transform=la1_transform, filter=la1_filter)

    if not args or "prog" in args:
        ilias.synchronize("851237", "Prog",
                transform=prog_transform, filter=prog_filter)

    if not args or "norbert" in args:
        norbert.synchronize("Prog-Tut")

    # Semester 2

    if not args or "algo1" in args:
        ilias.synchronize("959260", "Algo1",
                transform=algo1_transform, filter=algo1_filter)

    if not args or "hm2" in args:
        ffm.synchronize("iana2/lehre/hm2info2019s", "HM2",
                transform=hm2_transform)

    if not args or "la2" in args:
        ilias.synchronize("950588", "LA2",
                transform=la2_transform, filter=la2_filter)

    if not args or "swt1" in args:
        ilias.synchronize("945596", "SWT1",
                transform=swt1_transform, filter=swt1_filter)

if __name__ == "__main__":
    args = sys.argv[1:]
    main(args)
