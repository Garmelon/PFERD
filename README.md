# PFERD

**P**rogramm zum **F**lotten, **E**infachen **R**unterladen von **D**ateien

- [Quickstart with `sync_url`](#quickstart-with-sync_url)
- [Installation](#installation)
    - [Upgrading from 2.0.0 to 2.1.0+](#upgrading-from-200-to-210)
- [Example setup](#example-setup)
- [Usage](#usage)
    - [General concepts](#general-concepts)
    - [Constructing transforms](#constructing-transforms)
        - [Transform creators](#transform-creators)
        - [Transform combinators](#transform-combinators)
    - [A short, but commented example](#a-short-but-commented-example)

## Quickstart with `sync_url`

The `sync_url` program allows you to just synchronize a given ILIAS URL (of a
course, a folder, your personal desktop, etc.) without any extra configuration
or setting up. Download the program, open ILIAS, copy the URL from the address
bar and pass it to sync_url.

It bundles everything it needs in one executable and is easy to
use, but doesn't expose all the configuration options and tweaks a full install
does.

1. Download the `sync_url` binary from the [latest release](https://github.com/Garmelon/PFERD/releases/latest).
2. Recognize that you most likely need to enclose the URL in `""` quotes to prevent your shell from interpreting `&` and other symbols
3. Run the binary in your terminal (`./sync_url` or `sync_url.exe` in the CMD) to see the help and use it. I'd recommend using the `--cookies` option.  
  If you are on **Linux/Mac**, you need to *make the file executable* using `chmod +x <file>`.  
  If you are on **Mac**, you need to allow this unverified program to run (see e.g. [here](https://www.switchingtomac.com/tutorials/osx/how-to-run-unverified-apps-on-macos/))

## Installation

Ensure that you have at least Python 3.8 installed.

To install PFERD or update your installation to the latest version, run this
wherever you want to install or have already installed PFERD:
```
$ pip install git+https://github.com/Garmelon/PFERD@v2.4.5
```

The use of [venv] is recommended.

[venv]: https://docs.python.org/3/library/venv.html

### Upgrading from 2.0.0 to 2.1.0+

- The `IliasDirectoryType` type was renamed to `IliasElementType` and is now far more detailed.
  The new values are: `REGULAR_FOLDER`, `VIDEO_FOLDER`, `EXERCISE_FOLDER`, `REGULAR_FILE`, `VIDEO_FILE`, `FORUM`, `EXTERNAL_LINK`.
- Forums and external links are skipped automatically if you use the `kit_ilias` helper.

## Example setup

In this example, `python3` refers to at least Python 3.8.

A full example setup and initial use could look like:
```
$ mkdir Vorlesungen
$ cd Vorlesungen
$ python3 -m venv .venv
$ .venv/bin/activate
$ pip install git+https://github.com/Garmelon/PFERD@v2.4.5
$ curl -O https://raw.githubusercontent.com/Garmelon/PFERD/v2.4.5/example_config.py
$ python3 example_config.py
$ deactivate
```

Subsequent runs of the program might look like:
```
$ cd Vorlesungen
$ .venv/bin/activate
$ python3 example_config.py
$ deactivate
```

If you just want to get started and crawl *your entire ILIAS Desktop* instead
of a given set of courses, please replace `example_config.py` with
`example_config_personal_desktop.py` in all of the instructions below (`curl` call and
`python3` run command).

## Usage

### General concepts

A PFERD config is a normal python file that starts multiple *synchronizers*
which do all the heavy lifting. While you can create and wire them up manually,
you are encouraged to use the helper methods provided in `PFERD.Pferd`.

The synchronizers take some input arguments specific to their service and a
*transform*. The transform receives the computed path of an element in ILIAS and
can return either an output path (so you can rename files or move them around as
you wish) or `None` if you do not want to save the given file.

Additionally the ILIAS synchronizer allows you to define a *crawl filter*. This
filter also receives the computed path as the input, but is only called for
*directories*. If you return `True`, the directory will be crawled and
searched. If you return `False` the directory will be ignored and nothing in it
will be passed to the transform.

### Constructing transforms

While transforms are just normal python functions, writing them by hand can
quickly become tedious. In order to help you with writing your own transforms
and filters, PFERD defines a few useful transform creators and combinators in
the `PFERD.transform` module:

#### Transform creators

These methods let you create a few basic transform building blocks:

- **`glob(glob)`**  
  Creates a transform that returns the unchanged path if the glob matches the path and `None` otherwise.
  See also [Path.match].  
  Example: `glob("Übung/*.pdf")`
- **`predicate(pred)`**  
  Creates a transform that returns the unchanged path if `pred(path)` returns a truthy value.
  Returns `None` otherwise.  
  Example: `predicate(lambda path: len(path.parts) == 3)`
- **`move_dir(source, target)`**  
  Creates a transform that moves all files from the `source` to the `target` directory.  
  Example: `move_dir("Übung/", "Blätter/")`
- **`move(source, target)`**  
  Creates a transform that moves the `source` file to `target`.  
  Example: `move("Vorlesung/VL02_Automten.pdf", "Vorlesung/VL02_Automaten.pdf")`
- **`rename(source, target)`**  
  Creates a transform that renames all files named `source` to `target`.
  This transform works on the file names, not paths, and thus works no matter where the file is located.  
  Example: `rename("VL02_Automten.pdf", "VL02_Automaten.pdf")`
- **`re_move(regex, target)`**  
  Creates a transform that moves all files matching `regex` to `target`.
  The transform `str.format` on the `target` string with the contents of the capturing groups before returning it.
  The capturing groups can be accessed via their index.
  See also [Match.group].  
  Example: `re_move(r"Übung/Blatt (\d+)\.pdf", "Blätter/Blatt_{1:0>2}.pdf")`
- **`re_rename(regex, target)`**  
  Creates a transform that renames all files matching `regex` to `target`.
  This transform works on the file names, not paths, and thus works no matter where the file is located.  
  Example: `re_rename(r"VL(\d+)(.*)\.pdf", "Vorlesung_Nr_{1}__{2}.pdf")`

All movement or rename transforms above return `None` if a file doesn't match
their movement or renaming criteria. This enables them to be used as building
blocks to build up more complex transforms.

In addition, `PFERD.transform` also defines the `keep` transform which returns its input path unchanged.
This behaviour can be very useful when creating more complex transforms.
See below for example usage.

[Path.match]: https://docs.python.org/3/library/pathlib.html#pathlib.Path.match
[Match.group]: https://docs.python.org/3/library/re.html#re.Match.group

#### Transform combinators

These methods let you combine transforms into more complex transforms:

- **`optionally(transform)`**  
  Wraps a given transform and returns its result if it is not `None`.
  Otherwise returns the input path unchanged.
  See below for example usage.
* **`do(transforms)`**  
  Accepts a series of transforms and applies them in the given order to the result of the previous one.
  If any transform returns `None`, `do` short-circuits and also returns `None`.
  This can be used to perform multiple renames in a row:
  ```py
  do(
      # Move them
      move_dir("Vorlesungsmaterial/Vorlesungsvideos/", "Vorlesung/Videos/"),
      # Fix extensions (if they have any)
      optionally(re_rename("(.*).m4v.mp4", "{1}.mp4")),
      # Remove the 'dbs' prefix (if they have any)
      optionally(re_rename("(?i)dbs-(.+)", "{1}")),
  )
  ```
- **`attempt(transforms)`**  
  Applies the passed transforms in the given order until it finds one that does not return `None`.
  If it does not find any, it returns `None`.
  This can be used to give a list of possible transformations and automatically pick the first one that fits:
  ```py
  attempt(
      # Move all videos. If a video is passed in, this `re_move` will succeed
      # and attempt short-circuits with the result.
      re_move(r"Vorlesungsmaterial/.*/(.+?)\.mp4", "Vorlesung/Videos/{1}.mp4"),
      # Move the whole folder to a nicer name - now without any mp4!
      move_dir("Vorlesungsmaterial/", "Vorlesung/"),
      # If we got another file, keep it.
      keep,
  )
  ```

All of these combinators are used in the provided example configs, if you want
to see some more real-life usages.

### A short, but commented example

```py
from pathlib import Path, PurePath
from PFERD import Pferd
from PFERD.ilias import IliasElementType
from PFERD.transform import *

# This filter will later be used by the ILIAS crawler to decide whether it
# should crawl a directory (or directory-like structure).
def filter_course(path: PurePath, type: IliasElementType) -> bool:
    # Note that glob returns a Transform, which is a function from PurePath ->
    # Optional[PurePath]. Because of this, we need to apply the result of
    # 'glob' to our input path. The returned value will be truthy (a Path) if
    # the transform succeeded, or `None` if it failed.

    # We need to crawl the 'Tutorien' folder as it contains one that we want.
    if glob("Tutorien/")(path):
        return True
    # If we found 'Tutorium 10', keep it!
    if glob("Tutorien/Tutorium 10")(path):
        return True
    # Discard all other folders inside 'Tutorien'
    if glob("Tutorien/*")(path):
        return False

    # All other dirs (including subdirs of 'Tutorium 10') should be searched :)
    return True


# This transform will later be used to rename a few files. It can also be used
# to ignore some files.
transform_course = attempt(
    # We don't care about the other tuts and would instead prefer a cleaner
    # directory structure.
    move_dir("Tutorien/Tutorium 10/", "Tutorium/"),
    # We don't want to modify any other files, so we're going to keep them
    # exactly as they are.
    keep
)

# Enable and configure the text output. Needs to be called before calling any
# other PFERD methods.
Pferd.enable_logging()
# Create a Pferd instance rooted in the same directory as the script file. This
# is not a test run, so files will be downloaded (default, can be omitted).
pferd = Pferd(Path(__file__).parent, test_run=False)

# Use the ilias_kit helper to synchronize an ILIAS course
pferd.ilias_kit(
    # The directory that all of the downloaded files should be placed in
    "My_cool_course/",
    # The course ID (found in the URL when on the course page in ILIAS)
    "course id",
    # A path to a cookie jar. If you synchronize multiple ILIAS courses,
    # setting this to a common value requires you to only log in once.
    cookies=Path("ilias_cookies.txt"),
    # A transform can rename, move or filter out certain files
    transform=transform_course,
    # A crawl filter limits what paths the cralwer searches
    dir_filter=filter_course,
)
```
