"""Install only the official, checksum-pinned Linux APK verification files."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
import zipfile

VERSION = "36.0.0"
URL = "https://dl.google.com/android/repository/build-tools_r36_linux.zip"
SIZE = 63737259
# Verified against the official repository2-3.xml SHA-1 and downloaded SHA-256.
SHA256 = "5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b"
FILES = ("aapt2", "lib/apksigner.jar", "lib64/libc++.so", "NOTICE.txt", "source.properties")


def install(archive: Path, destination: Path) -> None:
    if archive.stat().st_size != SIZE:
        raise ValueError("android_archive_size_mismatch")
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != SHA256:
        raise ValueError("android_archive_sha256_mismatch")
    if destination.exists():
        raise ValueError("android_destination_already_exists")
    with zipfile.ZipFile(archive) as bundle:
        # Select known paths, never extract arbitrary archive names or symlinks.
        entries = [(name, bundle.getinfo("android-16/" + name)) for name in FILES]
        if any(info.file_size > 64 * 1024 * 1024 for _, info in entries):
            raise ValueError("android_member_too_large")
        for name, info in entries:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if name == "aapt2" else 0o644)
    (destination / "archive.sha256").write_text(SHA256 + "  build-tools_r36_linux.zip\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.archive:
        install(args.archive, args.destination)
    else:
        with tempfile.TemporaryDirectory(prefix="android-verifier-") as temporary:
            archive = Path(temporary) / "sdk.zip"
            with urlopen(URL, timeout=60) as response, archive.open("xb") as output:
                remaining = SIZE + 1
                while remaining:
                    block = response.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    output.write(block)
                    remaining -= len(block)
            install(archive, args.destination)
    print("Android APK verifier installed: " + VERSION + "; sha256=" + SHA256)


if __name__ == "__main__":
    main()
