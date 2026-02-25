"""
SCons entry point for RAKwireless RUI3 platform.

Sets up the ARM GCC toolchain, ELF-to-BIN/HEX conversion,
and dispatches to the framework-specific builder.
"""

import os

from SCons.Script import (
    COMMAND_LINE_TARGETS,
    AlwaysBuild,
    Default,
    DefaultEnvironment,
)

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

env.Replace(
    AR="arm-none-eabi-ar",
    AS="arm-none-eabi-gcc",
    CC="arm-none-eabi-gcc",
    CXX="arm-none-eabi-g++",
    GDB="arm-none-eabi-gdb",
    OBJCOPY="arm-none-eabi-objcopy",
    RANLIB="arm-none-eabi-ranlib",
    SIZETOOL="arm-none-eabi-size",
    ARFLAGS=["rcs"],
    SIZEPROGREGEXP=r"^(?:\.text|\.data|\.rodata|\.text.align|\.ARM.exidx)\s+(\d+).*",
    SIZEDATAREGEXP=r"^(?:\.data|\.bss|\.noinit)\s+(\d+).*",
    SIZECHECKCMD="$SIZETOOL -A -d $SOURCES",
    SIZEPRINTCMD="$SIZETOOL -B -d $SOURCES",
    PROGSUFFIX=".elf",
)

# Append toolchain bin directory to PATH
toolchain_dir = platform.get_package_dir("toolchain-gccarmnoneeabi")
if toolchain_dir:
    env.PrependENVPath("PATH", os.path.join(toolchain_dir, "bin"))

# ELF → BIN and HEX
# Note: framework scripts are invoked automatically by env.BuildProgram()
# via ProcessProgramDeps() → BuildFrameworks(). Do NOT call them manually here.
env.Append(
    BUILDERS=dict(
        ElfToBin=env.Builder(
            action=env.VerboseAction(
                " ".join(["$OBJCOPY", "-O", "binary", "$SOURCES", "$TARGET"]),
                "Creating $TARGET",
            ),
            suffix=".bin",
        ),
        ElfToHex=env.Builder(
            action=env.VerboseAction(
                " ".join(["$OBJCOPY", "-O", "ihex", "$SOURCES", "$TARGET"]),
                "Creating $TARGET",
            ),
            suffix=".hex",
        ),
    )
)

# Build targets
target_elf = None
if "nobuild" in COMMAND_LINE_TARGETS:
    target_elf = os.path.join("$BUILD_DIR", "${PROGNAME}.elf")
else:
    target_elf = env.BuildProgram()

target_bin = env.ElfToBin(
    os.path.join("$BUILD_DIR", "${PROGNAME}"), target_elf
)
target_hex = env.ElfToHex(
    os.path.join("$BUILD_DIR", "${PROGNAME}"), target_elf
)

target_buildprog = env.Alias("buildprog", target_bin, target_bin)

AlwaysBuild(env.Alias("nobuild", target_bin))
target_size = env.AddPlatformTarget(
    "size",
    target_elf,
    env.VerboseAction("$SIZEPRINTCMD", "Calculating size $SOURCE"),
    "Program Size",
    "Calculate program size",
)

Default([target_buildprog, target_size])
