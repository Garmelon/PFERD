<?php

/**
 * Bootstraps ILIAS as root and provides helpers to create the fixture objects.
 *
 * Uses the ILIAS object API directly, as the SOAP API is too limited (and addFile is broken for
 * inline content in ILIAS 10). Some objects need small fixups (mostly online flags and permissions)
 * that the GUI would normally do. These are noted where they happen.
 */

declare(strict_types=1);

chdir('/var/www/html');
require_once './vendor/composer/vendor/autoload.php';

// Not set in the CLI context, but needed e.g. by the news notifications of new files
define('ILIAS_HTTP_PATH', getenv('ILIAS_HTTP_PATH'));

// Some objects read the ref id of the current request while being created. ILIAS reads the request
// parameters once while bootstrapping, so they have to be set before (see create_in_request_context).
if (getenv('SEED_REF_ID') !== false) {
    $_GET['ref_id'] = getenv('SEED_REF_ID');
}

use ILIAS\Filesystem\Stream\Streams;
use ILIAS\ResourceStorage\Identification\ResourceCollectionIdentification;

const ROOT_REF_ID = 1;
const ROOT_USER_ID = 6;
const USER_ROLE_ID = 4;

(new ilCronStartUp('default', 'root'))->authenticate();

function db(): ilDBInterface
{
    global $DIC;
    return $DIC->database();
}

/**
 * Creates the object in the repository and makes it visible to the members of the surrounding course:
 * Most objects are offline by default and the default member role lacks permissions for some types.
 */
function put_in_tree(ilObject $obj, int $parent_ref_id): int
{
    global $DIC;

    $obj->create();
    $obj->createReference();
    $obj->putInTree($parent_ref_id);
    $obj->setPermissions($parent_ref_id);
    // ILIAS creates this entry on the first access. Parallel first accesses race, and the loser crashes
    // with "Undefined array key timing_type".
    ilObjectActivation::getItem($obj->getRefId());

    if ($DIC['objDefinition']->supportsOfflineHandling($obj->getType())) {
        $obj->setOfflineStatus(false);
        $obj->update();
    }

    if ($course_ref_id = $DIC->repositoryTree()->checkForParentType($obj->getRefId(), 'crs')) {
        $DIC->rbac()->admin()->grantPermission(
            (new ilObjCourse($course_ref_id))->getDefaultMemberRole(),
            ilRbacReview::_getOperationIdsByName(['visible', 'read']),
            $obj->getRefId()
        );
    }

    return $obj->getRefId();
}

function create_object(string $type, string $title, int $parent_ref_id): ilObject
{
    global $DIC;

    $class = 'ilObj' . $DIC['objDefinition']->getClassName($type);
    $obj = new $class();
    $obj->setTitle($title);
    put_in_tree($obj, $parent_ref_id);
    return $obj;
}

/**
 * Creates an object in a separate PHP process with the parent as the ref id of the current request.
 * Needed for objects that look at the request while being created (data collections).
 */
function create_in_request_context(string $type, string $title, int $parent_ref_id): int
{
    $output = shell_exec(
        'SEED_REF_ID=' . $parent_ref_id . ' php ' . escapeshellarg(__DIR__ . '/create_object.php')
        . ' ' . escapeshellarg($type) . ' ' . escapeshellarg($title) . ' ' . $parent_ref_id . ' 2>&1'
    );
    if (!preg_match('/^CREATED=(\d+)$/m', (string) $output, $match)) {
        throw new RuntimeException("Could not create $type '$title':\n$output");
    }
    return (int) $match[1];
}

// ---------------------------------------------------------------------------------------------------
// Users and containers
// ---------------------------------------------------------------------------------------------------

function create_user(string $login, string $password, string $language = 'en'): int
{
    global $DIC;

    $user = new ilObjUser();
    $user->setLogin($login);
    $user->setFirstname('Test');
    $user->setLastname(ucfirst($login));
    $user->setEmail("$login@example.com");
    $user->setPasswd($password, ilObjUser::PASSWD_PLAIN);
    $user->setActive(true);
    $user->setTimeLimitUnlimited(true);
    $user->setAgreeDate(date('Y-m-d H:i:s'));
    $user->setLanguage($language);
    $user->create();
    $user->saveAsNew();
    // saveAsNew does not store the preferences, which hold the language
    $user->writePrefs();
    // ILIAS creates this entry on the first login. Parallel first logins race, and the loser crashes
    // with "Duplicate entry".
    ilOnlineTracking::addUser($user->getId());

    $DIC->rbac()->admin()->assignUser(USER_ROLE_ID, $user->getId());
    return $user->getId();
}

