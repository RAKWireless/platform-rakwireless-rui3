"""
OTA package and serial upload for RUI3 Apollo3 boards (RAK11720, RAK11722).

The Arduino IDE runs two scripts from the BSP's security/apollo3_scripts:
ota_binary_converter.py turns the sketch's .bin into an OTA package
(<sketch>_Nonsecure_OTA_Package_UART.bin), and apollo3_uart_update_script.py
sends that package to the RUI3 bootloader. This module does both, in pure
Python. platform.txt calls the upload tool uploader_ymodem, but Apollo3 boards
do not use YMODEM: their bootloader takes Ambiq's AMOTA requests over the UART.

The package is a 48-byte header followed by the image, all fields
little-endian:
    0   encryption flag (0)
    4   load address
    8   image size (security info, its padding and the application)
    12  CRC of the image: CRC-32 with polynomial 0x1EDC6F41, most significant
        bit first, initial value 0 and no final inversion (the bootloader's)
    16  size of the security info and its padding
    20  reserved (12 bytes of 0xFF)
    32  image version
    36  binary type (0 firmware, 1 data)
    40  storage type (0 internal flash, 1 external)
    44  reserved (4 bytes of 0xFF)

The upload follows apollo3_uart_update_script.py:
1. AT+BOOT twice, two seconds apart, makes the firmware restart into the
   bootloader. RUI3 watches for it on the serial port even while the sketch
   uses the port for its own data; a bootloader already running ignores it.
2. AT+UPDATE starts the bootloader's update mode.
3. Requests are <length:u16> <command:u8> <payload> <crc:u32>, where length
   counts the payload and the CRC and the CRC is the standard CRC-32 of the
   payload. FW_HEADER carries the package header, each FW_DATA 512 bytes of
   the image, then FW_VERIFY and FW_RESET. The bootloader answers header and
   data requests with 8 bytes (length 5, command, status, 4 bytes) and
   FW_VERIFY with 4 (length 1, command, status).

The module's UART reaches the computer through a USB serial bridge, so the
port stays open while the module restarts into its bootloader.

usage: python apollo3_ota.py package --load-address 0x14000 firmware.bin package.bin
       python apollo3_ota.py upload --port /dev/ttyUSB0 package.bin
"""

import argparse
import binascii
import os
import struct
import sys
import time

HEADER_SIZE = 48
BAUDRATE = 115200
FRAME_SIZE = 512
TIMEOUT = 10.0
# apollo3_uart_update_script.py waits this long, in seconds, after each of
# AT+BOOT, AT+BOOT and AT+UPDATE.
COMMAND_WAIT = 2.0

FW_HEADER, FW_DATA, FW_VERIFY, FW_RESET = 1, 2, 3, 4
STATUS = {
    1: "CRC error",
    2: "invalid header",
    3: "invalid packet length",
    4: "insufficient buffer",
    5: "the image does not fit in the flash",
    6: "unknown error",
    7: "flash write error",
}

CONVERTER = "ota_binary_converter"


class OtaError(Exception):
    pass


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------

_POLY = 0x1EDC6F41


def _crc_table():
    table = []
    for i in range(256):
        rem = i << 24
        for _ in range(8):
            rem = ((rem << 1) ^ _POLY) if rem & 0x80000000 else rem << 1
            rem &= 0xFFFFFFFF
        table.append(rem)
    return table


_TABLE = _crc_table()


def image_crc(data):
    """The image CRC the Apollo3 bootloader checks (see the module docstring)."""
    rem = 0
    for byte in bytearray(data):
        rem = ((rem << 8) & 0xFFFFFFFF) ^ _TABLE[((rem >> 24) ^ byte) & 0xFF]
    return rem


def package_bytes(app, load_address, version=0, binary_type=0, storage_type=0,
                  security_info=b"", alignment=4):
    """The OTA package for application image `app`, as ota_binary_converter.py
    builds it. Security info, when given, precedes the application, padded
    with zeros to `alignment`."""
    security_info = bytes(security_info)
    pad = b""
    if security_info and len(security_info) % alignment:
        pad = bytes(alignment - len(security_info) % alignment)
    blob = security_info + pad + bytes(app)
    mask = 0xFFFFFFFF
    header = struct.pack(
        "<5I12s3I4s",
        0,
        load_address & mask,
        len(blob),
        image_crc(blob),
        len(security_info) + len(pad),
        b"\xff" * 12,
        version & mask,
        binary_type & mask,
        1 if storage_type else 0,
        b"\xff" * 4)
    return header + blob


