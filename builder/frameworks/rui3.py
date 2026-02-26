"""
RUI3 framework router.

Reads board.build.core and dispatches to the MCU-specific build script.
"""

Import("env")

core = env.BoardConfig().get("build.core", "")

if core == "STM32WLE":
    env.SConscript("rui3_stm32wle.py", exports="env")
elif core == "nRF5":
    env.SConscript("rui3_nrf52.py", exports="env")
elif core == "apollo3":
    env.SConscript("rui3_apollo3.py", exports="env")
else:
    env.Exit("Error: unsupported RUI3 core '%s'" % core)
