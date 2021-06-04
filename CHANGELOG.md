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

### Added
- `skip` option for crawlers

### Changed
- Use `/` instead of `\` as path separator for (regex) rules on Windows

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
