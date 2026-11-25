"""
SCons entry point for RAKwireless RUI3 platform.

Sets up the ARM GCC toolchain, ELF-to-BIN/HEX conversion, the upload images
(nRF52 DFU package, Apollo3 OTA package) and the serial upload of each MCU
family, and dispatches to the framework-specific builder.
"""

import os
import sys

from SCons.Script import (
    COMMAND_LINE_TARGETS,
    Action,
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

sys.path.insert(0, os.path.join(platform.get_dir(), "builder"))
import apollo3_ota  # noqa: E402
import nrf52_dfu  # noqa: E402
import stm32_ymodem  # noqa: E402

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

# PlatformIO's built-in image name is "program"; platforms name it "firmware"
# (firmware.elf, firmware.hex, ...). A name set by the project is kept.
if env.get("PROGNAME", "program") == "program":
    env.Replace(PROGNAME="firmware")

# Append toolchain bin directory to PATH
toolchain_dir = platform.get_package_dir("toolchain-gccarmnoneeabi")
if toolchain_dir:
    env.PrependENVPath("PATH", os.path.join(toolchain_dir, "bin"))

core = board.get("build.core", "")
is_nrf52 = core == "nRF5"
is_apollo3 = core == "apollo3"


def build_dfu_package(target, source, env):
    # RUI3_DFU holds the settings from the BSP's own zip recipe; the framework
    # script sets it (see builder/frameworks/rui3.py).
    options = env.get("RUI3_DFU")
    if not options:
        sys.stderr.write("Error: the BSP has no DFU package recipe "
                         "(recipe.objcopy.zip.pattern in platform.txt)\n")
        return 1
    try:
        nrf52_dfu.make_package(str(source[0]), str(target[0]), **options)
    except nrf52_dfu.DfuError as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1
    return None


def build_ota_package(target, source, env):
    # RUI3_OTA holds the settings from the BSP's OTA package recipe; the
    # framework script sets it (see builder/frameworks/rui3.py).
    options = env.get("RUI3_OTA")
    if not options:
        sys.stderr.write("Error: the BSP has no OTA package recipe "
                         "(ota_binary_converter in platform.txt)\n")
        return 1
    try:
        apollo3_ota.make_package(str(source[0]), str(target[0]), **options)
    except (apollo3_ota.OtaError, OSError) as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1
    return None


def serial_upload(module, error, check_version=False):
    def action(target, source, env):
        options = {}
        # `upload_flags = --force` uploads to a board that runs another RUI3
        # major version.
        if check_version and "--force" not in env.subst("$UPLOAD_FLAGS").split():
            options["expected_version"] = env.get("RUI3_VERSION")
        try:
            module.upload(str(source[0]), env.subst("$UPLOAD_PORT"), **options)
        except error as exc:
            sys.stderr.write("Error: %s\n" % exc)
            return 1
        return None
    return action


def upload_unsupported(target, source, env):
    sys.stderr.write(
        "Error: this platform cannot upload to %s boards yet (upload_protocol = %s)\n"
        % (core or "these", env.subst("$UPLOAD_PROTOCOL") or "none"))
    return 1


# ELF → BIN and HEX
# Note: framework scripts are invoked automatically by env.BuildProgram()
# via ProcessProgramDeps() → BuildFrameworks(). Do NOT call them manually here.
#
# Use SCons' Builder, not env.Builder: env.Builder substitutes construction
# variables in its arguments straight away. In verbose mode VerboseAction
# returns the bare command string, so $SOURCES and $TARGET would be expanded
# to nothing before any target exists and objcopy would run without files.
env.Append(
    BUILDERS=dict(
        ElfToBin=Builder(
            action=env.VerboseAction(
                " ".join(["$OBJCOPY", "-O", "binary", "$SOURCES", "$TARGET"]),
                "Creating $TARGET",
            ),
            suffix=".bin",
        ),
        ElfToHex=Builder(
            action=env.VerboseAction(
                " ".join(["$OBJCOPY", "-O", "ihex", "$SOURCES", "$TARGET"]),
                "Creating $TARGET",
            ),
            suffix=".hex",
        ),
        # varlist: a change in the recipe's settings rebuilds the package.
        HexToDfuPackage=Builder(
            action=Action(build_dfu_package, "Creating DFU package $TARGET",
                          varlist=["RUI3_DFU"]),
            suffix=".zip",
        ),
        BinToOtaPackage=Builder(
            action=Action(build_ota_package, "Creating OTA package $TARGET",
                          varlist=["RUI3_OTA"]),
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
# The Arduino IDE writes both images for every board.
build_targets = [target_bin, target_hex]

# nRF52 boards update through a signed DFU package built from the hex file.
target_zip = None
if is_nrf52:
    if "nobuild" in COMMAND_LINE_TARGETS:
        target_zip = os.path.join("$BUILD_DIR", "${PROGNAME}.zip")
    else:
        target_zip = env.HexToDfuPackage(os.path.join("$BUILD_DIR", "${PROGNAME}"), target_hex)
        key_file = (env.get("RUI3_DFU") or {}).get("key_file")
        if key_file:
            env.Depends(target_zip, key_file)
    build_targets.append(target_zip)

# Apollo3 boards update through an OTA package built from the bin file, under
# the name the Arduino IDE gives it.
target_ota = None
if is_apollo3:
    ota_path = os.path.join("$BUILD_DIR", "${PROGNAME}_Nonsecure_OTA_Package_UART.bin")
    if "nobuild" in COMMAND_LINE_TARGETS:
        target_ota = ota_path
    else:
        target_ota = env.BinToOtaPackage(ota_path, target_bin)
        security_info = (env.get("RUI3_OTA") or {}).get("security_info")
        if security_info:
            env.Depends(target_ota, security_info)
    build_targets.append(target_ota)

# No action: given the targets as its action too (a common PlatformIO
# idiom), SCons tries to execute them as commands once there is more than one.
target_buildprog = env.Alias("buildprog", build_targets)

AlwaysBuild(env.Alias("nobuild", target_bin))
target_size = env.AddPlatformTarget(
    "size",
    target_elf,
    env.VerboseAction("$SIZEPRINTCMD", "Calculating size $SOURCE"),
    "Program Size",
    "Calculate program size",
)

# Upload: (core, upload_protocol) -> (image, uploader module, its error,
# whether it checks the running firmware's RUI3 version first).
# Every family uploads over the board's serial port after asking the running
# firmware to restart into the RUI3 bootloader.
SERIAL_UPLOADS = {
    ("nRF5", "nrfutil"): (target_zip, nrf52_dfu, nrf52_dfu.DfuError, False),
    ("STM32WLE", "ymodem"): (target_bin, stm32_ymodem, stm32_ymodem.UploadError, True),
    ("apollo3", "amota"): (target_ota, apollo3_ota, apollo3_ota.OtaError, False),
}
upload = SERIAL_UPLOADS.get((core, env.subst("$UPLOAD_PROTOCOL")))
if upload:
    image, module, error, check_version = upload
    env.AddPlatformTarget(
        "upload",
        image,
        [
            env.VerboseAction(env.AutodetectUploadPort, "Looking for upload port..."),
            env.VerboseAction(serial_upload(module, error, check_version), "Uploading $SOURCE"),
        ],
        "Upload",
    )
else:
    env.AddPlatformTarget(
        "upload",
        target_bin,
        env.VerboseAction(upload_unsupported, "Uploading $SOURCE"),
        "Upload",
    )

Default([target_buildprog, target_size])
