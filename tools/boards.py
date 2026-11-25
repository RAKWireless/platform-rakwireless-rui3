#!/usr/bin/env python3
"""
Generate the PlatformIO board manifests from the upstream boards.txt files.

There is one PlatformIO board per RAKwireless product (PRODUCTS below). A
WisDuo module and the WisBlock Core built around it are separate boards that
share one upstream board definition (RAK4630 and RAK4631 both build with
WisCoreRAK4631Board, for instance), so users can pick the product they hold.

Fields that come from upstream (core, CPU, clock, variant, USB ids, memory
sizes, upload flags, the upstream board id) are rewritten on every run, and the name
and documentation URL come from PRODUCTS. Debug probe settings, upload
protocols and the PlatformIO MCU name are kept from the existing manifest, or
copied from the family's reference board for a new product. Compiler flags are
not stored in the manifests: the builder reads them from the installed BSP.

Also refreshes the board list in platform.json and writes docs/boards.md with
each board's options (the Arduino IDE menus) and their defaults.

  python tools/boards.py --tag v4.3.0_400                       # from dist/ tarballs
  python tools/boards.py --tag v4.3.0_400 --git-root references # from local clones
  python tools/boards.py --tag v4.3.0_400 --check               # fail if out of date
"""

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PLATFORM_DIR = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)
sys.path.insert(0, os.path.join(PLATFORM_DIR, "builder"))
import bsp as bsp_tool  # noqa: E402
import rui3_recipe  # noqa: E402

DOCS = "https://docs.rakwireless.com/product-categories/"

# One entry per product: (PlatformIO board id, upstream boards.txt id, name,
# documentation URL). Ids are public (users put them in platformio.ini), so
# never rename one. Names follow "<part> <family> (<module inside>)".
PRODUCTS = [
    # STM32WLE5
    ("rak3172", "WisDuoRAK3172EvaluationBoard", "RAK3172 WisDuo Module", DOCS + "wisduo/rak3172-module"),
    ("rak3372", "WisDuoRAK3172EvaluationBoard", "RAK3372 WisBlock Core (RAK3172)", DOCS + "wisblock/rak3372"),
    # Also covers the RAK3272SL (low-frequency RAK3172PL variant).
    ("rak3272s", "WisDuoRAK3172EvaluationBoard", "RAK3272S Breakout Board (RAK3172)", DOCS + "wisduo/rak3272s-breakout-board"),
    ("rak3172t", "WisDuoRAK3172TBoard", "RAK3172-T WisDuo Module", DOCS + "wisduo/rak3172-module"),
    ("rak3172f", "WisDuoRAK3172FBoard", "RAK3172-F WisDuo Module", DOCS + "wisduo/rak3172-module"),
    ("rak3172sip", "WisDuoRAK3272SiPBoard", "RAK3172-SiP WisDuo SiP", DOCS + "wisduo/rak3172-sip"),
    ("rak3272sip", "WisDuoRAK3272SiPBoard", "RAK3272-SiP Breakout Board (RAK3172-SiP)", DOCS + "wisduo/rak3272-sip-breakout-board"),
    # No public documentation page found for the LP-SiP parts.
    ("rak3272lpsip", "WisDuoRAK3272LPSiPBoard", "RAK3272LP-SiP Breakout Board", "https://docs.rakwireless.com/"),
    ("rak11160", "WisDuoRAK11160Board", "RAK11160 WisDuo Module", DOCS + "wisduo/rak11160-module"),
    ("rak11162", "WisDuoRAK11160Board", "RAK11162 WisBlock Core (RAK11160)", DOCS + "wisblock/rak11162"),
    ("rak2461", "WisNodeRAK2461T", "RAK2461 WisNode", DOCS + "wisnode/rak2461"),
    # nRF52840
    ("rak4630", "WisCoreRAK4631Board", "RAK4630 WisDuo Module", DOCS + "wisduo/rak4630-module"),
    ("rak4631", "WisCoreRAK4631Board", "RAK4631 WisBlock Core (RAK4630)", DOCS + "wisblock/rak4631"),
    ("rak3401", "WisCoreRAK3401Board", "RAK3401 WisBlock Core", DOCS + "wisblock/rak3401"),
    ("rak5010", "WisTrioRAK5010Board", "RAK5010 WisTrio NB-IoT Tracker", DOCS + "wistrio/rak5010"),
    # Apollo3
    ("rak11720", "WisCoreRAK11720Board", "RAK11720 WisDuo Module", DOCS + "wisduo/rak11720-module"),
    ("rak11722", "WisCoreRAK11720Board", "RAK11722 WisBlock Core (RAK11720)", DOCS + "wisblock/rak11722"),
]

