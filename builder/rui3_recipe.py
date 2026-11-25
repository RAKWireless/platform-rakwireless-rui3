"""
Resolve the Arduino build recipes shipped with a RUI3 BSP into compiler and
linker settings.

Every RUI3 BSP is an Arduino hardware package: platform.txt holds the compile
and link recipes, boards.txt the per-board properties and the IDE menus
(regions, LoRa mode, AT commands, debug level...). Reading them here, instead
of keeping our own copies of flags and include paths, means a new BSP release
builds with exactly the settings the Arduino IDE would use, including boards
and options added upstream.

Pure Python with no SCons or PlatformIO imports, so the board generator and
the parity checks in tools/ can use it too.
"""

import collections
import os
import re
import shlex
import sys

# MCU families, keyed by the board's build.core. "arch" is the architecture
# folder name the BSP has in the Arduino board index; Arduino derives
# ARDUINO_ARCH_<ARCH> from it.
FAMILIES = {
    "STM32WLE": {"package": "framework-rui3-stm32wle", "arch": "stm32"},
    "nRF5": {"package": "framework-rui3-nrf52", "arch": "nrf52"},
    "apollo3": {"package": "framework-rui3-apollo3", "arch": "apollo3"},
}

# The ARDUINO macro value arduino-cli passes (runtime.ide.version).
ARDUINO_IDE_VERSION = "10607"

# Stand-ins for the placeholders arduino-cli fills in per file. They contain
# no braces or whitespace, so they survive expansion and tokenising as single
# tokens.
_INCLUDES = "@@RUI3_INCLUDES@@"
_SOURCE = "@@RUI3_SOURCE@@"
_OBJECT = "@@RUI3_OBJECT@@"
_OBJECTS = "@@RUI3_OBJECTS@@"
_ARCHIVE = "@@RUI3_ARCHIVE@@"

# Options whose value is the next token when written separately.
_ARG_OPTIONS = {
    "--param", "-u", "-x", "-include", "-imacros", "-isystem", "-iquote",
    "-idirafter", "-iprefix", "-MF", "-MT", "-MQ", "-Xlinker", "-Xassembler",
    "-T", "-L", "-I", "-D", "-U", "-o", "-l",
}

# Compile options PlatformIO/SCons handle themselves, or that only make sense
# for Arduino's build layout (-save-temps would drop .i/.s files into the
# project folder).
_DROP_COMPILE = {"-c", "-MMD", "-MD", "-MP", "-save-temps"}
_DROP_LINK = {"-save-temps", "-Wl,--start-group", "-Wl,--end-group"}

# "${NAME}" is SCons syntax for construction variables, not an Arduino
# property, so a "{" preceded by "$" is left alone.
_PLACEHOLDER_RE = re.compile(r"(?<!\$)\{([^{}]+)\}")

if sys.platform.startswith("win"):
    _HOST_OS = "windows"
elif sys.platform == "darwin":
    _HOST_OS = "macosx"
else:
    _HOST_OS = "linux"


class RecipeError(Exception):
    pass


