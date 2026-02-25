"""
RUI3 build script for nRF52840 (RAK4631 / RAK5010 / RAK3401 family).

Translates the Arduino-style boards.txt / platform.txt configuration
into PlatformIO SCons build environment settings.
"""

import os
import sys

Import("env")


platform = env.PioPlatform()
board = env.BoardConfig()

FRAMEWORK_DIR = platform.get_package_dir("framework-rui3-nrf52")
CORES_DIR = os.path.join(FRAMEWORK_DIR, "cores", "nRF5")
NRF5_SDK = os.path.join(
    CORES_DIR,
    "external", "nRF5_SDK", "nRF5_SDK_17.0.2_d674dde",
)

assert os.path.isdir(FRAMEWORK_DIR), (
    "framework-rui3-nrf52 package not found at %s" % FRAMEWORK_DIR
)
assert os.path.isdir(CORES_DIR), (
    "nRF5 cores directory not found at %s" % CORES_DIR
)

# Board configuration
variant = board.get("build.variant")
series = board.get("build.series")
ldscript = board.get("build.ldscript", "flash_nrf52840.ld")
float_flags = board.get("build.float_flags", "-mfloat-abi=hard -mfpu=fpv4-sp-d16 -u _printf_float")
extra_flags = board.get("build.extra_flags", "")
feature_flags = board.get("build.feature_flags", "")
prebuilt_libs = board.get("build.prebuilt_libs", "")

VARIANT_DIR = os.path.join(FRAMEWORK_DIR, "variants", variant)

# Helper: join path relative to cores dir, with optional existence guard
def cores_join(*parts):
    return os.path.join(CORES_DIR, *parts)

def sdk_join(*parts):
    return os.path.join(NRF5_SDK, *parts)


# ---------------------------------------------------------------------------
# Compiler flags
# ---------------------------------------------------------------------------

env.Append(
    ASFLAGS=[
        "-g",
        "-x", "assembler-with-cpp",
    ],

    CCFLAGS=[
        "-mcpu=%s" % board.get("build.cpu"),
        "-mthumb",
        "-Os",
        "-g",
        "-ffunction-sections",
        "-fdata-sections",
        "--param", "max-inline-insns-single=500",
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
        "-mcpu=%s" % board.get("build.cpu"),
        "-mthumb",
        "-Wl,--cref",
        "-Wl,--check-sections",
        "-Wl,--gc-sections",
        "-Wl,--unresolved-symbols=report-all",
        "-Wl,--warn-common",
        "--specs=nano.specs",
        "--specs=nosys.specs",
    ] + float_flags.split(),

    LIBS=["c", "m", "nosys", "stdc++"],
)

# ---------------------------------------------------------------------------
# Preprocessor defines
# ---------------------------------------------------------------------------