# Board whose curated fields seed a new board of the same family.
FAMILY_TEMPLATE = {"stm32wle": "rak3172", "nrf52": "rak4631", "apollo3": "rak11720"}

# Keys earlier manifests used to carry compiler settings; the builder now
# takes these from the BSP recipes.
OBSOLETE_BUILD_KEYS = (
    "app_path", "extra_flags", "feature_flags", "float_flags", "ldscript",
    "prebuilt_libs", "series",
)

def log(msg):
    print(msg, flush=True)


def read_json(path):
    with open(path, newline="") as f:
        raw = f.read()
    return json.loads(raw), ("\r\n" if "\r\n" in raw else "\n")


def render_json(data):
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_text(path, text, eol):
    with open(path, "w", newline=eol) as f:
        f.write(text)


def current_text(path):
    if not os.path.isfile(path):
        return None
    with open(path, newline="") as f:
        return f.read().replace("\r\n", "\n")


# ---------------------------------------------------------------------------
# Loading boards.txt / platform.txt
# ---------------------------------------------------------------------------

def load_bsp(family, tag, args, workdir):
    info = bsp_tool.MCU_FAMILIES[family]
    dest = os.path.join(workdir, family)
    os.makedirs(dest)
    if args.git_root:
        git_dir = os.path.join(args.git_root, info["upstream"].split("/", 1)[1])
        for name in ("boards.txt", "platform.txt"):
            data = subprocess.run(["git", "-C", git_dir, "show", "%s:%s" % (tag, name)],
                                  check=True, capture_output=True).stdout
            with open(os.path.join(dest, name), "wb") as f:
                f.write(data)
    else:
        archive = os.path.join(args.dist, bsp_tool.asset_name(family, tag))
        if not os.path.isfile(archive):
            raise SystemExit("error: %s not found; run `tools/bsp.py package --tag %s` "
                             "or pass --git-root" % (archive, tag))
        with tarfile.open(archive, "r:gz") as tar:
            for name in ("boards.txt", "platform.txt"):
                member = tar.extractfile(name)
                with open(os.path.join(dest, name), "wb") as f:
                    shutil.copyfileobj(member, f)
    return rui3_recipe.Bsp(dest)


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _int(value):
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _f_cpu(value):
    value = str(value).strip()
    return value + "L" if value.isdigit() else value


def build_manifest(upstream_id, name, url, props, existing, template):
    manifest = json.loads(json.dumps(existing or template or {}))
    build = manifest.setdefault("build", {})
    for key in OBSOLETE_BUILD_KEYS:
        build.pop(key, None)
    build["core"] = props["build.core"]
    build["cpu"] = props.get("build.mcu", build.get("cpu", ""))
    build["f_cpu"] = _f_cpu(props.get("build.f_cpu", build.get("f_cpu", "")))
    build["variant"] = props.get("build.variant", "")
    build.setdefault("mcu", (template or {}).get("build", {}).get("mcu", ""))
    build["rui3"] = {"board": upstream_id}
    # USB ids of the board's serial port, so uploads find it among others.
    vid, pid = props.get("build.vid", "").strip(), props.get("build.pid", "").strip()
    if vid and pid:
        build["hwids"] = [["0x%04X" % int(vid, 16), "0x%04X" % int(pid, 16)]]
    else:
        build.pop("hwids", None)

    upload = manifest.setdefault("upload", {})
    for src, dst in (("upload.maximum_size", "maximum_size"),
                     ("upload.maximum_data_size", "maximum_ram_size")):
        if _int(props.get(src)) is not None:
            upload[dst] = _int(props[src])
    for flag in ("use_1200bps_touch", "wait_for_upload_port"):
        if "upload.%s" % flag in props:
            upload[flag] = props["upload.%s" % flag].strip().lower() == "true"

    manifest["name"] = name
    manifest["url"] = url
    manifest["frameworks"] = ["rui3"]
    manifest["vendor"] = "RAKwireless"
    return manifest


