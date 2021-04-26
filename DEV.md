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
$ pip install --editable .
```

After this, you can use PFERD as if it was installed normally. Since PFERD was
installed with `--editable`, there is no need to re-run `pip install` when the
source code is changed.

For more details, see [this part of the Python Tutorial][venv-tut] and
[this section on "development mode"][ppug-dev].

[venv]: <https://docs.python.org/3/library/venv.html> "venv - Creation of virtual environments"
[venv-tut]: <https://docs.python.org/3/tutorial/venv.html> "12. Virtual Environments and Packages"
[ppug-dev]: <https://packaging.python.org/guides/distributing-packages-using-setuptools/#working-in-development-mode> "Working in “development mode”"

## Contributing

When submitting a PR that adds, changes or modifies a feature, please ensure
that the corresponding documentation is updated.

In your first PR, please add your name to the `LICENSE` file.
