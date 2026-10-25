<?php

/**
 * Seeds the e2e test ILIAS instance with the fixture courses.
 *
 * Runs inside the ILIAS container: php /seed/seed.php
 *
 * Prints a single line "SEED_RESULT=<json>" with the ref ids of the created objects and also stores
 * that JSON in SEED_RESULT_PATH.
 */

declare(strict_types=1);

require_once __DIR__ . '/lib.php';
require_once __DIR__ . '/kit_courses.php';

const SEED_RESULT_PATH = '/var/iliasdata/ilias/seed-result.json';
const PASSWORD = 'pferd-e2e';

// Otherwise ILIAS redirects to the "change your password" form after the first login of every user
$security = ilSecuritySettings::_getInstance();
$security->setPasswordChangeOnFirstLoginEnabled(false);
$security->save();

// Favourites (and thereby the dashboard PFERD crawls) are disabled by default
$DIC->settings()->set('rep_favourites', '1');

// KIT users mostly see ILIAS in German
install_language('de');

// The default password policy forbids passwords containing the login
$student = create_user('student', PASSWORD);
$studentin = create_user('studentin', PASSWORD, 'de');
$desktop_user = create_user('desktop', PASSWORD);
$schreibtisch_user = create_user('schreibtisch', PASSWORD, 'de');
// Every course is crawled by both, to test parsing the pages in English and German
$students = [$student, $studentin];

$courses = [];

// Folder structure: nesting, empty folders, groups
$courses['structure'] = $crs = create_course('Structure', $students);
create_file('top.txt', $crs);
$folder_a = create_folder('Folder A', $crs);
create_file('a.txt', $folder_a);
create_file('deep.txt', create_folder('Nested C', create_folder('Nested B', $folder_a)));
create_folder('Empty Folder', $crs);
create_file('group.txt', create_group('Group G', $crs, $students));

// Names that need sanitizing or deduplication
$courses['naming'] = $crs = create_course('Naming', $students);
create_file('Übungsblatt 1 – Lösungen.pdf', $crs);
create_file('slash.txt', $crs, 'a/b slash.txt');
create_file('colon.txt', $crs, 'colon: name.txt');
create_file('README', $crs);
create_file('notes.pdf', $crs, 'Lecture Notes');
$duplicates = create_folder('Duplicates', $crs);
create_file('duplicate.txt', $duplicates, null, "First duplicate\n");
create_file('duplicate.txt', $duplicates, null, "Second duplicate\n");

// File dates, which are shown relative ("Today", "Yesterday") or absolute, in English and German
$courses['dates'] = $crs = create_course('Dates', $students);
$file_dates = [
    'old.txt' => gmmktime(10, 0, 0, 1, 5, 2020),
    'march.txt' => gmmktime(8, 0, 0, 3, 15, 2021),
    'yesterday.txt' => time() - 24 * 60 * 60,
    'today.txt' => time() - 60,
];
foreach ($file_dates as $filename => $timestamp) {
    set_file_date(create_file($filename, $crs), $timestamp);
}

// Course page with text, item groups and accordions, and a file on the info tab
$courses['page_content'] = $crs = create_course('Page Content', $students);
create_file('plain.txt', $crs);
$week = create_item_group('Week 1', $crs, [create_file('week.txt', $crs)]);
$accordion_group = create_item_group('Accordion Group', $crs, [create_file('accordion.txt', $crs)]);
set_container_page(
    $crs,
    paragraph('Welcome to the course!')
    . "<PageContent><Resources><ItemGroup RefId=\"$week\"/></Resources></PageContent>"
    . '<PageContent><Tabs Type="VerticalAccordion" Behavior="AllClosed"><Tab>'
    . "<PageContent><Resources><ItemGroup RefId=\"$accordion_group\"/></Resources></PageContent>"
    . '<TabCaption>Accordion Tab</TabCaption></Tab></Tabs></PageContent>'
    . '<PageContent><Resources><ResourceList Type="_other"/></Resources></PageContent>'
);
add_course_info_file($crs, 'syllabus.pdf', "Syllabus\n");

// Content pages with file lists. The file list shows the size, which PFERD has to strip.
$courses['content_page'] = $crs = create_course('Content Page', $students);
create_content_page_with_files('Material', $crs, [
    'small.pdf' => "Small\n",
    'large.pdf' => str_repeat("Large file\n", 300),
]);

// Videos embedded in a page and in a mediacast
$courses['videos'] = $crs = create_course('Videos', $students);
set_container_page(
    $crs,
    embedded_video(create_video_mob('lecture.mp4', 'lecture.mp4'), 'Embedded Lecture')
    . '<PageContent><Resources><ResourceList Type="_other"/></Resources></PageContent>'
);
create_mediacast('Recordings', $crs, ['recording-01.mp4' => 'Recording 01', 'recording-02.mp4' => 'Recording 02']);

// Links and booking pools, which PFERD stores as link files
$courses['links'] = $crs = create_course('Links', $students);
create_link('KIT Homepage', $crs, 'https://www.kit.edu', 'The KIT');
create_link_collection('Useful Links', $crs, [
    'Python' => 'https://www.python.org',
    'ILIAS' => 'https://www.ilias.de',
    'Rust' => 'https://www.rust-lang.org',
]);
create_object('book', 'Office Hours', $crs);

