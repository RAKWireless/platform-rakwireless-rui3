"""
Nordic Secure DFU for RUI3 nRF52 boards, in pure Python.

The Arduino IDE packages and uploads RUI3 nRF52 firmware with Nordic's nrfutil
6.1.7, which RAK ships as a separate frozen executable for each host. This
module does the same two jobs without any executable:

* make_package() writes the signed DFU package `nrfutil pkg generate` makes: a
  zip holding the application image (.bin), its signed init packet (.dat) and
  manifest.json, with the same contents nrfutil 6.1.7 produces.
* upload() does what RAK's uploader.py does: send "at+boot" to the running
  firmware, which restarts into the bootloader, then transfer the package with
  Nordic's serial DFU protocol, as `nrfutil dfu serial` does.

The package settings (hardware version, application version, SoftDevice id,
signing key) are not kept here: package_options() reads them from the nrfutil
command line in the BSP's own recipe. Only upload() needs a third-party module,
pyserial, which PlatformIO itself depends on.

    python nrf52_dfu.py package --key-file private.key --sd-req 0x0100 app.hex app.zip
    python nrf52_dfu.py upload --port /dev/ttyACM0 app.zip
"""

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time
import zipfile


class DfuError(Exception):
    pass


# ---------------------------------------------------------------------------
# Intel HEX to application image
# ---------------------------------------------------------------------------

# The Master Boot Record (the first 4 KB with the s140 SoftDevice) and the
# UICR/FICR registers are never part of an update image; nrfutil drops any
# data there before converting the hex file.
MBR_END = 0x1000
UICR_START = 0x10000000