def parse_properties(text):
    """Parse an Arduino .txt properties file into an ordered list of (key, value)."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        items.append((key.strip(), value.strip()))
    return items


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _slash(path):
    # Recipes are tokenised with POSIX shell rules, where a backslash is an
    # escape character; gcc accepts forward slashes on every host.
    return path.replace("\\", "/")


class Menu(object):
    def __init__(self, menu_id, title):
        self.id = menu_id
        self.title = title
        self.options = collections.OrderedDict()  # option id -> label

    @property
    def default(self):
        # Arduino selects the first option listed in boards.txt.
        return next(iter(self.options))

    def match(self, value):
        """Return the option id matching value (an option id or label), or None."""
        wanted = str(value).strip().lower()
        for opt_id, label in self.options.items():
            if wanted in (opt_id.lower(), label.strip().lower()):
                return opt_id
        return None


class BuildConfig(object):
    """Compiler and linker settings for one board, with Arduino defaults applied."""

    def __init__(self):
        self.props = {}
        self.selections = collections.OrderedDict()  # menu id -> option id
        self.ccflags = []        # C and C++
        self.cflags = []         # C only
        self.cxxflags = []       # C++ only
        self.asflags = []        # .S files
        self.warning_flags = []  # -w / -W..., meant for framework sources only
        self.defines = []        # [(name, value or None)], C and C++
        self.cpppath = []
        self.linkflags = []
        self.libpath = []
        self.libs = []           # library names, or absolute paths for -l:file
        self.ldscript = None
        self.unresolved = set()  # placeholders that expanded to nothing


class Bsp(object):
    """An unpacked RUI3 BSP (the root holding platform.txt and boards.txt)."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.platform = parse_properties(_read(os.path.join(self.root, "platform.txt")))
        self.boards_txt = parse_properties(_read(os.path.join(self.root, "boards.txt")))
        self.version = dict(self.platform).get("version", "")

    # -- boards.txt -----------------------------------------------------------

    def board_ids(self):
        ids = []
        for key, _ in self.boards_txt:
            parts = key.split(".")
            if len(parts) == 2 and parts[1] == "name" and parts[0] != "menu":
                ids.append(parts[0])
        return ids

    def board_props(self, board_id):
        props = collections.OrderedDict()
        prefix = board_id + "."
        for key, value in self.boards_txt:
            if key.startswith(prefix) and not key.startswith(prefix + "menu."):
                props[key[len(prefix):]] = value
        if not props:
            raise RecipeError("board %r is not defined in %s" % (
                board_id, os.path.join(self.root, "boards.txt")))
        return props

    def menus(self, board_id):
        titles = {}
        for key, value in self.boards_txt:
            parts = key.split(".")
            if len(parts) == 2 and parts[0] == "menu":
                titles[parts[1]] = value
        menus = collections.OrderedDict()
        prefix = board_id + ".menu."
        for key, value in self.boards_txt:
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix):].split(".")
            if len(parts) == 2:
                menu = menus.setdefault(parts[0], Menu(parts[0], titles.get(parts[0], parts[0])))
                menu.options[parts[1]] = value
        return menus

    def _menu_props(self, board_id, menu_id, option_id):
        prefix = "%s.menu.%s.%s." % (board_id, menu_id, option_id)
        return [(k[len(prefix):], v) for k, v in self.boards_txt if k.startswith(prefix)]

    # -- resolution -----------------------------------------------------------

    def select(self, board_id, selections=None):
        """Map user selections ({menu: option id or label}) onto the board's menus.

        Menu names match case-insensitively, since PlatformIO lowercases option
        names read from platformio.ini.
        """
        menus = self.menus(board_id)
        by_lower = {m.lower(): m for m in menus}
        chosen = collections.OrderedDict((m, menu.default) for m, menu in menus.items())
        for key, value in (selections or {}).items():
            menu_id = by_lower.get(str(key).lower())
            if menu_id is None:
                raise RecipeError(
                    "unknown RUI3 option %r for board %s; available: %s" % (
                        key, board_id, ", ".join(menus) or "none"))
            option = menus[menu_id].match(value)
            if option is None:
                raise RecipeError(
                    "invalid value %r for RUI3 option %r (%s); use one of: %s" % (
                        value, menu_id, menus[menu_id].title,
                        "; ".join("%s (%s)" % (o, l.strip()) for o, l in menus[menu_id].options.items())))
            chosen[menu_id] = option
        return chosen

    def properties(self, board_id, selections=None, arch="", build_path="$BUILD_DIR",
                   project_name="${PROGNAME}", tool_paths=None):
        """All properties for board_id, after menu selections and runtime values."""
        props = collections.OrderedDict(self.platform)
        props.update(self.board_props(board_id))
        chosen = self.select(board_id, selections)
        for menu_id, option_id in chosen.items():
            props.update(self._menu_props(board_id, menu_id, option_id))

        # Host-specific overrides (key.windows / key.macosx / key.linux).
        for key in list(props):
            base, _, suffix = key.rpartition(".")
            if suffix == _HOST_OS and base:
                props[base] = props[key]

        root = _slash(self.root)
        core = props.get("build.core", "")
        variant = props.get("build.variant", "")
        props.update({
            "runtime.platform.path": root,
            "runtime.hardware.path": _slash(os.path.dirname(self.root)),
            "runtime.ide.version": ARDUINO_IDE_VERSION,
            "runtime.os": _HOST_OS,
            "build.arch": arch.upper(),
            "build.core.path": "%s/cores/%s" % (root, core),
            "build.variant.path": "%s/variants/%s" % (root, variant) if variant else "",
            "build.system.path": "%s/system" % root,
            "build.path": build_path,
            "build.project_name": project_name,
            "compiler.path": "",
            "includes": _INCLUDES,
            "source_file": _SOURCE,
            "object_file": _OBJECT,
            "object_files": _OBJECTS,
            "archive_file": _ARCHIVE,
            "archive_file_path": _ARCHIVE,
        })
        for name, path in (tool_paths or {}).items():
            props["runtime.tools.%s.path" % name] = _slash(path)
        return props, chosen

    def expand(self, value, props, unresolved=None):
        def lookup(match):
            key = match.group(1)
            if key in props:
                return props[key]
            return _note(unresolved, key)

        for _ in range(32):
            expanded = _PLACEHOLDER_RE.sub(lookup, value)
            if expanded == value:
                return expanded
            value = expanded
        raise RecipeError("recursive property expansion in %r" % value)

    def recipe(self, key, props, unresolved=None):
        """Recipe `key` expanded and split into arguments, or None if
        platform.txt has no such recipe. Tool paths the platform does not
        provide (props without runtime.tools.*) expand to empty strings."""
        if key not in props:
            return None
        return _tokenise(self.expand(props[key], props, unresolved))

    def resolve(self, board_id, selections=None, arch="", **kwargs):
        """Resolve compile and link settings for board_id."""
        props, chosen = self.properties(board_id, selections, arch=arch, **kwargs)
        cfg = BuildConfig()
        cfg.props = props
        cfg.selections = chosen
        core_path = props["build.core.path"]
        variant_path = props["build.variant.path"]
        implicit_includes = [core_path] + ([variant_path] if variant_path else [])

        def compile_recipe(key):
            if key not in props:
                raise RecipeError("platform.txt has no %s" % key)
            tokens = _tokenise(self.expand(props[key], props, cfg.unresolved))
            return _classify_compile(tokens[1:], implicit_includes)

        c = compile_recipe("recipe.c.o.pattern")
        cxx = compile_recipe("recipe.cpp.o.pattern")
        asm = compile_recipe("recipe.S.o.pattern")

        cxx_groups = set(cxx["flags"])
        c_groups = set(c["flags"])
        cfg.ccflags = _flatten(g for g in c["flags"] if g in cxx_groups)
        cfg.cflags = _flatten(g for g in c["flags"] if g not in cxx_groups)
        cfg.cxxflags = _flatten(g for g in cxx["flags"] if g not in c_groups)
        cfg.asflags = _flatten(asm["flags"])
        cfg.warning_flags = _flatten(g for g in c["warnings"])

        # Macros defined identically for C and C++ go into CPPDEFINES; the rest
        # stay language-specific (platform.txt can add, say, -DDEBUG for C++ only).
        for name, value in c["defines"].items():
            if name in cxx["defines"] and cxx["defines"][name] == value:
                cfg.defines.append((name, value))
            else:
                cfg.cflags.append(_define_flag(name, value))
        for name, value in cxx["defines"].items():
            if name not in c["defines"] or c["defines"][name] != value:
                cfg.cxxflags.append(_define_flag(name, value))
        cfg.ccflags += ["-U%s" % n for n in c["builtin_undefs"] if n in cxx["builtin_undefs"]]

        cfg.cpppath = [p for p in _unique(c["includes"]) if os.path.isdir(p)]

        if "recipe.c.combine.pattern" in props:
            tokens = _tokenise(self.expand(props["recipe.c.combine.pattern"], props, cfg.unresolved))
            _classify_link(tokens[1:], cfg)
        return cfg


