# Product Requirements Document: rakwireless-platformio-rui3

## 1. Overview

**Project**: rakwireless-platformio-rui3
**Goal**: Build a custom PlatformIO platform that enables compiling, uploading, and debugging RAKwireless RUI3 firmware for all three supported MCU families — from a standard `platformio.ini` workflow.

**Problem**: RUI3 has zero official PlatformIO support. Developers are locked into Arduino IDE, VS Code (Arduino extension), or Visual Studio. This limits access to PlatformIO's build system, dependency management, CI/CD integration, and multi-environment workflows.

**Solution**: A single custom PlatformIO platform (`platform-rakwireless-rui3`) with per-MCU framework packages, following the proven multi-chip-family pattern established by [LibreTiny](https://github.com/libretiny-eu/libretiny).

---

## 2. Supported Targets

| Board ID | MCU | Radio | Connectivity | BSP Version | Upload Method |
|---|---|---|---|---|---|
| RAK3172 | STM32WLE5CC (Cortex-M4 @ 48 MHz) | Integrated SX126x | LoRaWAN | RUI_5.0.0 | YMODEM serial |
| RAK3172-T | STM32WLE5CC | Integrated SX126x | LoRaWAN | RUI_5.0.0 | YMODEM serial |
| RAK3272-SiP | STM32WLE5CC | Integrated SX126x | LoRaWAN | RUI_5.0.0 | YMODEM serial |
| RAK3272LP-SiP | STM32WLE5CC | Integrated SX126x | LoRaWAN | RUI_5.0.0 | YMODEM serial |
| RAK4631 | nRF52840 (Cortex-M4F @ 64 MHz) | SX1262 (SPI) | LoRaWAN + BLE 5.0 | 4.1.2 | DFU zip (nrfutil) |
| RAK5010 | nRF52840 | SX1262 (SPI) | LoRaWAN + BLE + Cellular | 4.1.2 | DFU zip (nrfutil) |
| RAK3401 | nRF52840 | SX1262 (SPI) | LoRaWAN + BLE | 4.1.2 | DFU zip (nrfutil) |
| RAK11720 | Apollo3 Blue (Cortex-M4F) | SX1262 (external) | LoRaWAN + BLE | TBD | TBD |

---

## 3. Target Developer Experience

A developer should be able to create a project with a minimal `platformio.ini` and immediately compile and upload RUI3 firmware:

```ini
[env:rak3172]
platform = rakwireless
board = rak3172
framework = rui3

build_flags =
    -DSUPPORT_LORA
    -DREGION_EU868
    -DSUPPORT_AT

monitor_speed = 115200
```

```ini
[env:rak4631]
platform = rakwireless
board = rak4631
framework = rui3

build_flags =
    -DSUPPORT_LORA
    -DSUPPORT_BLE
    -DREGION_US915
```

The user sketch is a standard Arduino-style `setup()` / `loop()` file that includes `Arduino.h` and uses the RUI3 API (`RAKLorawan`, `RAKBle`, `RAKSystem`, etc.).

---

## 4. Upstream Integration Strategy

### Relationship to RAK BSP Repositories

This project does **not** fork, replace, or modify the official RAKwireless BSP repositories. It is a **thin build-integration layer** that consumes them as-is:

| Upstream Repo | Owner | Our Role |
|---|---|---|
| [RAKWireless/RAK-STM32-RUI](https://github.com/RAKWireless/RAK-STM32-RUI) | RAKwireless | Consume via zip-archive URL, tag-pinned |
| [RAKWireless/RAK-nRF52-RUI](https://github.com/RAKWireless/RAK-nRF52-RUI) | RAKwireless | Consume via zip-archive URL, tag-pinned |
| [RAKWireless/RAK-APOLLO3-RUI](https://github.com/RAKWireless/RAK-APOLLO3-RUI) | RAKwireless | Consume via zip-archive URL, tag-pinned |

### Approach: No-Fork Wrapper with Zip-Archive URLs

PlatformIO's package manager can download zip archives directly from GitHub and use the package name from `platform.json` — no `package.json` is required inside the upstream repo. We reference each BSP as a tagged zip download:

```json
{
  "packages": {
    "framework-rui3-stm32wle": {
      "type": "framework",
      "optional": true,
      "version": "https://github.com/RAKWireless/RAK-STM32-RUI/archive/refs/tags/RUI_5.0.0.zip"
    },
    "framework-rui3-nrf52": {
      "type": "framework",
      "optional": true,
      "version": "https://github.com/RAKWireless/RAK-nRF52-RUI/archive/refs/tags/RUI_4.1.2.zip"
    },
    "framework-rui3-apollo3": {
      "type": "framework",
      "optional": true,
      "version": "https://github.com/RAKWireless/RAK-APOLLO3-RUI/archive/refs/tags/TBD.zip"
    }
  }
}
```

### Why This Strategy

**Alternatives considered:**

| Strategy | Verdict | Why |
|---|---|---|
| PRs to upstream RAK repos | Rejected | RAKwireless has shown no interest in PlatformIO; PRs could sit unmerged indefinitely. Creates a dependency on a third party for our release cycle. |
| Forked repos with `package.json` | Rejected as default | 4 repos to maintain instead of 1. Merge overhead on every upstream release. Fork divergence risk. Only justified if we need to patch BSP source. |
| **No-fork zip-archive wrapper** | **Chosen** | Single repo. Zero forks. Zero divergence. Upstream updates = bump tag in one file. Proven pattern (maxgerhardt's PoC used this). |
| Thin wrapper referencing local Arduino install | Rejected | Terrible UX. Requires Arduino IDE installed. No CI/CD support. |
| Custom download script at install time | Rejected | Reinvents PlatformIO's package manager. Adds complexity without benefit. |

### What We Own vs. What Upstream Owns

```
RAKWireless/RAK-*-RUI (UPSTREAM — untouched)
├── boards.txt              ← Arduino-only, we ignore
├── platform.txt            ← Arduino-only, we read for reference only
├── programmers.txt         ← Arduino-only, we ignore
├── cores/                  ← WE COMPILE THIS (source, headers, startup)
├── variants/               ← WE COMPILE THIS (board-specific source)
├── prebuilt/               ← WE REFERENCE THIS (bootloaders, FUOTA symbols)
├── security/               ← WE REFERENCE THIS (DFU signing key, nRF52 only)
└── libraries/              ← WE OPTIONALLY EXPOSE THIS (example sketches)

platform-rakwireless-rui3 (OUR REPO — single repo, all build logic)
├── platform.json           ← Zip-archive URLs to upstream + tool packages
├── platform.py             ← MCU family routing
├── boards/*.json           ← Our board definitions (replaces boards.txt)
├── builder/frameworks/     ← Our SCons build scripts (replaces platform.txt)
├── tools/                  ← Our upload tools (pure Python)
└── examples/               ← Our example projects
```

### Upstream Update Workflow

When RAKwireless releases a new BSP version (e.g., `RUI_6.0.0`):

1. **Update the tag** in `platform.json`:
   ```diff
   - "version": "https://github.com/RAKWireless/RAK-STM32-RUI/archive/refs/tags/RUI_5.0.0.zip"
   + "version": "https://github.com/RAKWireless/RAK-STM32-RUI/archive/refs/tags/RUI_6.0.0.zip"
   ```

2. **Run CI** — compile all boards on all OSes.

3. **If CI passes**: tag a new platform release. Done.

4. **If CI fails** (upstream restructured directories, renamed files, changed compiler flags):
   - Update builder scripts to match the new layout.
   - If a BSP source bug blocks compilation and RAK won't fix it:
     - **Escape hatch**: fork that one repo, apply the patch, point `platform.json` at the fork.
     - File an upstream issue/PR and revert to the upstream URL once merged.

### Version Alignment

Our platform version tracks upstream BSP versions with a mapping scheme:

| Upstream Tag | Platform Version | Notes |
|---|---|---|
| `RUI_5.0.0` (STM32) | `1.0.0` | Initial release, Phase 1 |
| `RUI_4.1.2` (nRF52) | `1.1.0` | Phase 2 adds nRF52 support |
| TBD (Apollo3) | `1.2.0` | Phase 3 adds Apollo3 support |
| `RUI_6.0.0` (STM32) | `1.3.0` | Upstream BSP update |

The `CHANGELOG.md` documents which upstream BSP tags each platform version is tested against.

### Upstream PR Contributions

Our `platform.py` currently injects a `package.json` into each BSP zip at install time because the upstream RAK repos do not ship one. This is the workaround that makes `get_package_dir()` work. The long-term goal is to eliminate this injection entirely by contributing `package.json` files directly to each upstream repo.

**Status of upstream PRs:**

| Repo | PR File | Status |
|---|---|---|
| [RAKWireless/RAK-STM32-RUI](https://github.com/RAKWireless/RAK-STM32-RUI) | `contrib/RAK-STM32-RUI/package.json` | Pending submission |
| [RAKWireless/RAK-nRF52-RUI](https://github.com/RAKWireless/RAK-nRF52-RUI) | `contrib/RAK-nRF52-RUI/package.json` | Pending submission |
| [RAKWireless/RAK-APOLLO3-RUI](https://github.com/RAKWireless/RAK-APOLLO3-RUI) | `contrib/RAK-APOLLO3-RUI/package.json` | Pending (Phase 3) |

**What each PR adds:**

A single `package.json` file at the repo root with the PlatformIO-compatible package name and version. The `name` field **must** match the package name declared in our `platform.json` for PlatformIO's package resolver to find the BSP automatically:

```json
{
  "name": "framework-rui3-stm32wle",
  "version": "5.0.2",
  "description": "RAKwireless RUI3 BSP for STM32WLE (RAK3172 family) — PlatformIO package manifest",
  "license": "Apache-2.0",
  "repository": { "type": "git", "url": "https://github.com/RAKWireless/RAK-STM32-RUI.git" }
}
```

**Once a PR is merged**, `platform.py` automatically uses the upstream `package.json` (it already checks for the file before injecting). No change to our code is required — only a tag bump in `platform.json` to reference the new release.

**PR submission checklist (per repo):**

1. Fork the target RAK repo
2. Copy the file from `contrib/<REPO-NAME>/package.json` to the repo root
3. Update `"version"` to match the current release tag (strip leading `v` and `_NNN` suffix for semver)
4. Open a PR with subject: `Add package.json for PlatformIO compatibility`
5. Reference this platform repo in the PR description as the consumer

---

## 5. Package Architecture

Everything we write lives in a **single repository**: `platform-rakwireless-rui3`. The upstream RAK BSP repos are consumed as external downloads — never forked, never modified.

```
platform-rakwireless-rui3/             ← SINGLE REPO (all our code)
│
├── platform.json                       # Package manifest + zip-archive URLs to upstream BSPs
├── platform.py                         # configure_default_packages() routes by MCU family
│
├── boards/
│   ├── rak3172.json                    # STM32WLE5 — WisDuo RAK3172 Evaluation Board
│   ├── rak3172t.json                   # STM32WLE5 — WisDuo RAK3172-T Board
│   ├── rak3272sip.json                 # STM32WLE5 — WisDuo RAK3272-SiP Board
│   ├── rak3272lpsip.json               # STM32WLE5 — WisDuo RAK3272LP-SiP Board
│   ├── rak4631.json                    # nRF52840  — WisBlock Core RAK4631
│   ├── rak5010.json                    # nRF52840  — WisTrio RAK5010
│   ├── rak3401.json                    # nRF52840  — WisBlock Core RAK3401
│   └── rak11720.json                   # Apollo3   — RAK11720 (Phase 3)
│
├── builder/
│   ├── main.py                         # SCons entry point — dispatches to framework builder
│   ├── buildtime.py                    # Pure Python prebuild (replaces RAK's buildtime.py/.exe)
│   └── frameworks/
│       ├── rui3.py                     # Top-level framework script — routes by MCU architecture
│       ├── rui3_stm32wle.py            # STM32WLE build: flags, includes, linker, post-build
│       ├── rui3_nrf52.py               # nRF52 build: flags, includes, SoftDevice, DFU zip
│       └── rui3_apollo3.py             # Apollo3 build (Phase 3)
│
├── tools/
│   └── uploader_ymodem.py              # Pure Python YMODEM uploader (replaces RAK's .py/.exe)
│
├── examples/
│   ├── lorawan-otaa/                   # Basic LoRaWAN OTAA join + uplink
│   │   └── src/main.cpp
│   ├── lorawan-abp/                    # LoRaWAN ABP
│   │   └── src/main.cpp
│   └── ble-beacon/                     # BLE beacon (nRF52 only)
│       └── src/main.cpp
│
└── README.md
```

### Upstream Framework Packages (downloaded automatically, never forked)

PlatformIO downloads each BSP as a zip archive at install time. The builder scripts in `builder/frameworks/` know how to compile the upstream directory layout.

| Package Name | Downloaded From | Pinned Tag | Contents Used |
|---|---|---|---|
| `framework-rui3-stm32wle` | `RAKWireless/RAK-STM32-RUI` | `RUI_5.0.0` | cores/, variants/, prebuilt/ |
| `framework-rui3-nrf52` | `RAKWireless/RAK-nRF52-RUI` | `RUI_4.1.2` | cores/, variants/, prebuilt/, security/ |
| `framework-rui3-apollo3` | `RAKWireless/RAK-APOLLO3-RUI` | TBD | cores/, variants/, prebuilt/ |

---

## 6. Configurable Build Options

RUI3 Arduino IDE uses dropdown menus. In PlatformIO these become `build_flags` or `board_build.*` fields in `platformio.ini`.

| Arduino Menu Option | PlatformIO Equivalent | Values |
|---|---|---|
| LoRa Support | `-DSUPPORT_LORA` | Define to enable |
| LoRa P2P | `-DSUPPORT_LORA_P2P` | Define to enable |
| LoRaWAN Region | `-DREGION_<REGION>` | `EU868`, `US915`, `AU915`, `KR920`, `IN865`, `AS923-1/2/3`, `EU433`, `CN470`, `RU864`, `LA915` |
| AT Command Support | `-DSUPPORT_AT` | Define to enable |
| BLE Support | `-DSUPPORT_BLE` | Define to enable (nRF52 / Apollo3 only) |
| Debug Level | `-DCFG_DEBUG=<N>` | `0` (off), `1` (error), `2` (warn), `3` (info), `4` (debug) |

Multiple regions can be enabled simultaneously:
```ini
build_flags =
    -DSUPPORT_LORA
    -DREGION_EU868
    -DREGION_US915
```

---

## 7. Build System Translation

The core engineering work is translating Arduino IDE build recipes (`platform.txt` + `boards.txt`) into PlatformIO SCons builder scripts.

### 6.1 STM32WLE Build Pipeline

**Source**: `RAK-STM32-RUI/platform.txt` + `RAK-STM32-RUI/boards.txt`

| Step | Arduino IDE | PlatformIO SCons |
|---|---|---|
| Prebuild | `buildtime.py` generates `version.c` timestamp | `env.AddPreAction()` calling same script |
| Compiler flags | `platform.txt` recipe lines | `env.Append(CCFLAGS=[...])` |
| Include paths | `boards.txt` `build.flags.inc_path` (60+ paths) | Auto-generated from framework directory tree |
| C/C++ standards | `gnu11` / `gnu++11` | `env.Append(CFLAGS=['-std=gnu11'])`, `CXXFLAGS` |
| FPU flags | `-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16` | `env.Append(CCFLAGS=[...])` |
| Linker script | `app_stm32wle5xx.ld` | `env.Append(LINKFLAGS=['-T', ldscript])` |
| FUOTA symbols | `--just-symbols=RUI_fuota_stack_1.0.0` | `env.Append(LINKFLAGS=['--just-symbols=...'])` |
| Output | `.bin` via `objcopy` | `env.AddPostAction()` or built-in ELF→BIN |
| Upload | `uploader_ymodem -f .bin -p PORT` | Custom upload target using `uploader_ymodem.py` |

### 6.2 nRF52 Build Pipeline

**Source**: `RAK-nRF52-RUI/platform.txt` + `RAK-nRF52-RUI/boards.txt`

| Step | Arduino IDE | PlatformIO SCons |
|---|---|---|
| Prebuild | `buildtime.py` generates `version.c` timestamp | `env.AddPreAction()` calling same script |
| Compiler flags | `-nostdlib`, hard-float ABI | `env.Append(CCFLAGS=[...], LINKFLAGS=['-nostdlib'])` |
| Include paths | `boards.txt` `build.flags.inc_path` (60+ paths) | Auto-generated from framework directory tree |
| Nordic SDK | nRF5_SDK_17.0.2 paths | Include via framework package paths |
| SoftDevice | `s140_nrf52_7.2.0_softdevice.hex` | Merge in post-build |
| Linker script | MCU-specific `.ld` | `env.Append(LINKFLAGS=['-T', ldscript])` |
| Post-build 1 | `objcopy` → `.hex` | Built-in ELF→HEX |
| Post-build 2 | `nrfutil settings generate` → `settings.hex` | `env.AddPostAction()` |
| Post-build 3 | `mergehex` → settings + bootloader | `env.AddPostAction()` |
| Post-build 4 | `mergehex` → full hex (app + SD + bootloader) | `env.AddPostAction()` |
| Post-build 5 | `nrfutil pkg generate` → signed `.zip` | `env.AddPostAction()` |
| Upload | `uploader -f .zip -p PORT -t nrfutil` | Custom upload target |

### 6.3 Include Path Strategy

The 60+ include paths in each `boards.txt` are the biggest translation challenge. Rather than hardcoding them, the builder script must:

1. Accept the framework package root as a base path.
2. Walk the directory tree to discover `cores/`, `components/`, `external/` subdirectories.
3. Generate include paths programmatically using a whitelist of known directory patterns.
4. Validate against the known set from `boards.txt` to catch missing paths.

This approach survives framework version updates without manual path maintenance.

---

## 8. Upload Tools

### 7.1 YMODEM Uploader (STM32WLE)

Wraps RAK's `uploader_ymodem.py` as a PlatformIO tool package.

- **Input**: `.bin` firmware file + serial port
- **Protocol**: YMODEM over UART at default baud
- **Invocation**: `uploader_ymodem.py -f firmware.bin -p /dev/ttyUSB0`
- **Prior art**: maxgerhardt's PoC validated this works

### 7.2 DFU Uploader (nRF52)

Uses `nrfutil` to upload signed DFU zip packages.

- **Input**: `.zip` DFU package + serial port
- **Dependencies**: `nrfutil` (PC tool from Nordic, already packaged by PlatformIO as `tool-nrfutil`)
- **Signing key**: `security/private.key` shipped with framework package (override via `board_build.dfu_private_key`)
- **Invocation**: `uploader -f firmware.zip -p /dev/ttyUSB0 -t nrfutil`

### 7.3 ST-Link / J-Link (Debug Probe)

Both MCU families support direct programming via SWD debug probes:
- STM32WLE: ST-Link via OpenOCD or STM32CubeProgrammer
- nRF52: J-Link or ST-Link via OpenOCD or nrfjprog

These are secondary upload protocols, not required for MVP but listed in each board JSON under `upload.protocols`.

---

## 9. Cross-Platform Support (macOS, Linux, Windows)

The platform must work identically on all three host operating systems. The RAK Arduino BSPs handle OS differences via key suffixes (`.windows`, `.macosx`) in `platform.txt`. In PlatformIO, OS differences are handled in Python (SCons builder scripts) using `platform.system()`.

### 8.1 OS-Specific Components

| Component | Linux | macOS | Windows |
|---|---|---|---|
| **YMODEM uploader** | `python3 uploader_ymodem.py` | `python3 uploader_ymodem.py` | `uploader_ymodem.exe` |
| **nRF52 DFU uploader** | `python3 uploader.py` | `python3 uploader.py` | `uploader.exe` |
| **buildtime prebuild** | `python3 buildtime.py` | `python3 buildtime.py` | `buildtime.exe` |
| **nrfutil** | `nrfutil` (binary) | `nrfutil` (binary) | `nrfutil.exe` |
| **mergehex** | `mergehex` (binary) | `mergehex` (binary) | `mergehex.exe` |
| **nrfjprog** | `nrfjprog` (binary) | `nrfjprog` (binary) | `nrfjprog.exe` |
| **Serial port paths** | `/dev/ttyUSB0`, `/dev/ttyACM0` | `/dev/cu.usbmodemXXXX` | `COM3`, `COM4`, etc. |
| **Path separators** | `/` | `/` | `\` (use `os.path.join()`) |
| **Executable suffix** | (none) | (none) | `.exe` |

### 8.2 Implementation Strategy

**Principle**: Use pure Python for all build logic and tool invocation. Avoid shell scripts, batch files, or OS-conditional file sets.

#### Upload Tools — Python-Only Approach

Rather than shipping three variants per upload tool (`.py` + `.exe` + macOS binary), rewrite upload tools as **pure Python scripts** invoked by PlatformIO's Python interpreter:

```python
# builder/upload_ymodem.py — works on all platforms
import sys, serial
from platformio.util import get_serial_ports

def upload(source, target, env):
    firmware_path = str(source[0])
    port = env.subst("$UPLOAD_PORT")
    # Pure Python YMODEM implementation — no external binary needed
    ...
```

This eliminates OS-conditional binary selection entirely. PlatformIO guarantees `python3` and `pyserial` are available on all platforms.

For tools that **must** remain as external binaries (`nrfutil`, `mergehex`), use PlatformIO's tool package system which handles per-OS binary distribution automatically:

```python
# In builder script
import platform

def get_tool_path(env, tool_name):
    tool_dir = env.PioPlatform().get_package_dir("tool-%s" % tool_name)
    suffix = ".exe" if platform.system() == "Windows" else ""
    return os.path.join(tool_dir, tool_name + suffix)
```

#### Path Handling

All path construction in builder scripts must use `os.path.join()` — never hardcoded `/` or `\\` separators:

```python
# Correct
include_path = os.path.join(framework_dir, "cores", "STM32WLE", "component", "rui_v3_api")

# Wrong — breaks on Windows
include_path = framework_dir + "/cores/STM32WLE/component/rui_v3_api"
```

#### Prebuild (buildtime.py)

Rewrite `buildtime.py` as a pure Python script (no compiled `.exe` needed). The original script generates a timestamp in `version.c` — trivial to implement cross-platform:

```python
# builder/buildtime.py
import time, os

def generate_version_c(version_c_path):
    timestamp = int(time.time())
    with open(version_c_path, 'w') as f:
        f.write('const unsigned long buildtime = %d;\n' % timestamp)
```

#### Serial Port Auto-Detection

PlatformIO handles serial port auto-detection natively (`$UPLOAD_PORT`), but the builder script should support the `upload_port` override and document platform-specific port naming:

```ini
; Linux
upload_port = /dev/ttyUSB0

; macOS
upload_port = /dev/cu.usbmodem14101

; Windows
upload_port = COM3
```

### 8.3 CI/CD Matrix

The GitHub Actions CI must test on all three platforms:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
    board: [rak3172, rak4631]
```

Each CI run validates:
- Platform installs correctly
- Framework packages resolve
- Compilation succeeds (all boards)
- Upload command assembles correctly (dry-run, no hardware)

### 8.4 Dependencies and Prerequisites

| Dependency | How Provided | Notes |
|---|---|---|
| Python 3 | PlatformIO Core bundles it | No user action needed |
| `pyserial` | PlatformIO Core bundles it | Required for YMODEM uploader |
| `arm-none-eabi-gcc` | PlatformIO auto-downloads `toolchain-gccarmnoneeabi` | Per-OS binary, transparent to user |
| `nrfutil` | PlatformIO auto-downloads `tool-nrfutil` | Per-OS binary, transparent to user |
| `mergehex` | Bundle as `tool-mergehex` or require Nordic CLI Tools | Must provide per-OS binaries or Python alternative |

---

## 10. Toolchain Requirements (all platforms)

| Component | Required Version | PlatformIO Package |
|---|---|---|
| `arm-none-eabi-gcc` | 9-2019q4 (per RAK BSP) | `toolchain-gccarmnoneeabi` — verify version compatibility or pin |
| `nrfutil` | Compatible with nRF5 SDK 17 | `tool-nrfutil` (existing PlatformIO package) |
| `mergehex` | Part of nRF Command Line Tools | Bundle as tool package with per-OS binaries |
| Python 3 | 3.6+ | Provided by PlatformIO Core |
| `pyserial` | Any recent version | Provided by PlatformIO Core |

**Toolchain version risk**: PlatformIO's default `toolchain-gccarmnoneeabi` may ship a newer GCC than 9-2019q4. The builder script should either:
- Test with PlatformIO's default version and document compatibility, OR
- Pin to a specific version via `platform_packages` override in `platform.json`

---

## 11. Execution Plan

### Phase 1: STM32WLE MVP (RAK3172)

Start here because maxgerhardt's PoC validates the approach and STM32WLE has the simpler post-build pipeline (no SoftDevice merge, no DFU signing).

#### Step 1.1 — Project Scaffolding

Create the platform repository structure:

```
rakwireless-platformio-rui3/
├── platform.json
├── platform.py
├── boards/
├── builder/
│   ├── main.py
│   └── frameworks/
├── tools/
└── examples/
```

**platform.json** must declare:
- Platform name: `rakwireless-rui3`
- Framework: `rui3`
- Package dependencies with zip-archive URLs to upstream RAK repos:
  - `framework-rui3-stm32wle` → `https://github.com/RAKWireless/RAK-STM32-RUI/archive/refs/tags/RUI_5.0.0.zip`
  - `toolchain-gccarmnoneeabi` → PlatformIO registry
- Repository URL for platform installation

**platform.py** must implement:
- `configure_default_packages()`: enable/disable packages based on board's MCU family
- Package version constraints

**Deliverable**: Empty platform that PlatformIO recognizes and can install locally via `pio platform install file:///path/to/rakwireless-platformio-rui3`.

#### Step 1.2 — Board Definitions

Create board JSON files for all four STM32WLE boards:
- `rak3172.json`
- `rak3172t.json`
- `rak3272sip.json`
- `rak3272lpsip.json`

Each must specify:
- `build.mcu`: `stm32wle5cc`
- `build.cpu`: `cortex-m4`
- `build.f_cpu`: `48000000L`
- `build.variant`: maps to the variant directory name in the framework package
- `build.ldscript`: `app_stm32wle5xx.ld`
- `upload.protocol`: `ymodem`
- `upload.maximum_size` / `upload.maximum_ram_size`: from `boards.txt`
- `frameworks`: `["rui3"]`
- `platform`: `rakwireless`

**Deliverable**: `pio boards` shows all four RAK3172 variants when the platform is installed.

#### Step 1.3 — Framework Package Integration (framework-rui3-stm32wle)

No fork or repackaging needed. The upstream `RAK-STM32-RUI` repo is consumed directly via zip-archive URL in `platform.json`:

1. Verify the zip-archive URL resolves correctly: `https://github.com/RAKWireless/RAK-STM32-RUI/archive/refs/tags/RUI_5.0.0.zip`
2. Verify PlatformIO downloads and unpacks it to `~/.platformio/packages/framework-rui3-stm32wle/`.
3. Confirm the directory layout after unpacking (GitHub zips add a `RAK-STM32-RUI-RUI_5.0.0/` prefix directory — the builder script must account for this).
4. Test that the package installs cleanly on all three OSes (watch for Windows long-path issues with deeply nested directories like `cores/STM32WLE/external/STM32CubeWL/`).

**Deliverable**: `pio platform install file:///path/to/platform-rakwireless-rui3` triggers automatic download of the upstream BSP zip and unpacks it correctly.

#### Step 1.4 — Builder Script (rui3_stm32wle.py)

The core engineering work. Translate the STM32WLE build recipe into SCons. **All path construction must use `os.path.join()` for Windows compatibility.**

1. **Compiler configuration**:
   - Set `CC`, `CXX`, `AS`, `AR`, `OBJCOPY`, `SIZE` to `arm-none-eabi-*` tools (PlatformIO resolves per-OS binary automatically via toolchain package)
   - Set `CCFLAGS`: `-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -u _printf_float`
   - Set `CFLAGS`: `-std=gnu11`
   - Set `CXXFLAGS`: `-std=gnu++11 -fno-exceptions -fno-rtti`

2. **Include paths**:
   - Parse framework package directory tree using `os.walk()` (cross-platform)
   - Generate all required include paths (cores, components, externals, variant-specific)
   - Use `os.path.join()` for all path construction
   - Validate against known set from `boards.txt`

3. **Source file collection**:
   - Collect `.c`, `.cpp`, `.S` source files from `cores/` and component directories
   - Exclude variant-specific files for non-selected variants
   - Include the user's `src/` directory

4. **Linker configuration**:
   - Set linker script path: `variants/<VARIANT>/app_stm32wle5xx.ld`
   - Add `--just-symbols` for FUOTA stack prebuilt
   - Set library search paths for prebuilt `.a` archives
   - Link system libraries: `-lm -lstdc++ -lsupc++`

5. **Prebuild action**:
   - Reimplement `buildtime.py` as pure Python (no `.exe` needed) — generates `version.c` timestamp
   - Invoke via PlatformIO's Python, not as an external process

6. **Post-build action**:
   - `objcopy` ELF to `.bin` and `.hex`

**Deliverable**: `pio run -e rak3172` compiles a minimal RUI3 sketch to `.bin` successfully.

#### Step 1.5 — YMODEM Upload Tool

Package the YMODEM uploader as a **pure Python** tool (no OS-specific binaries):

1. Create `tools/uploader_ymodem/package.json`.
2. Implement YMODEM upload in Python using `pyserial` (bundled with PlatformIO). The RAK BSP ships separate Linux/macOS/Windows variants (`uploader_ymodem.py` vs `uploader_ymodem.exe`); a single Python implementation eliminates this.
3. Handle serial port DFU mode entry (`AT+BOOT` command) cross-platform.
4. Register as a PlatformIO tool package.
5. Wire into the builder script as the upload command.

**Deliverable**: `pio run -e rak3172 -t upload` flashes firmware to a connected RAK3172 via serial on Linux, macOS, and Windows.

#### Step 1.6 — Validation & Examples

1. Compile the RAK3172 LoRaWAN OTAA example end-to-end on **all three OSes**.
2. Upload to hardware and verify LoRaWAN join.
3. Test all four board variants compile correctly.
4. Test configurable build flags (regions, AT support, debug levels).
5. Create example projects under `examples/`.
6. Set up GitHub Actions CI with `[ubuntu-latest, macos-latest, windows-latest]` matrix.

**Deliverable**: Working end-to-end compile + upload for all STM32WLE boards with example sketches, CI passing on all three platforms.

---

### Phase 2: nRF52 (RAK4631)

#### Step 2.1 — Board Definitions

Create board JSON files:
- `rak4631.json`
- `rak5010.json`
- `rak3401.json`

Key differences from STM32WLE:
- `build.mcu`: `cortex-m4`
- `build.f_cpu`: `64000000L`
- `build.softdevice`: `s140_7.2.0`
- `build.sd_fwid`: SoftDevice firmware ID for DFU
- `upload.protocol`: `nrfutil`

#### Step 2.2 — Framework Package Integration (framework-rui3-nrf52)

No fork needed. Consumed via zip-archive URL to upstream `RAK-nRF52-RUI`:

1. Add zip-archive URL to `platform.json`: `https://github.com/RAKWireless/RAK-nRF52-RUI/archive/refs/tags/RUI_4.1.2.zip`
2. Verify the unpacked layout includes `cores/`, `variants/`, `prebuilt/`, `security/`, `libraries/`
3. Confirm Nordic SDK 17.0.2, SoftDevice hex files, and per-board bootloader hex files are present
4. Account for GitHub zip prefix directory in builder script paths

#### Step 2.3 — Builder Script (rui3_nrf52.py)

Translate the nRF52 build recipe:

1. **Compiler configuration**: Same toolchain, add `-nostdlib`, hard-float ABI (`-mfloat-abi=hard`)
2. **Include paths**: Auto-generate from framework tree (cores, Nordic SDK, SoftDevice headers, components)
3. **Source files**: Collect from cores, components, Nordic SDK glue code
4. **Linker configuration**: Board-specific linker script, SoftDevice memory layout
5. **Post-build chain** (5 steps):
   - ELF → HEX via `objcopy`
   - Generate `settings.hex` via `nrfutil settings generate`
   - Merge settings + bootloader via `mergehex`
   - Merge all (app + SoftDevice + bootloader) → `_full.hex`
   - Generate signed DFU `.zip` via `nrfutil pkg generate`
6. **DFU signing**: Use `security/private.key` from framework package, allow override via `board_build.dfu_private_key`

#### Step 2.4 — Upload Integration

- Wire DFU zip upload using `nrfutil dfu serial`
- Support J-Link as alternative upload protocol via OpenOCD

#### Step 2.5 — Validation

- Compile RAK4631 LoRaWAN + BLE example
- Upload via DFU and verify join
- Test all three nRF52 board variants

---

### Phase 3: Apollo3 (RAK11720)

#### Step 3.1 — Research

- Obtain and analyze `RAK-APOLLO3-RUI` BSP (not yet cloned in references)
- Document build pipeline, upload protocol, and toolchain requirements

#### Step 3.2 — Board Definition + Framework Package + Builder Script

- Follow the same pattern established in Phases 1 and 2
- Create `rak11720.json`, `framework-rui3-apollo3`, `rui3_apollo3.py`

#### Step 3.3 — Validation

- End-to-end compile + upload on RAK11720 hardware

---

### Phase 4: Polish & Release

#### Step 4.1 — CI/CD

- GitHub Actions workflow: compile all board variants on every push
- **Triple-axis matrix**: OS (`ubuntu-latest`, `macos-latest`, `windows-latest`) × board × representative build flag combinations
- Validate that examples compile cleanly on all platforms
- Upload dry-run tests (verify upload command assembly without hardware)

#### Step 4.2 — Documentation

- README with installation instructions, quickstart, configuration reference
- Per-board documentation with pin maps and upload instructions
- Migration guide from Arduino IDE to PlatformIO

#### Step 4.3 — PlatformIO Registry

- Publish platform to PlatformIO registry (framework packages are not published — they are downloaded directly from upstream RAK repos via zip URLs)
- Publish tool packages (YMODEM uploader) if needed
- Set up versioning scheme aligned with upstream RUI3 BSP versions (see Section 4, Version Alignment)
- Maintain `CHANGELOG.md` documenting which upstream BSP tags each platform version is tested against

#### Step 4.4 — Debug Probe Support

- OpenOCD configuration files for STM32WLE (ST-Link) and nRF52 (J-Link)
- PlatformIO debug environment configuration
- Document debug setup per board

---

## 12. Known Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Toolchain version mismatch | Build failures or runtime bugs | Test with PlatformIO's default GCC first; pin version only if needed |
| Include path breakage on BSP update | Build failures after framework update | Auto-generate paths from directory tree, not hardcoded lists |
| FUOTA stack binary compatibility | Linker errors | Pin zip-archive URL to tested BSP tag; document upgrade process |
| `mergehex` / `nrfutil` availability | nRF52 post-build fails | Bundle as tool packages with per-OS binaries |
| RAKwireless changes BSP structure | Builder scripts break | Zip URLs are tag-pinned; we control when to update. CI catches breakage before release. |
| RAKwireless deletes/renames a Git tag | Zip-archive URL 404s, platform install fails | Pin to release tags (stable); mirror the zip as a GitHub Release asset on our repo as backup |
| RAKwireless BSP has a bug we can't work around | Blocked until upstream fixes it | **Escape hatch**: fork that one repo, apply patch, point `platform.json` at fork. Revert once upstream merges fix. |
| GitHub zip prefix directory | Builder scripts break if prefix changes | Detect prefix dynamically in `platform.py` or builder script (`os.listdir()` for single subdir pattern) |
| Apollo3 BSP not yet analyzed | Phase 3 scope unclear | Defer until Phase 1–2 complete; analyze before committing |
| DFU private key distribution | Security concern for production | Key lives in upstream repo (not our fork); document custom key override |
| License compliance (LGPL) | Legal exposure | We don't redistribute BSP source — PlatformIO downloads it directly from RAKwireless. Our builder scripts are our own code. |
| Windows path separator issues | Build failures on Windows | Use `os.path.join()` everywhere; never hardcode `/` in builder scripts |
| Windows long path limits (260 chars) | Framework install fails due to deep directory nesting | Test on Windows; flatten directory structure if needed; enable long paths in CI |
| macOS serial port permissions | Upload fails without user intervention | Document `cu.usbmodem` naming; test on macOS CI runners |
| Per-OS tool binary packaging | Missing binary for one platform blocks users | CI matrix tests all 3 OSes; provide Python fallbacks where possible |

---

## 13. Success Criteria

| Milestone | Criteria |
|---|---|
| Phase 1 Complete | `pio run` compiles any STM32WLE board on Linux, macOS, and Windows; `pio run -t upload` flashes via YMODEM; examples work |
| Phase 2 Complete | Same for nRF52 boards on all 3 OSes; DFU upload works; BLE + LoRaWAN examples compile |
| Phase 3 Complete | Same for Apollo3 on all 3 OSes; all 8 boards supported |
| Phase 4 Complete | Published to PlatformIO registry; CI green on Linux/macOS/Windows matrix; documentation complete |

---

## 14. Reference Material

| Resource | URL / Path | Purpose |
|---|---|---|
| RAK-STM32-RUI BSP | `references/RAK-STM32-RUI/` (local) | STM32WLE build recipes, source, prebuilts |
| RAK-nRF52-RUI BSP | `references/RAK-nRF52-RUI/` (local) | nRF52 build recipes, source, prebuilts |
| WisBlock repo | `references/WisBlock/` (local) | Existing PlatformIO board JSONs (Arduino, not RUI3) |
| LibreTiny | https://github.com/libretiny-eu/libretiny | Multi-chip PlatformIO platform reference |
| maxgerhardt PoC | https://github.com/maxgerhardt/pio-rak3172-demo | RAK3172 RUI3 proof-of-concept |
| PlatformIO docs | https://docs.platformio.org/en/latest/platforms/creating_platform.html | Platform development guide |
| platform-nordicnrf52 | https://github.com/platformio/platform-nordicnrf52 | nRF52 builder reference |
| platform-ststm32 | https://github.com/platformio/platform-ststm32 | STM32 builder reference |
| Feasibility Analysis | `ANALYSIS.md` (local) | Original analysis informing this PRD |
