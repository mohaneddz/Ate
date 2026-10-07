"""Build a portable Linux source-wheel archive for the current release."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
RELEASE = ROOT / "release"
ARCHIVE = RELEASE / f"Ate-{VERSION}-linux.tar.gz"


def main() -> None:
    RELEASE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        wheels = Path(temporary)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels),
                        str(ROOT)], check=True)
        wheel = wheels / f"ate_cli-{VERSION}-py3-none-any.whl"
        if not wheel.is_file():
            raise RuntimeError(f"Expected pure Python wheel was not built: {wheel.name}")
        files = {
            "install.sh": ROOT / "scripts" / "install-linux.sh",
            "uninstall.sh": ROOT / "scripts" / "uninstall-linux.sh",
            "README.md": ROOT / "README.md",
            wheel.name: wheel,
        }
        with tarfile.open(ARCHIVE, "w:gz") as archive:
            for name, path in files.items():
                info = archive.gettarinfo(str(path), arcname=f"Ate-{VERSION}-linux/{name}")
                info.mode = 0o755 if name.endswith(".sh") else 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    (RELEASE / f"{ARCHIVE.name}.sha256").write_text(f"{digest}  {ARCHIVE.name}\n", encoding="ascii")
    print(f"Package: {ARCHIVE}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
