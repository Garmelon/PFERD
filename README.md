# PFERD (**P**rogramm **F**ür's **E**infache **R**unterladen von **D**ateien)

## Installation

Ensure that you have at least Python 3.7 installed.

To install PFERD or update your installation to the latest version, run:
```
$ pip install git+https://github.com/Garmelon/PFERD@v0.1.0
```

The use of [venv](https://docs.python.org/3/library/venv.html) is recommended.

A full example setup and initial use could look like:
```
$ mkdir Vorlesungen
$ cd Vorlesungen
$ python3 -m venv .
$ . bin/activate
$ pip install git+https://github.com/Garmelon/PFERD@v0.1.0
$ curl -O https://raw.githubusercontent.com/Garmelon/PFERD/master/example_config.py
$ python example_config.py
```
