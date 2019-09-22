# PFERD

**P**rogramm zum **F**lotten, **E**infachen **R**unterladen von **D**ateien

## Installation

Ensure that you have at least Python 3.7 installed (3.6 might also work, didn't
test it though).

To install PFERD or update your installation to the latest version, run this
wherever you want to install/have installed PFERD:
```
$ pip install git+https://github.com/Garmelon/PFERD@v1.1.8
```

The use of [venv](https://docs.python.org/3/library/venv.html) is recommended.

## Example setup

In this example, `python3` refers to at least Python 3.7.

A full example setup and initial use could look like:
```
$ mkdir Vorlesungen
$ cd Vorlesungen
$ python3 -m venv .
$ . bin/activate
$ pip install git+https://github.com/Garmelon/PFERD@v1.1.8
$ curl -O https://raw.githubusercontent.com/Garmelon/PFERD/master/example_config.py
$ python3 example_config.py
$ deactivate
```

Subsequent runs of the program might look like:
```
$ cd Vorlesungen
$ . bin/activate
$ python3 example_config.py
$ deactivate
```