function install_language(string $key): void
{
    (new ilObjLanguage((int) ilObject::_getIdsForTitle($key, 'lng')[0]))->install();
}

/**
 * @param int[] $member_ids
 */
function create_course(string $title, array $member_ids): int
{
    $crs = new ilObjCourse();
    $crs->setTitle($title);
    $ref_id = put_in_tree($crs, ROOT_REF_ID);
    foreach ($member_ids as $member_id) {
        $crs->getMembersObject()->add($member_id, ilParticipants::IL_CRS_MEMBER);
    }
    return $ref_id;
}

/**
 * @param int[] $member_ids
 */
function create_group(string $title, int $parent_ref_id, array $member_ids): int
{
    $grp = new ilObjGroup();
    $grp->setTitle($title);
    $ref_id = put_in_tree($grp, $parent_ref_id);
    $grp->initDefaultRoles();
    foreach ($member_ids as $member_id) {
        ilGroupParticipants::_getInstanceByObjId($grp->getId())->add($member_id, ilParticipants::IL_GRP_MEMBER);
    }
    return $ref_id;
}

function create_folder(string $title, int $parent_ref_id): int
{
    return create_object('fold', $title, $parent_ref_id)->getRefId();
}

/**
 * @param int[] $item_ref_ids
 * @param string $display How the item group is shown: one of "title" (always open), "closed" or "open"
 *                        (expandable, initially closed or open) and "untitled"
 */
function create_item_group(string $title, int $parent_ref_id, array $item_ref_ids, string $display = 'title'): int
{
    $itgr = create_object('itgr', $title, $parent_ref_id);
    $ref_id = $itgr->getRefId();
    $items = new ilItemGroupItems($ref_id);
    $items->setItems($item_ref_ids);
    $items->update();

    if ($display !== 'title') {
        assert($itgr instanceof ilObjItemGroup);
        if ($display === 'untitled') {
            $itgr->setDisplay(ilItemGroupAR::DISPLAY_WITHOUT_TITLE);
        } else {
            $itgr->setDisplay(ilItemGroupAR::DISPLAY_WITH_TITLE_AND_TOGGLEABLE);
            $itgr->setDisplayWithTitleAndToggleableInitially(match ($display) {
                'closed' => ilItemGroupAR::DISPLAY_WITH_TITLE_AND_TOGGLEABLE_INITIALLY_CLOSED,
                'open' => ilItemGroupAR::DISPLAY_WITH_TITLE_AND_TOGGLEABLE_INITIALLY_OPEN,
            });
        }
        $itgr->update();
    }
    return $ref_id;
}

/**
 * Sets the page shown above the items of a container. $content is a list of PageContent elements.
 */
function set_container_page(int $ref_id, string $content): void
{
    $page = new ilContainerPage();
    $page->setId(ilObject::_lookupObjId($ref_id));
    $page->setParentId(ilObject::_lookupObjId($ref_id));
    $page->setXMLContent("<PageObject>$content</PageObject>");
    $page->create(false);
}

function paragraph(string $text): string
{
    return '<PageContent><Paragraph Language="en" Characteristic="Standard">' . htmlspecialchars($text)
        . '</Paragraph></PageContent>';
}

function heading(string $text, int $level = 1): string
{
    return "<PageContent><Paragraph Language=\"de\" Characteristic=\"Headline$level\">" . htmlspecialchars($text)
        . '</Paragraph></PageContent>';
}

/**
 * A paragraph with a link, as KIT course pages link to external pages and other ILIAS objects in their text.
 */
function paragraph_with_link(string $text, string $url): string
{
    return '<PageContent><Paragraph Language="de" Characteristic="Standard">' . htmlspecialchars($text)
        . ' <ExtLink Href="' . htmlspecialchars($url) . '">' . htmlspecialchars($url) . '</ExtLink>'
        . '</Paragraph></PageContent>';
}

/**
 * A section with a background style, which KIT courses use to frame parts of their page.
 */
function section(string $characteristic, string $content): string
{
    return "<PageContent><Section Characteristic=\"$characteristic\">$content</Section></PageContent>";
}

/**
 * Embeds an item group in a page. Its items are then only shown there.
 */
function item_group_block(int $item_group_ref_id): string
{
    return "<PageContent><Resources><ItemGroup RefId=\"$item_group_ref_id\"/></Resources></PageContent>";
}

