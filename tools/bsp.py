#!/usr/bin/env python3
"""
Build and pin the RUI3 framework packages used by this platform.

The upstream RUI3 BSP repositories ship no PlatformIO manifest, so each
upstream release tag is repackaged once: the tag's source tree, a package.json,
and the compatibility patches from bsp_patches.py, as one .tar.gz per MCU
family. The tarballs are published as assets of a "bsp-<upstream tag>" GitHub
release of this repository, and platform.json points at those assets.

  package   build the framework tarballs for an upstream tag into dist/
  pin       point platform.json at the release assets for an upstream tag

Examples:

  python tools/bsp.py package --tag v4.3.0_400
  python tools/bsp.py package --tag v4.3.0_400 --git-root ~/src/rui3
  python tools/bsp.py pin --tag v4.3.0_400 --platform-version 4.3.0

Standard library only, so it runs unchanged on Linux, macOS and Windows.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bsp_patches  # noqa: E402

PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where the repackaged framework tarballs are published. Changing the
# repository name only needs an edit here (or --repo) and a new `pin`.
DEFAULT_RELEASE_REPO = "RAKWireless/platform-rakwireless-rui3"

MCU_FAMILIES = {
    "stm32wle": {
        "package": "framework-rui3-stm32wle",
        "upstream": "RAKWireless/RAK-STM32-RUI",
        "core": "STM32WLE",
        "title": "RAKwireless RUI3 BSP for STM32WLE5 (RAK3172 family)",
        "keywords": ["rui3", "rakwireless", "stm32wle", "rak3172", "lorawan"],
    },
    "nrf52": {
        "package": "framework-rui3-nrf52",
        "upstream": "RAKWireless/RAK-nRF52-RUI",
        "core": "nRF5",
        "title": "RAKwireless RUI3 BSP for nRF52840 (RAK4631 family)",
        "keywords": ["rui3", "rakwireless", "nrf52", "rak4631", "lorawan", "ble"],
    },
    "apollo3": {
        "package": "framework-rui3-apollo3",
        "upstream": "RAKWireless/RAK-APOLLO3-RUI",
        "core": "apollo3",
        "title": "RAKwireless RUI3 BSP for Apollo3 (RAK11720)",
        "keywords": ["rui3", "rakwireless", "apollo3", "rak11720", "lorawan", "ble"],
    },
}

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)_(\d+)$")


def parse_tag(tag):
    """Split an upstream tag such as v4.3.0_400 into (version, build)."""
    m = TAG_RE.match(tag)
    if not m:
        raise SystemExit("error: unexpected upstream tag format %r (expected vX.Y.Z_NNN)" % tag)
    return "%s.%s.%s" % m.group(1, 2, 3), int(m.group(4))


def package_version(tag):
    # The build number goes into semver build metadata: several upstream
    # builds share one X.Y.Z (v4.3.0_394 and v4.3.0_400, for instance).
    version, build = parse_tag(tag)
    return "%s+%d" % (version, build)


def asset_name(family, tag):
    return "%s-%s.tar.gz" % (MCU_FAMILIES[family]["package"], tag)


def release_tag(tag):
    return "bsp-%s" % tag


def asset_url(repo, family, tag):
    return "https://github.com/%s/releases/download/%s/%s" % (
        repo, release_tag(tag), asset_name(family, tag))


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Fetching the upstream tree
# ---------------------------------------------------------------------------

def _safe_extract(tar, dest):
    if hasattr(tarfile, "data_filter"):
        tar.extractall(dest, filter="data")
        return
    dest_real = os.path.realpath(dest)
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(dest, member.name))
        if not (target == dest_real or target.startswith(dest_real + os.sep)):
            raise SystemExit("error: archive member escapes destination: %s" % member.name)
        if member.issym() or member.islnk():
            link = os.path.realpath(os.path.join(os.path.dirname(target), member.linkname))
            if not link.startswith(dest_real + os.sep):
                raise SystemExit("error: archive link escapes destination: %s" % member.name)
    tar.extractall(dest)


def _single_root(path):
    entries = os.listdir(path)
    if len(entries) == 1 and os.path.isdir(os.path.join(path, entries[0])):
        return os.path.join(path, entries[0])
    return path


def fetch_from_github(upstream, tag, workdir):
    url = "https://github.com/%s/archive/refs/tags/%s.tar.gz" % (upstream, tag)
    archive = os.path.join(workdir, "upstream.tar.gz")
    log("  downloading %s" % url)
    with urllib.request.urlopen(url) as resp, open(archive, "wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)
    extract_dir = os.path.join(workdir, "src")
    os.makedirs(extract_dir)
    with tarfile.open(archive, "r:gz") as tar:
        # GitHub archives carry the commit id in the pax global header, which
        # is only parsed once the first member has been read.
        mtime = next((m.mtime for m in tar if m.isfile()), 0)
        commit = tar.pax_headers.get("comment")
    with tarfile.open(archive, "r:gz") as tar:
        _safe_extract(tar, extract_dir)
    os.remove(archive)
    return _single_root(extract_dir), commit, mtime


def fetch_from_git(git_dir, tag, workdir):
    log("  exporting %s from %s" % (tag, git_dir))
    commit = subprocess.run(
        ["git", "-C", git_dir, "rev-parse", "%s^{commit}" % tag],
        check=True, capture_output=True, text=True).stdout.strip()
    mtime = int(subprocess.run(
        ["git", "-C", git_dir, "log", "-1", "--format=%ct", commit],
        check=True, capture_output=True, text=True).stdout.strip())
    archive = os.path.join(workdir, "upstream.tar")
    with open(archive, "wb") as out:
        subprocess.run(["git", "-C", git_dir, "archive", "--format=tar", commit],
                       check=True, stdout=out)
    extract_dir = os.path.join(workdir, "src")
    os.makedirs(extract_dir)
    with tarfile.open(archive, "r:") as tar:
        _safe_extract(tar, extract_dir)
    os.remove(archive)
    return extract_dir, commit, mtime


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def write_manifest(root, family, tag, commit):
    info = MCU_FAMILIES[family]
    manifest = {
        "name": info["package"],
        "version": package_version(tag),
        "title": info["title"],
        "description": "%s, repackaged for PlatformIO from %s tag %s." % (
            info["title"], info["upstream"], tag),
        "keywords": info["keywords"],
        # BSD-3-Clause plus a clause restricting use to RAKwireless products;
        # the full text ships as LICENSE.txt at the package root.
        "license": "LicenseRef-RAKwireless-RUI3",
        "repository": {"type": "git", "url": "https://github.com/%s.git" % info["upstream"]},
        "homepage": "https://github.com/%s" % info["upstream"],
        "rui3": {"upstream_tag": tag, "upstream_commit": commit},
    }
    if os.path.exists(os.path.join(root, "package.json")):
        log("  note: upstream now ships a package.json; replacing it with ours")
    with open(os.path.join(root, "package.json"), "w", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def write_tarball(root, out_path, mtime):
    """Create a reproducible .tar.gz of root's contents (no top-level folder)."""
    def normalise(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = mtime
        if info.isdir():
            info.mode = 0o755
        elif info.isfile():
            info.mode = 0o755 if info.mode & 0o111 else 0o644
        return info

    tmp_path = out_path + ".partial"
    with open(tmp_path, "wb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            rel_dir = os.path.relpath(dirpath, root)
            for name in sorted(dirnames) + sorted(filenames):
                full = os.path.join(dirpath, name)
                arcname = name if rel_dir == "." else "/".join(rel_dir.split(os.sep) + [name])
                tar.add(full, arcname=arcname, recursive=False, filter=normalise)
    os.replace(tmp_path, out_path)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_package(args):
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    families = args.mcu or list(MCU_FAMILIES)
    parse_tag(args.tag)
    index_path = os.path.join(out_dir, "%s.json" % release_tag(args.tag))
    index = {}
    if os.path.isfile(index_path):
        with open(index_path) as f:
            index = json.load(f)

    for family in families:
        info = MCU_FAMILIES[family]
        log("%s @ %s" % (info["package"], args.tag))
        workdir = tempfile.mkdtemp(prefix="rui3-bsp-")
        try:
            if args.git_root:
                git_dir = os.path.join(args.git_root, info["upstream"].split("/", 1)[1])
                root, commit, mtime = fetch_from_git(git_dir, args.tag, workdir)
            else:
                root, commit, mtime = fetch_from_github(info["upstream"], args.tag, workdir)
            if not os.path.isdir(os.path.join(root, "cores", info["core"])):
                raise SystemExit("error: %s has no cores/%s; not a RUI3 BSP?" % (args.tag, info["core"]))

            for path in bsp_patches.apply_all(root, info["core"], log=log):
                log("  patched %s" % path)
            manifest = write_manifest(root, family, args.tag, commit)

            out_path = os.path.join(out_dir, asset_name(family, args.tag))
            log("  writing %s" % os.path.relpath(out_path))
            write_tarball(root, out_path, mtime)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        digest = sha256_of(out_path)
        with open(out_path + ".sha256", "w", newline="\n") as f:
            f.write("%s  %s\n" % (digest, os.path.basename(out_path)))
        index[family] = {
            "package": info["package"],
            "version": manifest["version"],
            "upstream": info["upstream"],
            "upstream_tag": args.tag,
            "upstream_commit": commit,
            "file": os.path.basename(out_path),
            "size": os.path.getsize(out_path),
            "sha256": digest,
            "url": asset_url(args.repo, family, args.tag),
        }
        log("  %d bytes, sha256 %s" % (index[family]["size"], digest))

    with open(index_path, "w", newline="\n") as f:
        json.dump(index, f, indent=2, sort_keys=True)
        f.write("\n")
    log("wrote %s" % os.path.relpath(index_path))


def cmd_pin(args):
    parse_tag(args.tag)
    path = os.path.join(PLATFORM_DIR, "platform.json")
    with open(path, newline="") as f:
        raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    manifest = json.loads(raw)
    for family in args.mcu or list(MCU_FAMILIES):
        name = MCU_FAMILIES[family]["package"]
        manifest["packages"][name]["version"] = asset_url(args.repo, family, args.tag)
        log("%s -> %s" % (name, manifest["packages"][name]["version"]))
    if args.platform_version:
        manifest["version"] = args.platform_version
        log("platform version -> %s" % args.platform_version)
    # Keep the file's existing line endings so the diff shows only real changes.
    with open(path, "w", newline=eol) as f:
        f.write(json.dumps(manifest, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--tag", required=True, help="upstream tag, e.g. v4.3.0_400")
        p.add_argument("--mcu", action="append", choices=sorted(MCU_FAMILIES),
                       help="limit to one MCU family (repeatable); default: all")
        p.add_argument("--repo", default=DEFAULT_RELEASE_REPO,
                       help="GitHub repository hosting the release assets (default: %(default)s)")

    p = sub.add_parser("package", help="build framework tarballs into --out")
    common(p)
    p.add_argument("--out", default=os.path.join(PLATFORM_DIR, "dist"),
                   help="output directory (default: dist/)")
    p.add_argument("--git-root",
                   help="read tags from local clones under this folder (RAK-STM32-RUI/, "
                        "RAK-nRF52-RUI/, RAK-APOLLO3-RUI/) instead of downloading from GitHub")
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("pin", help="point platform.json at the release assets for --tag")
    common(p)
    p.add_argument("--platform-version", help="also set the platform version, e.g. 4.3.0")
    p.set_defaults(func=cmd_pin)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
