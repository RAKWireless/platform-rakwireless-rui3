"""
RUI3 build script for Apollo3 (RAK11720 family).

Translates the Arduino-style boards.txt / platform.txt configuration
into PlatformIO SCons build environment settings.
"""

import os
import sys

Import("env")


platform = env.PioPlatform()
board = env.BoardConfig()

FRAMEWORK_DIR = platform.get_package_dir("framework-rui3-apollo3")
CORES_DIR = os.path.join(FRAMEWORK_DIR, "cores", "apollo3")
AMBIQ_SDK = os.path.join(CORES_DIR, "external", "AmbiqSuiteSDK")

assert os.path.isdir(FRAMEWORK_DIR), (
    "framework-rui3-apollo3 package not found at %s" % FRAMEWORK_DIR
)
assert os.path.isdir(CORES_DIR), (
    "apollo3 cores directory not found at %s" % CORES_DIR
)

# Board configuration
variant = board.get("build.variant")
series = board.get("build.series")
ldscript = board.get("build.ldscript", "flash_apollo3.ld")
mcu = board.get("build.mcu", "cortex-m4")
float_flags = board.get("build.float_flags", "-mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -u _printf_float")
extra_flags = board.get("build.extra_flags", "")
feature_flags = board.get("build.feature_flags", "")

VARIANT_DIR = os.path.join(FRAMEWORK_DIR, "variants", variant)

# Helper: join path relative to cores dir
def cores_join(*parts):
    return os.path.join(CORES_DIR, *parts)

def sdk_join(*parts):
    return os.path.join(AMBIQ_SDK, *parts)


# ---------------------------------------------------------------------------
# Compiler flags
# ---------------------------------------------------------------------------

env.Append(
    ASFLAGS=[
        "-g",
        "-x", "assembler-with-cpp",
    ],

    CCFLAGS=[
        "-mcpu=%s" % mcu,
        "-mthumb",
        "-Os",
        "-g",
        "-ffunction-sections",
        "-fdata-sections",
        "--param", "max-inline-insns-single=500",
        "-nostdlib",
        "-fno-use-cxa-atexit",
    ] + float_flags.split(),

    CFLAGS=[
        "-std=gnu11",
    ],

    CXXFLAGS=[
        "-std=gnu++11",
        "-fno-threadsafe-statics",
        "-fno-rtti",
        "-fno-exceptions",
    ],

    LINKFLAGS=[
        "-mcpu=%s" % mcu,
        "-mthumb",
        "-Wl,--cref",
        "-Wl,--check-sections",
        "-Wl,--gc-sections",
        "-Wl,--unresolved-symbols=report-all",
        "-Wl,--warn-common",
        "--specs=nano.specs",
        "--specs=nosys.specs",
        "-nostartfiles",
    ] + float_flags.split(),

    LIBS=["c", "m", "nosys", "stdc++"],
)

# ---------------------------------------------------------------------------
# Preprocessor defines
# ---------------------------------------------------------------------------

env.Append(CPPDEFINES=[
    ("ARDUINO", 10808),
    ("ARDUINO_%s" % variant, 1),
    "ARDUINO_ARCH_APOLLO3",
    ("F_CPU", board.get("build.f_cpu")),
])

# Feature defines from board config
for flag in feature_flags.split():
    if flag.startswith("-D"):
        define = flag[2:]
        if "=" in define:
            key, val = define.split("=", 1)
            env.Append(CPPDEFINES=[(key, val)])
        else:
            env.Append(CPPDEFINES=[define])

# Board-specific extra defines
for flag in extra_flags.split():
    if flag.startswith("-D"):
        define = flag[2:]
        if "=" in define:
            key, val = define.split("=", 1)
            env.Append(CPPDEFINES=[(key, val)])
        else:
            env.Append(CPPDEFINES=[define])

# LoRa region support — only for boards with LoRa (not NO_LORA_SUPPORT)
_lora_support = "NO_LORA_SUPPORT" not in feature_flags

# ---------------------------------------------------------------------------
# LoRaMac-node: auto-detect version (prefer newest present)
# ---------------------------------------------------------------------------