/**
 * The list of all items that are not part of an item group.
 */
function other_items_block(): string
{
    return '<PageContent><Resources><ResourceList Type="_other"/></Resources></PageContent>';
}

/**
 * @param array<string, string> $tabs caption => page content
 * @param string $type VerticalAccordion, HorizontalAccordion or Carousel
 */
function accordion(array $tabs, string $type = 'VerticalAccordion'): string
{
    $xml = "<PageContent><Tabs Type=\"$type\" Behavior=\"AllClosed\">";
    foreach ($tabs as $caption => $content) {
        $xml .= "<Tab>$content<TabCaption>" . htmlspecialchars($caption) . '</TabCaption></Tab>';
    }
    return $xml . '</Tabs></PageContent>';
}

// ---------------------------------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------------------------------

function create_file(string $filename, int $parent_ref_id, ?string $title = null, ?string $content = null): int
{
    $file = new ilObjFile();
    $file->setTitle($filename);
    $ref_id = put_in_tree($file, $parent_ref_id);
    $file->appendStream(Streams::ofString($content ?? "Content of $filename\n"), $filename);
    if ($title !== null) {
        // appendStream sets the title to the filename
        $file->setTitle($title);
        $file->update();
    }
    return $ref_id;
}

/**
 * Sets the date ILIAS shows for (the current version of) a file.
 */
function set_file_date(int $ref_id, int $timestamp): void
{
    $file = new ilObjFile($ref_id);
    db()->manipulateF(
        'UPDATE il_resource_info SET creation_date = %s WHERE rid = %s AND version_number = '
        . '(SELECT max_version FROM (SELECT MAX(version_number) AS max_version FROM il_resource_info WHERE rid = %s) v)',
        ['integer', 'text', 'text'],
        [$timestamp, $file->getResourceId(), $file->getResourceId()]
    );
}

function replace_file_content(int $ref_id, string $content): void
{
    $file = new ilObjFile($ref_id);
    $file->replaceWithStream(Streams::ofString($content), $file->getFileName());
}

/**
 * Uploads a new version of a file, so ILIAS shows "Version: 2". Unlike replace_file_content, the old
 * version is kept.
 */
function add_file_version(int $ref_id, string $content): void
{
    $file = new ilObjFile($ref_id);
    $title = $file->getTitle();
    $file->appendStream(Streams::ofString($content), $file->getFileName());
    // appendStream sets the title to the filename
    $file->setTitle($title);
    $file->update();
}

/**
 * A valid PDF with the given number of pages. ILIAS shows the page count of PDFs ("Anzahl Seiten").
 */
function pdf(string $text, int $pages = 1): string
{
    $objects = ['<< /Type /Catalog /Pages 2 0 R >>'];
    $kids = [];
    for ($i = 0; $i < $pages; $i++) {
        $kids[] = (3 + $i) . ' 0 R';
    }
    $objects[] = '<< /Type /Pages /Kids [' . implode(' ', $kids) . "] /Count $pages >>";
    for ($i = 0; $i < $pages; $i++) {
        $objects[] = '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>';
    }
    // Make the content unique, so files with the same page count differ
    $objects[] = '<< /Title (' . str_replace(['(', ')', '\\'], '', $text) . ') >>';

    $pdf = "%PDF-1.4\n";
    $offsets = [];
    foreach ($objects as $index => $object) {
        $offsets[] = strlen($pdf);
        $pdf .= ($index + 1) . " 0 obj\n$object\nendobj\n";
    }
    $xref = strlen($pdf);
    $pdf .= "xref\n0 " . (count($objects) + 1) . "\n0000000000 65535 f \n";
    foreach ($offsets as $offset) {
        $pdf .= sprintf("%010d 00000 n \n", $offset);
    }
    $info = count($objects);
    $pdf .= "trailer\n<< /Size " . (count($objects) + 1) . " /Root 1 0 R /Info $info 0 R >>\n"
        . "startxref\n$xref\n%%EOF\n";
    return $pdf;
}

/**
 * Lets course members see an object in the list, but not open it. KIT tutorial groups the student is not
 * a member of look like this.
 */
function make_visible_only(int $ref_id): void
{
    global $DIC;

    $course_ref_id = $DIC->repositoryTree()->checkForParentType($ref_id, 'crs');
    $member_role = (new ilObjCourse($course_ref_id))->getDefaultMemberRole();
    $DIC->rbac()->admin()->revokePermission($ref_id, $member_role);
    $DIC->rbac()->admin()->grantPermission($member_role, ilRbacReview::_getOperationIdsByName(['visible']), $ref_id);
}

