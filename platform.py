import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile

from platformio.public import PlatformBase


class Rakwirelessrui3Platform(PlatformBase):

    def is_embedded(self):
        return True

    def configure_default_packages(self, variables, targets):
        board = variables.get("board")
        board_config = self.board_config(board)
        core = board_config.get("build.core", "")

        # Enable the correct framework package based on the MCU core
        if core == "STM32WLE":
            self.packages["framework-rui3-stm32wle"]["optional"] = False
        elif core == "nRF5":
            self.packages["framework-rui3-nrf52"]["optional"] = False

        return super().configure_default_packages(variables, targets)

    def install_required_packages(self, force=False):
        for name, options in self.packages.items():
            if options.get("optional"):
                continue

            version = options.get("version", "")
            if name.startswith("framework-rui3-") and version.startswith("http"):
                self._install_rak_bsp(name, version, force=force)
            else:
                self.install_package(name, force=force)

    def _install_rak_bsp(self, pkg_name, zip_url, force=False):
        """
        Download a RAK BSP zip, inject package.json and .piopm metadata
        (both absent from upstream), and install into the PlatformIO packages
        directory so get_package_dir() can find it.
        """
        from platformio.package.meta import PackageItem, PackageMetadata, PackageSpec

        pkg_dir = os.path.join(self.pm.package_dir, pkg_name)
        if not force and os.path.isdir(pkg_dir):
            return

        print("Downloading %s ..." % zip_url)
        tmp_zip = tempfile.mktemp(suffix=".zip")
        tmp_dir = tempfile.mkdtemp(prefix="rak-bsp-")

        try:
            urllib.request.urlretrieve(zip_url, tmp_zip)

            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(tmp_dir)

            # GitHub zips have a single top-level REPO-TAG/ directory
            entries = os.listdir(tmp_dir)
            if len(entries) == 1 and os.path.isdir(os.path.join(tmp_dir, entries[0])):
                extracted_root = os.path.join(tmp_dir, entries[0])
            else:
                extracted_root = tmp_dir

            # Derive a semver-compatible version from the tag in the URL
            # e.g. "v5.0.2_350" → "5.0.2"
            tag_match = re.search(r"tags/(.+)\.zip", zip_url)
            tag = tag_match.group(1) if tag_match else "0.0.0"
            semver = re.sub(r"^v", "", re.split(r"[_\-]", tag)[0])
            if not re.match(r"^\d+\.\d+\.\d+", semver):
                semver = "0.0.0"

            # Inject the package.json PlatformIO requires for find_pkg_root()
            pkg_json = {
                "name": pkg_name,
                "version": semver,
                "description": "RAKwireless RUI3 BSP (%s)" % tag,
            }
            with open(os.path.join(extracted_root, "package.json"), "w") as f:
                json.dump(pkg_json, f, indent=2)

            # Replace existing installation if forced
            if force and os.path.isdir(pkg_dir):
                shutil.rmtree(pkg_dir)

            shutil.copytree(extracted_root, pkg_dir)

            # Write .piopm so get_package_dir() can resolve this package
            from platformio.package.meta import PackageType
            pkg_item = PackageItem(
                pkg_dir,
                PackageMetadata(
                    type=PackageType.TOOL,
                    name=pkg_name,
                    version=semver,
                    spec=PackageSpec(name=pkg_name, uri=zip_url),
                ),
            )
            pkg_item.dump_meta()

            print("%s@%s has been installed!" % (pkg_name, semver))

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if os.path.isfile(tmp_zip):
                os.remove(tmp_zip)
