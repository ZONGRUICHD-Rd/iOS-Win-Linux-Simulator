#!/usr/bin/env python3
"""Lists the user-visible strings in Madeira's Swift sources.

    python3 madeira/l10n/extract.py MADEIRA_DIR > keys.json

A string literal counts when it is an argument of a SwiftUI view or modifier
that localizes (Text, Label, Button, ...), of String(localized:), or of one of
the app's own helpers that pass their title to Text. Interpolations become
%@ placeholders, as Xcode writes them for String values (other types get
%lld / %lf; check against the build's .stringsdata, see check.py).
"""
import json
import os
import re
import sys

CALLEES = ("Text", "Label", "Button", "Toggle", "Picker", "Section", "LabeledContent", "Menu", "TextField",
           "SecureField", "Link", "Stepper", "DisclosureGroup", "ContentUnavailableView", "ProgressView",
           "navigationTitle", "alert", "confirmationDialog", "help", "accessibilityLabel", "accessibilityHint",
           "Tab", "ShareLink", "localized", "LocalizedStringKey", "LocalizedStringResource",
           # the app's own helpers that put their title into Text
           "header", "primary", "secondary", "row", "step", "settingRow", "hint", "badge", "pill", "info")
# Developer-only settings, and the Steam/Dock screens this fork hides.
SKIP_FILES = ("ConfigCatalog.generated.swift", "SteamGames.swift", "SteamOwnedLibrary.swift", "SteamCloud.swift",
              "SteamDownloadBackground.swift", "SteamRuntime.swift", "MadeiraDockView.swift", "MadeiraDock.swift",
              "DockStartScreen.swift", "DockInstallers.swift", "SteamSignInView.swift", "SteamSignIn.swift")

LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def literal_key(raw):
    """Swift literal text -> catalog key (\\(x) -> %@, escapes resolved)."""
    out, i = [], 0
    while i < len(raw):
        if raw.startswith("\\(", i):
            depth, j = 1, i + 2
            while j < len(raw) and depth:
                depth += {"(": 1, ")": -1}.get(raw[j], 0)
                j += 1
            out.append("%@")
            i = j
        elif raw.startswith("\\u{", i):
            j = raw.index("}", i)
            out.append(chr(int(raw[i + 3:j], 16)))
            i = j + 1
        elif raw[i] == "\\" and i + 1 < len(raw):
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "'": "'"}.get(raw[i + 1], raw[i + 1]))
            i += 2
        elif raw[i] == "%":
            out.append("%%")
            i += 1
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def calls(src):
    """(callee, argument text) for every call of a CALLEES name."""
    pat = re.compile(r'(?<![\w.])\.?(' + "|".join(CALLEES) + r')\s*\(|String\((?=localized:)')
    for m in pat.finditer(src):
        start = m.end()
        depth, j, in_str = 1, start, False
        while j < len(src) and depth:
            c = src[j]
            if in_str:
                if c == "\\":
                    j += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            j += 1
        yield m.group(1) or "localized", src[start:j - 1]


def main(root):
    app = os.path.join(root, "app/Madeira")
    keys = {}
    for dirpath, _, files in os.walk(app):
        for f in sorted(files):
            if not f.endswith(".swift") or f in SKIP_FILES:
                continue
            path = os.path.join(dirpath, f)
            src = open(path, encoding="utf-8").read()
            for callee, args in calls(src):
                # Only literals at the top level of the argument list, or in a
                # ternary there, are keys; deeper ones belong to other calls.
                for lm in LITERAL.finditer(args):
                    prefix = args[:lm.start()]
                    if prefix.count("(") - prefix.count(")") > 0 and callee not in ("localized",):
                        continue
                    # "a" + "b" is a String, which SwiftUI shows as is: not a key.
                    if re.match(r"\s*\+", args[lm.end():]) or re.search(r"\+\s*$", prefix):
                        continue
                    key = literal_key(lm.group(1))
                    if not re.search(r"[A-Za-z]{2}", key) or key.startswith(("env.", "madeira", "com.", "http")):
                        continue
                    if re.fullmatch(r"[\w.\-/]+", key) and not re.search(r"[A-Z]", key[:1]):
                        continue  # identifiers, symbol names, file names
                    if re.fullmatch(r"[a-z0-9]+(\.[a-z0-9]+)+", key):
                        continue  # SF Symbol names
                    keys.setdefault(key, os.path.relpath(path, app))
    json.dump(keys, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1])