// Objects PFERD does not download. They have to be recognized and skipped without warnings.
$courses['unsupported'] = $crs = create_course('Unsupported', $students);
create_file('supported.txt', $crs);
foreach ([
    'tst' => 'Online Test',
    'svy' => 'Survey',
    'sahs' => 'SCORM Module',
    'bibl' => 'Literature List',
    'htlm' => 'HTML Module',
    'blog' => 'Blog',
    'dcl' => 'Data Collection',
    'mep' => 'Media Pool',
    'wiki' => 'Wiki',
    'iass' => 'Individual Assessment',
] as $type => $title) {
    create_unsupported_object($type, $title, $crs);
}
create_course_reference('Linked Course', $crs, $courses['structure']);

// Items that are visible but not yet available
$courses['availability'] = $crs = create_course('Availability', $students);
create_file('available.txt', $crs);
make_unavailable(create_file('future.txt', $crs));
$future_folder = create_folder('Future Folder', $crs);
create_file('hidden.txt', $future_folder);
make_unavailable($future_folder);

// Sessions with materials. Only one previous and next session is shown, the rest is collapsed.
$courses['sessions'] = $crs = create_course('Sessions', $students);
limit_course_sessions($crs, 1, 1);
create_session('Lecture 1', $crs, '2020-01-06 13:00:00', '2020-01-06 14:30:00', [create_file('slides-1.pdf', $crs)]);
create_session('Lecture 2', $crs, '2020-01-13 13:00:00', '2020-01-13 14:30:00', [create_file('slides-2.pdf', $crs)]);
create_session('Exam', $crs, '2040-02-10 09:00:00', '2040-02-10 11:00:00', [create_file('exam-info.pdf', $crs)]);
create_session('Exam Review', $crs, '2040-03-10 09:00:00', '2040-03-10 10:00:00', [create_file('review.pdf', $crs)]);

// Exercises with instruction files, an own submission and tutor feedback
$courses['exercises'] = $crs = create_course('Exercises', $students);
$exc = create_exercise('Exercise Sheets', $crs, $students);
$sheet_1 = create_assignment($exc, 'Sheet 1', 10, ['sheet-1.pdf', 'template.zip']);
create_assignment($exc, 'Sheet 2', 20, ['sheet-2.pdf']);
foreach ($students as $user) {
    add_submission($exc, $sheet_1, $user, 'solution.pdf', "My solution\n");
    add_feedback_file($sheet_1, $user, 'feedback.pdf', "Well done\n");
}

// Forum threads. The dates are fixed, as they end up in the exported threads.
$courses['forum'] = $crs = create_course('Forum', $students);
$forum = create_object('frm', 'Discussion', $crs);
create_forum_thread($forum, ROOT_USER_ID, 'Welcome', '<p>Welcome to the forum!</p>', '2020-01-05 10:00:00', [
    [$student, '<p>Thanks!</p>', '2020-01-06 12:00:00'],
]);
create_forum_thread($forum, $student, 'Question: Sheet 1?', '<p>How do I solve task 2?</p>', '2020-01-07 09:30:00', []);

// Learning modules with pages in multiple chapters, and with a single page containing a video
$courses['learning_module'] = $crs = create_course('Learning Module', $students);
create_learning_module('Lecture Notes', $crs, [
    'Chapter 1' => [
        'Introduction' => paragraph('This is the introduction.'),
        'Basics' => paragraph('Some basics.'),
    ],
    'Chapter 2' => ['Advanced Topics' => paragraph('Advanced things.')],
]);
// KIT lectures also use a learning module with a single page as a container for their recordings
create_learning_module('Recordings', $crs, [
    'Recordings' => [
        'Lecture 1' => paragraph('The recording of the first lecture.')
            . embedded_video(create_video_mob('lecture-1.mp4', 'lecture-1.mp4'), 'Lecture 1'),
    ],
]);

// Courses modelled after real KIT courses
[$courses['kit_lecture'], $kit_lecture_file_dates] = create_kit_lecture($students);
$courses['kit_seminar'] = create_kit_seminar($students);
$courses['kit_collapsed_groups'] = create_kit_collapsed_groups($students);
$courses['kit_weekly_accordions'] = create_kit_weekly_accordions($students);
$courses['nesting'] = create_nesting_course($students);

// The dashboard of a separate user, as it shows all courses and favourites of the user
$desktop_a = create_course('Desktop Course A', [$desktop_user, $schreibtisch_user]);
create_file('a.txt', $desktop_a);
$desktop_b = create_course('Desktop Course B', [$desktop_user, $schreibtisch_user]);
$favourite_folder = create_folder('Favourite Folder', $desktop_b);
create_file('in-folder.txt', $favourite_folder);
create_file('not-favourite.txt', $desktop_b);
$favourites = new ilFavouritesManager();
foreach ([$desktop_user, $schreibtisch_user] as $user) {
    $favourites->add($user, $desktop_a);
    $favourites->add($user, $favourite_folder);
}

$result = json_encode([
    'courses' => $courses,
    'users' => [
        'student' => ['login' => 'student', 'password' => PASSWORD],
        'studentin' => ['login' => 'studentin', 'password' => PASSWORD],
        'desktop' => ['login' => 'desktop', 'password' => PASSWORD],
        'schreibtisch' => ['login' => 'schreibtisch', 'password' => PASSWORD],
    ],
    'file_dates' => $file_dates,
    'kit_lecture_file_dates' => $kit_lecture_file_dates,
    'favourite_folder' => $favourite_folder,
]);
// Lets the test fixture reuse an already seeded instance
file_put_contents(SEED_RESULT_PATH, $result);
echo "SEED_RESULT=$result\n";
