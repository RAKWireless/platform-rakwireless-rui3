import os
import sys

from platformio.public import PlatformBase

# Framework packages are repackaged upstream BSP tags (see tools/bsp.py) that
# platform.json references by release-asset URL. The same file names are also
# looked up, in this order, in:
#   - RUI3_BSP_DIST: a local folder or another base URL (CI uses it to test
#     freshly built tarballs before they are published);
#   - dist/ next to this file, where `tools/bsp.py package` writes them, so a
#     platform installed from a working copy builds without any release.
BSP_DIST_ENV = "RUI3_BSP_DIST"
LOCAL_DIST_DIR = "dist"

CORE_TO_PACKAGE = {
    "STM32WLE": "framework-rui3-stm32wle",
    "nRF5": "framework-rui3-nrf52",
    "apollo3": "framework-rui3-apollo3",
}


class Rakwirelessrui3Platform(PlatformBase):

    _dist_notice_shown = False

    def is_embedded(self):
        return True

    def configure_default_packages(self, variables, targets):
        board = variables.get("board")
        core = self.board_config(board).get("build.core", "")

        # Reset every BSP package to optional first: in a multi-environment
        # project (rak3172 + rak4631) the same platform instance is configured
        # once per environment, and flags left over from the previous
        # environment would make PlatformIO install BSPs this board never uses.
        for name in CORE_TO_PACKAGE.values():
            if name in self.packages:
                self.packages[name]["optional"] = True
        if core in CORE_TO_PACKAGE:
            self.packages[CORE_TO_PACKAGE[core]]["optional"] = False

        self._apply_bsp_dist_override()
        return super().configure_default_packages(variables, targets)

    def _apply_bsp_dist_override(self):
        env_dist = os.environ.get(BSP_DIST_ENV, "").strip()
        if env_dist and "://" not in env_dist:
            env_dist = os.path.abspath(os.path.expanduser(env_dist))
        local_dist = os.path.join(self.get_dir(), LOCAL_DIST_DIR)

        sources = set()
        for name in CORE_TO_PACKAGE.values():
            options = self.packages.get(name)
            if not options:
                continue
            # A user's platform_packages override has already replaced the
            # version with its own spec; only rewrite release-asset URLs.
            version = options.get("version", "")
            if "/releases/download/" not in version:
                continue
            filename = version.rsplit("/", 1)[-1]
            if env_dist and "://" in env_dist:
                options["version"] = env_dist.rstrip("/") + "/" + filename
                sources.add(env_dist)
            elif env_dist:
                options["version"] = _file_url(os.path.join(env_dist, filename))
                sources.add(env_dist)
            elif os.path.isfile(os.path.join(local_dist, filename)):
                options["version"] = _file_url(os.path.join(local_dist, filename))
                sources.add(local_dist)
        # The platform is loaded by both the pio process and the SCons build
        # process; reporting from the build only gives one line per environment.
        if sources and "SCons" in sys.modules and not Rakwirelessrui3Platform._dist_notice_shown:
            Rakwirelessrui3Platform._dist_notice_shown = True
            print("RUI3: using framework packages from %s" % ", ".join(sorted(sources)))


def _file_url(path):
    return "file://" + path.replace(os.sep, "/")