function delete_object(int $ref_id): void
{
    global $DIC;
    ilRepUtil::deleteObjects($DIC->repositoryTree()->getParentId($ref_id), [$ref_id]);
}

/**
 * Makes the object visible, but not accessible, until 2035.
 */
function make_unavailable(int $ref_id): void
{
    $activation = new ilObjectActivation();
    $activation->setTimingType(ilObjectActivation::TIMINGS_ACTIVATION);
    $activation->setTimingStart(mktime(0, 0, 0, 1, 1, 2035));
    $activation->setTimingEnd(mktime(0, 0, 0, 1, 1, 2036));
    $activation->toggleVisible(true);
    $activation->update($ref_id);
}

function add_course_info_file(int $course_ref_id, string $filename, string $content): void
{
    $info = new ilCourseFile();
    $info->setCourseId(ilObject::_lookupObjId($course_ref_id));
    $info->setFileName($filename);
    $info->setFileSize(strlen($content));
    $info->setFileType('application/octet-stream');
    $info->create(false);
    file_put_contents($info->getInfoDirectory() . '/' . $info->getFileId(), $content);
}

// ---------------------------------------------------------------------------------------------------
// Pages and media
// ---------------------------------------------------------------------------------------------------

/**
 * A file object outside the repository tree, like the ones uploaded in the page editor.
 */
function create_page_file(string $filename, string $content): int
{
    $file = new ilObjFile();
    $file->setTitle($filename);
    $file->create();
    $file->appendStream(Streams::ofString($content), $filename);
    return $file->getId();
}

/**
 * @param array<string, string> $files filename => content
 */
function create_content_page_with_files(string $title, int $parent_ref_id, array $files): int
{
    $copa = create_object('copa', $title, $parent_ref_id);
    $items = '';
    foreach ($files as $filename => $content) {
        $items .= '<FileItem><Identifier Catalog="ILIAS" Entry="il__file_' . create_page_file($filename, $content) . '"/>'
            . '<Location Type="LocalFile">' . htmlspecialchars($filename) . '</Location>'
            . '<Format>application/octet-stream</Format></FileItem>';
    }
    $page = new ilContentPagePage();
    $page->setId($copa->getId());
    $page->setParentId($copa->getId());
    $page->setXMLContent('<PageObject><PageContent><FileList><Title Language="en">Files</Title>' . $items
        . '</FileList></PageContent></PageObject>');
    $page->create(false);
    return $copa->getRefId();
}

/**
 * A media object containing a (fake) video. PFERD only downloads it, so it does not need to be valid.
 */
function create_video_mob(string $filename, string $title): int
{
    $tmp = ilFileUtils::ilTempnam();
    file_put_contents($tmp, "Fake video $filename\n");
    $mob = new ilObjMediaObject();
    $mob->setTitle($title);
    $mob->create();
    // Tries to generate a preview with ffmpeg, which fails for the fake video. That is fine.
    $mob->addMediaItemFromLocalFile('Standard', $tmp, $filename);
    $mob->update();
    return $mob->getId();
}

function embedded_video(int $mob_id, string $caption): string
{
    return '<PageContent><MediaObject><MediaAlias OriginId="il__mob_' . $mob_id . '"/>'
        . '<MediaAliasItem Purpose="Standard"><Caption Align="bottom">' . htmlspecialchars($caption)
        . '</Caption></MediaAliasItem></MediaObject></PageContent>';
}

/**
 * @param array<string, string> $videos filename => title
 */
function create_mediacast(string $title, int $parent_ref_id, array $videos): int
{
    $mcst = create_object('mcst', $title, $parent_ref_id);
    $mcst->setOnline(true);
    $mcst->update();
    foreach ($videos as $filename => $video_title) {
        $mcst->addMobToCast(create_video_mob($filename, $video_title), ROOT_USER_ID, '', false);
    }
    return $mcst->getRefId();
}

// ---------------------------------------------------------------------------------------------------
// Links and other objects
// ---------------------------------------------------------------------------------------------------

function create_link(string $title, int $parent_ref_id, string $url, string $description): int
{
    $webr = create_object('webr', $title, $parent_ref_id);
    (new ilWebLinkDatabaseRepository($webr->getId()))->createItem(
        new ilWebLinkDraftItem(false, $title, $description, $url, true, [])
    );
    return $webr->getRefId();
}

/**
 * @param array<string, string> $links title => url
 */
