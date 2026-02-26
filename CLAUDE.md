# RAKwireless RUI3 PlatformIO Platform

## Project Overview

Custom PlatformIO platform wrapping the RAKwireless RUI3 BSP repos. Ships as a single repo with all build logic — no forks of upstream RAK repos. Framework packages are fetched via zip-archive URLs pinned to specific tags.

## Architecture

- `platform.json` / `platform.py` — PlatformIO platform definition
- `boards/` — Board JSON definitions (one per board variant)
- `builder/main.py` — SCons entry point
- `builder/frameworks/rui3.py` — Framework router (dispatches to MCU-specific scripts)
- `builder/frameworks/rui3_stm32wle.py` — STM32WLE build script
- `examples/` — Example PlatformIO projects

## Conventions

- **Cross-platform paths**: Always use `os.path.join()`, never hardcoded `/` or `\\`
- **Pure Python tools**: No platform-specific executables. All build helpers are Python.
- **No upstream forks**: Build logic wraps the upstream BSP as-is. If a BSP bug blocks us, fork only as last resort.
- **GitHub zip prefix**: Zips from GitHub have a `REPO-TAG/` prefix dir. PlatformIO handles this transparently.
- **Exclude `.fuota` files**: Files with `.fuota` suffix are alternate sources for FUOTA builds — exclude by default.

## Phased Approach

1. **Phase 1 (MVP)**: STM32WLE / RAK3172 family
2. **Phase 2**: nRF52 / RAK4631
3. **Phase 3**: Apollo3 / RAK11720
4. **Phase 4**: Polish, CI/CD, docs

## Build & Test

```bash
# Install platform locally for testing
pio pkg install -p file:///path/to/this/repo

# Uninstall
pio pkg uninstall -p rakwireless-rui3

# Build example
cd examples/lorawan-otaa && pio run

# List boards
pio boards --installed
```

## Key Reference Files (local only, not in repo)

- `references/RAK-STM32-RUI/` — STM32WLE BSP (tag RUI_5.0.0)
- `references/RAK-nRF52-RUI/` — nRF52 BSP (tag RUI_4.1.2)
- `references/RAK-STM32-RUI/boards.txt` — Board defines, include paths
- `references/RAK-STM32-RUI/platform.txt` — Compiler flags, recipes
