<?php

/**
 * Creates and changes a course for the tests that check how PFERD handles changes between runs.
 * Every call to "create" creates a new course, so these tests do not influence each other or the
 * fixtures of seed.php.
 *
 * Usage:
 *   php changes.php create            Prints the created ref ids as JSON
 *   php changes.php change <json>     Changes the course created by "create"
 */

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

$action = $argv[1];

if ($action === 'create') {
    $crs = create_course('Changes ' . uniqid(), [ilObjUser::_lookupId('student'), ilObjUser::_lookupId('studentin')]);
    $refs = [
        'course' => $crs,
        'unchanged.txt' => create_file('unchanged.txt', $crs),
        'changed.txt' => create_file('changed.txt', $crs),
        'deleted.txt' => create_file('deleted.txt', $crs),
    ];
    $folder = create_folder('Deleted Folder', $crs);
    $refs['Deleted Folder'] = $folder;
    create_file('in-folder.txt', $folder);
    // A date in the past, so the changed file is newer even if it changes in the same minute
    foreach (['unchanged.txt', 'changed.txt', 'deleted.txt'] as $name) {
        set_file_date($refs[$name], gmmktime(10, 0, 0, 1, 5, 2020));
    }
    echo json_encode($refs) . "\n";
} elseif ($action === 'change') {
    $refs = json_decode($argv[2], true);
    replace_file_content($refs['changed.txt'], "New content\n");
    delete_object($refs['deleted.txt']);
    delete_object($refs['Deleted Folder']);
    create_file('added.txt', $refs['course']);
    echo "{}\n";
} else {
    throw new InvalidArgumentException("Unknown action $action");
}