# Arduino compatibility defines
env.Append(CPPDEFINES=[
    ("ARDUINO", 10808),
    ("ARDUINO_%s" % variant, 1),
    "ARDUINO_ARCH_NRF5",
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
if "NO_LORA_SUPPORT" not in feature_flags:
    env.Append(CPPDEFINES=[
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
        "REGION_LA915",
    ])

# ---------------------------------------------------------------------------
# Include paths
# ---------------------------------------------------------------------------

# All include paths from boards.txt (RAK4631 as canonical reference),
# with os.path.isdir() guards for stale/missing directories.
inc_paths = [
    # Variant
    VARIANT_DIR,
    # App per-board source (boards.txt references cores/nRF5/app/BOARD/src,
    # which only exists for RAK4631 in the BSP; guard handles missing dirs)
    cores_join("app", variant.replace("WisCore_", "").replace("_Board", ""), "src"),
    # Component includes
    cores_join("component", "inc"),
    # MCU core
    cores_join("component", "core", "mcu", "nrf52840"),
    cores_join("component", "core", "mcu", "nrf52840", "uhal"),
    cores_join("component", "core", "mcu", "nrf52840", "uhal", "serial"),
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
    # LoRaMac-node-4.4.7
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "mac"),
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "mac", "region"),
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "radio"),
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "system"),
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "peripherals"),
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "apps", "LoRaMac", "common", "LmHandler"),
    cores_join("external", "lora", "LoRaMac-node-4.4.7", "src", "boards"),
    # FatFs / SPIFFS / micro-ecc
    cores_join("external", "FatFs", "source"),
    cores_join("external", "spiffs", "src"),
    cores_join("external", "micro_ecc"),
    # nRF5 SDK 17.0.2 — libraries
    sdk_join("components", "libraries", "log"),
    sdk_join("components", "libraries", "ringbuf"),
    sdk_join("components", "libraries", "log", "src"),
    sdk_join("components", "libraries", "memobj"),
    sdk_join("components", "libraries", "mutex"),
    # SoftDevice S140 headers
    sdk_join("components", "softdevice", "s140", "headers"),
    sdk_join("components", "softdevice", "s140", "headers", "nrf52"),
    # BLE
    sdk_join("components", "ble", "nrf_ble_scan"),
    sdk_join("components", "ble", "ble_link_ctx_manager"),
    sdk_join("components", "ble", "ble_db_discovery"),
    sdk_join("components", "ble", "nrf_ble_gatt"),
    sdk_join("components", "ble", "peer_manager"),
    sdk_join("components", "softdevice", "common"),
    sdk_join("components", "ble", "common"),
    sdk_join("components", "ble", "ble_services", "ble_nus"),
    sdk_join("components", "ble", "ble_services", "ble_nus_c"),
    sdk_join("components", "ble", "ble_advertising"),
    sdk_join("components", "ble", "ble_services", "ble_dfu"),
    sdk_join("components", "ble", "nrf_ble_qwr"),
    sdk_join("components", "ble", "ble_services", "ble_hids"),
    sdk_join("components", "ble", "ble_services", "ble_bas"),
    sdk_join("components", "ble", "ble_services", "ble_dis"),
    sdk_join("components", "ble", "nrf_ble_gq"),
    # Serial / USB
    sdk_join("components", "libraries", "serial"),
    sdk_join("components", "libraries", "queue"),
    sdk_join("components", "libraries", "usbd"),
    sdk_join("components", "libraries", "usbd", "class", "cdc", "acm"),
    sdk_join("components", "libraries", "usbd", "class", "cdc"),
    sdk_join("external", "utf_converter"),
    sdk_join("components", "drivers_nrf", "usbd"),
    # Drivers / HAL
    sdk_join("modules", "nrfx", "drivers", "include"),
    sdk_join("modules", "nrfx", "hal"),
    sdk_join("modules", "nrfx", "mdk"),
    sdk_join("modules", "nrfx", "drivers", "src", "prs"),
    sdk_join("modules", "nrfx", "drivers", "src"),
    sdk_join("modules", "nrfx"),
    sdk_join("integration", "nrfx"),
    sdk_join("integration", "nrfx", "legacy"),
    # Bootloader / DFU / Power
    sdk_join("components", "libraries", "bootloader"),
    sdk_join("components", "libraries", "bootloader", "ble_dfu"),
    sdk_join("components", "libraries", "bootloader", "dfu"),
    sdk_join("components", "libraries", "pwr_mgmt"),
    sdk_join("components", "libraries", "svc"),
    # Crypto
    sdk_join("components", "libraries", "crypto"),
    sdk_join("components", "libraries", "crypto", "backend", "cc310"),
    sdk_join("components", "libraries", "crypto", "backend", "cc310_bl"),
    sdk_join("components", "libraries", "crypto", "backend", "nrf_sw"),
    sdk_join("components", "libraries", "crypto", "backend", "mbedtls"),
    sdk_join("components", "libraries", "crypto", "backend", "oberon"),
    sdk_join("components", "libraries", "crypto", "backend", "micro_ecc"),
    sdk_join("components", "libraries", "crypto", "backend", "optiga"),
    sdk_join("components", "libraries", "crypto", "backend", "nrf_hw"),
    sdk_join("components", "libraries", "crypto", "backend", "cifra"),
    sdk_join("external", "nrf_cc310_bl", "include"),
    sdk_join("external", "nrf_cc310", "include"),
    sdk_join("external", "mbedtls", "include"),
    sdk_join("external", "mbedtls", "include", "mbedtls"),
    # Storage
    sdk_join("components", "libraries", "fstorage"),
    sdk_join("components", "libraries", "fds"),
    sdk_join("components", "libraries", "crc32"),
    sdk_join("components", "libraries", "sha256"),
    # Misc utility libraries
    sdk_join("components", "libraries", "balloc"),
    sdk_join("components", "libraries", "atomic"),
    sdk_join("components", "libraries", "atomic_flags"),
    sdk_join("components", "libraries", "atomic_fifo"),
    sdk_join("components", "libraries", "experimental_section_vars"),
    sdk_join("components", "libraries", "strerror"),
    sdk_join("components", "libraries", "util"),
    sdk_join("components", "libraries", "timer"),
    sdk_join("components", "libraries", "fifo"),
    sdk_join("components", "libraries", "uart"),
    sdk_join("components", "libraries", "delay"),
    sdk_join("components", "libraries", "bsp"),
    sdk_join("components", "libraries", "button"),
    sdk_join("components", "libraries", "pwm"),
    sdk_join("components", "libraries", "hardfault"),
    sdk_join("components", "libraries", "hardfault", "nrf52"),
    sdk_join("components", "libraries", "stack_info"),
    sdk_join("components", "libraries", "sortlist"),
    sdk_join("components", "libraries", "sensorsim"),
    sdk_join("components", "libraries", "scheduler"),
    sdk_join("components", "libraries", "cli"),
    sdk_join("components", "libraries", "cli", "uart"),
    # Components root / boards / toolchain
    sdk_join("components"),
    sdk_join("components", "boards"),
    sdk_join("components", "toolchain", "cmsis", "include"),
    sdk_join("components", "softdevice", "common"),
    # NFC
    sdk_join("components", "nfc", "t4t_lib"),
    sdk_join("components", "nfc", "ndef", "generic", "message"),
    sdk_join("components", "nfc", "ndef", "text"),
    sdk_join("components", "nfc", "ndef", "uri"),
    sdk_join("components", "nfc", "ndef", "launchapp"),
    sdk_join("components", "nfc", "ndef", "generic", "record"),
    sdk_join("components", "nfc", "platform"),
    # RUI Nordic-specific
    sdk_join("RUI", "Source", "nordic", "service", "wdt"),
    sdk_join("RUI", "Source", "nordic", "app"),
    sdk_join("RUI", "Source", "nordic", "include"),
    sdk_join("RUI", "Source", "nordic", "service", "ble_central"),
    sdk_join("RUI", "build", "nordic", "RTE"),
    # SEGGER RTT / fprintf
    sdk_join("external", "segger_rtt"),
    sdk_join("external", "fprintf"),
]

