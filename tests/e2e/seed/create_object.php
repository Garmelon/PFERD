<?php

/**
 * Creates a single object. Used by create_in_request_context, which has to set the ref id of the
 * request before ILIAS is bootstrapped.
 *
 * Usage: SEED_REF_ID=<parent ref id> php create_object.php <type> <title> <parent ref id>
 */

declare(strict_types=1);

require_once __DIR__ . '/lib.php';

[, $type, $title, $parent_ref_id] = $argv;
echo 'CREATED=' . create_object($type, $title, (int) $parent_ref_id)->getRefId() . "\n";