def _note(unresolved, key):
    if unresolved is not None:
        unresolved.add(key)
    return ""


def _tokenise(command):
    try:
        return shlex.split(command, posix=True)
    except ValueError as exc:
        raise RecipeError("cannot parse recipe %r: %s" % (command, exc))


def _groups(tokens):
    """Pair options that take a separate argument with that argument."""
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _ARG_OPTIONS and i + 1 < len(tokens):
            if tok in ("-I", "-D", "-U", "-L", "-l", "-T"):
                out.append((tok + tokens[i + 1],))
            else:
                out.append((tok, tokens[i + 1]))
            i += 2
        else:
            out.append((tok,))
            i += 1
    return out


def _flatten(groups):
    return [tok for group in groups for tok in group]


def _unique(items):
    seen = set()
    out = []
    for item in items:
        key = os.path.normcase(os.path.normpath(item))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _define_flag(name, value):
    return "-D%s" % name if value is None else "-D%s=%s" % (name, value)


def _is_warning(tok):
    return tok == "-w" or (tok.startswith("-W") and not tok.startswith(("-Wl,", "-Wa,", "-Wp,")))


def _classify_compile(tokens, implicit_includes):
    flags, warnings, includes = [], [], []
    defines = collections.OrderedDict()
    builtin_undefs = []
    for group in _groups(tokens):
        tok = group[0]
        if tok in (_SOURCE, _OBJECT) or tok in _DROP_COMPILE or tok == "-o" + _OBJECT:
            continue
        if tok == "-o":
            continue
        if tok == _INCLUDES:
            includes.extend(os.path.normpath(p) for p in implicit_includes)
        elif tok.startswith("-I"):
            includes.append(os.path.normpath(tok[2:]))
        elif tok.startswith("-D"):
            name, sep, value = tok[2:].partition("=")
            defines.pop(name, None)  # a later -D replaces the earlier one in place
            defines[name] = value if sep else None
        elif tok.startswith("-U"):
            name = tok[2:]
            if name in defines:
                del defines[name]
            else:
                builtin_undefs.append(name)
        elif _is_warning(tok):
            warnings.append(group)
        else:
            flags.append(group)
    return {"flags": flags, "warnings": warnings, "includes": includes,
            "defines": defines, "builtin_undefs": builtin_undefs}


