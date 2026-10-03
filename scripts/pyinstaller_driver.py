"""Run PyInstaller when a Conda install carries obsolete stdlib metadata.

Some Conda environments have a `pathlib` distribution for old packages even
though Python imports its standard-library pathlib. PyInstaller checks the
distribution metadata and aborts before inspecting the app. Suppress that one
metadata false positive only after checking the imported module is stdlib.
"""
import importlib.metadata as metadata
import pathlib
import sys

if "site-packages" not in str(pathlib.__file__).lower():
    original = metadata.distribution

    def distribution(name):
        if name == "pathlib":
            raise metadata.PackageNotFoundError(name)
        return original(name)

    metadata.distribution = distribution

from PyInstaller.__main__ import run

run(sys.argv[1:])
