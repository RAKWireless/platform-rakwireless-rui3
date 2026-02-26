# RAKwireless RUI3 PlatformIO Platform

## Project Overview

Custom PlatformIO platform wrapping the RAKwireless RUI3 BSP repos. Ships as a single repo with all build logic — no forks of upstream RAK repos. Framework packages are fetched via zip-archive URLs pinned to specific tags.

## Architecture

- `platform.json` / `platform.py` — PlatformIO platform definition
- `boards/` — Board JSON definitions (one per board variant)
- `builder/main.py` — SCons entry point
- `builder/frameworks/rui3.py` — Framework router (dispatches to MCU-specific scripts)
- `builder/frameworks/rui3_stm32wle.py` — STM32WLE build script
- `builder/frameworks/rui3_nrf52.py` — nRF52 build script
- `builder/frameworks/rui3_apollo3.py` — Apollo3 build script
- `examples/` — Example PlatformIO projects (lorawan-otaa, system-info)

## Conventions

- **Cross-platform paths**: Always use `os.path.join()`, never hardcoded `/` or `\\`
- **Pure Python tools**: No platform-specific executables. All build helpers are Python.
- **No upstream forks**: Build logic wraps the upstream BSP as-is. Fork only as last resort.
- **GitHub zip prefix**: Zips from GitHub have a `REPO-TAG/` prefix dir. PlatformIO handles this transparently.
- **Exclude `.fuota` files**: Files with `.fuota` suffix are alternate sources for FUOTA builds — exclude by default.
- **No SUPPORT_FUOTA**: Never define this in board JSONs — FUOTA package files are incompatible with LoRaMac 4.7.0 API. platform.py patches them at install time instead.
- **LORA_STACK_104**: Always defined in board JSONs — renames `LmhPackage_t.IsRunning` → `IsTxPending` for LoRaMac 4.7.0 compat.
- **LoRaMac-node 4.7.0**: All three BSPs require it (LORAMAC_REGION_LA915 + NetworkActivation).

## Phased Approach

1. **Phase 1 (DONE)**: STM32WLE / RAK3172 family — builds: Flash ~43%, RAM ~38%
2. **Phase 2 (DONE)**: nRF52 / RAK4631 — builds: Flash 57.5%, RAM 37.6%
3. **Phase 3 (DONE)**: Apollo3 / RAK11720 — builds: Flash 30.5%, RAM 39.9%
4. **Phase 4**: Polish, publish to PlatformIO registry, CI/CD, docs

## BSP Packages (all at v4.2.3_363)

- `framework-rui3-stm32wle` → `RAK-STM32-RUI/archive/refs/tags/v4.2.3_363.zip`
- `framework-rui3-nrf52` → `RAK-nRF52-RUI/archive/refs/tags/v4.2.3_363.zip`
- `framework-rui3-apollo3` → `RAK-APOLLO3-RUI/archive/refs/tags/v4.2.3_363.zip`

## Build & Test

```bash
# Install platform locally for testing (run from inside an example dir)
cd examples/lorawan-otaa
pio pkg install -p file:///path/to/this/repo --force

# Build all boards
pio run -e rak3172
pio run -e rak4631
pio run -e rak11720

# Build all at once
pio run

# List boards
pio boards --installed
```

## Key Reference Files (local only, not in repo)

- `references/RAK-STM32-RUI/` — STM32WLE BSP (tag v4.2.3_363)
- `references/RAK-nRF52-RUI/` — nRF52 BSP (tag v4.2.3_363)
- `references/RAK-APOLLO3-RUI/` — Apollo3 BSP (tag v4.2.3_363)
- Each BSP's `boards.txt` — Board defines, include paths (reference only; builder auto-discovers paths)
- Each BSP's `platform.txt` — Compiler flags, recipes (reference only)

## platform.py: Key Install Mechanism

BSPs have no `package.json` — `platform.py` overrides `install_required_packages()` to:
1. Download zip, extract, inject `package.json`, write `.piopm` metadata
2. Apply FUOTA compatibility patches via `_patch_fuota_packages(pkg_dir, mcu_dir)`
   - `mcu_dir`: `"nRF5"` / `"STM32WLE"` / `"apollo3"`
   - Patches guard `LmhpFragmentation.c`, `LmhpClockSync.c`, `LmhpRemoteMcastSetup.c`
     with `#ifdef LORA_STACK_104` for `IsTxPending` / `LmHandlerSend`
   - Normalizes CRLF → LF before patching (STM32 BSP uses CRLF)

## Builder Patterns (hard-won lessons)

- **Linker script**: `env.Replace(LDSCRIPT_PATH=full_path)` — never `env.Append(LINKFLAGS=["-T", path])`
- **Assembler**: `AS = arm-none-eabi-gcc` with `-x assembler-with-cpp` (BSP .S files use GCC preprocessor)
- **Double-call pitfall**: Never call framework scripts manually from `builder/main.py` — `BuildProgram()` already calls `BuildFrameworks()`
- **FreeRTOS ports**: Exclude IAR/Keil ports from src_filter — use only GCC port
- **Apollo3 specifics**: No prebuilt .a libs (all source); startup is `startup_gcc.c` (C, not .S); FreeRTOS port is `GCC/AMapollo2/`
- **nRF52 specifics**: Prebuilt cc310/oberon/t4t libs; exclude `app_error.c` + `app_error_handler_gcc.c` (variant overrides them)