function create_link_collection(string $title, int $parent_ref_id, array $links): int
{
    $webr = create_object('webr', $title, $parent_ref_id);
    $repo = new ilWebLinkDatabaseRepository($webr->getId());
    $repo->createList(new ilWebLinkDraftList($title, ''));
    foreach ($links as $link_title => $url) {
        $repo->createItem(new ilWebLinkDraftItem(false, $link_title, "About $link_title", $url, true, []));
    }
    return $webr->getRefId();
}

/**
 * Creates objects PFERD does not download, making them accessible for course members.
 */
function create_unsupported_object(string $type, string $title, int $parent_ref_id): int
{
    global $DIC;

    if ($type === 'dcl') {
        $ref_id = create_in_request_context('dcl', $title, $parent_ref_id);
        db()->manipulate('UPDATE il_dcl_data SET is_online = 1 WHERE id = ' . ilObject::_lookupObjId($ref_id));
        return $ref_id;
    }

    $obj = create_object($type, $title, $parent_ref_id);
    $obj_id = $obj->getId();
    switch ($type) {
        case 'tst':
            // Tests and surveys are only accessible once they are "complete", i.e. have questions
            $obj->saveToDb();
            db()->manipulate("UPDATE tst_tests SET complete = 1 WHERE obj_fi = $obj_id");
            break;
        case 'svy':
            db()->manipulate("UPDATE svy_svy SET complete = 1 WHERE obj_fi = $obj_id");
            break;
        case 'bibl':
            db()->manipulate("UPDATE object_data SET offline = 0 WHERE obj_id = $obj_id");
            break;
        case 'htlm':
            // HTML learning modules are only accessible with a start file
            $zip_path = ilFileUtils::ilTempnam();
            $zip = new ZipArchive();
            $zip->open($zip_path, ZipArchive::CREATE);
            $zip->addFromString('index.html', '<html><body>HTML learning module</body></html>');
            $zip->close();
            $rid = $DIC->resourceStorage()->manageContainer()->containerFromStream(
                Streams::ofResource(fopen($zip_path, 'rb')),
                new ilHTLMStakeholder(),
                $title
            );
            $obj->setRID($rid->serialize());
            $obj->setStartFile('index.html');
            $obj->update();
            break;
    }
    return $obj->getRefId();
}

function create_course_reference(string $title, int $parent_ref_id, int $target_ref_id): int
{
    $ref = create_object('crsr', $title, $parent_ref_id);
    $ref->setTargetId(ilObject::_lookupObjId($target_ref_id));
    $ref->update();
    return $ref->getRefId();
}

// ---------------------------------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------------------------------

/**
 * @param int[] $material_ref_ids items of the course shown as materials of the session
 */
function create_session(string $title, int $parent_ref_id, string $start_utc, string $end_utc, array $material_ref_ids): int
{
    $sess = create_object('sess', $title, $parent_ref_id);
    $appointment = new ilSessionAppointment();
    $appointment->setSessionId($sess->getId());
    $appointment->setStart(new ilDateTime($start_utc, IL_CAL_DATETIME, 'UTC'));
    $appointment->setEnd(new ilDateTime($end_utc, IL_CAL_DATETIME, 'UTC'));
    $appointment->toggleFullTime(false);
    $appointment->create();
    $items = new ilEventItems($sess->getId());
    $items->setItems($material_ref_ids);
    $items->update();
    return $sess->getRefId();
}

/**
 * Only shows the given number of previous and next sessions, the others are hidden behind a link.
 */
function limit_course_sessions(int $course_ref_id, int $previous, int $next): void
{
    $crs = new ilObjCourse($course_ref_id);
    $crs->enableSessionLimit(1);
    $crs->setNumberOfPreviousSessions($previous);
    $crs->setNumberOfNextSessions($next);
    $crs->update();
}

// ---------------------------------------------------------------------------------------------------
// Exercises
// ---------------------------------------------------------------------------------------------------

/**
 * @param int[] $member_ids
 */
function create_exercise(string $title, int $parent_ref_id, array $member_ids): ilObjExercise
{
    $exc = create_object('exc', $title, $parent_ref_id);
    foreach ($member_ids as $member_id) {
        (new ilExerciseMembers($exc))->assignMember($member_id);
    }
    return $exc;
}

/**
 * @param string[] $instruction_files
 */
