"""
Tests for builder/apollo3_ota.py.

The OTA package was checked byte for byte against the BSP's
ota_binary_converter.py, both as the RUI3 recipe runs it and with every
option it has. These tests pin the layout down without the BSP, read the
settings from recipes shaped like platform.txt's, and run the serial upload
against a simulated RUI3 Apollo3 board on a pseudo-terminal: the firmware,
which restarts into the bootloader on AT+BOOT, and the bootloader, which
checks the CRC of every request and the image CRC of the package header.

    python -m unittest discover -s tests
"""

import binascii
import os
import select
import shutil
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "builder"))
import apollo3_ota as ota  # noqa: E402

try:
    import serial  # noqa: F401
    HAVE_PTY = hasattr(os, "openpty")
except ImportError:
    HAVE_PTY = False


def reference_crc(data):
    """The bit-by-bit CRC of ota_binary_converter.py."""
    rem = 0
    for byte in bytearray(data):
        rem ^= byte << 24
        for _ in range(8):
            rem = ((rem << 1) ^ 0x1EDC6F41) if rem & 0x80000000 else rem << 1
            rem &= 0xFFFFFFFF
    return rem


# The recipes as rui3_recipe expands them (platform.txt of v4.3.0_400), on
# Linux and on Windows, where the converter is a frozen executable.
SCRIPTS = "/pkg/security/apollo3_scripts"
APP = "$BUILD_DIR/${PROGNAME}.bin"
UART = "$BUILD_DIR/${PROGNAME}_Nonsecure_OTA_Package_UART"
UPLOAD = ["-f", UART + ".bin", "-p"]


def objcopy_recipes(converter):
    return [
        ["arm-none-eabi-objcopy", "-O", "binary", "-S", "$BUILD_DIR/${PROGNAME}.elf", APP],
        converter + ["--load-address", "0x14000", "--appbin", APP, "-o", UART],
        ["python3", SCRIPTS + "/create_cust_image_blob.py", "--bin", APP, "--load-address",
         "0x14000", "--magic-num", "0xC1", "-o", "$BUILD_DIR/${PROGNAME}_Main_Nonsecure_OTA_BLOB",
         "--version", "0x0"],
        converter + ["--load-address", "0x84000", "--appbin",
                     "$BUILD_DIR/${PROGNAME}_Main_Nonsecure_OTA_BLOB.bin",
                     "-o", "$BUILD_DIR/${PROGNAME}_Nonsecure_OTA_Package_BLE"],
    ]


class Apollo3PackageTest(unittest.TestCase):
    def test_crc(self):
        data = os.urandom(3000)
        self.assertEqual(ota.image_crc(data), reference_crc(data))
        self.assertEqual(ota.image_crc(b""), 0)

    def test_package_layout(self):
        app = os.urandom(1001)
        package = ota.package_bytes(app, 0x14000)
        self.assertEqual(len(package), 48 + len(app))
        self.assertEqual(package[48:], app)
        self.assertEqual(package[:48], struct.pack("<5I", 0, 0x14000, len(app), reference_crc(app), 0)
                         + b"\xff" * 12 + struct.pack("<3I", 0, 0, 0) + b"\xff" * 4)

    def test_package_with_security_info(self):
        app, sec = os.urandom(64), os.urandom(5)
        package = ota.package_bytes(app, 0x84000, version=0x12, binary_type=1, storage_type=7,
                                    security_info=sec, alignment=4)
        blob = sec + bytes(3) + app
        self.assertEqual(package[48:], blob)
        fields = struct.unpack("<5I12s3I4s", package[:48])
        self.assertEqual(fields[1:5], (0x84000, len(blob), reference_crc(blob), 8))
        self.assertEqual(fields[6:9], (0x12, 1, 1))  # any non-zero storage type is 1

    def test_package_options(self):
        expected = {"load_address": 0x14000, "version": 0, "binary_type": 0, "storage_type": 0,
                    "security_info": None, "alignment": 4}
        for converter in (["python3", SCRIPTS + "/ota_binary_converter.py"],
                          [SCRIPTS + "/windows/ota_binary_converter.exe"]):
            self.assertEqual(ota.package_options(UPLOAD, objcopy_recipes(converter), APP), expected)

    def test_package_options_errors(self):
        converter = ["python3", SCRIPTS + "/ota_binary_converter.py"]
        recipes = objcopy_recipes(converter)
        with self.assertRaisesRegex(ota.OtaError, "does not implement"):
            changed = [list(r) for r in recipes]
            changed[1] += ["--encrypt", "1"]
            ota.package_options(UPLOAD, changed, APP)
        with self.assertRaisesRegex(ota.OtaError, "none of the BSP's objcopy recipes"):
            ota.package_options(["-f", "$BUILD_DIR/other.bin"], recipes, APP)
        with self.assertRaisesRegex(ota.OtaError, "not from the sketch"):
            ota.package_options(UPLOAD, recipes, "$BUILD_DIR/elsewhere.bin")
        with self.assertRaisesRegex(ota.OtaError, "does not name the file"):
            ota.package_options(None, recipes, APP)