def _classify_link(tokens, cfg):
    lib_files = []
    ldscript = None
    groups = _groups(tokens)
    skip_next_output = False
    for group in groups:
        tok = group[0]
        if skip_next_output:
            skip_next_output = False
            continue
        if tok == "-o":
            if len(group) == 1:
                skip_next_output = True
            continue
        if tok.startswith("-o"):
            continue
        if tok == _OBJECTS or _ARCHIVE in tok or tok in _DROP_LINK:
            continue
        if tok.startswith("-T"):
            ldscript = tok[2:]
        elif tok.startswith("-L"):
            path = os.path.normpath(tok[2:])
            if os.path.isdir(path):
                cfg.libpath.append(path)
        elif tok.startswith("-l:"):
            lib_files.append(tok[3:])
        elif tok.startswith("-l"):
            cfg.libs.append(tok[2:])
        else:
            cfg.linkflags.extend(group)
    cfg.libpath = _unique(cfg.libpath)

    for name in lib_files:
        found = _find_in(name, cfg.libpath)
        if not found:
            raise RecipeError("library %s (-l:%s) not found in %s" % (name, name, cfg.libpath))
        cfg.libs.append(found)

    if ldscript:
        cfg.ldscript = ldscript if os.path.isabs(ldscript) and os.path.isfile(ldscript) \
            else _find_in(ldscript, cfg.libpath)
        if not cfg.ldscript:
            raise RecipeError("linker script %s not found in %s" % (ldscript, cfg.libpath))


def _find_in(name, dirs):
    for d in dirs:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate):
            return candidate
    return None
