# PFERD

**P**rogramm zum **F**lotten, **E**infachen **R**unterladen von **D**ateien

## Installation

Ensure that you have at least Python 3.8 installed.

To install PFERD or update your installation to the latest version, run this
wherever you want to install/have installed PFERD:
```
$ pip install git+https://github.com/Garmelon/PFERD@v2.1.2
```

The use of [venv](https://docs.python.org/3/library/venv.html) is recommended.

### Upgrading from 2.0.0 to 2.1.0+

The `IliasDirectoryType` type was renamed to `IliasElementType` and is now far
more detailed.  
The new values are: REGULAR_FOLDER, VIDEO_FOLDER,
EXERCISE_FOLDER, REGULAR_FILE, VIDEO_FILE, FORUM, EXTERNAL_LINK.  
Forums and external links are skipped automatically if you use the `kit_ilias` helper.

## Example setup

In this example, `python3` refers to at least Python 3.8.

If you just want to get started and crawl *your entire ILIAS Desktop* instead
of a given set of courses, please replace `example_config.py` with
`example_config_personal_desktop.py` in all of the instructions below (`curl` call and
`python3` run command).

A full example setup and initial use could look like:
```
$ mkdir Vorlesungen
$ cd Vorlesungen
$ python3 -m venv .venv
$ .venv/bin/activate
$ pip install git+https://github.com/Garmelon/PFERD@v2.1.2
$ curl -O https://raw.githubusercontent.com/Garmelon/PFERD/v2.1.2/example_config.py
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

## Usage

A PFERD config is a normal python file that starts multiple *synchronizers*
which do all the heavy lifting. While you can create and wire them up manually,
you are encouraged to use the helper methods provided in `PFERD.Pferd`.

The synchronizers take some input arguments specific to their service and a
*transformer*. The transformer receives the computed path of an element in
ILIAS and can return either an output path (so you can rename files or move
them around as you wish) or `None` if you do not want to save the given file.

Additionally the ILIAS synchronizer allows you to define a *crawl filter*. This
filter also receives the computed path as the input, but is only called or
*directoties*. If you return `True`, the directory will be crawled and
searched. If you return `False` the directory will be ignored and nothing in it
will be passed to the transformer.

In order to help you with writing your own transformers and filters, PFERD
ships with a few powerful building blocks:

| Method | Description |
|--------|-------------|
| `glob`   | Returns a transform that returns `None` if the glob does not match and the unmodified path otherwise. |
| `predicate`   | Returns a transform that returns `None` if the predicate does not match the path and the unmodified path otherwise. |
| `move_dir(source, target)`   | Returns a transform that moves all files from the `source` to the `target` dir. |
| `move(source, target)`   | Returns a transform that moves the `source` file to `target`. |
| `rename(old, new)`   | Renames a single file. |
| `re_move(regex, sub)`   | Moves all files matching the given regular expression. The different captured groups are available under their index and can be used together with normal python format methods: `re_move(r"Blatt (\d+)\.pdf", "Blätter/Blatt_{1:0>2}.pdf"),`. |
| `re_rename(old, new)`   | Same as `re_move` but operates on the path *names* instead of the full path. |

And PFERD also offers a few combinator functions:

* **`keep`**  
  `keep` just returns the input path unchanged. It can be very useful as the
  last argument in an `attempt` call, to leave everything not matching a rule
  unchanged.
* **`optionally(transformer)`**  
  Wraps a given transformer and returns its result if it is not `None`.
  Otherwise returns the input path unchanged.
* **`do(transformers)`**  
  `do` accepts a series of transformers and applies them in the given order to
  the result of the previous one. If any transformer returns `None`, do
  short-circuits and also returns `None`. This can be used to perform multiple
  renames in a row:
  ```py
  do(
      # Move them
      move_dir("Vorlesungsmaterial/Vorlesungsvideos/", "Vorlesung/Videos/"),
      # Fix extensions (if they have any)
      optionally(re_rename("(.*).m4v.mp4", "{1}.mp4")),
      # Remove the 'dbs' prefix (if they have any)
      optionally(re_rename("(?i)dbs-(.+)", "{1}")),
  ),
  ```
* **`attempt(transformers)`**  
  `attempt` applies the passed transformers in the given order until it finds
  one that does not return `None`. If it does not find any, it returns `None`.
  This can be used to give a list of possible transformations and it will
  automatically pick the first one that fits:
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

All of these combinators are used in the provided example config, if you want
to see some more true-to-live usages.

### A short, but commented example

```py
def filter_course(path: PurePath) -> bool:
    # Note that glob returns a Transformer
    #  - a function from PurePath -> Optional[PurePath]
    # So we need to apply the result of 'glob' to our input path.
    # We need to crawl the 'Tutorien' folder as it contains the one we want.
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

enable_logging() # needed once before calling a Pferd method
# Create a Pferd instance rooted in the same directory as the script file
# This is not a test run, so files will be downloaded (default, can be omitted)
pferd = Pferd(Path(__file__).parent, test_run=False)

# Use the ilias_kit helper to synchronize an ILIAS course
pferd.ilias_kit(
    # The folder all of the course's content should be placed in
    Path("My cool course"),
    # The course ID (found in the URL when on the course page in ILIAS)
    "course id",
    # A path to a cookie jar. If you synchronize multiple ILIAS courses, setting this
    # to a common value requires you to only login once.
    cookies=Path("ilias_cookies.txt"),
    # A transform to apply to all found paths
    transform=transform_course,
    # A crawl filter limits what paths the cralwer searches
    dir_filter=filter_course,
)
```
