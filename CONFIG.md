# Config file format

A config file consists of sections. A section begins with a `[section]` header,
which is followed by a list of `key = value` or `key: value` pairs. Comments
must be on their own line and start with `#` or `;`. Multiline values must be
indented beyond their key. For more details and some examples on the format, see
the [configparser documentation][1] ([basic interpolation][2] is enabled).

[1]: <https://docs.python.org/3/library/configparser.html#supported-ini-file-structure> "Supported INI File Structure"
[2]: <https://docs.python.org/3/library/configparser.html#configparser.BasicInterpolation> "BasicInterpolation"

## The `DEFAULT` section

This section contains global configuration values. It can also be used to set
default values for the other sections.

- `working_dir`: The directory PFERD operates in. Set to an absolute path to
  make PFERD operate the same regardless of where it is executed. All other
  paths in the config file are interpreted relative to this path. If this path
  is relative, it is interpreted relative to the script's working dir. `~` is
  expanded to the current user's home directory. (Default: `.`)

## The `crawl:*` sections

Sections whose names start with `crawl:` are used to configure crawlers. The
rest of the section name specifies the name of the crawler.

A crawler synchronizes a remote resource to a local directory. There are
different types of crawlers for different kinds of resources, e. g. ILIAS
courses or lecture websites.

Each crawl section represents an instance of a specific type of crawler. The
`type` option is used to specify the crawler type. The crawler's name is usually
used as the name for the output directory. New crawlers can be created simply by
adding a new crawl section to the config file.

Depending on a crawler's type, it may have different options. For more details,
see the type's documentation below. The following options are common to all
crawlers:

