# RAKwireless RUI3 platform for PlatformIO

Build and upload [RUI3](https://docs.rakwireless.com/product-categories/software-apis-and-libraries/rui3/)
firmware for RAKwireless WisDuo modules and WisBlock Cores with
[PlatformIO](https://platformio.org), for all three RUI3 MCU families:

- **STM32WLE5**: RAK3172 and the boards built around it
- **nRF52840**: RAK4630 / RAK4631, RAK3401, RAK5010
- **Apollo3 Blue**: RAK11720 / RAK11722

The platform builds with RAKwireless's own RUI3 board support packages (BSPs), the ones the
Arduino IDE installs, and reads their compiler and linker settings from the BSP itself at build
time. A PlatformIO build uses the same sources, flags and libraries as the Arduino IDE, and a new
RUI3 release needs no hand-made build settings.

- One platform for every RUI3 board, with one board id per product (`rak3172`, `rak4631`, `rak11722`, ...)
- The Arduino IDE's menu options (LoRaWAN regions, debug level, ...) as board options in `platformio.ini`
- Upload over the board's USB serial port for every family, without nrfutil, RAK's uploaders or
  any other tool to install
- Arduino-style sketches: `.ino` or `.cpp` files, the RUI3 `api.*` calls, `Serial`, `Wire`, `SPI`, ...

## Requirements

- [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/) 6.1 or later, on its
  own or inside the PlatformIO IDE extension for VS Code
- For uploads, the board's USB port: native USB on nRF52840 boards, the CH340 USB-UART bridge of the
  WisBlock Core or breakout board on STM32WLE5 and Apollo3 boards (or a USB-UART adapter wired to
  the AT command UART of a bare WisDuo module)

The platform needs no other tools: the toolchain and the BSP of the board's MCU family are
downloaded on the first build.

## Quick start

`platformio.ini`:

```ini
[env:rak4631]
platform = https://github.com/RAKWireless/platform-rakwireless-rui3.git#v4.3.0
board = rak4631
framework = rui3
monitor_speed = 115200
```

`src/main.cpp`:

```cpp
#include "Arduino.h"

void setup()
{
    Serial.begin(115200);
}

void loop()
{
    Serial.print("Hello from ");
    Serial.println(api.system.modelId.get());
    delay(5000);
}
```

Then:

```bash
pio run                  # build
pio run -t upload        # build and upload
pio device monitor       # serial monitor
```

## Installing the platform

### From the repository

Name the repository in each environment, pinned to a release tag:

```ini
platform = https://github.com/RAKWireless/platform-rakwireless-rui3.git#v4.3.0
```

Without `#v4.3.0`, PlatformIO uses the latest commit of the default branch. The platform version
follows RUI3's: platform 4.3.x builds with RUI3 4.3.0.

To install it once for all projects instead, and then refer to it by name:

```bash
pio pkg install -g -p https://github.com/RAKWireless/platform-rakwireless-rui3.git#v4.3.0
```

```ini
platform = rakwireless-rui3
```

### From a local copy

To try changes to the platform itself, clone it and point the project at the folder:

```ini
platform = symlink:///home/me/platform-rakwireless-rui3
```

`symlink://` uses the folder in place, so edits apply on the next build. `file://` would copy
the whole folder into `~/.platformio/platforms` instead, `.git` included.

A local copy downloads the BSPs from the repository's releases, like an installed platform. To
build them yourself, see [Development](#development).

## Supported boards

<!-- generated:boards -->
<!-- From the boards.txt files of RUI3 v4.3.0_400. Run tools/boards.py instead of editing. -->

| `board =` | Product | MCU | Flash | RAM | Upload |
|---|---|---|---|---|---|
| `rak3172` | [RAK3172 WisDuo Module](https://docs.rakwireless.com/product-categories/wisduo/rak3172-module) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3372` | [RAK3372 WisBlock Core (RAK3172)](https://docs.rakwireless.com/product-categories/wisblock/rak3372) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3272s` | [RAK3272S Breakout Board (RAK3172)](https://docs.rakwireless.com/product-categories/wisduo/rak3272s-breakout-board) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3172t` | [RAK3172-T WisDuo Module](https://docs.rakwireless.com/product-categories/wisduo/rak3172-module) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3172f` | [RAK3172-F WisDuo Module](https://docs.rakwireless.com/product-categories/wisduo/rak3172-module) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3172sip` | [RAK3172-SiP WisDuo SiP](https://docs.rakwireless.com/product-categories/wisduo/rak3172-sip) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3272sip` | [RAK3272-SiP Breakout Board (RAK3172-SiP)](https://docs.rakwireless.com/product-categories/wisduo/rak3272-sip-breakout-board) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak3272lpsip` | RAK3272LP-SiP Breakout Board | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak11160` | [RAK11160 WisDuo Module](https://docs.rakwireless.com/product-categories/wisduo/rak11160-module) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak11162` | [RAK11162 WisBlock Core (RAK11160)](https://docs.rakwireless.com/product-categories/wisblock/rak11162) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak2461` | [RAK2461 WisNode](https://docs.rakwireless.com/product-categories/wisnode/rak2461) | STM32WLE5 | 196 KB | 47 KB | `ymodem` |
| `rak4630` | [RAK4630 WisDuo Module](https://docs.rakwireless.com/product-categories/wisduo/rak4630-module) | nRF52840 | 544 KB | 201 KB | `nrfutil` |
| `rak4631` | [RAK4631 WisBlock Core (RAK4630)](https://docs.rakwireless.com/product-categories/wisblock/rak4631) | nRF52840 | 544 KB | 201 KB | `nrfutil` |
| `rak3401` | [RAK3401 WisBlock Core](https://docs.rakwireless.com/product-categories/wisblock/rak3401) | nRF52840 | 544 KB | 201 KB | `nrfutil` |
| `rak5010` | [RAK5010 WisTrio NB-IoT Tracker](https://docs.rakwireless.com/product-categories/wistrio/rak5010) | nRF52840 | 544 KB | 201 KB | `nrfutil` |
| `rak11720` | [RAK11720 WisDuo Module](https://docs.rakwireless.com/product-categories/wisduo/rak11720-module) | Apollo3 Blue | 896 KB | 383 KB | `amota` |
| `rak11722` | [RAK11722 WisBlock Core (RAK11720)](https://docs.rakwireless.com/product-categories/wisblock/rak11722) | Apollo3 Blue | 896 KB | 383 KB | `amota` |
<!-- /generated:boards -->

A WisDuo module and the WisBlock Core built around it (for example `rak4630` and `rak4631`)
build the same firmware: pick the board you have. Product names link to their documentation.

`rak5010` does not compile with RUI3 4.2.3 or 4.3.0, in the Arduino IDE either (`LoRaMac.c` uses
`NUM_OF_KEYS`, which the RAK5010 build does not define).

### Board options

Each board has the options of the Arduino IDE's board menus. Set them per environment with
`board_build.rui3.<option>`, using either the value id or its label (case does not matter):

```ini
[env:rak3172]
platform = https://github.com/RAKWireless/platform-rakwireless-rui3.git#v4.3.0
board = rak3172
framework = rui3
board_build.rui3.supportcn470 = on
board_build.rui3.debug = l2
```

Defaults, in **bold**, are the Arduino IDE's. The build prints the options it applied, and an
unknown option or value fails the build with the list of valid ones.

<!-- generated:board-options -->
<!-- From the boards.txt files of RUI3 v4.3.0_400. Run tools/boards.py instead of editing. -->

#### `rak3172`, `rak3372`, `rak3272s`, `rak3172t`, `rak3172f`, `rak3172sip`, `rak3272sip`, `rak3272lpsip`, `rak11160`, `rak11162`, `rak2461`, `rak11720`, `rak11722`

| Option | Menu | Values |
|---|---|---|
| `debug` | Debug | **`l0` Level 0 (Release)**<br>`l1` Level 1 (Error Message)<br>`l2` Level 2 (Full Debug)<br>`l3` Level 3 (Segger SystemView) |
| `supportat` | Support AT | **`1` On**<br>`2` Off |
| `supportlora` | Support LoRaWAN | **`1` Support LoRaWAN and LoRa P2P**<br>`2` Support LoRaWAN<br>`3` Support LoRa P2P<br>`4` Not Support |
| `supportas923` | Support LoRaWAN Region AS923 | **`1` On**<br>`2` Off |
| `supportau915` | Support LoRaWAN Region AU915 | **`1` On**<br>`2` Off |
| `supportcn470` | Support LoRaWAN Region CN470 | **`2` Off**<br>`1` On |
| `supportcn779` | Support LoRaWAN Region CN779 | **`2` Off**<br>`1` On |
| `supporteu433` | Support LoRaWAN Region EU433 | **`2` Off**<br>`1` On |
| `supporteu868` | Support LoRaWAN Region EU868 | **`1` On**<br>`2` Off |
| `supportkr920` | Support LoRaWAN Region KR920 | **`1` On**<br>`2` Off |
| `supportin865` | Support LoRaWAN Region IN865 | **`1` On**<br>`2` Off |
| `supportus915` | Support LoRaWAN Region US915 | **`1` On**<br>`2` Off |
| `supportru864` | Support LoRaWAN Region RU864 | **`1` On**<br>`2` Off |
| `supportla915` | Support LoRaWAN Region LA915 | **`1` On**<br>`2` Off |

#### `rak4630`, `rak4631`

| Option | Menu | Values |
|---|---|---|
| `softdevice` | Bootloader | **`s140v6` 0.3.2 SoftDevice s140 7.2.0** |
| `debug` | Debug | **`l0` Level 0 (Release)**<br>`l1` Level 1 (Error Message)<br>`l2` Level 2 (Full Debug)<br>`l3` Level 3 (Segger SystemView) |
| `supportnfc` | Support NFC | **`1` Disable**<br>`2` Enable |
| `supportat` | Support AT | **`1` On**<br>`2` Off |
| `supportlora` | Support LoRaWAN | **`1` Support LoRaWAN and LoRa P2P**<br>`2` Support LoRaWAN<br>`3` Support LoRa P2P<br>`4` Not Support |
| `supportas923` | Support LoRaWAN Region AS923 | **`1` On**<br>`2` Off |
| `supportau915` | Support LoRaWAN Region AU915 | **`1` On**<br>`2` Off |
| `supportcn470` | Support LoRaWAN Region CN470 | **`2` Off**<br>`1` On |
| `supportcn779` | Support LoRaWAN Region CN779 | **`2` Off**<br>`1` On |
| `supporteu433` | Support LoRaWAN Region EU433 | **`2` Off**<br>`1` On |
| `supporteu868` | Support LoRaWAN Region EU868 | **`1` On**<br>`2` Off |
| `supportkr920` | Support LoRaWAN Region KR920 | **`1` On**<br>`2` Off |
| `supportin865` | Support LoRaWAN Region IN865 | **`1` On**<br>`2` Off |
| `supportus915` | Support LoRaWAN Region US915 | **`1` On**<br>`2` Off |
| `supportru864` | Support LoRaWAN Region RU864 | **`1` On**<br>`2` Off |
| `supportla915` | Support LoRaWAN Region LA915 | **`1` On**<br>`2` Off |

#### `rak3401`

| Option | Menu | Values |
|---|---|---|
| `softdevice` | Bootloader | **`s140v6` 0.3.2 SoftDevice s140 7.2.0** |
| `debug` | Debug | **`l0` Level 0 (Release)**<br>`l1` Level 1 (Error Message)<br>`l2` Level 2 (Full Debug)<br>`l3` Level 3 (Segger SystemView) |
| `supportnfc` | Support NFC | **`1` Disable**<br>`2` Enable |
| `supportat` | Support AT | **`1` On**<br>`2` Off |

#### `rak5010`

| Option | Menu | Values |
|---|---|---|
| `softdevice` | Bootloader | **`s140v6` 0.3.2 SoftDevice s140 7.2.0** |
| `debug` | Debug | **`l0` Level 0 (Release)**<br>`l1` Level 1 (Error Message)<br>`l2` Level 2 (Full Debug)<br>`l3` Level 3 (Segger SystemView) |
| `auto_display_cellular_response` | Auto Display Cellular Response | **`1` Off**<br>`2` On |
| `supportat` | Support AT | **`1` On**<br>`2` Off |
<!-- /generated:board-options -->

## Uploading

`pio run -t upload` builds the firmware and uploads it over the board's serial port. The uploader
first sends `at+boot`, which makes the running RUI3 firmware restart into its bootloader, then
sends the image in the bootloader's protocol. This works whether the sketch leaves the port to
the AT command console or uses it for its own data. There is no button to press.

| MCU | `upload_protocol` | Image | Protocol |
|---|---|---|---|
| nRF52840 | `nrfutil` | `firmware.zip` | Nordic serial DFU with a signed package, as nrfutil and the Arduino IDE make it |
| STM32WLE5 | `ymodem` | `firmware.bin` | YMODEM, as RAK's `uploader_ymodem` sends it |
| Apollo3 | `amota` | `firmware_Nonsecure_OTA_Package_UART.bin` | Ambiq's AMOTA over UART, as the BSP's update script sends it |

Each is the board's default; all images are written to `.pio/build/<env>/`.

PlatformIO finds the port from the board's USB ids. With several boards connected, name it:

```ini
upload_port = /dev/ttyUSB0    ; COM5 on Windows
```

An STM32WLE5 board whose AT console runs at another baud rate (`AT+BAUD`) is found automatically.

### Boards that run RUI3 5.x

A board that came with RUI3 5.x can have a different bootloader. On STM32WLE5 boards, the 5.x
FUOTA bootloader keeps the LoRaWAN stack in a flash partition of its own and installs only the
first 92 KB of a 4.x image, while acknowledging all of it: the board no longer starts and needs
an SWD probe to recover. The STM32WLE5 uploader therefore asks the board for its version
(`AT+VER=?`) and refuses one that runs another RUI3 major version than the BSP it builds with. To
upload anyway:

```ini
upload_flags = --force
```

### Without PlatformIO

The uploaders are plain Python scripts (they need [pyserial](https://pypi.org/project/pyserial/),
which PlatformIO already includes):

```bash
python builder/nrf52_dfu.py upload --port /dev/ttyACM0 .pio/build/rak4631/firmware.zip
python builder/stm32_ymodem.py --port /dev/ttyUSB0 .pio/build/rak3172/firmware.bin
python builder/apollo3_ota.py upload --port /dev/ttyUSB0 .pio/build/rak11722/firmware_Nonsecure_OTA_Package_UART.bin
```

## Serial monitor and AT commands

RUI3's serial console runs at 115200 baud. With a local echo, AT commands can be typed straight
into `pio device monitor`:

```ini
monitor_speed = 115200
monitor_echo = yes
```

`AT+VER=?` shows the firmware version and `AT+BUILDTIME=?` the time it was built, which tells
whether an upload took. (`api.system.firmwareVersion.get()` reads a copy kept in the board's
settings, which can still name the firmware the board had before.)

## Libraries

PlatformIO treats Arduino libraries (those with a `library.properties` file) as compatible with
its own `arduino` framework only. To use them with `framework = rui3`, turn the compatibility
check off:

```ini
lib_deps =
    ; libraries from the PlatformIO registry or Git URLs, as usual
lib_compat_mode = off
```

## Using another RUI3 release

The platform pins one RUI3 release per version. A project can build with another one by pointing
the framework package at a BSP tarball (see [Development](#development) to make one):

```ini
platform_packages =
    framework-rui3-nrf52 @ file:///path/to/framework-rui3-nrf52-v4.2.3_363.tar.gz
```

The packages are `framework-rui3-stm32wle`, `framework-rui3-nrf52` and `framework-rui3-apollo3`.

## Examples

- [`examples/system-info`](examples/system-info): prints the API version, firmware version, model
  and chip id every 10 seconds
- [`examples/lorawan-otaa`](examples/lorawan-otaa): joins a LoRaWAN network with OTAA and sends
  an uplink counter (set your keys and region in `src/main.cpp` first)

The examples refer to the platform by name, so install it first (see
[Installing the platform](#installing-the-platform)), then:

```bash
cd examples/system-info
pio run -e rak4631 -t upload
```

## Limitations

- Uploads over SWD (`upload_protocol = jlink` or `stlink`) and debugging (`pio debug`) are not
  supported yet.
- FUOTA (`SUPPORT_FUOTA`) is not available with the RUI3 4.x BSPs: their FUOTA sources predate the
  LoRaMac version they ship with.
- On Apollo3 boards, the package for Bluetooth OTA updates that the Arduino IDE also writes is not
  built.
- The platform has been used on Linux so far. It has no OS-specific parts, but macOS and Windows
  are untested.

## Development

The repository holds the whole platform; it does not fork RAK's BSP repositories.

| Path | Contents |
|---|---|
| `platform.json`, `platform.py` | Platform definition; picks the BSP package for the board's MCU family |
| `builder/` | Build scripts: `main.py` (toolchain, images, upload), `frameworks/rui3.py` (the RUI3 build), `rui3_recipe.py` (reads the BSP's Arduino recipes), the three uploaders |
| `boards/` | Board manifests, generated by `tools/boards.py` |
| `tools/` | `bsp.py` (repackages BSP releases), `bsp_patches.py` (their compatibility fixes), `boards.py` (board manifests and this README's tables) |
| `tests/` | Unit tests, including the uploaders against simulated boards |
| `examples/` | Example projects |

Each RUI3 release of RAK's BSP repositories ([RAK-STM32-RUI](https://github.com/RAKWireless/RAK-STM32-RUI),
[RAK-nRF52-RUI](https://github.com/RAKWireless/RAK-nRF52-RUI),
[RAK-APOLLO3-RUI](https://github.com/RAKWireless/RAK-APOLLO3-RUI)) is repackaged once into
framework tarballs, which this repository publishes as release assets:

```bash
python tools/bsp.py package --tag v4.3.0_400                             # into dist/
python tools/bsp.py pin --tag v4.3.0_400 --platform-version 4.3.0        # platform.json
python tools/boards.py --tag v4.3.0_400                                  # boards/, platform.json, README.md
python tools/boards.py --tag v4.3.0_400 --check                          # fails if any is out of date
```

`bsp.py package` and `boards.py` download the tag from GitHub. With `--git-root <folder>` they read
it from local clones of the three BSP repositories instead, kept side by side in that folder
under their GitHub names (`RAK-STM32-RUI/`, `RAK-nRF52-RUI/`, `RAK-APOLLO3-RUI/`). In those
clones, read a release with `git show <tag>:<path>`: their checked-out `main` branch is not where
releases are made.

A platform used from a local copy takes the tarballs from `dist/` when they are there, so it builds
before anything is published. The `RUI3_BSP_DIST` environment variable (a folder or a base URL)
overrides both `dist/` and the release URLs.

Tests (the upload tests need pyserial, so use PlatformIO's Python):

```bash
~/.platformio/penv/bin/python -m unittest discover -s tests
```

## License

The platform is licensed under the [Apache License 2.0](LICENSE).

The framework packages are RAKwireless's RUI3 BSPs, Copyright Shenzhen RAKwireless Technology
Co., Ltd., under RAKwireless's own license: BSD-style, with the condition that the software is used
only with RAKwireless products. Each package carries it as `LICENSE.txt`, as do the BSP
repositories.
