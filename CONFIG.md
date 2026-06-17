# Config file format

A config file consists of sections. A section begins with a `[section]` header,
which is followed by a list of `key = value` pairs. Comments must be on their
own line and start with `#`. Multiline values must be indented beyond their key.
Boolean values can be `yes` or `no`. For more details and some examples on the
format, see the [configparser documentation][cp-file]
([interpolation][cp-interp] is disabled).

[cp-file]: <https://docs.python.org/3/library/configparser.html#supported-ini-file-structure> "Supported INI File Structure"
[cp-interp]: <https://docs.python.org/3/library/configparser.html#interpolation-of-values> "Interpolation of values"

## The `DEFAULT` section

This section contains global configuration values. It can also be used to set
default values for the other sections.

- `working_dir`: The directory PFERD operates in. Set to an absolute path to
  make PFERD operate the same regardless of where it is executed from. All other
  paths in the config file are interpreted relative to this path. If this path
  is relative, it is interpreted relative to the script's working dir. `~` is
  expanded to the current user's home directory. (Default: `.`)
- `explain`: Whether PFERD should log and explain its actions and decisions in
  detail. (Default: `no`)
- `status`: Whether PFERD should print status updates (like `Crawled ...`,
  `Added ...`) while running a crawler. (Default: `yes`)
- `report`: Whether PFERD should print a report of added, changed and deleted
   local files for all crawlers before exiting. (Default: `yes`)
- `show_not_deleted`: Whether PFERD should print messages in status and report
   when a local-only file wasn't deleted. Combines nicely with the
   `no-delete-prompt-override` conflict resolution strategy.
- `share_cookies`: Whether crawlers should share cookies where applicable. For
  example, some crawlers share cookies if they crawl the same website using the
  same account. (Default: `yes`)

## The `crawl:*` sections

Sections whose names start with `crawl:` are used to configure crawlers. The
rest of the section name specifies the name of the crawler.

A crawler synchronizes a remote resource to a local directory. There are
different types of crawlers for different kinds of resources, e.g. ILIAS
courses or lecture websites.

Each crawl section represents an instance of a specific type of crawler. The
`type` option is used to specify the crawler type. The crawler's name is usually
used as the output directory. New crawlers can be created simply by adding a new
crawl section to the config file.

Depending on a crawler's type, it may have different options. For more details,
see the type's [documentation](#crawler-types) below. The following options are
common to all crawlers:

