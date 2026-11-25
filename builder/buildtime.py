"""
Build timestamp for RUI3 firmware.

Each BSP variant ships a version.c whose BUILD_DATE and BUILD_TIME macros the
firmware reports (for example through AT commands). The Arduino IDE rewrites
them in place before every build with RAK's buildtime tool; here the same
substitution is written to a copy, so the installed package stays untouched.
Pure Python, so it behaves the same on every host.
"""

import os
import re
import time

_DATE_RE = re.compile(r'^(\s*#\s*define\s+BUILD_DATE\s+)"[^"]*"', re.MULTILINE)
_TIME_RE = re.compile(r'^(\s*#\s*define\s+BUILD_TIME\s+)"[^"]*"', re.MULTILINE)


def generate_version_source(template_path, output_path, now=None):
    """Write template_path to output_path with the current build date and time."""
    now = time.localtime() if now is None else now
    with open(template_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    content = _DATE_RE.sub(r'\g<1>"%s"' % time.strftime("%Y%m%d", now), content)
    content = _TIME_RE.sub(r'\g<1>"%s"' % time.strftime("%H%M%S", now), content)

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
