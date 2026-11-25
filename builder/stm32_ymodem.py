"""
Serial upload for RUI3 STM32WLE boards (RAK3172 and the boards built on it).

Pure Python replacement for RAK's uploader_ymodem.py, which the Arduino IDE
runs with the sketch's .bin file:

1. The RUI3 bootloader answers commands it does not know with
   "AT not support.", so a probe tells whether the board is already in it.
2. Otherwise "at+boot" makes the firmware restart into the bootloader. RUI3
   watches for it on the serial port even while the sketch uses the port for
   its own data. A firmware whose AT console runs at another baud rate is
   found by trying the rates RAK's uploader tries until one answers "at".
3. "at+update" starts the bootloader's YMODEM receiver. The image goes over
   as YMODEM-1K, framed as RAK's uploader frames it: a 1 KB header block with
   the file name and size, 1 KB data blocks padded with 0x1A and checked with
   CRC-16, EOT, and an empty header block that ends the batch.

The module's UART reaches the computer through a USB serial bridge, so the
port stays open while the module restarts into its bootloader.

usage: python stm32_ymodem.py --port /dev/ttyUSB0 .pio/build/<env>/firmware.bin
"""

import argparse
import binascii
import os
import re
import struct
import sys
import time

BOOT_BAUDRATE = 115200
# The rates RAK's uploader tries, in its order, to find the AT console.
APP_BAUDRATES = (115200, 9600, 921600, 57600, 38400, 19200, 230400, 460800,
                 76800, 56000, 31250, 28800, 14400, 4800, 250000, 1000000,
                 2400, 1200)
BOOT_REPLY = b"AT not support"

# Timings of RAK's uploader, in seconds: the gap between characters typed one
# at a time, between command lines, how long to wait for an answer, and for
# the firmware to restart into the bootloader.
TYPE_GAP = 0.5
LINE_GAP = 0.5
REPLY_WAIT = 2.0
RESTART_WAIT = 1.0
# The bootloader reads the UART only between answers: a command that arrives
# while it is still answering the previous one is lost. Commands to it wait
# until the line has been quiet this long.
QUIET = 0.3
# It asks for the first block about 0.5 s after "at+update".
UPDATE_WAIT = 3.0
UPDATE_ATTEMPTS = 3

SOH, STX, EOT, ACK, NAK, CAN, CRC16 = 0x01, 0x02, 0x04, 0x06, 0x15, 0x18, 0x43
BLOCK_SIZE = 1024
PAD = b"\x1a"
RETRIES = 10
# The bootloader acknowledges the header block once it has erased the
# application area (about 2 s for the whole STM32WLE5 flash), and each data
# block once it is written.
START_TIMEOUT = 15.0
HEADER_TIMEOUT = 15.0
BLOCK_TIMEOUT = 5.0


class UploadError(Exception):
    pass


def _serial():
    try:
        import serial  # noqa: F401
    except ImportError:
        raise UploadError("uploading needs pyserial (pip install pyserial)")
    return serial


# ---------------------------------------------------------------------------
# Entering the bootloader
# ---------------------------------------------------------------------------

def _read_for(ser, seconds, until=()):
    """What the device sends within `seconds`, returning early once any of
    the byte strings in `until` has arrived."""
    data = bytearray()
    deadline = time.time() + seconds
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            data += chunk
            if any(marker in data for marker in until):
                break
    return bytes(data)


def _settle(ser):
    """Wait until the device has stopped sending (QUIET), for at most REPLY_WAIT."""
    deadline = time.time() + REPLY_WAIT
    last = time.time()
    while time.time() < deadline and time.time() - last < QUIET:
        if ser.read(ser.in_waiting or 1):
            last = time.time()


def in_bootloader(ser):
    """Whether the RUI3 bootloader answers on the port.

    These are the bytes RAK's uploader sends: a sleeping firmware wakes up on
    the first character it receives and can lose it, so the command is first
    typed one character at a time.
    """
    ser.baudrate = BOOT_BAUDRATE
    ser.reset_input_buffer()
    for char in bytearray(b"at+\r\n"):
        ser.write(bytes(bytearray((char,))))
        time.sleep(TYPE_GAP)
    ser.write(b"at+\r\n")
    return BOOT_REPLY in _read_for(ser, REPLY_WAIT, until=(BOOT_REPLY,))


def _set_baudrate(ser, baudrate):
    serial = _serial()
    try:
        ser.baudrate = baudrate
    except (ValueError, serial.SerialException):
        return False  # a rate this host's driver does not support
    return True


_VERSION_RE = re.compile(br"(\d+)\.(\d+)\.(\d+)")


def _major(version):
    """Major number of a RUI3 version string ("4.3.0", "RUI_5.0.2"), or None."""
    match = _VERSION_RE.search(version if isinstance(version, bytes) else version.encode())
    return int(match.group(1)) if match else None


