# PFERD

**P**rogramm zum **F**lotten, **E**infachen **R**unterladen von **D**ateien

Other resources:

- [Config file format](CONFIG.md)
- [Changelog](CHANGELOG.md)
- [Development Guide](DEV.md)

## Installation

### Direct download

Binaries for Linux, Windows and Mac can be downloaded directly from the
[latest release](https://github.com/Garmelon/PFERD/releases/latest).

### With pip

Ensure you have at least Python 3.9 installed. Run the following command to
install PFERD or upgrade it to the latest version:

```
$ pip install --upgrade git+https://github.com/Garmelon/PFERD@latest
```

The use of [venv](https://docs.python.org/3/library/venv.html) is recommended.

### With package managers

Unofficial packages are available for:
- [AUR](https://aur.archlinux.org/packages/pferd)
- [brew](https://formulae.brew.sh/formula/pferd)
- [conda-forge](https://github.com/conda-forge/pferd-feedstock)
- [nixpkgs](https://github.com/NixOS/nixpkgs/blob/master/pkgs/tools/misc/pferd/default.nix)
- [PyPi](https://pypi.org/project/pferd)

See also PFERD's [repology page](https://repology.org/project/pferd/versions).

## Basic usage

PFERD can be run directly from the command line with no config file. Run `pferd
-h` to get an overview of available commands and options. Run `pferd <command>
-h` to see which options a command has.

For example, you can download your personal desktop from the KIT ILIAS like
this:

```
$ pferd kit-ilias-web desktop <output_directory>
```

Also, you can download most ILIAS pages directly like this:

```
$ pferd kit-ilias-web <url> <output_directory>
```

[You want to use antoher ILIAS instance? Read here!](#other-ilias-instances)

However, the CLI only lets you download a single thing at a time, and the
resulting command can grow long quite quickly. Because of this, PFERD can also
be used with a config file.

To get started, just take a command you've been using and add `--dump-config`
directly after `pferd`, like this:

```
$ pferd --dump-config kit-ilias-web <url> <output_directory>
```

This will make PFERD write its current configuration to its default config file
path. You can then run `pferd` without a command and it will execute the config
file. Alternatively, you can use `--dump-config-to` and specify a path yourself.
Using `--dump-config-to -` will print the configuration to stdout instead of a
file, which is a good way to see what is actually going on when using a CLI
command.

Another good way to see what PFERD is doing is the `--explain` option. When
enabled, PFERD explains in detail what it is doing and why. This can help with
debugging your own config.

If you don't want to run all crawlers from your config file, you can specify the
crawlers you want to run with `--crawler` or `-C`, like this:

```
$ pferd -C crawler1 -C crawler2
```

## Advanced usage

PFERD supports lots of different options. For example, you can configure PFERD
to [use your system's keyring](CONFIG.md#the-keyring-authenticator) instead of
prompting you for your username and password. PFERD also supports
[transformation rules](CONFIG.md#transformation-rules) that let you rename or
exclude certain files.

For more details, see the comprehensive [config format documentation](CONFIG.md).

## Example

This example downloads a few courses from the KIT ILIAS with a common keyring
authenticator. It reorganizes and ignores some files.

```ini
[DEFAULT]
# All paths will be relative to this.
# The crawler output directories will be <working_dir>/Foo and <working_dir>/Bar.
working_dir = ~/stud
# If files vanish from ILIAS the local files are not deleted, allowing us to
# take a look at them before deleting them ourselves.
on_conflict = no-delete

[auth:ilias]
type = keyring
username = foo

[crawl:Foo]
type = kit-ilias-web
auth = auth:ilias
# Crawl a course by its ID (found as `ref_id=ID` in the URL)
target = 1234567

# Plaintext files are easier to read by other tools
links = plaintext

transform =
  # Ignore unneeded folders
  Online-Tests --> !
  Vorlesungswerbung --> !

  # Rename folders
  Lehrbücher --> Vorlesung
  # Note the ">>" arrow head which lets us apply further rules to files moved to "Übung"
  Übungsunterlagen -->> Übung

  # Move exercises to own folder. Rename them to "Blatt-XX.pdf" to make them sort properly
  "Übung/(\d+). Übungsblatt.pdf" -re-> Blätter/Blatt-{i1:02}.pdf
  # Move solutions to own folder. Rename them to "Blatt-XX-Lösung.pdf" to make them sort properly
  "Übung/(\d+). Übungsblatt.*Musterlösung.pdf" -re-> Blätter/Blatt-{i1:02}-Lösung.pdf

  # The course has nested folders with the same name - flatten them
  "Übung/(.+?)/\\1" -re-> Übung/{g1}

[crawl:Bar]
type = kit-ilias-web
auth = auth:ilias
target = 1337420
```

# Other ILIAS instances

PFERD was originally developed for the KIT ILIAS instance, so you might have to adapt some parts of the code for full compatibility with your instance.

To run PFERD against any instance using the integrated ILIAS authentication, simply add the `--base-url` and `--client-id` flags to the CLI command, e.g.

```
$ pferd ilias-web --base-url https://ilias.my-university.example --client-id My_University desktop <output_directory>
```

To use a config file for the given instance, just extend the example above as follows:

```ini
[DEFAULT]
base_url = https://ilias.my-university.example
client_id = My_University

[auth:ilias]
...

[crawl:foo]
...
```

Note that `base_url` and `client_id` can also be specified on a per-crawler level.

## Example configuration

Inspired by [this ILIAS downloader](https://github.com/V3lop5/ilias-downloader/blob/main/configs), the following configurations should work out of the box for the corresponding universities:

| University    | `base_url`                           | `client_id`   |
|---------------|--------------------------------------|---------------|
| FH Aachen     | https://www.ili.fh-aachen.de         | elearning     |
| Uni Koeln     | https://www.ilias.uni-koeln.de/ilias | uk            |
| Uni Konstanz  | https://ilias.uni-konstanz.de        | ILIASKONSTANZ |
| Uni Stuttgart | https://ilias3.uni-stuttgart.de      | Uni_Stuttgart |


### My university isn't listed

No problem, your university might also just work fine. To retrieve the values required for your instance, navigate to the corresponding login page. You should be redirected to

```jinja
{{ base_url }}/login.php?client_id={{ client_id }}&cmd=force_login&lang=
```

From this URL, you can simply extract your required values. Feel free to open a PR to add your configuration to the table above. This will help people find out if their ILIAS instance is supported too.
