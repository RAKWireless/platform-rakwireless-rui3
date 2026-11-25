"""
Compatibility patches applied to an upstream RUI3 BSP tree while it is being
repackaged as a PlatformIO framework package.

Every patch is a plain text substitution, so it is safe to run on any BSP
version: if the original text is missing, either the patch is already in place
(the replacement text is present) or upstream changed the file, in which case
a warning is reported and the file is left as it was.
"""

import os

# The FUOTA package sources (LmhpFragmentation.c, LmhpClockSync.c,
# LmhpRemoteMcastSetup.c) still use the LmhPackage_t API of LoRaMac-node 4.4.7:
# an IsRunning member and an OnSendRequest callback. With LORA_STACK_104 defined
# (it is, for every 4.x board), LmhPackage_t uses IsTxPending and has no
# OnSendRequest, so these files stop compiling as soon as SUPPORT_FUOTA is
# enabled. The guards below let them compile with either API.
_ON_SEND_REQUEST_NULL = (
    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
    "    .OnDeviceTimeRequest = NULL,"
)
_ON_SEND_REQUEST_NULL_GUARDED = (
    "#ifndef LORA_STACK_104\n"
    "    .OnSendRequest = NULL,                                     // To be initialized by LmHandler\n"
    "#endif\n"
    "    .OnDeviceTimeRequest = NULL,"
)


def _is_running_guard(func):
    return (
        "    .IsRunning = %s," % func,
        "#ifdef LORA_STACK_104\n"
        "    .IsTxPending = %s,\n"
        "#else\n"
        "    .IsRunning = %s,\n"
        "#endif" % (func, func),
    )


def _send_guard(indent, prefix, package, payload):
    call = "%s%sPackage.OnSendRequest( &%s, LORAMAC_HANDLER_UNCONFIRMED_MSG );" % (
        indent + prefix, package, payload)
    return (
        call,
        "#ifdef LORA_STACK_104\n"
        "%sLmHandlerSend( &%s, LORAMAC_HANDLER_UNCONFIRMED_MSG );\n"
        "#else\n"
        "%s\n"
        "#endif" % (indent + prefix, payload, call),
    )


FUOTA_PATCHES = {
    "LmhpFragmentation.c": [
        _is_running_guard("LmhpFragmentationIsRunning"),
        (_ON_SEND_REQUEST_NULL, _ON_SEND_REQUEST_NULL_GUARDED),
        _send_guard("            ", "", "LmhpFragmentation", "cmdReplyAppData"),
    ],
    "LmhpClockSync.c": [
        _is_running_guard("LmhpClockSyncIsRunning"),
        (_ON_SEND_REQUEST_NULL, _ON_SEND_REQUEST_NULL_GUARDED),
        _send_guard("        ", "", "LmhpClockSync", "appData"),
        _send_guard("    ", "return ", "LmhpClockSync", "appData"),
    ],
    "LmhpRemoteMcastSetup.c": [
        _is_running_guard("LmhpRemoteMcastSetupIsRunning"),
        (_ON_SEND_REQUEST_NULL, _ON_SEND_REQUEST_NULL_GUARDED),
        _send_guard("        ", "", "LmhpRemoteMcastSetup", "appData"),
    ],
}


def apply_fuota_patches(bsp_root, core_dir, log=print):
    """Patch the FUOTA package sources under cores/<core_dir>/.../lora/packages.

    Returns the list of files that were modified.
    """
    packages_dir = os.path.join(
        bsp_root, "cores", core_dir, "component", "service", "lora", "packages"
    )
    changed = []
    for filename, patches in FUOTA_PATCHES.items():
        path = os.path.join(packages_dir, filename)
        if not os.path.isfile(path):
            log("  warning: patch target not found: %s" % os.path.relpath(path, bsp_root))
            continue
        with open(path, "r", newline="") as f:
            original = f.read()
        # The STM32 BSP uses CRLF line endings and the others use LF. Matching on
        # LF-normalised text keeps a single set of patch strings for all three.
        content = original.replace("\r\n", "\n")
        for old, new in patches:
            # The replacement still contains the original line (inside #else),
            # so look for the replacement first; otherwise a second run would
            # nest the guards.
            if new in content:
                continue
            if old in content:
                content = content.replace(old, new)
            else:
                log("  warning: %s: text to patch not found: %r" % (filename, old[:70]))
        if content != original.replace("\r\n", "\n"):
            with open(path, "w", newline="\n") as f:
                f.write(content)
            changed.append(os.path.relpath(path, bsp_root))
    return changed


def apply_all(bsp_root, core_dir, log=print):
    """Apply every compatibility patch; returns the modified files."""
    return apply_fuota_patches(bsp_root, core_dir, log=log)