def firmware_version(ser):
    """The version the running firmware reports ("RUI_4.3.0_RAK3172-E"), or
    None when no AT console answers (the sketch may use the port itself)."""
    _settle(ser)
    ser.reset_input_buffer()
    ser.write(b"AT+VER=?\r\n")
    reply = _read_for(ser, REPLY_WAIT, until=(b"OK\r\n", b"ERROR"))
    match = re.search(br"AT\+VER=(\S+)", reply)
    return match.group(1).decode("ascii", "replace") if match else None


def check_firmware_version(ser, expected):
    """Refuse to replace firmware of another RUI3 major version than `expected`.

    A board that came with RUI3 5.x can have the 5.x FUOTA bootloader, which
    keeps the LoRaWAN stack in a partition of its own. Given a 4.x image it
    writes only the part that fits the application partition (92 KB of
    179 KB, seen on a RAK3172), acknowledges every block anyway, and then
    crashes calling into the stack partition: the board no longer starts and
    needs SWD to recover.
    """
    match = _VERSION_RE.search((expected or "").encode())
    if not match:
        return
    running = firmware_version(ser)
    if running and _major(running) is not None and _major(running) != int(match.group(1)):
        raise UploadError(
            "the board runs %s and this firmware is built with RUI3 %s. Its bootloader may "
            "belong to the other major version: a RUI3 5.x FUOTA bootloader installs only the "
            "first 92 KB of a 4.x image (and acknowledges all of it), and the board no longer "
            "starts. Build with a BSP of the board's major version, or set "
            "`upload_flags = --force` to upload anyway"
            % (running, match.group(0).decode()))


def _at_console_answers(ser, baudrate):
    """Whether a RUI3 AT console answers "at" at `baudrate`."""
    if not _set_baudrate(ser, baudrate):
        return False
    ser.reset_input_buffer()
    ser.write(b"\r\n\r\n")
    time.sleep(LINE_GAP)
    ser.write(b"at\r\n")
    reply = _read_for(ser, REPLY_WAIT, until=(b"OK\r\n", b"AT_ERROR"))
    return b"OK\r\n" in reply or b"AT_ERROR" in reply


def _request_boot(ser, baudrate):
    # The line ending clears whatever the firmware has half received, and
    # "at" wakes a sleeping firmware before the command that matters.
    _set_baudrate(ser, baudrate)
    for chunk in (b"\r\n", b"at\r\n", b"at+boot\r\n"):
        ser.write(chunk)
        time.sleep(LINE_GAP)
    time.sleep(RESTART_WAIT)
    return in_bootloader(ser)


def enter_bootloader(ser, log=print, expected_version=None):
    """Bring the board into the RUI3 bootloader, at BOOT_BAUDRATE. With
    `expected_version` (the BSP's), refuse a firmware of another major version
    (see check_firmware_version)."""
    if in_bootloader(ser):
        log("The board is in its bootloader")
        return
    check_firmware_version(ser, expected_version)
    log("Requesting the bootloader (at+boot)")
    if _request_boot(ser, BOOT_BAUDRATE):
        return
    log("No answer at %d baud; looking for the AT console" % BOOT_BAUDRATE)
    for baudrate in APP_BAUDRATES:
        if _at_console_answers(ser, baudrate):
            log("AT console found at %d baud" % baudrate)
            check_firmware_version(ser, expected_version)
            if _request_boot(ser, baudrate):
                return
            raise UploadError("the firmware answers at %d baud but did not restart "
                              "into its bootloader after at+boot" % baudrate)
    raise UploadError("neither RUI3 firmware nor the RUI3 bootloader answers on this "
                      "port (is it the board's port?)")


# ---------------------------------------------------------------------------
# YMODEM
# ---------------------------------------------------------------------------

def crc16(data):
    """CRC-16/XMODEM (polynomial 0x1021, initial value 0), as YMODEM uses."""
    return binascii.crc_hqx(bytes(data), 0)


def make_block(seq, payload, use_crc=True):
    """One YMODEM block: start byte, sequence number and its complement,
    payload, and the CRC-16 (big-endian) or the 8-bit sum of the payload."""
    payload = bytes(payload)
    start = STX if len(payload) == BLOCK_SIZE else SOH
    seq &= 0xFF
    if use_crc:
        check = struct.pack(">H", crc16(payload))
    else:
        check = struct.pack("B", sum(bytearray(payload)) & 0xFF)
    return struct.pack("BBB", start, seq, 0xFF - seq) + payload + check


def header_payload(name, size):
    """Block 0: file name, NUL, size in decimal, padded with NULs."""
    info = name.encode("utf-8") + b"\0" + str(size).encode("ascii")
    if len(info) >= BLOCK_SIZE:
        raise UploadError("file name too long for a YMODEM header: %s" % name)
    return info.ljust(BLOCK_SIZE, b"\0")