def make_package(bin_path, package_path, load_address, version=0, binary_type=0,
                 storage_type=0, security_info=None, alignment=4):
    with open(bin_path, "rb") as f:
        app = f.read()
    sec = b""
    if security_info:
        with open(security_info, "rb") as f:
            sec = f.read()
    data = package_bytes(app, load_address, version, binary_type, storage_type, sec, alignment)
    tmp = package_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, package_path)


def _converter_args(tokens):
    """Arguments of an ota_binary_converter command, or None for another command."""
    for i, token in enumerate(tokens):
        name = os.path.basename(token.replace("\\", "/"))
        if os.path.splitext(name)[0] == CONVERTER:
            return tokens[i + 1:]
    return None


def _parse_converter(args):
    # ota_binary_converter.py reads every number as hexadecimal; its defaults
    # apply to options the recipe leaves out.
    hex_value = lambda v: int(v, 16)  # noqa: E731
    with_value = {
        "--load-address": ("load_address", hex_value),
        "--appbin": ("appbin", str),
        "--secbin": ("security_info", str),
        "--version": ("version", hex_value),
        "--binary-type": ("binary_type", hex_value),
        "--storage-type": ("storage_type", hex_value),
        "-o": ("output", str),
        "-a": ("alignment", int),
    }
    options = {"load_address": 0x4000, "version": 0, "binary_type": 0, "storage_type": 0,
               "security_info": "", "alignment": 4, "appbin": None, "output": None}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in with_value and i + 1 < len(args):
            name, convert = with_value[arg]
            try:
                options[name] = convert(args[i + 1])
            except ValueError:
                raise OtaError("invalid value %r for %s in the BSP's OTA package recipe"
                               % (args[i + 1], arg))
            i += 2
        else:
            raise OtaError("the BSP's OTA package recipe uses `%s`, which this platform "
                           "does not implement yet" % arg)
    return options


def package_options(upload_args, objcopy_recipes, app_bin):
    """Package settings from the BSP's Arduino recipes.

    upload_args is the BSP's upload command (tools.<upload.tool>.upload.pattern):
    its -f names the file it sends. One of objcopy_recipes (the
    recipe.objcopy.*.pattern commands) builds that file with
    ota_binary_converter, from app_bin, the sketch's .bin. Reading the settings
    there keeps the package identical to the Arduino IDE's; an option this
    module does not implement is an error, so that an upstream change to the
    recipe is noticed instead of silently producing a different package.
    """
    upload_args = list(upload_args or [])
    sent = None
    for i, arg in enumerate(upload_args[:-1]):
        if arg == "-f":
            sent = upload_args[i + 1]
    if not sent:
        raise OtaError("the BSP's upload recipe does not name the file it sends (-f)")
    for tokens in objcopy_recipes:
        args = _converter_args(tokens or [])
        if args is None:
            continue
        options = _parse_converter(args)
        if options["output"] is None or options["output"] + ".bin" != sent:
            continue
        if options["appbin"] != app_bin:
            raise OtaError("the BSP builds its OTA package from %s, not from the sketch's "
                           ".bin file" % options["appbin"])
        del options["appbin"], options["output"]
        options["security_info"] = options["security_info"] or None
        return options
    raise OtaError("none of the BSP's objcopy recipes builds %s, the file its upload "
                   "recipe sends" % sent)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _serial():
    try:
        import serial  # noqa: F401
    except ImportError:
        raise OtaError("uploading needs pyserial (pip install pyserial)")
    return serial


def make_request(command, payload=b""):
    payload = bytes(payload)
    return (struct.pack("<HB", len(payload) + 4, command) + payload
            + struct.pack("<I", binascii.crc32(payload) & 0xFFFFFFFF))


