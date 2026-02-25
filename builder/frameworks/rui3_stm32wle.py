"""
RUI3 build script for STM32WLE (RAK3172 family).

Translates the Arduino-style boards.txt / platform.txt configuration
into PlatformIO SCons build environment settings.
"""

import os
import sys

Import("env")


platform = env.PioPlatform()
board = env.BoardConfig()

FRAMEWORK_DIR = platform.get_package_dir("framework-rui3-stm32wle")
CORES_DIR = os.path.join(FRAMEWORK_DIR, "cores", "STM32WLE")

assert os.path.isdir(FRAMEWORK_DIR), (
    "framework-rui3-stm32wle package not found at %s" % FRAMEWORK_DIR
)
assert os.path.isdir(CORES_DIR), (
    "STM32WLE cores directory not found at %s" % CORES_DIR
)

# Board configuration
variant = board.get("build.variant")
series = board.get("build.series")
app_path = board.get("build.app_path", "")
ldscript = board.get("build.ldscript", "app_stm32wle5xx.ld")
float_flags = board.get("build.float_flags", "-mfpu=fpv4-sp-d16 -u _printf_float")
extra_flags = board.get("build.extra_flags", "")
feature_flags = board.get("build.feature_flags", "")

VARIANT_DIR = os.path.join(FRAMEWORK_DIR, "variants", variant)

# Helper: join path relative to cores dir, with existence guard
def cores_join(*parts):
    return os.path.join(CORES_DIR, *parts)


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
    "ARDUINO_ARCH_STM32WLE",
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

# LoRa support — default to LoRa + P2P with all regions enabled
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

# All include paths from boards.txt, with isdir guards for stale entries
inc_paths = [
    # Variant
    VARIANT_DIR,
    os.path.join(FRAMEWORK_DIR, "system", variant),
    # App (stale in most BSP versions, guarded)
    cores_join("app", app_path, "src") if app_path else None,
    cores_join("component", "inc"),
    # MCU core
    cores_join("component", "core", "mcu", "stm32wle5xx"),
    cores_join("component", "core", "mcu", "stm32wle5xx", "uhal"),
    cores_join("component", "core", "mcu", "stm32wle5xx", "uhal", "serial"),
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
    # LoRaMac-node
    cores_join("external", "lora", "LoRaMac-node-4.7.0", "src", "mac"),
    cores_join("external", "lora", "LoRaMac-node-4.7.0", "src", "mac", "region"),
    cores_join("external", "lora", "LoRaMac-node-4.7.0", "src", "radio"),
    cores_join("external", "lora", "LoRaMac-node-4.7.0", "src", "system"),
    cores_join("external", "lora", "LoRaMac-node-4.7.0", "src", "peripherals"),
    cores_join("external", "lora", "LoRaMac-node-4.7.0", "src", "boards"),
    # STM32CubeWL
    cores_join("external", "STM32CubeWL", "Drivers", "CMSIS", "Device", "ST", "STM32WLxx", "Include"),
    cores_join("external", "STM32CubeWL", "Drivers", "CMSIS", "Include"),
    cores_join("external", "STM32CubeWL", "Drivers", "STM32WLxx_HAL_Driver", "Inc"),
    cores_join("external", "STM32CubeWL", "Middlewares", "Third_Party", "SubGHz_Phy", "stm32_radio_driver"),
    cores_join("external", "STM32CubeWL", "Middlewares", "Third_Party", "SubGHz_Phy"),
    cores_join("external", "STM32CubeWL", "Utilities", "timer"),
    cores_join("external", "STM32CubeWL", "Utilities", "lpm", "tiny_lpm"),
    cores_join("external", "STM32CubeWL", "Utilities", "misc"),
    cores_join("external", "STM32CubeWL", "Utilities", "sequencer"),
    cores_join("external", "STM32CubeWL", "Utilities", "trace", "adv_trace"),
    cores_join("external", "STM32CubeWL", "Libraries", "queue"),
    cores_join("external", "STM32CubeWL", "Libraries", "include"),
    cores_join("external", "STM32CubeWL", "Libraries", "scheduler"),
    # FatFs / SPIFFS
    cores_join("external", "FatFs", "source"),
    cores_join("external", "spiffs", "src"),
]

# Filter out None entries and non-existent directories
env.Append(CPPPATH=[p for p in inc_paths if p and os.path.isdir(p)])