class FakeApollo3Board(threading.Thread):
    def __init__(self, fd, in_bootloader=False, status=None, silent=False):
        super().__init__(daemon=True)
        self.fd = fd
        self.state = "bootloader" if in_bootloader else "firmware"
        self.status = status or {}  # command -> status to answer with
        self.silent = silent
        self.stop = False
        self.error = None
        self.log = []
        self.header = None
        self.image = bytearray()

    def read_exact(self, size, timeout=0.5):
        out = bytearray()
        while len(out) < size:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                return None
            try:
                data = os.read(self.fd, size - len(out))
            except OSError:
                return None
            if not data:
                return None
            out += data
        return bytes(out)

    def send(self, data):
        os.write(self.fd, bytes(data))

    def run(self):
        try:
            line = bytearray()
            while not self.stop and self.state != "done":
                if self.state == "update":
                    self.serve()
                    continue
                byte = self.read_exact(1, 0.05)
                if byte is None or self.silent:
                    continue
                if byte in (b"\r", b"\n"):
                    if line:
                        self.command(bytes(line).upper())
                    line = bytearray()
                else:
                    line += byte
        except Exception as exc:  # reported by the test
            self.error = exc

    def command(self, line):
        self.log.append("%s in %s" % (line.decode(), self.state))
        if self.state == "firmware":
            if line == b"AT+BOOT":
                self.state = "bootloader"
        elif line == b"AT+UPDATE":
            self.send(b"OK\r\n")
            self.state = "update"
        else:
            self.send(b"AT not support.\r\n")

    def reply(self, command, extra=b""):
        status = self.status.get(command, 0)
        self.send(struct.pack("<HBB", 1 + len(extra), command, status) + extra)
        return status

    def serve(self):
        first = self.read_exact(1)
        if first is None or first in (b"\r", b"\n"):
            return  # the line ending of AT+UPDATE
        rest = self.read_exact(2)
        length, command = struct.unpack("<HB", first + rest)
        body = self.read_exact(length)
        payload, crc = body[:-4], struct.unpack("<I", body[-4:])[0]
        assert crc == binascii.crc32(payload) & 0xFFFFFFFF, "request CRC"
        if command == ota.FW_HEADER:
            assert len(payload) == 48
            self.header = payload
            if self.reply(command, struct.pack("<I", 0)):
                self.state = "done"
        elif command == ota.FW_DATA:
            assert len(payload) <= 512
            self.image += payload
            if self.reply(command, struct.pack("<I", len(self.image))):
                self.state = "done"
        elif command == ota.FW_VERIFY:
            size, crc = struct.unpack("<II", self.header[8:16])
            ok = len(self.image) == size and ota.image_crc(self.image) == crc
            self.status.setdefault(command, 0 if ok else 1)
            self.reply(command)
            self.log.append("verified" if ok else "verify failed")
        elif command == ota.FW_RESET:
            self.reply(command)
            self.state = "done"


@unittest.skipUnless(HAVE_PTY, "needs pyserial and a POSIX pty")
class Apollo3SerialUploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.package = ota.package_bytes(os.urandom(1500), 0x14000)  # 3 data frames
        self.path = os.path.join(self.tmp, "firmware_Nonsecure_OTA_Package_UART.bin")
        with open(self.path, "wb") as f:
            f.write(self.package)
        self.saved = ota.COMMAND_WAIT, ota.TIMEOUT
        ota.COMMAND_WAIT, ota.TIMEOUT = 0.1, 2.0

    def tearDown(self):
        ota.COMMAND_WAIT, ota.TIMEOUT = self.saved
        shutil.rmtree(self.tmp)

    def upload(self, **board_options):
        master, slave = os.openpty()
        board = FakeApollo3Board(master, **board_options)
        board.start()
        lines = []
        try:
            ota.upload(self.path, os.ttyname(slave), log=lines.append)
            error = None
        except ota.OtaError as exc:
            error = exc
        finally:
            board.stop = True
            board.join(3)
            os.close(slave)
            os.close(master)
        self.assertIsNone(board.error)
        return error, board, lines

    def test_upload(self):
        error, board, lines = self.upload()
        self.assertIsNone(error)
        self.assertEqual(board.header, self.package[:48])
        self.assertEqual(bytes(board.image), self.package[48:])
        self.assertEqual(board.log, ["AT+BOOT in firmware", "AT+BOOT in bootloader",
                                     "AT+UPDATE in bootloader", "verified"])
        self.assertIn("Device programmed.", lines)

    def test_upload_rejected(self):
        error, _, _ = self.upload(status={ota.FW_HEADER: 5})
        self.assertIn("does not fit in the flash", str(error))

    def test_no_board(self):
        error, _, _ = self.upload(silent=True)
        self.assertIn("no answer from the bootloader", str(error))


if __name__ == "__main__":
    unittest.main()
