import argparse
from pathlib import Path, PurePath

from PFERD import Pferd
from PFERD.ilias import IliasElementType
from PFERD.transform import (attempt, do, glob, keep, move, move_dir,
                             optionally, re_move, re_rename)

tf_ss_2020_numerik = attempt(
    re_move(r"Übungsblätter/(\d+)\. Übungsblatt/.*", "Blätter/Blatt_{1:0>2}.pdf"),
    keep,
)


tf_ss_2020_db = attempt(
    move_dir("Begrüßungsvideo/", "Vorlesung/Videos/"),
    do(
        move_dir("Vorlesungsmaterial/Vorlesungsvideos/", "Vorlesung/Videos/"),
        optionally(re_rename("(.*).m4v.mp4", "{1}.mp4")),
        optionally(re_rename("(?i)dbs-(.+)", "{1}")),
    ),
    move_dir("Vorlesungsmaterial/", "Vorlesung/"),
    keep,
)


tf_ss_2020_rechnernetze = attempt(
    re_move(r"Vorlesungsmaterial/.*/(.+?)\.mp4", "Vorlesung/Videos/{1}.mp4"),
    move_dir("Vorlesungsmaterial/", "Vorlesung/"),
    keep,
)


tf_ss_2020_sicherheit = attempt(
    move_dir("Vorlesungsvideos/", "Vorlesung/Videos/"),
    move_dir("Übungsvideos/", "Übung/Videos/"),
    re_move(r"VL(.*)\.pdf", "Vorlesung/{1}.pdf"),
    re_move(r"Übungsblatt (\d+)\.pdf", "Blätter/Blatt_{1:0>2}.pdf"),
    move("Chiffrat.txt", "Blätter/Blatt_01_Chiffrat.txt"),
    keep,
)


tf_ss_2020_pg = attempt(
    move_dir("Vorlesungsaufzeichnungen/", "Vorlesung/Videos/"),
    move_dir("Vorlesungsmaterial/", "Vorlesung/"),
    re_move(r"Übungen/uebungsblatt(\d+).pdf", "Blätter/Blatt_{1:0>2}.pdf"),
    keep,
)


def df_ss_2020_or1(path: PurePath, _type: IliasElementType) -> bool:
    if glob("Tutorien/")(path):
        return True
    if glob("Tutorien/Tutorium 10, dienstags 15:45 Uhr/")(path):
        return True
    if glob("Tutorien/*")(path):
        return False
    return True


tf_ss_2020_or1 = attempt(
    move_dir("Vorlesung/Unbeschriebene Folien/", "Vorlesung/Folien/"),
    move_dir("Video zur Organisation/", "Vorlesung/Videos/"),
    keep,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    parser.add_argument("synchronizers", nargs="*")
    args = parser.parse_args()

    pferd = Pferd(Path(__file__).parent, test_run=args.test_run)
    pferd.enable_logging()

    ilias = pferd.ilias_kit(
                cookies="PFERD/ilias_cookies.txt",
            )

    if not args.synchronizers or "numerik" in args.synchronizers:
        pferd.add_ilias_course(
            ilias,
            target="Numerik",
            course_id="1083036",
            transform=tf_ss_2020_numerik,
            cookies="ilias_cookies.txt",
        )

    if not args.synchronizers or "db" in args.synchronizers:
        pferd.add_ilias_course(
            ilias,
            target="DB",
            course_id="1101554",
            transform=tf_ss_2020_db,
            cookies="ilias_cookies.txt",
        )

    if not args.synchronizers or "rechnernetze" in args.synchronizers:
        pferd.add_ilias_course(
            ilias,
            target="Rechnernetze",
            course_id="1099996",
            transform=tf_ss_2020_rechnernetze,
            cookies="ilias_cookies.txt",
        )

    if not args.synchronizers or "sicherheit" in args.synchronizers:
        pferd.add_ilias_course(
            ilias,
            target="Sicherheit",
            course_id="1101980",
            transform=tf_ss_2020_sicherheit,
            cookies="ilias_cookies.txt",
        )

    if not args.synchronizers or "pg" in args.synchronizers:
        pferd.add_ilias_course(
            ilias,
            target="PG",
            course_id="1106095",
            transform=tf_ss_2020_pg,
            cookies="ilias_cookies.txt",
        )

    if not args.synchronizers or "or1" in args.synchronizers:
        pferd.add_ilias_course(
            ilias,
            target="OR1",
            course_id="1105941",
            dir_filter=df_ss_2020_or1,
            transform=tf_ss_2020_or1,
            cookies="ilias_cookies.txt",
        )

    pferd.syncronize_ilias(ilias)
    # Prints a summary listing all new, modified or deleted files
    pferd.print_summary()

if __name__ == "__main__":
    main()
