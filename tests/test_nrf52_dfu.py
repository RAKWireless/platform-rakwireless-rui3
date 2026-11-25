"""
Tests for builder/nrf52_dfu.py.

The package layout was checked byte for byte against packages from nrfutil
6.1.7 (`nrfutil pkg generate`, as the RUI3 Arduino recipe runs it): the
manifest, the image and the init packet are identical except the signature,
whose nonce nrfutil picks at random. These tests pin that layout down without
needing nrfutil or a BSP, and run the serial upload against a simulated
bootloader that checks the init packet signature and the image hash the way
the nRF5 SDK bootloader does.

    python -m unittest discover -s tests
"""

import base64
import binascii
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "builder"))
import nrf52_dfu as dfu  # noqa: E402

try:
    import serial  # noqa: F401
    HAVE_PYSERIAL = True
except ImportError:
    HAVE_PYSERIAL = False

# RFC 6979, A.2.5 (P-256): private key and the signature of "sample" with SHA-256.
RFC6979_KEY = int("C9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721", 16)
RFC6979_R = int("EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716", 16)
RFC6979_S = int("F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8", 16)


def sec1_pem(secret):
    """PEM "EC PRIVATE KEY" (SEC 1) for a P-256 scalar, as nrfutil writes them."""
    x, y = dfu._scalar_mult(secret, dfu._G)
    public = b"\x04" + dfu._bytes32(x) + dfu._bytes32(y)
    body = (b"\x02\x01\x01" + b"\x04\x20" + dfu._bytes32(secret)
            + b"\xa0\x0a\x06\x08" + dfu._PRIME256V1_OID
            + b"\xa1\x44\x03\x42\x00" + public)
    der = b"\x30" + bytes(bytearray((len(body),))) + body
    b64 = base64.b64encode(der).decode("ascii")
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return "-----BEGIN EC PRIVATE KEY-----\n%s\n-----END EC PRIVATE KEY-----\n" % "\n".join(lines)


def hex_records(segments):
    """Intel HEX text for {address: data}, with extended linear address records."""
    out, upper = [], None

    def record(rtype, address, data):
        raw = bytearray((len(data), (address >> 8) & 0xFF, address & 0xFF, rtype)) + data
        raw.append((-sum(raw)) & 0xFF)
        out.append(":" + binascii.hexlify(bytes(raw)).decode().upper())

    for base, data in sorted(segments.items()):
        for offset in range(0, len(data), 16):
            address = base + offset
            if address >> 16 != upper:
                upper = address >> 16
                record(0x04, 0, struct.pack(">H", upper))
            record(0x00, address & 0xFFFF, bytearray(data[offset:offset + 16]))
    record(0x01, 0, bytearray())
    return "\n".join(out) + "\n"


def pb_fields(data):
    """Minimal protobuf reader: {field: [values]}."""
    data, out, i = bytearray(data), {}, 0

    def varint(i):
        shift = value = 0
        while True:
            b = data[i]
            i += 1
            value |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return value, i

    while i < len(data):
        key, i = varint(i)
        if key & 7 == 0:
            value, i = varint(i)
        elif key & 7 == 2:
            n, i = varint(i)
            value, i = bytes(data[i:i + n]), i + n
        else:
            raise ValueError("unexpected wire type")
        out.setdefault(key >> 3, []).append(value)
    return out


def decode_init_packet(dat):
    signed = pb_fields(pb_fields(dat)[2][0])
    command = pb_fields(signed[1][0])
    init_bytes = command[2][0]
    init = pb_fields(init_bytes)
    signature = signed[3][0]
    return {
        "op_code": command[1][0],
        "init_bytes": init_bytes,
        "fw_version": init[1][0],
        "hw_version": init[2][0],
        "sd_req": [pb_fields(b"\x08" + init[3][0])[1][0]],  # single packed varint
        "type": init[4][0],
        "app_size": init[7][0],
        "hash_type": pb_fields(init[8][0])[1][0],
        "hash": pb_fields(init[8][0])[2][0][::-1],
        "boot_validation": pb_fields(init[10][0])[1][0],
        "signature_type": signed[2][0],
        "r": dfu._int32(signature[:32][::-1]),
        "s": dfu._int32(signature[32:][::-1]),
    }