function create_assignment(ilObjExercise $exc, string $title, int $order, array $instruction_files): int
{
    global $DIC;

    $ass = new ilExAssignment();
    $ass->setExerciseId($exc->getId());
    $ass->setTitle($title);
    $ass->setType(ilExAssignment::TYPE_UPLOAD);
    $ass->setStartTime(mktime(10, 0, 0, 1, 1, 2020));
    // Stored as a 32-bit timestamp
    $ass->setDeadline(mktime(10, 0, 0, 1, 1, 2035));
    $ass->setInstruction("Instructions for $title");
    $ass->setOrderNr($order);
    $ass->setPeerReviewValid(ilExAssignment::PEER_REVIEW_VALID_NONE);
    $ass->save();

    $dir = ilFileUtils::ilTempnam();
    mkdir($dir);
    foreach ($instruction_files as $name) {
        file_put_contents("$dir/$name", "Content of $name\n");
    }
    $files = $DIC->exercise()->internal()->domain()->assignment()->instructionFiles($ass->getId());
    $files->createCollection();
    $files->importFromDirectory($dir);
    return $ass->getId();
}

function add_submission(ilObjExercise $exc, int $ass_id, int $user_id, string $filename, string $content): void
{
    global $DIC;

    $tmp = ilFileUtils::ilTempnam();
    file_put_contents($tmp, $content);
    // The submission manager only accepts submissions by the current user, so use the repository directly
    $DIC->exercise()->internal()->repo()->submission()->addLocalFile(
        $exc->getId(), $ass_id, $user_id, 0, $tmp, $filename, false, new ilExcSubmissionStakeholder()
    );
}

function add_feedback_file(int $ass_id, int $user_id, string $filename, string $content): void
{
    global $DIC;

    $feedback = $DIC->exercise()->internal()->domain()->assignment()->tutorFeedbackFile($ass_id);
    $feedback->createCollection($user_id);
    $irss = $DIC->resourceStorage();
    $collection = $irss->collection()->get(
        new ResourceCollectionIdentification($feedback->getCollectionIdString($user_id))
    );
    $collection->add($irss->manage()->stream(Streams::ofString($content), $feedback->getStakeholder(), $filename));
    $irss->collection()->store($collection);
}

// ---------------------------------------------------------------------------------------------------
// Forums and learning modules
// ---------------------------------------------------------------------------------------------------

/**
 * @param array<array{int, string, string}> $replies [author id, message, date]
 */
function create_forum_thread(
    ilObjForum $forum,
    int $author_id,
    string $subject,
    string $message,
    string $date,
    array $replies
): void {
    $frm = $forum->Forum;
    $frm->setForumId($forum->getId());
    $frm->setForumRefId($forum->getRefId());
    $frm->setMDB2WhereCondition('top_frm_fk = %s', ['integer'], [$forum->getId()]);
    $top = $frm->getOneTopic();

    $thread = new ilForumTopic(0, true, true);
    $thread->setForumId($top->getTopPk());
    $thread->setThrAuthorId($author_id);
    $thread->setDisplayUserId($author_id);
    $thread->setSubject($subject);
    $thread->setCreateDate($date);
    $root_post = $frm->generateThread($thread, $message, false, false, true);

    foreach ($replies as [$reply_author_id, $reply_message, $reply_date]) {
        $frm->generatePost(
            $top->getTopPk(),
            $thread->getId(),
            $reply_author_id,
            $reply_author_id,
            $reply_message,
            $root_post,
            false,
            "Re: $subject",
            null,
            $reply_date
        );
    }
}

/**
 * @param array<string, array<string, string>> $chapters chapter title => [page title => page content]
 */
function create_learning_module(string $title, int $parent_ref_id, array $chapters): int
{
    $lm = create_object('lm', $title, $parent_ref_id);
    $lm->createLMTree();

    foreach ($chapters as $chapter_title => $pages) {
        $chapter = new ilStructureObject($lm);
        $chapter->setTitle($chapter_title);
        $chapter->setLMId($lm->getId());
        $chapter->create();
        ilLMObject::putInTree($chapter);

        foreach ($pages as $page_title => $content) {
            $lm_page = new ilLMPageObject($lm);
            $lm_page->setTitle($page_title);
            $lm_page->setLMId($lm->getId());
            $lm_page->create(false, true);
            $page = new ilLMPage();
            $page->setId($lm_page->getId());
            $page->setParentId($lm->getId());
            $page->setXMLContent("<PageObject>$content</PageObject>");
            $page->create(false);
            ilLMObject::putInTree($lm_page, $chapter->getId());
        }
    }
    return $lm->getRefId();
}