class YmodemSender(object):
    def __init__(self, ser):
        self.ser = ser
        self.use_crc = True

    def _reply(self, timeout, wanted):
        """The first byte in `wanted` the receiver sends within `timeout`, or
        None. Other bytes (text the bootloader prints) are skipped; two CAN
        bytes in a row abort the transfer."""
        deadline = time.time() + timeout
        cancels = 0
        while time.time() < deadline:
            byte = self.ser.read(1)
            if not byte:
                continue
            byte = bytearray(byte)[0]
            if byte == CAN:
                cancels += 1
                if cancels == 2:
                    raise UploadError("the bootloader cancelled the transfer")
                continue
            cancels = 0
            if byte in wanted:
                return byte
        return None

    def wait_for_receiver(self, timeout=START_TIMEOUT):
        """Wait for the receiver to ask for a block: 'C' for CRC-16, NAK for
        the 8-bit checksum. False if it does not ask within `timeout`."""
        byte = self._reply(timeout, (CRC16, NAK))
        if byte is None:
            return False
        self.use_crc = byte == CRC16
        return True

    def send_block(self, seq, payload, timeout, what):
        # Sent again on NAK or silence. A 'C' is not treated as a request to
        # repeat: the receiver also sends one whenever it has waited a while,
        # and one crossing an acknowledgement would duplicate a block.
        block = make_block(seq, payload, self.use_crc)
        for _ in range(RETRIES + 1):
            self.ser.write(block)
            if self._reply(timeout, (ACK, NAK)) == ACK:
                return
        raise UploadError("the bootloader did not acknowledge the %s" % what)

    def send(self, name, data, progress=None, requested=False):
        """Send one file; `requested` if the receiver has already asked for
        the first block (see wait_for_receiver)."""
        if not requested and not self.wait_for_receiver():
            raise UploadError("the bootloader did not start a YMODEM transfer")
        # Requests that came while the receiver was waiting are answered by
        # the header itself.
        self.ser.reset_input_buffer()
        self.send_block(0, header_payload(name, len(data)), HEADER_TIMEOUT, "file header")
        if not self.wait_for_receiver():
            raise UploadError("the bootloader did not ask for the file's data")

        for offset in range(0, len(data), BLOCK_SIZE):
            chunk = data[offset:offset + BLOCK_SIZE].ljust(BLOCK_SIZE, PAD)
            seq = offset // BLOCK_SIZE + 1
            self.send_block(seq, chunk, BLOCK_TIMEOUT, "block %d" % seq)
            if progress:
                progress(min(offset + BLOCK_SIZE, len(data)), len(data))

        for _ in range(RETRIES + 1):
            self.ser.write(bytes(bytearray((EOT,))))
            if self._reply(BLOCK_TIMEOUT, (ACK, NAK)) == ACK:
                break
        else:
            raise UploadError("the bootloader did not acknowledge the end of the file")
        self.send_block(0, bytes(BLOCK_SIZE), BLOCK_TIMEOUT, "end of the batch")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _progress_printer(log):
    state = {"last": -1}

    def show(done, total):
        percent = done * 100 // total
        if percent // 10 != state["last"] // 10 or done == total:
            state["last"] = percent
            log("  %3d%% (%d of %d bytes)" % (percent, done, total))
    return show


def start_update(ser, sender):
    """Start the bootloader's YMODEM receiver with "at+update"."""
    for _ in range(UPDATE_ATTEMPTS):
        _settle(ser)
        ser.write(b"at+update\r\n")
        if sender.wait_for_receiver(UPDATE_WAIT):
            return
    raise UploadError("the bootloader did not start a YMODEM transfer after at+update")


def upload(bin_path, port, log=print, request_bootloader=True, expected_version=None):
    """Flash an application image through the RUI3 bootloader.

    expected_version: the RUI3 version the image is built with; the upload is
    refused if the running firmware reports another major version.
    """
    serial = _serial()
    with open(bin_path, "rb") as f:
        image = f.read()
    if not image:
        raise UploadError("%s is empty" % bin_path)
    if not port:
        raise UploadError("no upload port (set upload_port in platformio.ini)")
    try:
        with serial.Serial(port=port, baudrate=BOOT_BAUDRATE, timeout=0.1) as ser:
            if request_bootloader:
                enter_bootloader(ser, log, expected_version)
            log("Sending %s (%d bytes) to the bootloader on %s" % (
                os.path.basename(bin_path), len(image), port))
            sender = YmodemSender(ser)
            start_update(ser, sender)
            sender.send(os.path.basename(bin_path), image, _progress_printer(log), requested=True)
    except (serial.SerialException, OSError) as exc:
        raise UploadError("serial error on %s: %s" % (port, exc))
    log("Device programmed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("--port", required=True)
    parser.add_argument("--no-at-boot", action="store_true",
                        help="the board is already in the bootloader")
    parser.add_argument("--rui3-version",
                        help="RUI3 version the image is built with; refuse a board that runs "
                             "another major version")
    parser.add_argument("bin")
    args = parser.parse_args(argv)
    try:
        upload(args.bin, args.port, request_bootloader=not args.no_at_boot,
               expected_version=args.rui3_version)
    except UploadError as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