class AmotaClient(object):
    def __init__(self, ser):
        self.ser = ser

    def _read(self, size, timeout):
        data = bytearray()
        deadline = time.time() + timeout
        while len(data) < size and time.time() < deadline:
            data += self.ser.read(size - len(data))
        return bytes(data)

    def request(self, command, payload=b"", reply_size=8, timeout=TIMEOUT):
        self.ser.write(make_request(command, payload))
        reply = bytearray(self._read(reply_size, timeout))
        if not reply:
            raise OtaError("no answer from the bootloader (is the board's port %s?)"
                           % self.ser.port)
        if len(reply) < 4 or reply[2] != command:
            raise OtaError("unexpected answer from the bootloader: %s"
                           % binascii.hexlify(bytes(reply)).decode())
        if reply[3] != 0:
            raise OtaError("the bootloader rejected the update: %s"
                           % STATUS.get(reply[3], "status %d" % reply[3]))
        if len(reply) != reply_size or struct.unpack("<H", bytes(reply[:2]))[0] != reply_size - 3:
            raise OtaError("unexpected answer from the bootloader: %s"
                           % binascii.hexlify(bytes(reply)).decode())

    def send_package(self, package, progress=None):
        header, image = package[:HEADER_SIZE], package[HEADER_SIZE:]
        self.request(FW_HEADER, header)
        for offset in range(0, len(image), FRAME_SIZE):
            self.request(FW_DATA, image[offset:offset + FRAME_SIZE])
            if progress:
                progress(min(offset + FRAME_SIZE, len(image)), len(image))
        self.request(FW_VERIFY, reply_size=4)
        # The bootloader restarts into the new firmware; RAK's script does not
        # check this answer either.
        self.ser.write(make_request(FW_RESET))
        self._read(4, 2.0)


def enter_update_mode(ser, request_bootloader=True):
    time.sleep(0.15)
    if request_bootloader:
        for _ in range(2):
            ser.write(b"AT+BOOT\r\n")
            time.sleep(COMMAND_WAIT)
    ser.write(b"AT+UPDATE\r\n")
    time.sleep(COMMAND_WAIT)
    # Drop the bootloader's answers to the commands.
    ser.reset_input_buffer()


def _progress_printer(log):
    state = {"last": -1}

    def show(done, total):
        percent = done * 100 // total
        if percent // 10 != state["last"] // 10 or done == total:
            state["last"] = percent
            log("  %3d%% (%d of %d bytes)" % (percent, done, total))
    return show


def upload(package_path, port, log=print, request_bootloader=True):
    """Flash an OTA package through the RUI3 bootloader."""
    serial = _serial()
    with open(package_path, "rb") as f:
        package = f.read()
    if len(package) <= HEADER_SIZE:
        raise OtaError("%s is not an OTA package" % package_path)
    if not port:
        raise OtaError("no upload port (set upload_port in platformio.ini)")
    try:
        with serial.Serial(port=port, baudrate=BAUDRATE, timeout=0.5) as ser:
            log("Requesting the bootloader's update mode on %s (AT+BOOT, AT+UPDATE)" % port)
            enter_update_mode(ser, request_bootloader)
            log("Sending %s (%d bytes)" % (os.path.basename(package_path), len(package)))
            AmotaClient(ser).send_package(package, _progress_printer(log))
    except (serial.SerialException, OSError) as exc:
        raise OtaError("serial error on %s: %s" % (port, exc))
    log("Device programmed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    sub = parser.add_subparsers(dest="command")
    pkg = sub.add_parser("package", help="build an OTA package from an application image")
    pkg.add_argument("--load-address", type=lambda v: int(v, 16), required=True)
    pkg.add_argument("--version", type=lambda v: int(v, 16), default=0)
    pkg.add_argument("bin")
    pkg.add_argument("package")
    up = sub.add_parser("upload", help="flash an OTA package over serial")
    up.add_argument("--port", required=True)
    up.add_argument("--no-at-boot", action="store_true",
                    help="the board is already in the bootloader")
    up.add_argument("package")
    args = parser.parse_args(argv)
    try:
        if args.command == "package":
            make_package(args.bin, args.package, args.load_address, args.version)
        elif args.command == "upload":
            upload(args.package, args.port, request_bootloader=not args.no_at_boot)
        else:
            parser.print_help()
            return 2
    except OtaError as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
