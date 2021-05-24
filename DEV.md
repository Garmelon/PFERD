# PFERD Development Guide

PFERD is packaged following the [Python Packaging User Guide][ppug] (in
particular [this][ppug-1] and [this][ppug-2] guide).

[ppug]: <https://packaging.python.org/> "Python Packaging User Guide"
[ppug-1]: <https://packaging.python.org/tutorials/packaging-projects/> "Packaging Python Projects"
[ppug-2]: <https://packaging.python.org/guides/distributing-packages-using-setuptools/> "Packaging and distributing projects"

## Setting up a dev environment

The use of [venv][venv] is recommended. To initially set up a development
environment, run these commands in the same directory as this file:

```
$ python -m venv .venv
$ . .venv/bin/activate
$ ./scripts/setup
```

The setup script installs a few required dependencies and tools. It also
installs PFERD via `pip install --editable .`, which means that you can just run
`pferd` as if it was installed normally. Since PFERD was installed with
`--editable`, there is no need to re-run `pip install` when the source code is
changed.

If you get any errors because pip can't update itself, try running
`./scripts/setup --no-pip` instead of `./scripts/setup`.

For more details, see [this part of the Python Tutorial][venv-tut] and
[this section on "development mode"][ppug-dev].

[venv]: <https://docs.python.org/3/library/venv.html> "venv - Creation of virtual environments"
[venv-tut]: <https://docs.python.org/3/tutorial/venv.html> "12. Virtual Environments and Packages"
[ppug-dev]: <https://packaging.python.org/guides/distributing-packages-using-setuptools/#working-in-development-mode> "Working in “development mode”"

## Checking and formatting the code

To run a set of checks against the code, run `./scripts/check` in the repo's
root directory. This script will run a few tools installed by `./scripts/setup`
against the entire project.

To format the code, run `./scripts/format` in the repo's root directory.

Before committing changes, please make sure the checks return no warnings and
the code is formatted.

## Contributing

When submitting a PR that adds, changes or modifies a feature, please ensure
that the corresponding documentation is updated as well. Also, please ensure
that `./scripts/check` returns no warnings and the code has been run through
`./scripts/format`.

In your first PR, please add your name to the `LICENSE` file.

## Releasing a new version

This section describes the steps required to release a new version of PFERD.
Usually, they don't need to performed manually and `scripts/bump-version` can be
used instead.

1. Update the version number in `PFERD/version.py`
2. Update `CHANGELOG.md`
3. Commit changes to `master` with message `Bump version to <version>` (e. g. `Bump version to 3.2.5`)
4. Create annotated tag named `v<version>` (e. g. `v3.2.5`)
    - Copy changes from changelog
    - Remove `#` symbols (which git would interpret as comments)
    - As the first line, add `Version <version> - <date>` (e. g. `Version 3.2.5 - 2021-05-24`)
    - Leave the second line empty
5. Fast-forward `latest` to `master`
6. Push `master`, `latest` and the new tag

Example tag annotation:
```
Version 3.2.5 - 2021-05-24

Added
- Support for concurrent downloads
- Support for proper config files
- This changelog

Changed
- Rewrote almost everything
- Redesigned CLI

Removed
- Backwards compatibility with 2.x
```
