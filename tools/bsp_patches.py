"""
Compatibility patches applied to an upstream RUI3 BSP tree while it is being
repackaged as a PlatformIO framework package.

Every patch is a plain text substitution or a small added file, so it is safe
to run on any BSP version: if the original text is missing, either the patch is
already in place (the replacement text is present) or upstream changed the
file, in which case a warning is reported and the file is left as it was.
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


# ruiTop.h, which Arduino.h includes, reaches the variant's app.h (prototypes of
# rui_setup, rui_loop and app_cli_handler) with #include "app.h". arduino-cli
# never puts the sketch folder on the include path, so that always finds
# variants/<variant>/app.h. PlatformIO puts the project's src/ and include/
# folders on it, and many RUI3 sketches have an app.h of their own: it would be
# included in the middle of the BSP headers, before the Arduino classes it uses
# are declared, and the build fails in unrelated places (in RAK's
# RUI3-Best-Practice examples: "'::Print' has not been declared" in ArduinoJson,
# redefined structs). No include-path order fixes it for both the BSP and the
# sketch, because the BSP reaches the variant folder only through -I. So
# ruiTop.h includes a header that exists only in the variant folders, and that
# header includes the app.h next to it: a quoted include is looked up in the
# including file's own folder first.
VARIANT_APP_HEADER = "rui3_variant_app.h"
_RUITOP_PATCH = ('#include "app.h"\n', '#include "%s"\n' % VARIANT_APP_HEADER)
_VARIANT_APP_SOURCE = (
    "/*\n"
    " * Added when this BSP was repackaged for PlatformIO. ruiTop.h includes this\n"
    " * file instead of \"app.h\": PlatformIO puts the project's src/ and include/\n"
    " * folders on the include path, so a sketch's own app.h would be found\n"
    " * instead of this variant's. A quoted include is looked up next to the\n"
    " * including file first, so the line below reaches the app.h in this folder.\n"
    " */\n"
    "#include \"app.h\"\n"
)


def _patch_file(bsp_root, path, patches, log):
    """Apply (old, new) text substitutions to one file; True if it changed."""
    rel = os.path.relpath(path, bsp_root)
    if not os.path.isfile(path):
        log("  warning: patch target not found: %s" % rel)
        return False
    with open(path, "r", newline="") as f:
        original = f.read()
    # The STM32 BSP uses CRLF line endings and the others use LF. Matching on
    # LF-normalised text keeps a single set of patch strings for all three.
    content = original.replace("\r\n", "\n")
    for old, new in patches:
        # A replacement may still contain the original text (the FUOTA guards
        # keep it inside #else), so look for the replacement first; otherwise a
        # second run would nest the guards.
        if new in content:
            continue
        if old in content:
            content = content.replace(old, new)
        else:
            log("  warning: %s: text to patch not found: %r" % (rel, old[:70]))
    if content == original.replace("\r\n", "\n"):
        return False
    with open(path, "w", newline="\n") as f:
        f.write(content)
    return True


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
        if _patch_file(bsp_root, path, patches, log):
            changed.append(os.path.relpath(path, bsp_root))
    return changed


def apply_variant_app_patch(bsp_root, core_dir, log=print):
    """Make ruiTop.h reach the variant's app.h even when the sketch has one.

    Returns the list of files that were modified or added.
    """
    changed = []
    variants_dir = os.path.join(bsp_root, "variants")
    variants = sorted(os.listdir(variants_dir)) if os.path.isdir(variants_dir) else []
    if not variants:
        log("  warning: no variants in %s" % os.path.relpath(variants_dir, bsp_root))
        return changed
    for variant in variants:
        folder = os.path.join(variants_dir, variant)
        if not os.path.isdir(folder):
            continue
        if not os.path.isfile(os.path.join(folder, "app.h")):
            # ruiTop.h needs an app.h from the variant; without one, the
            # Arduino IDE would fail on this variant too.
            log("  warning: variant %s has no app.h" % variant)
            continue
        path = os.path.join(folder, VARIANT_APP_HEADER)
        if os.path.isfile(path):
            with open(path, "r", newline="") as f:
                if f.read() == _VARIANT_APP_SOURCE:
                    continue
        with open(path, "w", newline="\n") as f:
            f.write(_VARIANT_APP_SOURCE)
        changed.append(os.path.relpath(path, bsp_root))

    ruitop = os.path.join(bsp_root, "cores", core_dir, "component", "rui_v3_api", "ruiTop.h")
    if _patch_file(bsp_root, ruitop, [_RUITOP_PATCH], log):
        changed.append(os.path.relpath(ruitop, bsp_root))
    return changed


def apply_all(bsp_root, core_dir, log=print):
    """Apply every compatibility patch; returns the modified files."""
    return (apply_fuota_patches(bsp_root, core_dir, log=log)
            + apply_variant_app_patch(bsp_root, core_dir, log=log))