class FakeBootloader(threading.Thread):
    """Device side of the RUI3 serial update, on a pseudo-terminal."""

    def __init__(self, fd, public, mtu=131, reject_with=None):
        super(FakeBootloader, self).__init__()
        self.daemon = True
        self.fd, self.public, self.mtu, self.reject_with = fd, public, mtu, reject_with
        self.events, self.error, self.done = [], None, False
        self.command, self.data, self.current = bytearray(), bytearray(), None
        self.object_start = self.object_size = 0
        self.init = None

    def send(self, payload):
        os.write(self.fd, dfu.slip_encode(payload))

    def reply(self, opcode, payload=b""):
        self.send(bytearray((dfu.OP_RESPONSE, opcode, dfu.RES_SUCCESS)) + payload)

    def run(self):
        try:
            seen = b""
            while not seen.endswith(b"at+boot\r\n"):
                seen += os.read(self.fd, 1)
            self.events.append("at+boot")
            frame, escaped = bytearray(), False
            while not self.done:
                byte = bytearray(os.read(self.fd, 1))[0]
                if escaped:
                    frame.append({dfu.SLIP_ESC_END: dfu.SLIP_END, dfu.SLIP_ESC_ESC: dfu.SLIP_ESC}[byte])
                    escaped = False
                elif byte == dfu.SLIP_ESC:
                    escaped = True
                elif byte == dfu.SLIP_END:
                    if frame:
                        self.handle(bytes(frame))
                    frame = bytearray()
                else:
                    frame.append(byte)
        except Exception as exc:  # reported by the test
            self.error = exc

    def handle(self, frame):
        frame = bytearray(frame)
        op = frame[0]
        if op == dfu.OP_PING:
            self.reply(op, frame[1:2])
        elif op == dfu.OP_SET_PRN:
            self.reply(op)
        elif op == dfu.OP_MTU:
            self.reply(op, struct.pack("<H", self.mtu))
        elif op == dfu.OP_SELECT:
            buf, limit = (self.command, 512) if frame[1] == dfu.OBJ_COMMAND else (self.data, 4096)
            self.reply(op, struct.pack("<III", limit, len(buf), binascii.crc32(bytes(buf)) & 0xFFFFFFFF))
        elif op == dfu.OP_CREATE:
            kind, size = struct.unpack("<BI", bytes(frame[1:6]))
            self.current = kind
            if kind == dfu.OBJ_COMMAND:
                self.command = bytearray()
            else:
                assert self.init is not None, "data object before a valid init packet"
                assert size <= 4096, "data object larger than the bootloader's buffer"
                self.object_start, self.object_size = len(self.data), size
            self.reply(op)
        elif op == dfu.OP_WRITE:
            assert len(dfu.slip_encode(bytes(frame))) <= self.mtu, "frame exceeds the MTU"
            (self.command if self.current == dfu.OBJ_COMMAND else self.data).extend(frame[1:])
        elif op == dfu.OP_CRC:
            buf = self.command if self.current == dfu.OBJ_COMMAND else self.data
            self.reply(op, struct.pack("<II", len(buf), binascii.crc32(bytes(buf)) & 0xFFFFFFFF))
        elif op == dfu.OP_EXECUTE:
            if self.reject_with is not None:
                self.send(bytearray((dfu.OP_RESPONSE, op, dfu.RES_EXTENDED_ERROR, self.reject_with)))
                return
            if self.current == dfu.OBJ_COMMAND:
                init = decode_init_packet(bytes(self.command))
                assert dfu.ecdsa_verify(self.public, init["init_bytes"], init["r"], init["s"]), \
                    "init packet signature does not verify"
                self.init = init
                self.events.append("init packet")
            else:
                assert len(self.data) - self.object_start == self.object_size, "object incomplete"
            self.reply(op)
            if self.current == dfu.OBJ_DATA and len(self.data) == self.init["app_size"]:
                assert hashlib.sha256(bytes(self.data)).digest() == self.init["hash"], "image hash mismatch"
                self.events.append("image %d bytes" % len(self.data))
                self.done = True