# Filter out non-existent directories
env.Append(CPPPATH=[p for p in inc_paths if p and os.path.isdir(p)])

# ---------------------------------------------------------------------------
# Library search paths (for linker -L flags)
# ---------------------------------------------------------------------------

lib_paths = [
    # Core
    cores_join("app"),
    cores_join("component", "core", "mcu", "nrf52840"),
    cores_join("component", "core", "mcu", "nrf52840", "uhal"),
    cores_join("external"),
    cores_join("component", "core", "board", series),
    # udrv
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
    # Services
    cores_join("component", "service", "nvm"),
    cores_join("component", "service", "lora"),
    cores_join("component", "service", "runtimeConfig"),
    cores_join("component", "service", "battery"),
    cores_join("component", "service", "mode"),
    cores_join("component", "service", "debug"),
    # Other
    cores_join("component", "rui_v3_api"),
    cores_join("component", "fund", "event_queue"),
    cores_join("component", "fund", "circular_queue"),
    # Prebuilt libraries (by name, board-specific)
    sdk_join("external", "nrf_cc310", "lib", "cortex-m4", "hard-float"),
    sdk_join("external", "nrf_oberon", "lib", "cortex-m4", "hard-float"),
    sdk_join("components", "nfc", "t4t_lib"),
    # nrf_common.ld is found here (required by flash_nrf52840.ld INCLUDE directive)
    sdk_join("modules", "nrfx", "mdk"),
    # Variant
    VARIANT_DIR,
]

env.Append(LIBPATH=[p for p in lib_paths if os.path.isdir(p)])

# ---------------------------------------------------------------------------
# Linker script
# ---------------------------------------------------------------------------

ld_dir = cores_join("component", "core", "mcu", "nrf52840")
ld_file = os.path.join(ld_dir, ldscript)

if os.path.isfile(ld_file):
    # Let PlatformIO's piobuild.py prepend "-T $LDSCRIPT_PATH".
    # Do NOT add "-T" to LINKFLAGS manually — piobuild checks for "-Wl,-T"
    # (not bare "-T"), so a manual "-T" would result in duplicate linker scripts.
    env.Replace(LDSCRIPT_PATH=ld_file)
else:
    env.Exit("Error: linker script not found: %s" % ld_file)

# Map file
env.Append(LINKFLAGS=[
    "-Wl,-Map,%s" % os.path.join("$BUILD_DIR", "${PROGNAME}.map"),
])

# ---------------------------------------------------------------------------
# Prebuilt libraries (board-specific)
# ---------------------------------------------------------------------------

# Parse "build.prebuilt_libs" from board JSON.
# Handles both -lname (normal) and -l:filename (exact filename, no lib prefix).
for lib_flag in prebuilt_libs.split():
    if lib_flag.startswith("-l:"):
        # Colon syntax tells ld to match the filename exactly, not "lib" + name.
        # Must go into LINKFLAGS (not LIBS) since SCons always prepends "lib".
        env.Append(LINKFLAGS=[lib_flag])
    elif lib_flag.startswith("-l"):
        env.Append(LIBS=[lib_flag[2:]])

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

# Build cores/nRF5/ as a library, broadly including component/ and external/
# and filtering out .fuota alternate sources.
src_filter = [
    "+<component/>",
    "+<external/lora/>",
    "+<external/FatFs/>",
    "+<external/spiffs/>",
    "+<external/micro_ecc/>",
    "+<external/nRF5_SDK/>",
    "+<app/app_glue.cpp>",
    # Exclude FUOTA alternate sources
    "-<**/*.c.fuota>",
    "-<**/*.cpp.fuota>",
    # Exclude prebuilt static libraries (not source)
    "-<external/nRF5_SDK/nRF5_SDK_17.0.2_d674dde/external/nrf_cc310/>",
    "-<external/nRF5_SDK/nRF5_SDK_17.0.2_d674dde/external/nrf_oberon/>",
    "-<external/nRF5_SDK/nRF5_SDK_17.0.2_d674dde/external/nrf_cc310_bl/>",
    # Exclude SDK error handlers — the variant's rui_inner_main.c provides
    # its own implementations that take precedence over these SDK defaults.
    "-<external/nRF5_SDK/nRF5_SDK_17.0.2_d674dde/components/libraries/util/app_error.c>",
    "-<external/nRF5_SDK/nRF5_SDK_17.0.2_d674dde/components/libraries/util/app_error_handler_gcc.c>",
]

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
