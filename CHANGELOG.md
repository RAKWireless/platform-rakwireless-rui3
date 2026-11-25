# Changelog

All notable changes to the platform are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The platform version follows RUI3's major.minor: 4.3.x builds with RUI3 4.3.0, and the patch
number counts platform releases. The BSP packages each release uses are published separately,
as `bsp-<upstream tag>` releases.

## [Unreleased]

Nothing yet.

## [4.3.0] - 2026-11-25

First release, published as a pre-release: so far the platform has been used on Linux only.

### Added

- 17 boards in three MCU families, one board id per product:
  - STM32WLE5: `rak3172`, `rak3372`, `rak3272s`, `rak3172t`, `rak3172f`, `rak3172sip`,
    `rak3272sip`, `rak3272lpsip`, `rak11160`, `rak11162`, `rak2461`
  - nRF52840: `rak4630`, `rak4631`, `rak3401`, `rak5010`
  - Apollo3 Blue: `rak11720`, `rak11722`
- Builds with RAKwireless's RUI3 BSPs at `v4.3.0_400` (release `bsp-v4.3.0_400`), with the
  compiler and linker settings read from the BSPs' Arduino recipes at build time.
- The Arduino IDE's board menus as board options (`board_build.rui3.<menu> = <option>`).
- Upload over the board's USB serial port for every family, with no external tools: `nrfutil`
  (Nordic serial DFU) on nRF52840, `ymodem` on STM32WLE5, `amota` on Apollo3.
- STM32WLE5 uploads refuse a board that runs another RUI3 major version than the BSP, since a
  RUI3 5.x FUOTA bootloader cannot take a 4.x image (`upload_flags = --force` skips the check).
- `framework = arduino`: `.ino` and `.cpp` sketches, and Arduino libraries installed together
  with the libraries they depend on.
- Two patches applied while repackaging the BSPs. One guards the LoRaWAN FUOTA sources so they
  compile with 4.x; the other keeps a sketch's own `app.h` from replacing the variant's inside the
  BSP headers.
- Examples: `system-info` and `lorawan-otaa`.

[Unreleased]: https://github.com/RAKWireless/platform-rakwireless-rui3/compare/v4.3.0...HEAD
[4.3.0]: https://github.com/RAKWireless/platform-rakwireless-rui3/releases/tag/v4.3.0
