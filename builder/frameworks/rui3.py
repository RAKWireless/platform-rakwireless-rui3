"""
RUI3 framework build script, shared by every MCU family.

Compiler and linker settings come from the BSP's own Arduino recipes
(platform.txt + boards.txt), resolved by builder/rui3_recipe.py for the
upstream board named in the board manifest (build.rui3.board). IDE menu
choices are set per project with board options, for example:

    board_build.rui3.supportcn470 = on
    board_build.rui3.debug = l2

Sources are laid out the way arduino-cli builds them: everything under
cores/<core> goes into a framework library, and the variant's files are
linked as objects, so they take precedence over default implementations in
the core (the nRF52 variant's app_error handlers, for instance).
"""

import os
import sys

from SCons.Script import COMMAND_LINE_TARGETS, DefaultEnvironment

Import("env")

platform = env.PioPlatform()
board = env.BoardConfig()

sys.path.insert(0, os.path.join(platform.get_dir(), "builder"))
import buildtime  # noqa: E402
import rui3_recipe  # noqa: E402


def fail(message):
    sys.stderr.write("Error: %s\n" % message)
    env.Exit(1)


core = board.get("build.core", "")
family = rui3_recipe.FAMILIES.get(core)
if not family:
    fail("unsupported RUI3 core '%s' (expected one of: %s)" % (
        core, ", ".join(sorted(rui3_recipe.FAMILIES))))

FRAMEWORK_DIR = platform.get_package_dir(family["package"])
if not FRAMEWORK_DIR or not os.path.isdir(FRAMEWORK_DIR):
    fail("%s is not installed" % family["package"])
CORE_DIR = os.path.join(FRAMEWORK_DIR, "cores", core)

# RUI3 sketches are Arduino-style .ino files. PlatformIO converts .ino to C++
# (adding the prototypes the Arduino IDE generates) only for its own "arduino"
# framework; without this call, .ino files in the project are not compiled.
if "nobuild" not in COMMAND_LINE_TARGETS:
    env.ConvertInoToCpp()

upstream_board = board.get("build.rui3.board", "")
if not upstream_board:
    fail("board manifest has no build.rui3.board (the upstream boards.txt id)")

options = dict(board.get("build.rui3", {}))
options.pop("board", None)

toolchain_dir = platform.get_package_dir("toolchain-gccarmnoneeabi") or ""
try:
    bsp = rui3_recipe.Bsp(FRAMEWORK_DIR)
    cfg = bsp.resolve(
        upstream_board, options, arch=family["arch"],
        tool_paths={"arm-none-eabi-gcc": toolchain_dir})
except rui3_recipe.RecipeError as exc:
    fail(str(exc))

if options:
    print("RUI3 options: %s" % ", ".join(
        "%s=%s" % (menu, cfg.selections[menu])
        for menu in cfg.selections if menu.lower() in {k.lower() for k in options}))


def cppdefine(name, value):
    if value is None:
        return name
    # Recipe values such as "4.3.0" or "WisDuo RAK3172 Evaluation Board" keep
    # their quotes; StringifyMacro escapes them so they survive the shell.
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return (name, env.StringifyMacro(value[1:-1]))
    return (name, value)


env.Append(
    ASFLAGS=cfg.asflags,
    CCFLAGS=cfg.ccflags,
    CFLAGS=cfg.cflags,
    CXXFLAGS=cfg.cxxflags,
    CPPDEFINES=[cppdefine(name, value) for name, value in cfg.defines],
    CPPPATH=cfg.cpppath,
    LINKFLAGS=cfg.linkflags,
    LIBPATH=cfg.libpath,
    # "-l:file.a" libraries are resolved to full paths; SCons would otherwise
    # strip the "lib" prefix and ".a" suffix and ask ld for the wrong name.
    LIBS=[env.File(lib) if os.path.isabs(lib) else lib for lib in cfg.libs],
)
# PlatformIO adds "-T $LDSCRIPT_PATH" itself; a -T in LINKFLAGS would be
# passed twice.
env.Replace(LDSCRIPT_PATH=cfg.ldscript)

