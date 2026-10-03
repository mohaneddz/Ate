# Bundled dependencies

The Windows executable bundles Python packages listed in `pyproject.toml` and
the optional `hermes-dec` importer. `hermes-dec` is published under GPL-3.0 and
its source is available at <https://github.com/P1sec/hermes-dec>. PyInstaller is
used to build the executable. The APK/XAPK and any account data are never part
of the release package.

Dependency versions and licenses can be inspected in the release source tree
and the Python package metadata. Users can also install from source instead of
using the executable.
