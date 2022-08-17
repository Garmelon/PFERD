# Changelog

All notable changes to this project will be documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

This project has its own custom versioning scheme. Version numbers consist of
three parts (e. g. `3.1.5`).
- The first number is increased on major rewrites or changes. What classifies as
  a major change is up to the maintainers. This is pretty rare and a PFERD
  version 4 should hopefully not be necessary.
- The second number is increased on backwards-incompatible changes in behaviour.
  This refers to any change that would make an existing setup behave differently
  (e. g. renaming options or changing crawler behaviour). If this number is
  increased, it may be necessary for you to adapt your own setup.
- The third number is increased on backwards-compatible changes (e. g. adding
  new options or commands, changing documentation, fixing bugs). Updates that
  only increase this number should be safe and not require manual intervention.

We will try to correctly classify changes as backwards-compatible or
backwards-incompatible, but may occasionally make mistakes or stumble across
ambiguous situations.

## Unreleased

## 3.4.1 - 2022-08-17

### Added
- Download of page descriptions
- Forum download support
- `pass` authenticator

### Changed
- Add `cpp` extension to default `link_regex` of IPD crawler
- Mention hrefs in IPD crawler's `--explain` output for users of `link_regex` option
- Simplify default IPD crawler `link_regex`

### Fixed
- IPD crawler crashes on some sites
- Meeting name normalization for yesterday, today and tomorrow
- Crawling of meeting file previews
- Login with new login button html layout
- Descriptions for courses are now placed in the correct subfolder when
  downloading the whole desktop

## 3.4.0 - 2022-05-01

### Added
- Message when Shibboleth entitlements need to be manually reviewed
- Links to unofficial packages and repology in the readme

### Changed
- Increase minimum supported Python version to 3.9
- Support video listings with more columns
- Use UTF-8 when reading/writing the config file

### Fixed
- Crash during authentication when the Shibboleth session is still valid

## 3.3.1 - 2022-01-15

### Fixed
- ILIAS login
- Local video cache if `windows_paths` is enabled

## 3.3.0 - 2022-01-09

### Added
- A KIT IPD crawler
- Support for ILIAS cards
- (Rudimentary) support for content pages
- Support for multi-stream videos
- Support for ILIAS 7

### Removed
- [Interpolation](https://docs.python.org/3/library/configparser.html#interpolation-of-values) in config file

### Fixed
- Crawling of recursive courses
- Crawling files directly placed on the personal desktop
- Ignore timestamps at the unix epoch as they crash on windows

## 3.2.0 - 2021-08-04

### Added
- `--skip` command line option
- Support for ILIAS booking objects

### Changed
- Using multiple path segments on left side of `-name->` now results in an
  error. This was already forbidden by the documentation but silently accepted
  by PFERD.
- More consistent path printing in some `--explain` messages

### Fixed
- Nondeterministic name deduplication due to ILIAS reordering elements
- More exceptions are handled properly

## 3.1.0 - 2021-06-13

If your config file doesn't do weird things with transforms, it should continue
to work. If your `-re->` arrows behave weirdly, try replacing them with
`-exact-re->` arrows. If you're on Windows, you might need to switch from `\`
path separators to `/` in your regex rules.

### Added
- `skip` option for crawlers
- Rules with `>>` instead of `>` as arrow head
- `-exact-re->` arrow (behaves like `-re->` did previously)

### Changed
- The `-re->` arrow can now rename directories (like `-->`)
- Use `/` instead of `\` as path separator for (regex) rules on Windows
- Use the label to the left for exercises instead of the button name to
  determine the folder name

### Fixed
- Video pagination handling in ILIAS crawler

## 3.0.1 - 2021-06-01

### Added
- `credential-file` authenticator
- `--credential-file` option for `kit-ilias-web` command
- Warning if using concurrent tasks with `kit-ilias-web`

### Changed
- Cookies are now stored in a text-based format

### Fixed
- Date parsing now also works correctly in non-group exercises

## 3.0.0 - 2021-05-31

### Added
- Proper config files
- Concurrent crawling
- Crawl external ILIAS links
- Crawl uploaded exercise solutions
- Explain what PFERD is doing and why (`--explain`)
- More control over output (`--status`, `--report`)
- Debug transform rules with `--debug-transforms`
- Print report after exiting via Ctrl+C
- Store crawler reports in `.report` JSON file
- Extensive config file documentation (`CONFIG.md`)
- Documentation for developers (`DEV.md`)
- This changelog

### Changed
- Rewrote almost everything
- Better error messages
- Redesigned CLI
- Redesigned transform rules
- ILIAS crawling logic (paths may be different)
- Better support for weird paths on Windows
- Set user agent (`PFERD/<version>`)

### Removed
- Backwards compatibility with 2.x
- Python files as config files
- Some types of crawlers
