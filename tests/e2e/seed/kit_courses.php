<?php

/**
 * Courses modelled after real KIT courses: course pages consisting of headings, text and accordions,
 * which contain item groups with files, folders and links. Course names, tutorial details and dates
 * are fictional. Included by seed.php.
 */

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

/**
 * The dates of some slides of the KIT lecture, by their path in the download, in German month
 * abbreviations as KIT shows them ("9. Dez 2024, 14:00").
 */
const KIT_LECTURE_FILE_DATES = [
    'Vorlesungsmaterial/Folien/0-Organization.pdf' => '2024-10-14 10:00:00',
    'Vorlesungsmaterial/Folien/2_Process.pdf' => '2024-05-06 08:00:00',
    'Vorlesungsmaterial/Folien/_10-CPU-Caches.pdf' => '2024-12-09 13:00:00',
];

/**
 * Modelled after a large lecture: material in item groups inside accordions, weekly sheet folders and
 * tutorial groups, of which the students are members of only one.
 *
 * @return array{int, array<string, int>} The course and the dates of KIT_LECTURE_FILE_DATES as timestamps
 */
function create_kit_lecture(array $students): array
{
    $crs = create_course('Beispielvorlesung WS 24/25', $students);

    $forum = create_object('frm', 'Forum', $crs)->getRefId();
    $news = create_object('frm', 'Neuigkeiten', $crs)->getRefId();
    $forums = create_item_group('Foren', $crs, [$forum, $news]);

    // Slides, some with several versions, and a link at the end
    $slides = [];
    foreach (['0-Organization' => 11, '1-Introduction' => 13, '2_Process' => 48, '_10-CPU-Caches' => 29] as $title => $pages) {
        $slides[$title] = create_file("$title.pdf", $crs, $title, pdf($title, $pages));
    }
    add_file_version($slides['0-Organization'], pdf('0-Organization v2', 11));
    add_file_version($slides['1-Introduction'], pdf('1-Introduction v2', 13));
    $file_dates = [];
    foreach (KIT_LECTURE_FILE_DATES as $path => $date_utc) {
        $file_dates[$path] = strtotime("$date_utc UTC");
        set_file_date($slides[pathinfo($path, PATHINFO_FILENAME)], $file_dates[$path]);
    }
    $slides[] = create_link('_21_Tutorial on the Extended Berkeley Packet Filter (eBPF)', $crs, 'https://ebpf.io', '');
    $slides_group = create_item_group('Folien', $crs, array_values($slides));

    $old_slides = create_folder('Folien WS 20/21', $crs);
    create_file('0-Organization.pdf', $old_slides, '0-Organization', pdf('0-Organization WS 20/21', 9));
    create_file('2_c_intro_I.pdf', $old_slides, '2_c_intro_I', pdf('2_c_intro_I', 30));
    $related = create_folder('Related Work', $crs);
    create_file('fork.pdf', $related, 'HOTOS19 A fork() in the road', pdf('fork', 6));
    create_file('scheduler.pdf', $related, 'EuroSys16 The Linux Scheduler: a Decade of Wasted Cores', pdf('scheduler', 12));
    $book = create_link('Operating Systems: Three Easy Pieces', $crs, 'https://pages.cs.wisc.edu/~remzi/OSTEP/', '');
    $material_group = create_item_group('Videos und Materialien', $crs, [$old_slides, $book, $related]);

    // Weekly folders with the week in their name, containing PDFs and archives
    $tutorial_sheets = [];
    $exercise_sheets = [];
    foreach ([[0, '14.10.2024 - 18.10.2024', '21.10.2024 - 28.10.2024'], [1, '21.10.2024 - 25.10.2024', '28.10.2024 - 04.11.2024']] as [$week, $tutorial_dates, $exercise_dates]) {
        $nr = sprintf('%02d', $week);
        $folder = create_folder("Tutoriumsblatt $nr ($tutorial_dates)", $crs);
        create_file("tutorial-$nr-question.pdf", $folder, "tutorial-$nr-question", pdf("tutorial $nr question"));
        create_file("tutorial-$nr-solution.pdf", $folder, "tutorial-$nr-solution", pdf("tutorial $nr solution", 5));
        // ILIAS takes everything after the last dot as the file type, so the title keeps ".tar"
        create_file("tut$nr-templates.tar.gz", $folder, "tut$nr-templates.tar", "tut$nr templates\n");
        $tutorial_sheets[] = $folder;

        $nr = sprintf('%02d', $week + 1);
        $folder = create_folder("Übungsblatt $nr ($exercise_dates)", $crs);
        create_file("assignment-$nr-question.pdf", $folder, "assignment-$nr-question", pdf("assignment $nr question", 4));
        create_file("asst$nr-templates.tar.gz", $folder, "asst$nr-templates.tar", "asst$nr templates\n");
        $exercise_sheets[] = $folder;
    }
    $tutorials_group = create_item_group('Tutoriumsblätter', $crs, $tutorial_sheets);
    $exercises_group = create_item_group('Übungsblätter', $crs, $exercise_sheets);

    // Only the own tutorial group can be opened
    $own_tutorial = create_group('Tutorium 01 Mittwoch Block 2 (20.22 Raum 123)', $crs, $students);
    $tutorial_slides = create_folder('Folien', $own_tutorial);
    create_file('Tut-01.pdf', $tutorial_slides, 'Tut-01', pdf('Tut-01', 59));
    // The same title twice, as tutors upload a file again instead of a new version
    create_file('Tut-03-Handout.pdf', $tutorial_slides, 'Tut-03-Handout', pdf('Tut-03-Handout', 19));
    create_file('Tut-03-Handout.pdf', $tutorial_slides, 'Tut-03-Handout', pdf('Tut-03-Handout again', 19));
    create_unsupported_object('tst', 'Übungsblatt 01', $own_tutorial);
    $other_tutorial = create_group('Tutorium 02 Donnerstag Block 1 (20.22 Raum 124)', $crs, []);
    create_file('secret.pdf', $other_tutorial, 'secret', pdf('secret'));
    make_visible_only($other_tutorial);
    $groups_group = create_item_group('Gruppen', $crs, [$own_tutorial, $other_tutorial]);

    set_container_page(
        $crs,
        heading('Überblick')
        . paragraph_with_link('Die Vorlesung orientiert sich an dem Lehrbuch', 'https://pages.cs.wisc.edu/~remzi/OSTEP/')
        . item_group_block($forums)
        . heading('Hinweise zur Vorlesung')
        . accordion(['Vorlesungsmaterial' => item_group_block($slides_group) . item_group_block($material_group)])
        . heading('Hinweise zur Übung')
        . accordion(['Übungsmaterial' => item_group_block($tutorials_group) . item_group_block($exercises_group)])
        . heading('Hinweise zu den Tutorien')
        . item_group_block($groups_group)
    );

    return [$crs, $file_dates];
}