lora_dir = None
lora_ver_name = None
# Apollo3 BSP at v4.2.3_363 ships only 4.7.0 in inc_path, but all three exist.
# Prefer 4.7.0: service_lora.h uses LORAMAC_REGION_LA915 (4.7.0+ only) and
# LORA_STACK_104 in board JSON aligns with the 4.7.0 LmhPackage_t API.
for _lora_ver in ["LoRaMac-node-4.7.0", "LoRaMac-node-4.5.2", "LoRaMac-node-4.4.7"]:
    _candidate = cores_join("external", "lora", _lora_ver)
    if os.path.isdir(_candidate):
        lora_dir = _candidate
        lora_ver_name = _lora_ver
        break

if _lora_support:
    lora_regions = [
        "SUPPORT_LORA",
        "SUPPORT_LORA_P2P",
        "REGION_AS923",
        "REGION_AU915",
        "REGION_CN470",
        "REGION_CN779",
        "REGION_EU433",
        "REGION_EU868",
        "REGION_KR920",
        "REGION_IN865",
        "REGION_US915",
        "REGION_RU864",
    ]
    # LA915 requires LoRaMac-node >= 4.7.0
    if lora_ver_name and lora_ver_name >= "LoRaMac-node-4.7.0":
        lora_regions.append("REGION_LA915")
    env.Append(CPPDEFINES=lora_regions)

# ---------------------------------------------------------------------------
# Include paths
# ---------------------------------------------------------------------------

# Derived from boards.txt inc_path for WisCore_RAK11720_Board.
# All paths are guarded by os.path.isdir() — stale paths (e.g., SystemView
# which is absent from this BSP release) are silently ignored.
inc_paths = [
    # Variant
    VARIANT_DIR,
    # App per-board source (boards.txt references app/RAK11720/src — may not exist)
    cores_join("app", variant.replace("WisCore_", "").replace("_Board", ""), "src"),
    # Component includes
    cores_join("component", "inc"),
    # MCU core
    cores_join("component", "core", "mcu", "apollo3"),
    cores_join("component", "core", "mcu", "apollo3", "uhal"),
    cores_join("component", "core", "mcu", "apollo3", "uhal", "serial"),
    cores_join("component", "core", "mcu", "none", "uhal"),
    cores_join("component", "core", "board", series),
    # udrv components
    cores_join("component", "udrv"),
    cores_join("component", "udrv", "serial"),
    cores_join("component", "udrv", "timer"),
    cores_join("component", "udrv", "delay"),
    cores_join("component", "udrv", "spimst"),
    cores_join("component", "udrv", "powersave"),
    cores_join("component", "udrv", "gpio"),
    cores_join("component", "udrv", "rtc"),
    cores_join("component", "udrv", "twimst"),
    cores_join("component", "udrv", "dfu"),
    cores_join("component", "udrv", "crypto"),
    cores_join("component", "udrv", "trng"),
    cores_join("component", "udrv", "pwm"),
    cores_join("component", "udrv", "adc"),
    cores_join("component", "udrv", "system"),
    cores_join("component", "udrv", "ble"),
    cores_join("component", "udrv", "flash"),
    cores_join("component", "udrv", "wdt"),
    cores_join("component", "udrv", "nfc"),
    cores_join("component", "udrv", "pdm"),
    # Services
    cores_join("component", "service", "lora"),
    cores_join("component", "service", "lora", "packages"),
    cores_join("component", "service", "lora", "LmHandler"),
    cores_join("component", "service", "runtimeConfig"),
    cores_join("component", "service", "nvm"),
    cores_join("component", "service", "battery"),
    cores_join("component", "service", "debug"),
    cores_join("component", "service", "mode"),
    cores_join("component", "service", "mode", "cli"),
    cores_join("component", "service", "mode", "transparent"),
    cores_join("component", "service", "mode", "protocol"),
    # RUI v3 API
    cores_join("component", "rui_v3_api"),
    cores_join("component", "rui_v3_api", "avr"),
    # Foundation
    cores_join("component", "fund", "event_queue"),
    cores_join("component", "fund", "circular_queue"),
    # External libraries
    cores_join("external", "FatFs", "source"),
    cores_join("external", "RTT", "RTT"),
    cores_join("external", "RTT", "Config"),
    cores_join("external", "libraries", "common"),
    cores_join("external", "libraries", "debug"),
    cores_join("external", "libraries", "ambiq_log"),
    # AmbiqSuiteSDK
    AMBIQ_SDK,
    sdk_join("bootloader"),
    sdk_join("ambiq_ble", "apps", "amota"),
    sdk_join("ambiq_ble", "services"),
    sdk_join("ambiq_ble", "profiles", "amota"),
    sdk_join("utils"),
    sdk_join("CMSIS", "AmbiqMicro", "Include"),
    sdk_join("CMSIS", "ARM", "Include"),
    sdk_join("devices"),
    sdk_join("mcu", "apollo3"),
    sdk_join("mcu", "apollo3", "regs"),
    # FreeRTOS v10
    sdk_join("third_party", "FreeRTOSv10.1.1", "Source"),
    sdk_join("third_party", "FreeRTOSv10.1.1", "Source", "include"),
    sdk_join("third_party", "FreeRTOSv10.1.1", "Source", "portable", "GCC", "AMapollo2"),
    sdk_join("third_party", "FreeRTOSv10.1.1", "Source", "portable", "MemMang"),
    # Cordio BLE stack
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "gatt"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "hid"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "uribeacon"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "bas"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "hrps"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "include"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "rscp"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "profiles", "gap"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "apps"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "apps", "app"),
    sdk_join("third_party", "cordio", "ble-profiles", "sources", "services"),
    sdk_join("third_party", "cordio", "ble-profiles", "include", "app"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "hci", "ambiq", "apollo3"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "hci", "ambiq"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "sec", "common"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "stack", "dm"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "stack", "l2c"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "stack", "hci"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "stack", "att"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "stack", "cfg"),
    sdk_join("third_party", "cordio", "ble-host", "sources", "stack", "smp"),
    sdk_join("third_party", "cordio", "ble-host", "include"),
    sdk_join("third_party", "cordio", "wsf", "sources"),
    sdk_join("third_party", "cordio", "wsf", "sources", "util"),
    sdk_join("third_party", "cordio", "wsf", "sources", "port", "freertos"),
    sdk_join("third_party", "cordio", "wsf", "include"),
    sdk_join("third_party", "uecc"),
    sdk_join("third_party", "mbedtls-2.4.2", "include"),
]

