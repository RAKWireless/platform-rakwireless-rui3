"""
Tests for tools/bsp_patches.py.

The FUOTA guards are checked by building the 4.x BSPs with SUPPORT_FUOTA;
these tests cover the app.h patch on a small BSP-shaped tree, and check with
the host C preprocessor that a sketch's own app.h no longer replaces the
variant's inside ruiTop.h.

    python -m unittest discover -s tests
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import bsp_patches  # noqa: E402

CORE = "nRF5"
RUITOP = os.path.join("cores", CORE, "component", "rui_v3_api", "ruiTop.h")
HOST_CC = shutil.which("cc") or shutil.which("gcc")


def write(path, text, eol="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        f.write(text.replace("\n", eol))


def read(path):
    with open(path, newline="") as f:
        return f.read()


class VariantAppPatchTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="bsp-patches-")
        self.addCleanup(shutil.rmtree, self.root)
        self.log = []

    def make_bsp(self, eol="\n"):
        write(os.path.join(self.root, RUITOP),
              "#pragma once\n#include \"app.h\"\n#define RUI_TOP 1\n", eol)
        for variant in ("WisCore_RAK4631_Board", "WisCore_RAK3401_Board"):
            write(os.path.join(self.root, "variants", variant, "app.h"),
                  "#define VARIANT_APP \"%s\"\n" % variant, eol)

    def patch(self):
        return bsp_patches.apply_variant_app_patch(self.root, CORE, log=self.log.append)

    def test_ruitop_includes_variant_header(self):
        self.make_bsp()
        changed = self.patch()
        self.assertEqual(sorted(changed), sorted([
            RUITOP,
            os.path.join("variants", "WisCore_RAK3401_Board", "rui3_variant_app.h"),
            os.path.join("variants", "WisCore_RAK4631_Board", "rui3_variant_app.h"),
        ]))
        ruitop = read(os.path.join(self.root, RUITOP))
        self.assertIn('#include "rui3_variant_app.h"\n', ruitop)
        self.assertNotIn('#include "app.h"', ruitop)
        header = read(os.path.join(self.root, "variants", "WisCore_RAK4631_Board", "rui3_variant_app.h"))
        self.assertTrue(header.endswith('#include "app.h"\n'))
        self.assertEqual(self.log, [])

    def test_second_run_changes_nothing(self):
        self.make_bsp()
        self.patch()
        self.assertEqual(self.patch(), [])
        self.assertEqual(self.log, [])

    def test_crlf_ruitop(self):
        self.make_bsp(eol="\r\n")
        self.assertIn(RUITOP, self.patch())
        self.assertIn('#include "rui3_variant_app.h"', read(os.path.join(self.root, RUITOP)))

    def test_variant_without_app_h_is_reported(self):
        self.make_bsp()
        os.makedirs(os.path.join(self.root, "variants", "NoApp_Board"))
        self.patch()
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "variants", "NoApp_Board", "rui3_variant_app.h")))
        self.assertEqual(self.log, ["  warning: variant NoApp_Board has no app.h"])

    def test_upstream_change_is_reported(self):
        write(os.path.join(self.root, RUITOP), "#pragma once\n#include <app.h>\n")
        write(os.path.join(self.root, "variants", "A", "app.h"), "")
        self.patch()
        self.assertEqual(len(self.log), 1)
        self.assertIn("text to patch not found", self.log[0])

    def preprocess(self):
        """Preprocess a sketch the way PlatformIO compiles it: the project's
        include/ and src/ folders come first on the include path, then the BSP's
        core and variant folders, and the sketch has an app.h of its own. The
        sketch includes ruiTop.h, as Arduino.h does."""
        project = os.path.join(self.root, "project")
        write(os.path.join(project, "include", "app.h"), "#define SKETCH_APP 1\n")
        sketch = os.path.join(project, "src", "main.c")
        write(sketch, '#include "ruiTop.h"\n')
        return subprocess.run(
            [HOST_CC, "-E", "-dM",
             "-I", os.path.join(project, "include"),
             "-I", os.path.join(project, "src"),
             "-I", os.path.join(self.root, os.path.dirname(RUITOP)),
             "-I", os.path.join(self.root, "variants", "WisCore_RAK4631_Board"),
             sketch],
            check=True, capture_output=True, text=True).stdout

    @unittest.skipUnless(HOST_CC, "no host C compiler")
    def test_unpatched_bsp_reaches_sketch_app_h(self):
        self.make_bsp()
        out = self.preprocess()
        self.assertIn("SKETCH_APP", out)
        self.assertNotIn("VARIANT_APP", out)

    @unittest.skipUnless(HOST_CC, "no host C compiler")
    def test_patched_bsp_reaches_variant_app_h(self):
        self.make_bsp()
        self.patch()
        out = self.preprocess()
        self.assertIn('#define VARIANT_APP "WisCore_RAK4631_Board"', out)
        self.assertNotIn("SKETCH_APP", out)

if __name__ == "__main__":
    unittest.main()