/**
 * Modelled after a smaller lecture: a plain course page, and a folder with lectures and folders with
 * additional material mixed.
 */
function create_kit_seminar(array $students): int
{
    $crs = create_course('Beispielseminar II - Anwendung', $students);
    create_unsupported_object('blog', 'Hinweise zur Vorlesung', $crs);
    create_link('Website zur Vorlesung', $crs, 'https://formal.kit.edu', '');

    $material = create_folder('Vorlesungsmaterialien', $crs);
    create_file('00aOrganisatorisches.pdf', $material, '00aOrganisatorisches', pdf('organisation', 22));
    create_file('01a_JML.pdf', $material, '01a_JML', pdf('jml', 125));
    $key = create_folder('Material zu KeY', $material);
    create_file('key-examples.zip', $key, 'key-examples', "zip\n");
    create_file('06a_Isabelle.pdf', $material, '06a_Isabelle', pdf('isabelle', 89));
    $isabelle = create_folder('Material zu Isabelle', $material);
    create_file('Isabelle.thy', $isabelle, 'Isabelle', "theory Scratch imports Main begin end\n");
    // A title with a comma and a different file type than its neighbours
    create_file('pts2.zip', $material, 'Pluggable Typsysteme II, teilweise Lösung der Übung', "zip\n");
    create_file('pts2.pdf', $material, 'Pluggable Typsysteme II', pdf('pts2', 32));

    return $crs;
}

/**
 * Modelled after an older lecture: the page is split into sections with headings, and the material is
 * in item groups that are collapsed until clicked, in a folder of the same name, or not titled at all.
 */