- `type`: The available types are specified in [this section](#crawler-types).
- `skip`: Whether the crawler should be skipped during normal execution. The
  crawler can still be executed manually using the `--crawler` or `-C` flags.
  (Default: `no`)
- `output_dir`: The directory the crawler synchronizes files to. A crawler will
  never place any files outside this directory. (Default: the crawler's name)
- `redownload`: When to download a file that is already present locally.
  (Default: `never-smart`)
    - `never`: If a file is present locally, it is not downloaded again.
    - `never-smart`: Like `never`, but PFERD tries to detect if an already
      downloaded files has changed via some (unreliable) heuristics.
    - `always`: All files are always downloaded, regardless of whether they are
      already present locally.
    - `always-smart`: Like `always`, but PFERD tries to avoid unnecessary
      downloads via some (unreliable) heuristics.
- `on_conflict`: What to do when the local and remote versions of a file or
  directory differ, including when a file is replaced by a directory or a
  directory by a file. (Default: `prompt`)
    - `prompt`: Always ask the user before overwriting or deleting local files
      and directories.
    - `local-first`: Always keep the local file or directory. Equivalent to
      using `prompt` and always choosing "no". Implies that `redownload` is set
      to `never`.
    - `remote-first`: Always keep the remote file or directory. Equivalent to
      using `prompt` and always choosing "yes".
    - `no-delete`: Never delete local files, but overwrite local files if the
      remote file is different.
    - `no-delete-prompt-overwrite`: Never delete local files, but prompt to
      overwrite local files if the remote file is different. Combines nicely
      with the `show_not_deleted` option.
- `transform`: Rules for renaming and excluding certain files and directories.
  For more details, see [this section](#transformation-rules). (Default: empty)
- `tasks`: The maximum number of concurrent tasks (such as crawling or
  downloading). (Default: `1`)
- `downloads`: How many of those tasks can be download tasks at the same time.
  Must not be greater than `tasks`. (Default: Same as `tasks`)
- `task_delay`: Time (in seconds) that the crawler should wait between
  subsequent tasks. Can be used as a sort of rate limit to avoid unnecessary
  load for the crawl target. (Default: `0.0`)
- `windows_paths`: Whether PFERD should find alternative names for paths that
  are invalid on Windows. (Default: `yes` on Windows, `no` otherwise)

Some crawlers may also require credentials for authentication. To configure how
the crawler obtains its credentials, the `auth` option is used. It is set to the
full name of an auth section (including the `auth:` prefix).

Here is a simple example:

```ini
[auth:example]
type = simple
username = foo
password = bar

[crawl:something]
type = some-complex-crawler
auth = auth:example
on_conflict = no-delete
tasks = 3
```

## The `auth:*` sections

Sections whose names start with `auth:` are used to configure authenticators. An
authenticator provides a username and a password to one or more crawlers.

Authenticators work similar to crawlers: A section represents an authenticator
instance whose name is the rest of the section name. The type is specified by
the `type` option.

Depending on an authenticator's type, it may have different options. For more
details, see the type's [documentation](#authenticator-types) below. The only
option common to all authenticators is `type`:

- `type`: The types are specified in [this section](#authenticator-types).

## Crawler types

### The `local` crawler

This crawler crawls a local directory. It is really simple and mostly useful for
testing different setups. The various delay options are meant to make the
crawler simulate a slower, network-based crawler.

- `target`: Path to the local directory to crawl. (Required)
- `crawl_delay`: Artificial delay (in seconds) to simulate for crawl requests.
  (Default: `0.0`)
- `download_delay`: Artificial delay (in seconds) to simulate for download
  requests. (Default: `0.0`)
- `download_speed`: Download speed (in bytes per second) to simulate. (Optional)

### The `kit-ipd` crawler

This crawler crawls a KIT-IPD page by url. The root page can be crawled from
outside the KIT network so you will be informed about any new/deleted files,
but downloading files requires you to be within. Adding a short delay between
requests is likely a good idea.

- `target`: URL to a KIT-IPD page
- `link_regex`: A regex that is matched against the `href` part of links. If it
  matches, the given link is downloaded as a file. This is used to extract
  files from KIT-IPD pages. (Default: `^.*?[^/]+\.(pdf|zip|c|cpp|java)$`)
- `auth`: Name of auth section to use for basic authentication. (Optional)

### The `ilias-web` crawler

This crawler crawls a generic ILIAS instance.

Inspired by [this ILIAS downloader][ilias-dl], the following configurations should work
out of the box for the corresponding universities:

[ilias-dl]: https://github.com/V3lop5/ilias-downloader/blob/main/configs "ilias-downloader configs"

| University      | `base_url`                              | `login_type` | `client_id`   |
|-----------------|-----------------------------------------|--------------|---------------|
| FH Aachen       | https://www.ili.fh-aachen.de            | local        | elearning     |
| HHU Düsseldorf  | https://ilias.hhu.de                    | local        | UniRZ         |
| Uni Köln        | https://www.ilias.uni-koeln.de/ilias    | local        | uk            |
| Uni Konstanz    | https://ilias.uni-konstanz.de           | local        | ILIASKONSTANZ |
| Uni Stuttgart   | https://ilias3.uni-stuttgart.de         | local        | Uni_Stuttgart |
| Uni Tübingen    | https://ovidius.uni-tuebingen.de/ilias3 | shibboleth   |               |
| KIT ILIAS Pilot | https://pilot.ilias.studium.kit.edu     | shibboleth   | pilot         |
| FAU StudOn      | https://www.studon.fau.de/studon        | simple-saml  | StudOn        |

If your university isn't listed, try navigating to your instance's login page.
Assuming no custom login service is used, the URL will look something like this:

```jinja
{{ base_url }}/login.php?client_id={{ client_id }}&cmd=force_login&lang=
```

If the values work, feel free to submit a PR and add them to the table above.

- `base_url`: The URL where the ILIAS instance is located. (Required)
- `login_type`: How you authenticate. (Required)
    - `local`: Use `client_id` for authentication.
    - `shibboleth`: Use shibboleth for authentication.
    - `simple-saml`: Use SimpleSAML based authentication.
- `client_id`: An ID used for authentication if `login_type` is `local`. Is
  ignored if `login_type` is `shibboleth` or `simple-saml`.
- `target`: The ILIAS element to crawl. (Required)
    - `desktop`: Crawl your personal desktop / dashboard
    - `<course id>`: Crawl the course with the given id
    - `<url>`: Crawl a given element by URL (preferably the permanent URL linked
      at the bottom of its ILIAS page).  
      This also supports the "My Courses" overview page to download *all*
      courses. Note that this might produce confusing local directory layouts
      and duplication warnings if you are a member of an ILIAS group. The
      `desktop` target is generally preferable.
- `auth`: Name of auth section to use for login. (Required)
- `tfa_auth`: Name of auth section to use for two-factor authentication. Only
  uses the auth section's password. (Default: Anonymous `tfa` authenticator)
- `links`: How to represent external links. (Default: `fancy`)
    - `ignore`: Don't download links.
    - `plaintext`: A text file containing only the URL.
    - `fancy`: A HTML file looking like the ILIAS link element.
    - `internet-shortcut`: An internet shortcut file (`.url` file).
- `link_redirect_delay`: Time (in seconds) until `fancy` link files will
  redirect to the actual URL. Set to a negative value to disable the automatic
  redirect. (Default: `-1`)
- `videos`: Whether to download videos. (Default: `no`)
- `forums`: Whether to download forum threads. (Default: `no`)
- `http_timeout`: The timeout (in seconds) for all HTTP requests. (Default:
  `20.0`)

### The `kit-ilias-web` crawler

This crawler crawls the KIT ILIAS instance.

ILIAS is not great at handling too many concurrent requests. To avoid
unnecessary load, please limit `tasks` to `1`.

There is a spike in ILIAS usage at the beginning of lectures, so please don't
run PFERD during those times.

If you're automatically running PFERD periodically (e. g. via cron or a systemd
timer), please randomize the start time or at least don't use the full hour. For
systemd timers, this can be accomplished using the `RandomizedDelaySec` option.
Also, please schedule the script to run in periods of low activity. Running the
script once per day should be fine.

- `target`: The ILIAS element to crawl. (Required)
    - `desktop`: Crawl your personal desktop
    - `<course id>`: Crawl the course with the given id
    - `<url>`: Crawl a given element by URL (preferably the permanent URL linked
      at the bottom of its ILIAS page)
- `auth`: Name of auth section to use for login. (Required)
- `tfa_auth`: Name of auth section to use for two-factor authentication. Only
  uses the auth section's password. (Default: Anonymous `tfa` authenticator)
- `links`: How to represent external links. (Default: `fancy`)
    - `ignore`: Don't download links.
    - `plaintext`: A text file containing only the URL.
    - `fancy`: A HTML file looking like the ILIAS link element.
    - `internet-shortcut`: An internet shortcut file (`.url` file).
- `link_redirect_delay`: Time (in seconds) until `fancy` link files will
  redirect to the actual URL. Set to a negative value to disable the automatic
  redirect. (Default: `-1`)
- `videos`: Whether to download videos. (Default: `no`)
- `forums`: Whether to download forum threads. (Default: `no`)
- `http_timeout`: The timeout (in seconds) for all HTTP requests. (Default:
  `20.0`)

## Authenticator types

### The `simple` authenticator

With this authenticator, the username and password can be set directly in the
config file. If the username or password are not specified, the user is prompted
via the terminal.

- `username`: The username. (Optional)
- `password`: The password. (Optional)

### The `credential-file` authenticator

This authenticator reads a username and a password from a credential file.

- `path`: Path to the credential file. (Required)

The credential file has exactly two lines (trailing newline optional). The first
line starts with `username=` and contains the username, the second line starts
with `password=` and contains the password. The username and password may
contain any characters except a line break.

```
username=AzureDiamond
password=hunter2
```

### The `keyring` authenticator

This authenticator uses the system keyring to store passwords. The username can
be set directly in the config file. If the username is not specified, the user
is prompted via the terminal. If the keyring contains no entry or the entry is
incorrect, the user is prompted for a password via the terminal and the password
is stored in the keyring.

- `username`: The username. (Optional)
- `keyring_name`: The service name PFERD uses for storing credentials. (Default:
  `PFERD`)

### The `pass` authenticator

This authenticator queries the [`pass` password manager][pass] for a username
and password. It tries to be mostly compatible with [browserpass][browserpass]
and [passff][passff], so see those links for an overview of the format. If PFERD
fails to load your password, you can use the `--explain` flag to see why.

- `passname`: The name of the password to use (Required)
- `username_prefixes`: A comma-separated list of username line prefixes
  (Default: `login,username,user`)
- `password_prefixes`: A comma-separated list of password line prefixes
  (Default: `password,pass,secret`)

[pass]: <https://www.passwordstore.org/> "Pass: The Standard Unix Password Manager"
[browserpass]: <https://github.com/browserpass/browserpass-extension#organizing-password-store> "Organizing password store"
[passff]: <https://github.com/passff/passff#multi-line-format> "Multi-line format"

### The `tfa` authenticator

This authenticator prompts the user on the console for a two-factor
authentication token. The token is provided as password and it is not cached.
This authenticator does not support usernames.

## Transformation rules

Transformation rules are rules for renaming and excluding files and directories.
They are specified line-by-line in a crawler's `transform` option. When a
crawler needs to apply a rule to a path, it goes through this list top-to-bottom
and applies the first matching rule.

To see this process in action, you can use the `--debug-transforms` or flag or
the `--explain` flag.

Each rule has the format `SOURCE ARROW TARGET` (e. g. `foo/bar --> foo/baz`).
The arrow specifies how the source and target are interpreted. The different
kinds of arrows are documented below.

`SOURCE` and `TARGET` are either a bunch of characters without spaces (e. g.
`foo/bar`) or string literals (e. g, `"foo/b a r"`). The former syntax has no
concept of escaping characters, so the backslash is just another character. The
string literals however support Python's escape syntax (e. g.
`"foo\\bar\tbaz"`). This also means that in string literals, backslashes must be
escaped.

`TARGET` can additionally be a single exclamation mark `!` (*not* `"!"`). When a
rule with a `!` as target matches a path, the corresponding file or directory is
ignored by the crawler instead of renamed.

`TARGET` can also be omitted entirely. When a rule without target matches a
path, the path is returned unmodified. This is useful to prevent rules further
down from matching instead.

Each arrow's behaviour can be modified slightly by changing the arrow's head
from `>` to `>>`. When a rule with a `>>` arrow head matches a path, it doesn't
return immediately like a normal arrow. Instead, it replaces the current path
with its output and continues on to the next rule. In effect, this means that
multiple rules can be applied sequentially.

### The `-->` arrow

The `-->` arrow is a basic renaming operation for files and directories. If a
path matches `SOURCE`, it is renamed to `TARGET`.

Example: `foo/bar --> baz`
- Doesn't match `foo`, `a/foo/bar` or `foo/baz`
- Converts `foo/bar` into `baz`
- Converts `foo/bar/wargl` into `baz/wargl`

Example: `foo/bar --> !`
- Doesn't match `foo`, `a/foo/bar` or `foo/baz`
- Ignores `foo/bar` and any of its children

### The `-name->` arrow

The `-name->` arrow lets you rename files and directories by their name,
regardless of where they appear in the file tree. Because of this, its `SOURCE`
must not contain multiple path segments, only a single name. This restriction
does not apply to its `TARGET`.

Example: `foo -name-> bar/baz`
- Doesn't match `a/foobar/b` or `x/Foo/y/z`
- Converts `hello/foo` into `hello/bar/baz`
- Converts `foo/world` into `bar/baz/world`
- Converts `a/foo/b/c/foo` into `a/bar/baz/b/c/bar/baz`

Example: `foo -name-> !`
- Doesn't match `a/foobar/b` or `x/Foo/y/z`
- Ignores any path containing a segment `foo`

### The `-exact->` arrow

The `-exact->` arrow requires the path to match `SOURCE` exactly. The examples
below show why this is useful.

Example: `foo/bar -exact-> baz`
- Doesn't match `foo`, `a/foo/bar` or `foo/baz`
- Converts `foo/bar` into `baz`
- Doesn't match `foo/bar/wargl`

Example: `foo/bar -exact-> !`
- Doesn't match `foo`, `a/foo/bar` or `foo/baz`
- Ignores only `foo/bar`, not its children

### The `-re->` arrow

The `-re->` arrow is like the `-->` arrow but with regular expressions. `SOURCE`
is a regular expression and `TARGET` an f-string based template. If a path
matches `SOURCE`, the output path is created using `TARGET` as template.
`SOURCE` is automatically anchored.

`TARGET` uses Python's [format string syntax][6]. The *n*-th capturing group can
be referred to as `{g<n>}` (e.g. `{g3}`). `{g0}` refers to the original path.
If capturing group *n*'s contents are a valid integer, the integer value is
available as `{i<n>}` (e.g. `{i3}`). If capturing group *n*'s contents are a
valid float, the float value is available as `{f<n>}` (e.g. `{f3}`). Named capture
groups (e.g. `(?P<name>)`) are available by their name (e.g. `{name}`). If a
capturing group is not present (e.g. when matching the string `cd` with the
regex `(ab)?cd`), the corresponding variables are not defined.

Python's format string syntax has rich options for formatting its arguments. For
example, to left-pad the capturing group 3 with the digit `0` to width 5, you
can use `{i3:05}`.

PFERD even allows you to write entire expressions inside the curly braces, for
example `{g2.lower()}` or `{g3.replace(' ', '_')}`.

Example: `f(oo+)/be?ar -re-> B{g1.upper()}H/fear`
- Doesn't match `a/foo/bar`, `foo/abc/bar`, `afoo/bar` or `foo/bars`
- Converts `foo/bar` into `BOOH/fear`
- Converts `fooooo/bear` into `BOOOOOH/fear`
- Converts `foo/bar/baz` into `BOOH/fear/baz`

[6]: <https://docs.python.org/3/library/string.html#format-string-syntax> "Format String Syntax"

### The `-name-re->` arrow

The `-name-re>` arrow is like a combination of the `-name->` and `-re->` arrows.

Example: `(.*)\.jpeg -name-re-> {g1}.jpg`
- Doesn't match `foo/bar.png`, `baz.JPEG` or `hello,jpeg`
- Converts `foo/bar.jpeg` into `foo/bar.jpg`
- Converts `foo.jpeg/bar/baz.jpeg` into `foo.jpg/bar/baz.jpg`

Example: `\..+ -name-re-> !`
- Doesn't match `.`, `test`, `a.b`
- Ignores all files and directories starting with `.`.

### The `-exact-re->` arrow

The `-exact-re>` arrow is like a combination of the `-exact->` and `-re->`
arrows.

Example: `f(oo+)/be?ar -exactre-> B{g1.upper()}H/fear`
- Doesn't match `a/foo/bar`, `foo/abc/bar`, `afoo/bar` or `foo/bars`
- Converts `foo/bar` into `BOOH/fear`
- Converts `fooooo/bear` into `BOOOOOH/fear`
- Doesn't match `foo/bar/baz`

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
the `tutorials/` directory and thus not discover that `tutorials/tut02/` exists.

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

### Example: Crawl a Python project

You are crawling a Python project and want to ignore all hidden files (files
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

For this task, the name arrows can be used.

```
\..*        -name-re-> !
__pycache__ -name->    !
.*\.md      -name-re-> !
```

### Example: Clean up names

You want to convert all paths into lowercase and replace spaces with underscores
before applying any rules. This can be achieved using the `>>` arrow heads.

```
(.*) -re->> "{g1.lower().replace(' ', '_')}"

<other rules go here>
```