def read_hex(path):
    """Return the data records of an Intel HEX file as (address, bytes)."""
    records = []
    base = 0
    with open(path, "r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                if not line.startswith(":"):
                    raise ValueError
                raw = bytearray(binascii.unhexlify(line[1:]))
            except (ValueError, TypeError, binascii.Error):
                raise DfuError("%s:%d: not an Intel HEX record" % (path, lineno))
            if len(raw) < 5 or len(raw) != raw[0] + 5 or sum(raw) & 0xFF:
                raise DfuError("%s:%d: corrupt Intel HEX record" % (path, lineno))
            address, rtype, data = (raw[1] << 8) | raw[2], raw[3], bytes(raw[4:-1])
            if rtype == 0x00:
                records.append((base + address, data))
            elif rtype == 0x01:
                break
            elif rtype == 0x02:
                base = int(binascii.hexlify(data), 16) << 4
            elif rtype == 0x04:
                base = int(binascii.hexlify(data), 16) << 16
            # 0x03 and 0x05 hold a start address, which is not image data.
    return records


def application_image(hex_path):
    """The application image as nrfutil sends it.

    Bytes from the lowest to the highest address, gaps filled with 0xFF and
    the length rounded up to a whole word.
    """
    chunks = []
    for address, data in read_hex(hex_path):
        lo, hi = max(address, MBR_END), min(address + len(data), UICR_START)
        if lo < hi:
            chunks.append((lo, data[lo - address:hi - address]))
    if not chunks:
        raise DfuError("%s holds no application data" % hex_path)
    start = min(a for a, _ in chunks)
    end = max(a + len(d) for a, d in chunks)
    image = bytearray(b"\xff" * ((end - start + 3) // 4 * 4))
    for address, data in chunks:
        image[address - start:address - start + len(data)] = data
    return bytes(image)


# ---------------------------------------------------------------------------
# Init packet (protobuf messages from nrfutil's dfu-cc.proto)
# ---------------------------------------------------------------------------

OP_CODE_INIT = 1
FW_TYPE_APPLICATION = 0
HASH_TYPE_SHA256 = 3
VALIDATE_GENERATED_CRC = 1
SIGNATURE_ECDSA_P256_SHA256 = 0


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _uint_field(number, value):
    return _varint(number << 3) + _varint(value)


def _bytes_field(number, data):
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def init_command(image, fw_version, hw_version, sd_req):
    """InitCommand for an application update, field by field as nrfutil 6.1.7
    sets it (every field is set explicitly, so the defaults are encoded too)."""
    sd_list = []
    for sd in sd_req:
        if sd not in sd_list:
            sd_list.append(sd)
    digest = hashlib.sha256(image).digest()[::-1]  # stored little-endian
    return b"".join((
        _uint_field(1, fw_version),
        _uint_field(2, hw_version),
        _bytes_field(3, b"".join(_varint(sd) for sd in sd_list)),  # packed
        _uint_field(4, FW_TYPE_APPLICATION),
        _uint_field(5, 0),  # sd_size
        _uint_field(6, 0),  # bl_size
        _uint_field(7, len(image)),  # app_size
        _bytes_field(8, _uint_field(1, HASH_TYPE_SHA256) + _bytes_field(2, digest)),
        _uint_field(9, 0),  # is_debug
        _bytes_field(10, _uint_field(1, VALIDATE_GENERATED_CRC) + _bytes_field(2, b"")),
    ))


def signed_init_packet(command, signature):
    """Packet { signed_command { command { op_code, init }, type, signature } }"""
    cmd = _uint_field(1, OP_CODE_INIT) + _bytes_field(2, command)
    signed = (_bytes_field(1, cmd) + _uint_field(2, SIGNATURE_ECDSA_P256_SHA256)
              + _bytes_field(3, signature))
    return _bytes_field(2, signed)


# ---------------------------------------------------------------------------
# ECDSA P-256 signing
# ---------------------------------------------------------------------------
#
# The bootloader only accepts init packets signed with the key matching the
# public key built into it, and RAK publishes that private key in every BSP
# (security/private.key): the signature identifies RUI3 firmware, it does not
# keep anything secret. Signing therefore does not need constant-time code.
# Nonces are derived as RFC 6979 specifies, so packages are reproducible.

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)
_PRIME256V1_OID = binascii.unhexlify("2a8648ce3d030107")
_EC_PUBLIC_KEY_OID = binascii.unhexlify("2a8648ce3d0201")


def _inverse(value, modulus):
    return pow(value, modulus - 2, modulus)  # both moduli are prime


def _point_add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % _P == 0:
            return None
        slope = (3 * p[0] * p[0] + _A) * _inverse(2 * p[1], _P) % _P
    else:
        slope = (q[1] - p[1]) * _inverse(q[0] - p[0], _P) % _P
    x = (slope * slope - p[0] - q[0]) % _P
    return x, (slope * (p[0] - x) - p[1]) % _P


def _scalar_mult(k, point):
    result = None
    while k:
        if k & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        k >>= 1
    return result


def _int32(data):
    return int(binascii.hexlify(data), 16)


def _bytes32(value):
    return binascii.unhexlify("%064x" % value)


def _rfc6979_nonces(secret, digest):
    key = b"\x00" * 32
    v = b"\x01" * 32
    seed = _bytes32(secret) + _bytes32(_int32(digest) % _N)
    key = hmac.new(key, v + b"\x00" + seed, hashlib.sha256).digest()
    v = hmac.new(key, v, hashlib.sha256).digest()
    key = hmac.new(key, v + b"\x01" + seed, hashlib.sha256).digest()
    v = hmac.new(key, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(key, v, hashlib.sha256).digest()
        k = _int32(v)
        if 1 <= k < _N:
            yield k
        key = hmac.new(key, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(key, v, hashlib.sha256).digest()


def ecdsa_sign(secret, message):
    """Return (r, s) for SHA-256(message)."""
    digest = hashlib.sha256(message).digest()
    e = _int32(digest)
    for k in _rfc6979_nonces(secret, digest):
        r = _scalar_mult(k, _G)[0] % _N
        s = _inverse(k, _N) * (e + r * secret) % _N
        if r and s:
            return r, s


def ecdsa_verify(public, message, r, s):
    if not (0 < r < _N and 0 < s < _N):
        return False
    w = _inverse(s, _N)
    e = _int32(hashlib.sha256(message).digest())
    point = _point_add(_scalar_mult(e * w % _N, _G), _scalar_mult(r * w % _N, public))
    return point is not None and point[0] % _N == r


def _der(data, pos=0):
    """One DER element at pos: (tag, value, next position)."""
    tag, length, pos = data[pos], data[pos + 1], pos + 2
    if length & 0x80:
        count = length & 0x7F
        length, pos = _int32(data[pos:pos + count].rjust(32, b"\x00")), pos + count
    return tag, data[pos:pos + length], pos + length


def _der_children(data):
    items, pos = [], 0
    while pos < len(data):
        tag, value, pos = _der(data, pos)
        items.append((tag, value))
    return items


def load_signing_key(path):
    """The private scalar from a PEM P-256 key (SEC 1 or PKCS #8)."""
    with open(path, "r") as f:
        pem = f.read()
    match = re.search(r"-----BEGIN (EC PRIVATE KEY|PRIVATE KEY)-----(.*?)-----END \1-----", pem, re.S)
    if not match:
        raise DfuError("%s is not a PEM EC private key" % path)
    try:
        der = bytearray(base64.b64decode("".join(match.group(2).split())))
        if match.group(1) == "PRIVATE KEY":
            _, info, _ = _der(der)
            fields = _der_children(info)
            algorithm = [v for t, v in _der_children(fields[1][1]) if t == 0x06]
            if algorithm[:1] != [_EC_PUBLIC_KEY_OID] or algorithm[1:2] != [_PRIME256V1_OID]:
                raise DfuError("%s is not a P-256 key" % path)
            der = fields[2][1]
        _, sec1, _ = _der(der)
        fields = _der_children(sec1)
        curve = [v for t, v in fields if t == 0xA0]
        if curve and _der(curve[0])[1] != _PRIME256V1_OID:
            raise DfuError("%s is not a P-256 key" % path)
        if fields[1][0] != 0x04:
            raise ValueError
        secret = _int32(bytes(fields[1][1]))
    except (IndexError, ValueError, TypeError, binascii.Error):
        raise DfuError("cannot parse the private key in %s" % path)
    if not 0 < secret < _N:
        raise DfuError("invalid private key in %s" % path)
    return secret


def sign_init_command(secret, command):
    """Signature in the layout the bootloader expects: r and s, each 32 bytes
    little-endian (nrfutil reverses each half of the big-endian signature)."""
    r, s = ecdsa_sign(secret, command)
    # Guards against an arithmetic slip: the bootloader would reject the
    # package with a bare "invalid signature" at upload time.
    if not ecdsa_verify(_scalar_mult(secret, _G), command, r, s):
        raise DfuError("internal error: the init packet signature does not verify")
    return _bytes32(r)[::-1] + _bytes32(s)[::-1]


# ---------------------------------------------------------------------------
# DFU package
# ---------------------------------------------------------------------------

def package_options(args):
    """Package settings from an `nrfutil pkg generate` command line.

    RUI3 BSPs keep them in platform.txt (recipe.objcopy.zip.pattern); reading
    them from there keeps the package identical to the Arduino IDE's. An option
    this module does not implement is an error, so that an upstream change to
    the recipe is noticed instead of silently producing a different package.
    """
    args = list(args)
    for i in range(len(args) - 1):
        if args[i] == "pkg" and args[i + 1] == "generate":
            args = args[i + 2:]
            break
    else:
        raise DfuError("not an `nrfutil pkg generate` command: %s" % " ".join(args))

    options = {"hw_version": None, "app_version": None, "sd_req": None, "key_file": None}
    with_value = {
        "--hw-version": ("hw_version", lambda v: int(v, 0)),
        "--application-version": ("app_version", lambda v: int(v, 0)),
        "--sd-req": ("sd_req", lambda v: [int(x, 16) for x in v.split(",")]),
        "--key-file": ("key_file", str),
        # The image and the output name come from the build itself.
        "--application": (None, str),
    }
    positional = 0
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in with_value and i + 1 < len(args):
            name, convert = with_value[arg]
            try:
                value = convert(args[i + 1])
            except ValueError:
                raise DfuError("invalid value %r for %s in the BSP's DFU recipe" % (args[i + 1], arg))
            if name:
                options[name] = value
            i += 2
        elif not arg.startswith("-") and positional == 0:
            positional += 1  # the output zip
            i += 1
        else:
            raise DfuError("the BSP's DFU recipe uses `%s`, which this platform does not "
                           "implement yet" % arg)
    missing = [k for k, v in options.items() if v is None]
    if missing:
        raise DfuError("the BSP's DFU recipe sets no %s" % ", ".join(sorted(missing)))
    return options


def make_package(hex_path, zip_path, key_file, sd_req, hw_version, app_version):
    """Write the signed DFU package for the application in hex_path."""
    image = application_image(hex_path)
    command = init_command(image, app_version, hw_version, sd_req)
    packet = signed_init_packet(command, sign_init_command(load_signing_key(key_file), command))

    stem = os.path.splitext(os.path.basename(hex_path))[0]
    manifest = {"manifest": {"application": {"bin_file": stem + ".bin", "dat_file": stem + ".dat"}}}
    files = (("manifest.json", json.dumps(manifest, indent=4).encode("utf-8")),
             (stem + ".dat", packet),
             (stem + ".bin", image))
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for name, data in files:
            # Fixed timestamps, so the same firmware gives the same package.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    os.replace(tmp, zip_path)


def read_package(zip_path):
    """(name, init packet, image) for each image, in the order nrfutil sends them."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))["manifest"]
            return [(kind, z.read(manifest[kind]["dat_file"]), z.read(manifest[kind]["bin_file"]))
                    for kind in ("softdevice_bootloader", "softdevice", "bootloader", "application")
                    if kind in manifest]
    except (OSError, KeyError, ValueError, zipfile.BadZipfile) as exc:
        raise DfuError("cannot read DFU package %s: %s" % (zip_path, exc))


# ---------------------------------------------------------------------------
# Serial DFU
# ---------------------------------------------------------------------------

SLIP_END, SLIP_ESC, SLIP_ESC_END, SLIP_ESC_ESC = 0xC0, 0xDB, 0xDC, 0xDD

OP_CREATE, OP_SET_PRN, OP_CRC, OP_EXECUTE = 0x01, 0x02, 0x03, 0x04
OP_SELECT, OP_MTU, OP_WRITE, OP_PING, OP_RESPONSE = 0x06, 0x07, 0x08, 0x09, 0x60
OBJ_COMMAND, OBJ_DATA = 0x01, 0x02
RES_SUCCESS, RES_EXTENDED_ERROR = 0x01, 0x0B

RESULTS = {
    0x00: "invalid opcode", 0x02: "opcode not supported", 0x03: "invalid parameter",
    0x04: "insufficient resources", 0x05: "invalid object", 0x06: "invalid signature",
    0x07: "unsupported type", 0x08: "operation not permitted", 0x0A: "operation failed",
}
EXTENDED_ERRORS = {
    0x03: "command not supported", 0x04: "invalid init command",
    0x05: "firmware version too low (the bootloader refuses downgrades)",
    0x06: "hardware version does not match this device",
    0x07: "the update requires a different SoftDevice than the one on the device",
    0x08: "the init packet must be signed", 0x09: "hash type not supported",
    0x0A: "cannot calculate the firmware hash", 0x0B: "signature type not supported",
    0x0C: "the firmware hash does not match the init packet",
    0x0D: "not enough space on the device", 0x0E: "this firmware is already on the device",
}

BAUDRATE = 115200
# Same timings as `nrfutil dfu serial`: wait before connecting to the
# bootloader, then up to TIMEOUT for the port to appear and answer a ping.
CONNECT_DELAY = 3.0
TIMEOUT = 30.0
READ_TIMEOUT = 1.0


def slip_encode(data):
    out = bytearray()
    for byte in bytearray(data):
        if byte == SLIP_END:
            out += bytearray((SLIP_ESC, SLIP_ESC_END))
        elif byte == SLIP_ESC:
            out += bytearray((SLIP_ESC, SLIP_ESC_ESC))
        else:
            out.append(byte)
    out.append(SLIP_END)
    return bytes(out)


def _serial():
    try:
        import serial  # noqa: F401
        import serial.tools.list_ports  # noqa: F401
    except ImportError:
        raise DfuError("uploading needs pyserial (pip install pyserial)")
    return serial


def _port_present(port):
    serial = _serial()
    if any(p.device == port for p in serial.tools.list_ports.comports()):
        return True
    return os.name != "nt" and os.path.exists(port)


def enter_bootloader(port, log=print):
    """Ask the running RUI3 firmware to restart into its DFU bootloader.

    RUI3 enters DFU on "at+boot" both in AT command mode and when the sketch
    uses the port for its own data (its serial driver watches for the string),
    and ignores the 1200-baud touch other Arduino cores use. These are the
    bytes RAK's uploader.py sends. A board already in the bootloader discards
    them as an invalid frame.
    """
    serial = _serial()
    log("Requesting DFU mode on %s (at+boot)" % port)
    try:
        with serial.Serial(port=port, baudrate=BAUDRATE, timeout=5) as ser:
            for chunk in (b"\r", b"\n", b"at\r\n", b"at+boot\r\n"):
                ser.write(chunk)
            time.sleep(1)
    except (serial.SerialException, OSError) as exc:
        raise DfuError("cannot open %s: %s" % (port, exc))


class SerialDfu(object):
    """Client side of Nordic's serial DFU transport (SLIP-framed requests)."""

    def __init__(self, ser):
        self.ser = ser
        self.ping_id = 0
        self.mtu = 0

    def _send(self, payload):
        self.ser.write(slip_encode(payload))

    def _receive(self):
        """One decoded frame, or None if the device stays silent READ_TIMEOUT."""
        frame, escaped = bytearray(), False
        while True:
            byte = self.ser.read(1)
            if not byte:
                return None
            byte = bytearray(byte)[0]
            if escaped:
                escaped = False
                if byte == SLIP_ESC_END:
                    frame.append(SLIP_END)
                elif byte == SLIP_ESC_ESC:
                    frame.append(SLIP_ESC)
                else:
                    frame, escaped = bytearray(), False  # invalid escape: drop the frame
            elif byte == SLIP_END:
                return bytes(frame)
            elif byte == SLIP_ESC:
                escaped = True
            else:
                frame.append(byte)

    def request(self, opcode, payload=b"", optional_response=False):
        self._send(bytearray((opcode,)) + payload)
        response = self._receive()
        if response is None:
            # nrfutil does not wait for Execute replies that do not come in
            # time either: after the last object the bootloader may already
            # be validating the image and restarting.
            if optional_response:
                return b""
            raise DfuError("no response from the bootloader (opcode 0x%02X)" % opcode)
        response = bytearray(response)
        if len(response) < 3 or response[0] != OP_RESPONSE or response[1] != opcode:
            raise DfuError("unexpected response %s to opcode 0x%02X" % (
                binascii.hexlify(bytes(response)).decode(), opcode))
        if response[2] == RES_SUCCESS:
            return bytes(response[3:])
        if response[2] == RES_EXTENDED_ERROR and len(response) > 3:
            raise DfuError("bootloader error: %s" % EXTENDED_ERRORS.get(
                response[3], "extended error 0x%02X" % response[3]))
        raise DfuError("bootloader error: %s" % RESULTS.get(response[2], "0x%02X" % response[2]))

    def ping(self):
        self.ping_id = (self.ping_id + 1) % 256
        self._send(bytearray((OP_PING, self.ping_id)))
        response = self._receive()
        if not response or len(response) < 3:
            return False
        response = bytearray(response)
        if response[0] != OP_RESPONSE or response[1] != OP_PING:
            return False
        # Bootloaders without ping answer with an error code: still alive.
        return response[2] != RES_SUCCESS or response[3:4] == bytearray((self.ping_id,))

    def connect(self, timeout=TIMEOUT):
        deadline = time.time() + timeout
        while not self.ping():
            if time.time() > deadline:
                raise DfuError("the bootloader does not answer (is the board in DFU mode?)")
        self.request(OP_SET_PRN, struct.pack("<H", 0))
        self.mtu = struct.unpack("<H", self.request(OP_MTU)[:2])[0]
        if self.mtu < 8:
            raise DfuError("bootloader reports an unusable MTU of %d" % self.mtu)

    def _select(self, kind):
        return struct.unpack("<III", self.request(OP_SELECT, bytearray((kind,)))[:12])

    def _stream(self, data, crc, offset):
        # Every byte may need escaping, so a write carries at most half the
        # MTU, less the opcode (nrfutil's sizing).
        step = (self.mtu - 1) // 2 - 1
        for i in range(0, len(data), step):
            chunk = data[i:i + step]
            self._send(bytearray((OP_WRITE,)) + chunk)
            crc = binascii.crc32(chunk, crc) & 0xFFFFFFFF
            offset += len(chunk)
        got_offset, got_crc = struct.unpack("<II", self.request(OP_CRC)[:8])
        if (got_offset, got_crc) != (offset, crc):
            raise DfuError("transfer check failed: device has %d bytes, CRC 0x%08X; "
                           "expected %d bytes, CRC 0x%08X" % (got_offset, got_crc, offset, crc))
        return crc

    def send_init_packet(self, packet):
        max_size = self._select(OBJ_COMMAND)[0]
        if len(packet) > max_size:
            raise DfuError("init packet (%d bytes) exceeds the bootloader's %d" % (len(packet), max_size))
        self.request(OP_CREATE, struct.pack("<BI", OBJ_COMMAND, len(packet)))
        self._stream(packet, 0, 0)
        self.request(OP_EXECUTE, optional_response=True)

    def send_firmware(self, image, progress=None):
        max_size = self._select(OBJ_DATA)[0]
        crc = 0
        for offset in range(0, len(image), max_size):
            chunk = image[offset:offset + max_size]
            self.request(OP_CREATE, struct.pack("<BI", OBJ_DATA, len(chunk)))
            crc = self._stream(chunk, crc, offset)
            self.request(OP_EXECUTE, optional_response=True)
            if progress:
                progress(offset + len(chunk), len(image))


def _progress_printer(log):
    state = {"last": -1}

    def show(done, total):
        percent = done * 100 // total
        if percent // 10 != state["last"] // 10 or done == total:
            state["last"] = percent
            log("  %3d%% (%d of %d bytes)" % (percent, done, total))
    return show


def upload(zip_path, port, log=print, request_bootloader=True):
    """Flash a DFU package through the RUI3 bootloader on a serial port."""
    serial = _serial()
    images = read_package(zip_path)
    if not port:
        raise DfuError("no upload port (set upload_port in platformio.ini)")
    if request_bootloader:
        enter_bootloader(port, log)

    for kind, packet, image in images:
        time.sleep(CONNECT_DELAY)
        deadline = time.time() + TIMEOUT
        while not _port_present(port):
            if time.time() > deadline:
                raise DfuError("%s did not come back after restarting into the bootloader" % port)
            time.sleep(0.5)
        log("Sending %s (%d bytes) to the bootloader on %s" % (kind, len(image), port))
        try:
            # rtscts as in nrfutil, which RAK's uploader runs with its defaults.
            with serial.Serial(port=port, baudrate=BAUDRATE, rtscts=True,
                               timeout=READ_TIMEOUT) as ser:
                dfu = SerialDfu(ser)
                dfu.connect()
                dfu.send_init_packet(packet)
                dfu.send_firmware(image, _progress_printer(log))
        except (serial.SerialException, OSError) as exc:
            raise DfuError("serial error on %s: %s" % (port, exc))
    log("Device programmed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    pkg = sub.add_parser("package", help="build a signed DFU package from an Intel HEX file")
    pkg.add_argument("--key-file", required=True)
    pkg.add_argument("--sd-req", required=True, help="comma-separated SoftDevice ids, e.g. 0x0100")
    pkg.add_argument("--hw-version", type=lambda v: int(v, 0), default=52)
    pkg.add_argument("--application-version", type=lambda v: int(v, 0), default=1)
    pkg.add_argument("hex")
    pkg.add_argument("zip")
    up = sub.add_parser("upload", help="flash a DFU package over serial")
    up.add_argument("--port", required=True)
    up.add_argument("--no-at-boot", action="store_true",
                    help="the board is already in the bootloader")
    up.add_argument("zip")
    args = parser.parse_args(argv)
    try:
        if args.command == "package":
            make_package(args.hex, args.zip, args.key_file,
                         [int(x, 16) for x in args.sd_req.split(",")],
                         args.hw_version, args.application_version)
        elif args.command == "upload":
            upload(args.zip, args.port, request_bootloader=not args.no_at_boot)
        else:
            parser.print_help()
            return 2
    except DfuError as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