# nRF52 firmware is uploaded as a signed DFU package. Its settings (hardware
# and application version, SoftDevice id, signing key) are arguments of the
# nrfutil command in the BSP's zip recipe; builder/main.py builds the package.
if family["arch"] == "nrf52":
    import nrf52_dfu  # noqa: E402
    zip_recipe = bsp.recipe("recipe.objcopy.zip.pattern", cfg.props)
    if zip_recipe:
        try:
            env.Replace(RUI3_DFU=nrf52_dfu.package_options(zip_recipe))
        except nrf52_dfu.DfuError as exc:
            fail(str(exc))

# BSP code embeds __FILE__ in assert and log messages, so the firmware would
# otherwise carry the absolute install path of the package: different on
# every machine, and on nRF52 about 2 KB more flash for a typical
# ~/.platformio path. Make those paths relative to the package root.
env.Append(CCFLAGS=["-fmacro-prefix-map=%s=." % FRAMEWORK_DIR])

# The recipes compile with -w. Keep that for BSP sources only, so warnings in
# the project's own code are still reported.
framework_env = env.Clone()
framework_env.Append(CCFLAGS=cfg.warning_flags, ASFLAGS=cfg.warning_flags)

# arduino-cli compiles .c, .cpp and .S files. The STM32 BSP also carries a
# Tasking-compiler FreeRTOS port (port_asm.asm) that GCC cannot assemble.
# Lowercase .s is not filtered here: on Windows the glob would match .S too.
CORE_SRC_FILTER = "+<*> -<**/*.asm> -<**/*.ASM>"



def shadowed_core_sources(core_dir):
    """Core sources the Arduino IDE compiles but never links.

    arduino-cli archives core objects into core.a under their file name
    (system_nrf52840.c.o) with `ar r`, which replaces a member of the same
    name. When two core sources share a file name, only the one archived last
    (in walk order, i.e. sorted by path) ends up in the firmware: on nRF52,
    the SDK's modules/nrfx/mdk/system_nrf52840.c replaces RUI3's own copy,
    which changes SystemInit() and the chip errata it applies at boot.
    Excluding the shadowed copies reproduces that.
    """
    by_name = {}
    for dirpath, dirnames, filenames in os.walk(core_dir):
        for name in filenames:
            if name.endswith((".c", ".cpp", ".S")):
                rel = os.path.relpath(os.path.join(dirpath, name), core_dir)
                by_name.setdefault(name, []).append(rel)
    shadowed = []
    for paths in by_name.values():
        paths.sort(key=lambda p: p.split(os.sep))
        shadowed.extend(paths[:-1])
    return sorted(shadowed)


core_filter = CORE_SRC_FILTER + "".join(
    " -<%s>" % path.replace(os.sep, "/") for path in shadowed_core_sources(CORE_DIR))

env.Prepend(LIBS=[
    framework_env.BuildLibrary(
        os.path.join("$BUILD_DIR", "FrameworkRUI3"), CORE_DIR, src_filter=core_filter)
])

variant_dir = cfg.props.get("build.variant.path", "")
if variant_dir and os.path.isdir(variant_dir):
    framework_env.BuildSources(
        os.path.join("$BUILD_DIR", "FrameworkRUI3Variant"), variant_dir,
        src_filter=CORE_SRC_FILTER + " -<version.c>")

    # The Arduino IDE stamps BUILD_DATE/BUILD_TIME into the variant's
    # version.c before every build (the firmware reports them over AT
    # commands). Do the same on a copy in the build folder rather than
    # editing the installed package.
    template = os.path.join(variant_dir, "version.c")
    if os.path.isfile(template):
        version_c = env.subst(os.path.join("$BUILD_DIR", "FrameworkRUI3Version", "version.c"))
        buildtime.generate_version_source(template, version_c)
        DefaultEnvironment().Append(PIOBUILDFILES=[
            framework_env.Object(os.path.splitext(version_c)[0] + ".o", version_c)
        ])