def docs_markdown(entries, tag):
    lines = [
        "# Boards",
        "",
        "Generated by `tools/boards.py` from the upstream `boards.txt` files of RUI3 `%s`." % tag,
        "Do not edit by hand.",
        "",
        "Boards that share an upstream board (a WisDuo module and its WisBlock Core)",
        "build the same firmware.",
        "",
        "| Board id | Name | Core | Flash | RAM | Upstream board |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        m = e["manifest"]
        lines.append("| `%s` | %s | %s | %s KB | %s KB | `%s` |" % (
            e["id"], m["name"], m["build"]["core"],
            m["upload"].get("maximum_size", 0) // 1024,
            m["upload"].get("maximum_ram_size", 0) // 1024, e["upstream"]))
    lines += [
        "",
        "## Options",
        "",
        "Each board exposes the menus of the Arduino IDE. Set them per environment in",
        "`platformio.ini` with the menu id (any case) and either the option id or its label:",
        "",
        "```ini",
        "[env:rak3172]",
        "platform = rakwireless-rui3",
        "board = rak3172",
        "framework = rui3",
        "board_build.rui3.supportcn470 = on",
        "board_build.rui3.debug = l2",
        "```",
        "",
        "Defaults (marked **bold**) are the ones the Arduino IDE uses.",
    ]
    groups = collections.OrderedDict()
    for e in entries:
        signature = tuple((m.id, tuple(m.options.items())) for m in e["menus"].values())
        groups.setdefault(signature, []).append(e)
    for members in groups.values():
        lines += ["", "### %s" % ", ".join("`%s`" % e["id"] for e in members), ""]
        menus = members[0]["menus"]
        if not menus:
            lines.append("No options.")
            continue
        lines += ["| Option | Menu | Values |", "|---|---|---|"]
        for menu in menus.values():
            values = []
            for opt_id, label in menu.options.items():
                text = "`%s` %s" % (opt_id, label.strip())
                values.append("**%s**" % text if opt_id == menu.default else text)
            lines.append("| `%s` | %s | %s |" % (menu.id.lower(), menu.title, "<br>".join(values)))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", required=True, help="upstream tag, e.g. v4.3.0_400")
    parser.add_argument("--dist", default=os.path.join(PLATFORM_DIR, "dist"),
                        help="folder with the framework tarballs (default: dist/)")
    parser.add_argument("--git-root", help="read the tag from local clones under this folder")
    parser.add_argument("--check", action="store_true",
                        help="do not write anything; exit 1 if files are out of date")
    args = parser.parse_args(argv)

    boards_dir = os.path.join(PLATFORM_DIR, "boards")
    outputs = collections.OrderedDict()  # path -> (text, eol)
    entries = []
    known = {}
    workdir = tempfile.mkdtemp(prefix="rui3-boards-")
    try:
        for family, info in bsp_tool.MCU_FAMILIES.items():
            bsp = load_bsp(family, args.tag, args, workdir)
            template_path = os.path.join(boards_dir, FAMILY_TEMPLATE[family] + ".json")
            template = read_json(template_path)[0] if os.path.isfile(template_path) else None
            upstream_ids = bsp.board_ids()
            products = [p for p in PRODUCTS if p[1] in upstream_ids]
            for upstream_id in upstream_ids:
                if not any(p[1] == upstream_id for p in products):
                    log("warning: upstream board %s has no product; add it to PRODUCTS "
                        "in tools/boards.py" % upstream_id)
            for board_id, upstream_id, name, url in products:
                path = os.path.join(boards_dir, board_id + ".json")
                existing, eol = read_json(path) if os.path.isfile(path) else (None, "\r\n")
                props = bsp.board_props(upstream_id)
                manifest = build_manifest(upstream_id, name, url, props, existing, template)
                outputs[path] = (render_json(manifest), eol)
                entries.append({"id": board_id, "upstream": upstream_id, "manifest": manifest,
                                "menus": bsp.menus(upstream_id), "new": existing is None})
                known[board_id] = upstream_id
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    for name in sorted(os.listdir(boards_dir)):
        board_id, ext = os.path.splitext(name)
        if ext == ".json" and board_id not in known:
            log("warning: boards/%s has no upstream board in %s; left untouched" % (name, args.tag))

    platform_path = os.path.join(PLATFORM_DIR, "platform.json")
    platform, platform_eol = read_json(platform_path)
    platform["boards"] = [{"id": e["id"], "name": e["manifest"]["name"]} for e in entries]
    outputs[platform_path] = (json.dumps(platform, indent=2) + "\n", platform_eol)
    outputs[os.path.join(PLATFORM_DIR, "docs", "boards.md")] = (docs_markdown(entries, args.tag), "\r\n")

    stale = [p for p, (text, _) in outputs.items() if current_text(p) != text]
    for e in entries:
        if e["new"]:
            log("new board: %s (%s); review its debug settings and upload protocols" % (
                e["id"], e["upstream"]))
    for board_id, upstream_id, _, _ in PRODUCTS:
        if board_id not in known:
            log("warning: %s needs upstream board %s, which %s does not define" % (
                board_id, upstream_id, args.tag))
    if args.check:
        for path in stale:
            log("out of date: %s" % os.path.relpath(path, PLATFORM_DIR))
        return 1 if stale else 0
    for path in stale:
        text, eol = outputs[path]
        write_text(path, text, eol)
        log("wrote %s" % os.path.relpath(path, PLATFORM_DIR))
    if not stale:
        log("everything up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