class Nrf52DfuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.key_path = os.path.join(self.tmp, "private.key")
        with open(self.key_path, "w") as f:
            f.write(sec1_pem(RFC6979_KEY))
        self.public = dfu._scalar_mult(RFC6979_KEY, dfu._G)
        # An application at 0x26000 with a gap, plus data the image must not
        # contain: the MBR page and a UICR register.
        self.hex_path = os.path.join(self.tmp, "firmware.hex")
        app = bytes(bytearray(range(256))) * 9 + b"\x01\x02\x03"
        with open(self.hex_path, "w") as f:
            f.write(hex_records({0x0: b"\xaa" * 32, 0x26000: app, 0x27000: b"\x55" * 6,
                                 0x10001014: b"\x00\xf0\x0f\x00"}))
        self.app = app

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def package(self, name="firmware.zip"):
        path = os.path.join(self.tmp, name)
        dfu.make_package(self.hex_path, path, self.key_path, [0x0100], 52, 1)
        return path

    def test_rfc6979_vector(self):
        self.assertEqual(dfu.ecdsa_sign(RFC6979_KEY, b"sample"), (RFC6979_R, RFC6979_S))
        self.assertEqual(dfu.load_signing_key(self.key_path), RFC6979_KEY)

    def test_application_image(self):
        image = dfu.application_image(self.hex_path)
        gap = 0x27000 - 0x26000 - len(self.app)
        self.assertEqual(image[:len(self.app)], self.app)
        self.assertEqual(image[len(self.app):len(self.app) + gap], b"\xff" * gap)
        self.assertEqual(image[0x1000:0x1006], b"\x55" * 6)
        self.assertEqual(len(image), 0x1008)  # 0x1006 rounded up to a word

    def test_package(self):
        path = self.package()
        with zipfile.ZipFile(path) as z:
            self.assertEqual(z.namelist(), ["manifest.json", "firmware.dat", "firmware.bin"])
            self.assertEqual(json.loads(z.read("manifest.json").decode()), {
                "manifest": {"application": {"bin_file": "firmware.bin", "dat_file": "firmware.dat"}}})
            image, dat = z.read("firmware.bin"), z.read("firmware.dat")
        self.assertEqual(image, dfu.application_image(self.hex_path))
        init = decode_init_packet(dat)
        self.assertEqual((init["op_code"], init["fw_version"], init["hw_version"], init["sd_req"],
                          init["type"], init["app_size"], init["hash_type"], init["boot_validation"],
                          init["signature_type"]),
                         (1, 1, 52, [0x0100], 0, len(image), 3, 1, 0))
        self.assertEqual(init["hash"], hashlib.sha256(image).digest())
        self.assertTrue(dfu.ecdsa_verify(self.public, init["init_bytes"], init["r"], init["s"]))
        # Byte layout of the init packet nrfutil 6.1.7 writes for an
        # application (taken from one of its packages), signature aside.
        def varint(n):
            return bytes(bytearray((n & 0x7F | 0x80, n >> 7))) if n > 0x7F else bytes(bytearray((n,)))
        expected_init = (binascii.unhexlify("08011034" "1a028002" "20002800300038") + varint(len(image))
                         + binascii.unhexlify("42240803" "1220") + hashlib.sha256(image).digest()[::-1]
                         + binascii.unhexlify("4800" "520408011200"))
        command = binascii.unhexlify("0801") + b"\x12" + varint(len(expected_init)) + expected_init
        signed = b"\x0a" + varint(len(command)) + command + binascii.unhexlify("10001a40")
        self.assertEqual(dat[:-64], b"\x12" + varint(len(signed) + 64) + signed)
        with open(path, "rb") as a, open(self.package("again.zip"), "rb") as b:
            self.assertEqual(a.read(), b.read(), "packages are not reproducible")

    def test_package_options(self):
        recipe = ["/nrfutil", "pkg", "generate", "--hw-version", "52", "--application-version", "1",
                  "--application", "/b/firmware.hex", "--sd-req", "0x0100",
                  "--key-file", "/bsp/security/private.key", "/b/firmware.zip"]
        self.assertEqual(dfu.package_options(recipe), {
            "hw_version": 52, "app_version": 1, "sd_req": [0x0100],
            "key_file": "/bsp/security/private.key"})
        with self.assertRaises(dfu.DfuError):
            dfu.package_options(recipe[:-1] + ["--bootloader-version", "2", recipe[-1]])
        with self.assertRaises(dfu.DfuError):
            dfu.package_options(recipe[:3] + recipe[5:])  # no --hw-version

    @unittest.skipUnless(HAVE_PYSERIAL and hasattr(os, "openpty"), "needs pyserial and a POSIX pty")
    def test_serial_upload(self):
        path = self.package()
        for mtu in (131, 64):
            master, slave = os.openpty()
            try:
                boot = FakeBootloader(master, self.public, mtu)
                boot.start()
                saved, dfu.CONNECT_DELAY = dfu.CONNECT_DELAY, 0.1
                try:
                    dfu.upload(path, os.ttyname(slave), log=lambda _: None)
                finally:
                    dfu.CONNECT_DELAY = saved
                boot.join(2)
                self.assertIsNone(boot.error)
                self.assertEqual(boot.events, ["at+boot", "init packet",
                                               "image %d bytes" % len(dfu.application_image(self.hex_path))])
            finally:
                os.close(slave)
                os.close(master)

    @unittest.skipUnless(HAVE_PYSERIAL and hasattr(os, "openpty"), "needs pyserial and a POSIX pty")
    def test_serial_upload_rejected(self):
        master, slave = os.openpty()
        try:
            FakeBootloader(master, self.public, reject_with=0x05).start()
            saved, dfu.CONNECT_DELAY = dfu.CONNECT_DELAY, 0.1
            try:
                with self.assertRaisesRegex(dfu.DfuError, "refuses downgrades"):
                    dfu.upload(self.package(), os.ttyname(slave), log=lambda _: None)
            finally:
                dfu.CONNECT_DELAY = saved
        finally:
            os.close(slave)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