function create_kit_collapsed_groups(array $students): int
{
    $crs = create_course('Beispielvorlesung mit aufklappbaren Gruppen', $students);

    $schedule = create_content_page_with_files('Termine für das SS2024', $crs, []);
    $board = create_object('frm', 'Schwarzes Brett', $crs)->getRefId();
    $info_group = create_item_group('Allgemeine Kursinformationen', $crs, [$schedule, $board]);

    $lecture_material = create_folder('Vorlesungsmaterial', $crs);
    $chapter = create_folder('Kapitel 5 - Rechnerarithmetik', $lecture_material);
    create_file('k5.pdf', $chapter, 'Kapitel 5 & 5.1', pdf('Kapitel 5 & 5.1', 20));
    create_file('k5-2.pdf', $chapter, 'Kapitel 5.2', pdf('Kapitel 5.2', 10));
    create_file('k5-all.pdf', $chapter, 'Kapitel 5 komplett', pdf('Kapitel 5 komplett', 60));
    $literature = create_unsupported_object('bibl', 'Literaturliste', $crs);
    $lecture_group = create_item_group('Vorlesung', $crs, [$lecture_material, $literature], 'closed');

    // Both item groups have a folder "Zusatzmaterialien"
    $sheets = create_folder('Übungsblätter', $crs);
    create_file('blatt1.pdf', $sheets, '1. Übungsblatt', pdf('1. Übungsblatt', 2));
    $exercise_extra = create_folder('Zusatzmaterialien', $crs);
    create_file('noten.pdf', $exercise_extra, 'Notenschlüssel', pdf('Notenschlüssel'));
    $leaflet = create_file('merkblatt.pdf', $crs, 'Merkblatt für die Übung', pdf('Merkblatt', 3));
    $exercise_group = create_item_group('Übung', $crs, [$sheets, $leaflet, $exercise_extra], 'closed');

    $tutorial_sheets = create_folder('Tutoriumsblätter', $crs);
    create_file('tut12.pdf', $tutorial_sheets, '12. Tutoriumsblatt', pdf('12. Tutoriumsblatt', 2));
    $tutorial_extra = create_folder('Zusatzmaterialien', $crs);
    create_file('karnaugh.pdf', $tutorial_extra, 'KV-Diagramme', pdf('KV-Diagramme'));
    $tutorial_group = create_item_group('Tutorium', $crs, [$tutorial_sheets, $tutorial_extra], 'closed');

    $script = create_folder('Skript', $crs);
    create_file('skript.pdf', $script, 'Auflage-13-skript', pdf('Skript', 200));
    $script_group = create_item_group('Skript zur Vorlesung', $crs, [$script], 'open');

    // The item group and its only folder have the same name
    $exams = create_folder('Altklausuren', $crs);
    $exam = create_folder('Klausur WS13-14', $exams);
    create_file('k_ws_14.pdf', $exam, 'k_ws_14', pdf('k_ws_14', 8));
    $exams_group = create_item_group('Altklausuren', $crs, [$exams], 'closed');

    $hidden_title_group = create_item_group('Ohne Titel', $crs, [create_file('untitled.pdf', $crs, 'untitled', pdf('untitled'))], 'untitled');

    set_container_page(
        $crs,
        section(
            'Background',
            heading('Willkommen zum Ilias-Kurs der Vorlesung "Beispielvorlesung mit aufklappbaren Gruppen"')
            . paragraph_with_link('Hier', 'http://ti.itec.uka.de/')
            . section(
                'Attention',
                heading('+++++ CORONA-VIRUS +++++', 2)
                . paragraph('Die Vorlesung wird im Voraus aufgezeichnet.')
                . heading('+++++ Klausurergebnisse/Einsicht +++++', 2)
            )
        )
        . section('Background', heading('Allgemeine Kursinformationen') . item_group_block($info_group))
        . item_group_block($lecture_group)
        . item_group_block($exercise_group)
        . item_group_block($tutorial_group)
        . item_group_block($script_group)
        . item_group_block($exams_group)
        . item_group_block($hidden_title_group)
    );

    return $crs;
}

/**
 * Modelled after a lecture with one accordion per week, each containing several item groups without a
 * title. Some weeks have titled item groups instead.
 */
