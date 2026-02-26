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

        # Reset all BSP packages to optional so that a multi-environment project
        # (e.g. rak3172 + rak4631) doesn't accumulate non-optional flags across
        # successive configure_default_packages() calls on the same platform instance.
        for name in self.packages:
            if name.startswith("framework-rui3-"):
                self.packages[name]["optional"] = True

        # Enable only the BSP package required by this board's MCU core
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

            # Inject package.json only if the BSP does not already ship one.
            # If RAK's upstream repo includes package.json (e.g. after a PR is merged),
            # we use theirs and read the version from it.
            pkg_json_path = os.path.join(extracted_root, "package.json")
            if os.path.isfile(pkg_json_path):
                with open(pkg_json_path) as f:
                    existing = json.load(f)
                semver = existing.get("version", semver)
            else:
                pkg_json = {
                    "name": pkg_name,
                    "version": semver,
                    "description": "RAKwireless RUI3 BSP (%s)" % tag,
                }
                with open(pkg_json_path, "w") as f:
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

            # Apply BSP-specific compatibility patches
            if pkg_name == "framework-rui3-nrf52":
                self._patch_nrf52_bsp(pkg_dir)

            print("%s@%s has been installed!" % (pkg_name, semver))

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if os.path.isfile(tmp_zip):
                os.remove(tmp_zip)

    @staticmethod
    def _patch_nrf52_bsp(pkg_dir):
        """
        Apply compatibility patches to the nRF52 BSP package files.

        The BSP's FUOTA package source files (LmhpFragmentation.c,
        LmhpClockSync.c, LmhpRemoteMcastSetup.c) were not updated for the
        LORA_STACK_104 API change that renamed LmhPackage_t.IsRunning to
        IsTxPending and removed OnSendRequest. This patch adds the required
        #ifdef LORA_STACK_104 guards so the files compile with either API.
        """
        packages_dir = os.path.join(
            pkg_dir, "cores", "nRF5", "component", "service", "lora", "packages"
        )
        patches = {
            "LmhpFragmentation.c": [
                # Fix: .IsRunning → .IsTxPending when LORA_STACK_104
                (
                    "    .IsRunning = LmhpFragmentationIsRunning,",
                    "#ifdef LORA_STACK_104\n"
                    "    .IsTxPending = LmhpFragmentationIsRunning,\n"
                    "#else\n"
                    "    .IsRunning = LmhpFragmentationIsRunning,\n"
                    "#endif",
                ),
                # Fix: .OnSendRequest = NULL only when not LORA_STACK_104
                (
                    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
                    "    .OnDeviceTimeRequest = NULL,",
                    "#ifndef LORA_STACK_104\n"
                    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
                    "#endif\n"
                    "    .OnDeviceTimeRequest = NULL,",
                ),
                # Fix: replace OnSendRequest call with LmHandlerSend in LORA_STACK_104
                (
                    "            LmhpFragmentationPackage.OnSendRequest( &cmdReplyAppData, LORAMAC_HANDLER_UNCONFIRMED_MSG );",
                    "#ifdef LORA_STACK_104\n"
                    "            LmHandlerSend( &cmdReplyAppData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#else\n"
                    "            LmhpFragmentationPackage.OnSendRequest( &cmdReplyAppData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#endif",
                ),
            ],
            "LmhpClockSync.c": [
                (
                    "    .IsRunning = LmhpClockSyncIsRunning,",
                    "#ifdef LORA_STACK_104\n"
                    "    .IsTxPending = LmhpClockSyncIsRunning,\n"
                    "#else\n"
                    "    .IsRunning = LmhpClockSyncIsRunning,\n"
                    "#endif",
                ),
                (
                    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
                    "    .OnDeviceTimeRequest = NULL,",
                    "#ifndef LORA_STACK_104\n"
                    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
                    "#endif\n"
                    "    .OnDeviceTimeRequest = NULL,",
                ),
                (
                    "        LmhpClockSyncPackage.OnSendRequest( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );",
                    "#ifdef LORA_STACK_104\n"
                    "        LmHandlerSend( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#else\n"
                    "        LmhpClockSyncPackage.OnSendRequest( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#endif",
                ),
                (
                    "    return LmhpClockSyncPackage.OnSendRequest( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );",
                    "#ifdef LORA_STACK_104\n"
                    "    return LmHandlerSend( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#else\n"
                    "    return LmhpClockSyncPackage.OnSendRequest( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#endif",
                ),
            ],
            "LmhpRemoteMcastSetup.c": [
                (
                    "    .IsRunning = LmhpRemoteMcastSetupIsRunning,",
                    "#ifdef LORA_STACK_104\n"
                    "    .IsTxPending = LmhpRemoteMcastSetupIsRunning,\n"
                    "#else\n"
                    "    .IsRunning = LmhpRemoteMcastSetupIsRunning,\n"
                    "#endif",
                ),
                (
                    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
                    "    .OnDeviceTimeRequest = NULL,",
                    "#ifndef LORA_STACK_104\n"
                    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
                    "#endif\n"
                    "    .OnDeviceTimeRequest = NULL,",
                ),
                (
                    "        LmhpRemoteMcastSetupPackage.OnSendRequest( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );",
                    "#ifdef LORA_STACK_104\n"
                    "        LmHandlerSend( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#else\n"
                    "        LmhpRemoteMcastSetupPackage.OnSendRequest( &appData, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
                    "#endif",
                ),
            ],
        }

        for filename, file_patches in patches.items():
            fpath = os.path.join(packages_dir, filename)
            if not os.path.isfile(fpath):
                print("Warning: patch target not found: %s" % fpath)
                continue
            with open(fpath, "r") as f:
                content = f.read()
            for old, new in file_patches:
                if old in content:
                    content = content.replace(old, new)
                elif new not in content:
                    # Patch not applied and new content also absent — warn
                    print("Warning: patch target not found in %s:\n  %r" % (filename, old[:80]))
            with open(fpath, "w") as f:
                f.write(content)