- `type`: The types are specified in [this section](#crawler-types).
- `output_dir`: The directory the crawler synchronizes files to. A crawler will
  never place any files outside of this directory. (Default: the crawler's name)
- `redownload`: When to download again a file that is already present locally.
  (Default: `never-smart`)
    - `never`: If a file is present locally, it is not downloaded again.
    - `never-smart`: Like `never`, but PFERD tries to detect if an already
      downloaded files has changed via some (unreliable) heuristics.
    - `always`: All files are always downloaded, regardless of whether they are
      already present locally.
    - `always-smart`: Like `always`, but PFERD tries to avoid unnecessary
      downloads via some (unreliable) heuristics.
- `on_conflict`: What to do when the local and remote versions of a file or
  directory differ. Includes the cases where a file is replaced by a directory
  or a directory by a file. (Default: `prompt`)
    - `prompt`: Always ask the user before overwriting or deleting local files
      and directories.
    - `local-first`: Always keep the local file or directory. Equivalent to
      using `prompt` and always choosing "no". Implies that `redownload` is set
      to `never`.
    - `remote-first`: Always keep the remote file or directory. Equivalent to
      using `prompt` and always choosing "yes".
    - `no-delete`: Never delete local files, but overwrite local files if the
      remote file is different.
- `transform`: Rules for renaming and excluding certain files and directories.
  For more details, see [this section](#transformation-rules). (Default: empty)
- `max_concurrent_tasks`: The maximum number of concurrent tasks (such as
  crawling or downloading). (Default: 1)
- `max_concurrent_downloads`: How many of those tasks can be download tasks at
  the same time. Must not be greater than `max_concurrent_tasks`. When not set,
  this is the same as `max_concurrent_tasks`. (Optional)
- `delay_between_tasks`: Time (in seconds) that the crawler should wait between
  subsequent tasks. Can be used as a sort of rate limit to avoid unnecessary
  load for the crawl target. (Default: 0.0)

Some crawlers may also require credentials for authentication. To configure how
the crawler obtains its credentials, the `auth` option is used. It is set to the
full name of an auth section (including the `auth:` prefix).

Here is a simple example:

```
[auth:example]
type = simple
username = foo
password = bar

[crawl:something]
type = some-complex-crawler
auth = auth:example
```

## The `auth:*` sections

Sections whose names start with `auth:` are used to configure authenticators. An
authenticator provides a username and a password to one or more crawlers.

Authenticators work similar to crawlers: A section represents an authenticator
instance, whose name is the rest of the section name. The type is specified by
the `type` option.

Depending on an authenticator's type, it may have different options. For more
details, see the type's documentation below. The only option common to all
authenticators is `type`:

- `type`: The types are specified in [this section](#authenticator-types).

## Crawler types

### The `local` crawler

This crawler crawls a local directory. It is really simple and mostly useful for
testing different setups. The various delay options are meant to make the
crawler simulate a slower, network-based crawler.

- `target`: Path to the local directory to crawl. (Required)
- `crawl_delay`: Maximum artificial delay (in seconds) to simulate for crawl
  requests. (Default: 0.0)
- `download_delay`: Maximum artificial delay (in seconds) to simulate for
  download requests. (Default: 0.0)
- `download_speed`: Download speed (in bytes per second) to simulate. (Optional)

## Authenticator types

### The `simple` authenticator

With this authenticator, the username and password can be set directly in the
config file. If the username or password are not specified, the user is prompted
via the terminal.

- `username`: The username. (Optional)
- `password`: The password. (Optional)

### The `tfa` authenticator

This authenticator prompts the user on the console for a two-factor
authentication token. The token is provided as password and it is not cached.
This authenticator does not support usernames.

## Transformation rules

Transformation rules are rules for renaming and excluding files and directories.
They are specified line-by-line in a crawler's `transform` option. When a
crawler needs to apply a rule to a path, it goes through this list top-to-bottom
and choose the first matching rule.

Each line has the format `SOURCE ARROW TARGET` where `TARGET` is optional.
`SOURCE` is either a normal path without spaces (e. g. `foo/bar`), or a string
literal delimited by `"` or `'` (e. g. `"foo\" bar/baz"`). Python's string
escape syntax is supported. Trailing slashes are ignored. `TARGET` can be
formatted like `SOURCE`, but it can also be a single exclamation mark without
quotes (`!`). `ARROW` is one of `-->`, `-exact->`, `-name->`, `-re->` and
`-name-re->`

If a rule's target is `!`, this means that when the rule matches on a path, the
corresponding file or directory is ignored. If a rule's target is missing, the
path is matched but not modified.

### The `-->` arrow

The `-->` arrow is a basic renaming operation. If a path begins with `SOURCE`,
that part of the path is replaced with `TARGET`. This means that the rule
`foo/bar --> baz` would convert `foo/bar` into `baz`, but also `foo/bar/xyz`
into `baz/xyz`. The rule `foo --> !` would ignore a directory named `foo` as
well as all its contents.

### The `-name->` arrow

The `-name->` arrow works similar to the `-->` arrow, but pretends it is in the
same directory as the file or directory it is applied to. For example, the rule
`bar -name-> baz` would convert `foo/bar` into `foo/baz` and `foo/bar/xyz` into
`foo/baz/xyz`. The rule `foo --> !` would ignore all files and directories named
`foo` as well as their contents.

### The `-exact->` arrow

The `-exact->` arrow requires the path to match `SOURCE` exactly. This means
that the rule `foo/bar -exact-> baz` would still convert `foo/bar` into `baz`,
but `foo/bar/xyz` would be unaffected. Also, `foo -exact-> !` would only ignore
`foo`, but not its contents (if it has any). The examples below show why this is
useful.

### The `-name-exact->` arrow

The `-name-exact->` arrow works similar to the `-exact->` arrow, but pretends it
is in the same directory as the file or directory it is applied to. For example,
the rule `bar -name-exact-> baz` would convert `foo/bar` into `foo/baz` but
`foo/bar/xyz` would be unaffected. The rule `foo --> !` would ignore only ignore
files and directories named `foo`, but not their contents.

### The `-re->` arrow

The `-re->` arrow uses regular expressions. `SOURCE` is a regular expression
that must match the entire path. If this is the case, then the capturing groups
are available in `TARGET` for formatting.

`TARGET` uses Python's [format string syntax][3]. The *n*-th capturing group can
be referred to as `{g<n>}` (e. g. `{g3}`). `{g0}` refers to the original path.
If capturing group *n*'s contents are a valid integer, the integer value is
available as `{i<n>}` (e. g. `{i3}`). If capturing group *n*'s contents are a
valid float, the float value is available as `{f<n>}` (e. g. `{f3}`).

Python's format string syntax has rich options for formatting its arguments. For
example, to left-pad the capturing group 3 with the digit `0` to width 5, you
can use `{i3:05}`.

PFERD even allows you to write entire expressions inside the curly braces, for
example `{g2.lower()}` or `{g3.replace(' ', '_')}`.

[3]: <https://docs.python.org/3/library/string.html#format-string-syntax> "Format String Syntax"

### The `-name-re->` arrow

The `-name-re>` arrow works similar to the `-re->` arrow, but pretends it is in
the same directory as the file or directory it is applied to.

### Example: Tutorials

You have an ILIAS course with lots of tutorials, but are only interested in a
single one.

```
tutorials/
  |- tut_01/
  |- tut_02/
  |- tut_03/
  ...
```

You can use a mix of normal and exact arrows to get rid of the other ones and
move the `tutorials/tut_02/` folder to `my_tut/`:

```
tutorials/tut_02 --> my_tut
tutorials -exact->
tutorials --> !
```

The second rule is required for many crawlers since they use the rules to decide
which directories to crawl. If it was missing when the crawler looks at
`tutorials/`, the third rule would match. This means the crawler would not crawl
the `tutorials/` directory and thus not discover that `tutorials/tut02/`
existed.

Since the second rule is only relevant for crawling, the `TARGET` is left out.

### Example: Lecture slides

You have a course with slides like `Lecture 3: Linear functions.PDF` and you
would like to rename them to `03_linear_functions.pdf`.

```
Lectures/
  |- Lecture 1: Introduction.PDF
  |- Lecture 2: Vectors and matrices.PDF
  |- Lecture 3: Linear functions.PDF
  ...
```

To do this, you can use the most powerful of arrows: The regex arrow.

```
"Lectures/Lecture (\\d+): (.*)\\.PDF" -re-> "Lectures/{i1:02}_{g2.lower().replace(' ', '_')}.pdf"
```

Note the escaped backslashes on the `SOURCE` side.

### Example: Crawl a python project

You are crawling a python project and want to ignore all hidden files (files
whose name starts with a `.`), all `__pycache__` directories and all markdown
files (for some weird reason).

```
.gitignore
.mypy_cache/
.venv/
CONFIG.md
PFERD/
  |- __init__.py
  |- __main__.py
  |- __pycache__/
  |- authenticator.py
  |- config.py
  ...
README.md
...
```

For this task, the name arrows can be used. They are variants of the normal
arrows that only look at the file name instead of the entire path.

```
\..*        -name-re-> !
__pycache__ -name->    !
.*\.md      -name-re-> !
```
