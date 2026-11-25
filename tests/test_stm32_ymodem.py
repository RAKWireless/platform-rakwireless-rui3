"""
Tests for builder/stm32_ymodem.py.

The serial upload runs against a simulated RUI3 STM32WLE board on a
pseudo-terminal: the firmware (an AT console at a given baud rate, or a sketch
that uses the port for its own data) and the RUI3 bootloader, whose YMODEM
receiver follows ST's IAP implementation (a 'C' whenever it has waited for a
block, ACK then 'C' for the header, ACK for EOT). Bytes sent at a baud rate the
listening side does not use are dropped, so the baud rate search is tested
too. Like the real bootloader, which reads the UART only between replies, the
simulated one loses what arrives while it is still sending an answer.

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
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "builder"))
import stm32_ymodem as ym  # noqa: E402

try:
    import serial  # noqa: F401
    import termios
    HAVE_PTY = hasattr(os, "openpty")
except ImportError:
    HAVE_PTY = False

SOH, STX, EOT, ACK, NAK, CAN = 0x01, 0x02, 0x04, 0x06, 0x15, 0x18
# Time the simulated bootloader takes per character of an answer (a real one
# at 115200 baud: 87 us), long enough to make the window visible on a pty.
ANSWER_CHAR_TIME = 0.001


class FakeStm32Board(threading.Thread):
    def __init__(self, fd, app_baud=115200, at_console=True, in_bootloader=False,
                 nak_block=None, nak_first_eot=False, refuse=False, silent=False,
                 version="4.3.0"):
        super().__init__(daemon=True)
        self.fd = fd
        self.app_baud = app_baud
        self.version = version
        self.at_console = at_console
        self.state = "bootloader" if in_bootloader else "firmware"
        self.nak_block, self.nak_first_eot, self.refuse = nak_block, nak_first_eot, refuse
        self.silent = silent
        self.stop = False
        self.error = None
        self.log = []
        self.name = self.size = self.image = None

    # -- I/O ------------------------------------------------------------
    def _baud_code(self, rate):
        return getattr(termios, "B%d" % rate)

    def read_byte(self, timeout):
        """(byte, baud code the port was set to) or None."""
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return None
        try:
            data = os.read(self.fd, 1)
        except OSError:
            return None
        if not data:
            return None
        return bytearray(data)[0], termios.tcgetattr(self.fd)[5]

    def read_exact(self, size, timeout=1.0):
        out = bytearray()
        while len(out) < size:
            got = self.read_byte(timeout)
            if got is None:
                return None
            out.append(got[0])
        return bytes(out)

    def send(self, data):
        os.write(self.fd, bytes(data))

    def answer(self, text):
        """A bootloader answer: sent at serial speed, input arriving meanwhile is lost."""
        for char in bytearray(text):
            os.write(self.fd, bytes((char,)))
            time.sleep(ANSWER_CHAR_TIME)
        while select.select([self.fd], [], [], 0)[0]:
            self.log.append("lost %r" % os.read(self.fd, 256))

    # -- Firmware and bootloader command lines ---------------------------
    def run(self):
        try:
            line = bytearray()
            while not self.stop:
                if self.state == "ymodem":
                    self.receive()
                    continue
                got = self.read_byte(0.05)
                if got is None or self.silent:
                    continue
                byte, baud = got
                rate = self.app_baud if self.state == "firmware" else 115200
                if baud != self._baud_code(rate):
                    continue  # garbage at this baud rate
                if byte in (0x0D, 0x0A):
                    if line:
                        self.command(bytes(line).lower())
                    line = bytearray()
                else:
                    line.append(byte)
        except Exception as exc:  # reported by the test
            self.error = exc

    def command(self, line):
        if self.state == "firmware":
            if line == b"at+boot":
                self.log.append("at+boot at %d" % self.app_baud)
                self.state = "bootloader"
                self.send(b"<BOOT MODE>\r\n")
            elif self.at_console:
                if line == b"at+ver=?":
                    self.send(b"AT+VER=RUI_%s_RAK3172-E\r\nOK\r\n" % self.version.encode())
                else:
                    self.send(b"OK\r\n" if line == b"at" else b"AT_COMMAND_NOT_FOUND\r\n")
        elif line == b"at+update":
            self.log.append("at+update")
            self.state = "ymodem"
        else:
            self.answer(b"AT not support.\r\n")

    # -- YMODEM receiver ---------------------------------------------------
    def receive(self):
        expected, data, file_done, nakked_eot = 0, bytearray(), False, False
        while not self.stop:
            got = self.read_byte(0.3)
            if got is None:
                self.send(b"C")  # ask for a block
                continue
            start = got[0]
            if start == EOT:
                if self.nak_first_eot and not nakked_eot:
                    nakked_eot = True
                    self.send(bytes((NAK,)))
                    continue
                self.send(bytes((ACK,)))
                file_done, expected = True, 0
                continue
            if start not in (SOH, STX):
                continue
            size = 1024 if start == STX else 128
            rest = self.read_exact(size + 4)
            if rest is None:
                self.send(b"C")
                continue
            seq, inv, payload, check = rest[0], rest[1], rest[2:2 + size], rest[2 + size:]
            if seq != 0xFF - inv or struct.unpack(">H", check)[0] != binascii.crc_hqx(payload, 0):
                self.send(bytes((NAK,)))
                continue
            if seq != expected & 0xFF:
                self.send(bytes((NAK,)))
                continue
            if expected == 0:
                if file_done:
                    assert payload == bytes(size), "batch must end with an empty header"
                    self.send(bytes((ACK,)))
                    self.image = bytes(data[:self.size])
                    self.log.append("done")
                    self.state = "done"
                    return
                name, length = payload.split(b"\0")[:2]
                if self.refuse:
                    self.send(bytes((CAN, CAN)))
                    self.state = "done"
                    return
                self.name, self.size = name.decode(), int(length)
                self.send(bytes((ACK,)) + b"C")
            else:
                if seq == self.nak_block:
                    self.nak_block = None
                    self.send(bytes((NAK,)))
                    continue
                data += payload
                self.send(bytes((ACK,)))
            expected += 1


@unittest.skipUnless(HAVE_PTY, "needs pyserial and a POSIX pty")
class Stm32SerialUploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.image = os.urandom(5000)  # 5 blocks, the last one padded
        self.path = os.path.join(self.tmp, "firmware.bin")
        with open(self.path, "wb") as f:
            f.write(self.image)
        self.saved = {name: getattr(ym, name) for name in
                      ("TYPE_GAP", "LINE_GAP", "REPLY_WAIT", "RESTART_WAIT", "START_TIMEOUT",
                       "QUIET", "UPDATE_WAIT")}
        ym.QUIET, ym.UPDATE_WAIT = 0.1, 1.0
        # Typed characters come slower than an answer takes, as on hardware.
        ym.TYPE_GAP, ym.LINE_GAP, ym.REPLY_WAIT, ym.RESTART_WAIT = 0.03, 0.05, 0.4, 0.05
        ym.START_TIMEOUT = 5.0

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(ym, name, value)
        shutil.rmtree(self.tmp)

    def upload(self, expected_version=None, **board_options):
        master, slave = os.openpty()
        board = FakeStm32Board(master, **board_options)
        board.start()
        lines = []
        try:
            ym.upload(self.path, os.ttyname(slave), log=lines.append,
                      expected_version=expected_version)
            error = None
        except ym.UploadError as exc:
            error = exc
        finally:
            board.stop = True
            board.join(3)
            os.close(slave)
            os.close(master)
        self.assertIsNone(board.error)
        return error, board, lines

    def assert_programmed(self, error, board):
        self.assertIsNone(error)
        self.assertEqual(board.name, "firmware.bin")
        self.assertEqual(board.size, len(self.image))
        self.assertEqual(board.image, self.image)

    def test_block_format(self):
        self.assertEqual(ym.crc16(b"123456789"), 0x31C3)  # CRC-16/XMODEM check value
        block = ym.make_block(1, b"\x1a" * 1024)
        self.assertEqual(block[:3], b"\x02\x01\xfe")
        self.assertEqual(len(block), 3 + 1024 + 2)
        self.assertEqual(ym.make_block(0, b"x" * 128, use_crc=False)[-1], (ord("x") * 128) & 0xFF)
        header = ym.header_payload("firmware.bin", 5000)
        self.assertEqual(header[:18], b"firmware.bin\x005000\x00")
        self.assertEqual(len(header), 1024)

    def test_upload_from_at_console(self):
        error, board, lines = self.upload(expected_version="4.3.0")
        self.assert_programmed(error, board)
        # Characters typed while the bootloader answers are lost, as on hardware.
        events = [e for e in board.log if not e.startswith("lost")]
        self.assertEqual(events, ["at+boot at 115200", "at+update", "done"])
        self.assertIn("Device programmed.", lines)

    def test_upload_while_sketch_uses_the_port(self):
        # RUI3 catches at+boot even when the sketch owns the serial port, so
        # no answer to "at" is needed (RAK's uploader insists on one). There
        # is no AT console to ask for the version either.
        error, board, _ = self.upload(expected_version="4.3.0", at_console=False)
        self.assert_programmed(error, board)

    def test_upload_refuses_another_major_version(self):
        error, board, _ = self.upload(expected_version="4.3.0", version="5.0.2")
        self.assertIn("the board runs RUI_5.0.2_RAK3172-E", str(error))
        self.assertIn("upload_flags = --force", str(error))
        self.assertNotIn("at+boot at 115200", board.log)
        # Same major version, and the 5.x spelling of platform.txt's version.
        error, board, _ = self.upload(expected_version="RUI_5.0.2", version="5.1.0")
        self.assert_programmed(error, board)

    def test_upload_finds_the_console_baud_rate(self):
        error, board, lines = self.upload(app_baud=9600)
        self.assert_programmed(error, board)
        self.assertIn("at+boot at 9600", board.log)
        self.assertIn("AT console found at 9600 baud", lines)

    def test_upload_from_bootloader(self):
        error, board, lines = self.upload(in_bootloader=True)
        self.assert_programmed(error, board)
        self.assertIn("The board is in its bootloader", lines)
        self.assertNotIn("at+boot at 115200", board.log)

    def test_upload_resends_refused_blocks(self):
        error, board, _ = self.upload(nak_block=3, nak_first_eot=True)
        self.assert_programmed(error, board)

    def test_upload_refused(self):
        error, _, _ = self.upload(refuse=True)
        self.assertIn("cancelled", str(error))

    def test_no_board(self):
        ym.REPLY_WAIT = 0.1
        error, _, _ = self.upload(silent=True)
        self.assertIn("neither RUI3 firmware nor the RUI3 bootloader", str(error))


if __name__ == "__main__":
    unittest.main()
