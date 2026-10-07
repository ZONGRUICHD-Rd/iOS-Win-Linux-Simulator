#!/usr/bin/env python3
"""Writes Madeira's string catalog from madeira/l10n/zh-Hans.json.

    python3 madeira/l10n/build_catalog.py MADEIRA_DIR

Checks every string extract.py finds has a translation whose placeholders
match, then writes app/Madeira/Localizable.xcstrings (source language en,
translations zh-Hans). Exits non-zero when a string is missing or mismatched.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:@|lld|ld|d|lf|f|%)")


def placeholders(s):
    return sorted(p for p in (re.sub(r"\d+\$", "", m) for m in PLACEHOLDER.findall(s)) if p != "%%")


def main(root):
    zh = json.load(open(os.path.join(HERE, "zh-Hans.json"), encoding="utf-8"))
    keys = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "extract.py"), root],
                                     check=True, capture_output=True, text=True).stdout)
    missing = sorted(k for k in keys if k not in zh)
    bad = sorted(k for k, v in zh.items() if placeholders(k) != placeholders(v))
    for k in missing:
        print("missing translation: %r (%s)" % (k, keys[k]))
    for k in bad:
        print("placeholders differ: %r -> %r" % (k, zh[k]))
    catalog = {"sourceLanguage": "en", "version": "1.0", "strings": {}}
    for k, v in sorted(zh.items()):
        catalog["strings"][k] = {"localizations": {"zh-Hans": {"stringUnit": {"state": "translated", "value": v}}}}
    out = os.path.join(root, "app/Madeira/Localizable.xcstrings")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2, separators=(",", " : "))
        f.write("\n")
    print("%d translations -> %s" % (len(zh), os.path.relpath(out, root)))
    return 1 if missing or bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