# ---------------------------------------------------------------------------
# Library search paths (for linker -L flags)
# ---------------------------------------------------------------------------

lib_paths = [
    cores_join("app"),
    cores_join("component", "core", "mcu", "stm32wle5xx"),
    cores_join("component", "core", "mcu", "stm32wle5xx", "uhal"),
    cores_join("external"),
    cores_join("component", "core", "board", series),
    cores_join("component", "udrv", "serial"),
    cores_join("component", "udrv", "flash"),
    cores_join("component", "udrv", "timer"),
    cores_join("component", "service", "nvm"),
    cores_join("component", "udrv", "system"),
    cores_join("component", "udrv", "powersave"),
    cores_join("component", "udrv", "wdt"),
    cores_join("component", "udrv", "gpio"),
    cores_join("component", "udrv", "twimst"),
    cores_join("component", "udrv", "delay"),
    cores_join("component", "udrv", "rtc"),
    cores_join("component", "service", "lora"),
    cores_join("component", "service", "runtimeConfig"),
    cores_join("component", "udrv", "dfu"),
    cores_join("component", "udrv", "pwm"),
    cores_join("component", "udrv", "crypto"),
    cores_join("component", "udrv", "trng"),
    cores_join("component", "udrv", "adc"),
    cores_join("component", "udrv", "pdm"),
    cores_join("component", "udrv", "spimst"),
    cores_join("component", "service", "battery"),
    cores_join("component", "service", "mode"),
    cores_join("component", "service", "debug"),
    cores_join("component", "rui_v3_api"),
    cores_join("component", "fund", "event_queue"),
    cores_join("component", "fund", "circular_queue"),
    VARIANT_DIR,
    os.path.join(FRAMEWORK_DIR, "system", variant),
]

env.Append(LIBPATH=[p for p in lib_paths if os.path.isdir(p)])

# ---------------------------------------------------------------------------
# Linker script + FUOTA symbols
# ---------------------------------------------------------------------------

# Linker script lives in the MCU core directory
ld_dir = cores_join("component", "core", "mcu", "stm32wle5xx")
ld_file = os.path.join(ld_dir, ldscript)

if os.path.isfile(ld_file):
    # Let PlatformIO's piobuild.py prepend "-T $LDSCRIPT_PATH" (piobuild.py:66-67).
    # Do NOT add "-T" to LINKFLAGS manually — piobuild checks for "-Wl,-T" (not "-T"),
    # so a manual "-T" would result in two linker scripts being passed.
    env.Replace(LDSCRIPT_PATH=ld_file)
else:
    env.Exit("Error: linker script not found: %s" % ld_file)

# FUOTA prebuilt symbols
fuota_symbols = os.path.join(FRAMEWORK_DIR, "prebuilt", "RUI_fuota_stack_1.0.0")
if os.path.isfile(fuota_symbols):
    env.Append(LINKFLAGS=[
        "-Wl,--just-symbols=%s" % fuota_symbols,
    ])

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

# Build the cores/STM32WLE tree as a library, excluding .fuota files
# We use a broad src_filter and rely on the compiler to handle unused symbols
# via -ffunction-sections + --gc-sections.

src_filter = [
    "+<component/>",
    "+<external/>",
    "+<app/app_glue.cpp>",
    # Exclude .fuota alternate sources
    "-<**/*.c.fuota>",
    "-<**/*.cpp.fuota>",
    # Exclude FreeRTOS Tasking port — uses Tasking-specific ASM syntax, not GCC
    "-<external/STM32CubeWL/Middlewares/Third_Party/FreeRTOS/Source/portable/Tasking/>",
    # Exclude IAR and Keil (RVDS) RTOS ports — wrong toolchain
    "-<external/STM32CubeWL/Middlewares/Third_Party/FreeRTOS/Source/portable/IAR/>",
    "-<external/STM32CubeWL/Middlewares/Third_Party/FreeRTOS/Source/portable/RVDS/>",
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

# Startup assembly (in MCU core dir)
startup_file = cores_join(
    "component", "core", "mcu", "stm32wle5xx", "startup_stm32wl55xx_cm4.S"
)
if os.path.isfile(startup_file):
    libs.append(
        env.BuildLibrary(
            os.path.join("$BUILD_DIR", "FrameworkRUI3Startup"),
            os.path.dirname(startup_file),
            src_filter="+<%s>" % os.path.basename(startup_file),
        )
    )

env.Prepend(LIBS=libs)