if lora_dir:
    inc_paths += [
        os.path.join(lora_dir, "src", "mac"),
        os.path.join(lora_dir, "src", "mac", "region"),
        os.path.join(lora_dir, "src", "radio"),
        os.path.join(lora_dir, "src", "system"),
        os.path.join(lora_dir, "src", "peripherals"),
        os.path.join(lora_dir, "src", "boards"),
        os.path.join(lora_dir, "src", "apps", "LoRaMac", "common", "LmHandler"),
    ]

# Filter out non-existent directories
env.Append(CPPPATH=[p for p in inc_paths if p and os.path.isdir(p)])

# ---------------------------------------------------------------------------
# Library search paths (for linker -L flags)
# ---------------------------------------------------------------------------

lib_paths = [
    cores_join("app"),
    cores_join("component", "core", "mcu", "apollo3"),
    cores_join("component", "core", "mcu", "apollo3", "uhal"),
    cores_join("external"),
    cores_join("component", "core", "board", series),
    cores_join("component", "udrv", "serial"),
    cores_join("component", "udrv", "flash"),
    cores_join("component", "udrv", "timer"),
    cores_join("component", "udrv", "system"),
    cores_join("component", "udrv", "powersave"),
    cores_join("component", "udrv", "wdt"),
    cores_join("component", "udrv", "gpio"),
    cores_join("component", "udrv", "twimst"),
    cores_join("component", "udrv", "delay"),
    cores_join("component", "udrv", "rtc"),
    cores_join("component", "udrv", "dfu"),
    cores_join("component", "udrv", "pwm"),
    cores_join("component", "udrv", "crypto"),
    cores_join("component", "udrv", "trng"),
    cores_join("component", "udrv", "adc"),
    cores_join("component", "udrv", "pdm"),
    cores_join("component", "udrv", "spimst"),
    cores_join("component", "udrv", "ble"),
    cores_join("component", "udrv", "nfc"),
    cores_join("component", "service", "nvm"),
    cores_join("component", "service", "lora"),
    cores_join("component", "service", "runtimeConfig"),
    cores_join("component", "service", "battery"),
    cores_join("component", "service", "mode"),
    cores_join("component", "service", "debug"),
    cores_join("component", "rui_v3_api"),
    cores_join("component", "fund", "event_queue"),
    cores_join("component", "fund", "circular_queue"),
    VARIANT_DIR,
]