function create_kit_weekly_accordions(array $students): int
{
    $crs = create_course('Beispielvorlesung mit Wochenabschnitten', $students);

    $forum = create_object('frm', 'Allgemeines Forum', $crs)->getRefId();
    $forums = create_item_group('Vorlesungsforen', $crs, [$forum]);
    $scripts = create_item_group('Skript(e) zur Vorlesung', $crs, [
        create_file('skript.pdf', $crs, 'skript-students', pdf('skript', 120)),
    ]);
    $page = accordion(['Allgemeines zur Vorlesung' => item_group_block($forums) . item_group_block($scripts)]);

    $weeks = [
        'Woche 1: Einführung und Commitment-Protokolle' => [
            ['vl-0-prolog-01-intro', 'Sitzung'],
            ['vl-1-commitments-01-intro'],
            // Untitled item groups of the same week end up in the same folder, so these files collide
            ['Sitzung'],
        ],
        'Woche 2: Commitment-Protokolle: Konstruktionen und Interaktion' => [
            ['vl-1-commitments-02-romcom'],
            ['Sitzung', 'exercise-week-2.zip'],
        ],
    ];
    foreach ($weeks as $week => $groups) {
        $blocks = '';
        foreach ($groups as $index => $files) {
            $refs = [];
            foreach ($files as $file) {
                $refs[] = str_ends_with($file, '.zip')
                    ? create_file($file, $crs, pathinfo($file, PATHINFO_FILENAME), "zip\n")
                    : create_file("$file.pdf", $crs, $file, pdf("$week $file"));
            }
            $blocks .= item_group_block(create_item_group("$week $index", $crs, $refs, 'untitled'));
        }
        $page .= accordion([$week => $blocks]);
    }

    // Later weeks have titled item groups
    $session = create_item_group('Sitzung Woche 10', $crs, [
        create_file('sitzung-10.pdf', $crs, 'Sitzung Woche 10', pdf('Sitzung Woche 10')),
    ]);
    $slides = create_item_group('Woche 10 Folien 1', $crs, [
        create_file('ot.pdf', $crs, 'Oblivious Transfer: Erasure-Channel', pdf('OT')),
    ]);
    $page .= accordion([
        'Woche 10: Weitere OT-Protokolle und aktive Sicherheit' => item_group_block($session) . item_group_block($slides),
    ]);

    set_container_page($crs, $page);
    return $crs;
}

/**
 * Nesting deeper than seen at KIT, to make the parser work for it: accordions in accordions,
 * accordions of different types, item groups with folders whose pages contain accordions again,
 * and the same file name on several levels.
 */
function create_nesting_course(array $students): int
{
    $crs = create_course('Nesting', $students);

    create_file('same.txt', $crs, null, "Course level\n");

    // An accordion in an accordion, with an item group in the inner one
    $inner_group = create_item_group('Inner Group', $crs, [create_file('inner.txt', $crs)]);
    $outer_group = create_item_group('Outer Group', $crs, [create_file('outer.txt', $crs)]);

    // A folder in an item group, whose own page has an accordion with an item group with a folder
    $folder = create_folder('Folder In Group', $crs);
    create_file('same.txt', $folder, null, "Folder level\n");
    $deep_folder = create_folder('Deep Folder', $folder);
    create_file('same.txt', $deep_folder, null, "Deep folder level\n");
    $folder_group = create_item_group('Folder Group', $folder, [$deep_folder]);
    set_container_page(
        $folder,
        accordion(['Folder Accordion' => item_group_block($folder_group)]) . other_items_block()
    );
    $folder_holder = create_item_group('Folder Holder', $crs, [$folder]);

    // Other accordion types
    $horizontal_group = create_item_group('Horizontal Group', $crs, [create_file('horizontal.txt', $crs)]);
    $carousel_group = create_item_group('Carousel Group', $crs, [create_file('carousel.txt', $crs)]);

    // A group whose page puts old content into an accordion
    $group = create_group('Tutor Area', $crs, $students);
    create_file('current.txt', $group);
    $old_group = create_item_group('Old Content', $group, [create_file('old.txt', $group)]);
    set_container_page(
        $group,
        other_items_block() . accordion(['Old Semester' => item_group_block($old_group)])
    );

    set_container_page(
        $crs,
        heading('Nesting')
        . accordion([
            'Outer' => item_group_block($outer_group)
                . accordion(['Inner' => item_group_block($inner_group)]),
            'Second Outer' => item_group_block($folder_holder),
        ])
        . accordion(['Horizontal' => item_group_block($horizontal_group)], 'HorizontalAccordion')
        . accordion(['Carousel' => item_group_block($carousel_group)], 'Carousel')
        . other_items_block()
    );

    return $crs;
}