env.Append(LIBPATH=[p for p in lib_paths if os.path.isdir(p)])

# ---------------------------------------------------------------------------
# Linker script
# ---------------------------------------------------------------------------

ld_dir = cores_join("component", "core", "mcu", "apollo3")
ld_file = os.path.join(ld_dir, ldscript)

if os.path.isfile(ld_file):
    env.Replace(LDSCRIPT_PATH=ld_file)
else:
    env.Exit("Error: linker script not found: %s" % ld_file)

# Map file
env.Append(LINKFLAGS=[
    "-Wl,-Map,%s" % os.path.join("$BUILD_DIR", "${PROGNAME}.map"),
])

# ---------------------------------------------------------------------------
# Generate version.c with build timestamp (prebuild step)
# ---------------------------------------------------------------------------

PLATFORM_DIR = platform.get_dir()
sys.path.insert(0, PLATFORM_DIR)
from builder.buildtime import generate_version_source

version_c_path = os.path.join("$BUILD_DIR", "version.c")
generate_version_source(env.subst(version_c_path))

# ---------------------------------------------------------------------------
# Source files — framework library
# ---------------------------------------------------------------------------

# Build cores/apollo3/ as a library: component/ + external/ + app_glue.
src_filter = [
    "+<component/>",
    "+<external/lora/%s/>" % (lora_ver_name or "LoRaMac-node-4.7.0"),
    "+<external/AmbiqSuiteSDK/>",
    "+<external/FatFs/>",
    "+<external/RTT/>",
    "+<external/libraries/>",
    "+<app/app_glue.cpp>",
    # Exclude FUOTA alternate sources
    "-<**/*.c.fuota>",
    "-<**/*.cpp.fuota>",
    # Exclude FreeRTOS 9.x (use FreeRTOSv10.1.1 only)
    "-<external/AmbiqSuiteSDK/third_party/FreeRTOS9/>",
    # Exclude IAR and Keil FreeRTOS ports (incompatible with GCC toolchain)
    "-<external/AmbiqSuiteSDK/third_party/FreeRTOSv10.1.1/Source/portable/IAR/>",
    "-<external/AmbiqSuiteSDK/third_party/FreeRTOSv10.1.1/Source/portable/Keil/>",
    "-<external/AmbiqSuiteSDK/third_party/FreeRTOSv10.1.1/Source/portable/Keil6/>",
]

# Exclude other LoRaMac-node versions to avoid duplicate symbols
if lora_ver_name:
    for _other_ver in ["LoRaMac-node-4.7.0", "LoRaMac-node-4.5.2", "LoRaMac-node-4.4.7"]:
        if _other_ver != lora_ver_name:
            src_filter.append("-<external/lora/%s/>" % _other_ver)

libs = []

libs.append(
    env.BuildLibrary(
        os.path.join("$BUILD_DIR", "FrameworkRUI3"),
        CORES_DIR,
        src_filter=" ".join(src_filter),
    )
)

# Build variant sources
if os.path.isdir(VARIANT_DIR):
    libs.append(
        env.BuildLibrary(
            os.path.join("$BUILD_DIR", "FrameworkRUI3Variant"),
            VARIANT_DIR,
        )
    )

env.Prepend(LIBS=libs)
