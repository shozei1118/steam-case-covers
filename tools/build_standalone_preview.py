#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Embed every frame, SVG logo and source notice into one portable HTML file."""
import base64
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_catalog import ROOT, load_catalog


def main():
    source = os.path.join(ROOT, "logo-preview.html")
    output = os.path.join(ROOT, "logo-preview-standalone.html")
    with open(source, encoding="utf-8") as page_file:
        page = page_file.read()
    embedded = []

    def inline_image(match):
        relative = html.unescape(match.group(2))
        path = os.path.realpath(os.path.join(ROOT, relative))
        if os.path.commonpath((ROOT, path)) != ROOT or not os.path.isfile(path):
            raise ValueError("Unsafe or missing preview image: " + relative)
        extension = os.path.splitext(path)[1].lower()
        if extension not in (".png", ".svg"):
            raise ValueError("Unsupported preview image: " + relative)
        mime = "image/png" if extension == ".png" else "image/svg+xml"
        with open(path, "rb") as asset:
            data = base64.b64encode(asset.read()).decode("ascii")
        embedded.append(relative)
        return match.group(1) + "data:" + mime + ";base64," + data + match.group(3)

    page = re.sub(r'(<img\b[^>]*\bsrc=")([^"]+)(")', inline_image, page)
    with open(os.path.join(ROOT, "assets", "logos", "MANIFEST.json"), encoding="utf-8") as manifest:
        manifest_data = json.load(manifest)
    expected = len(load_catalog()["platforms"]) + len(manifest_data["files"])
    if len(embedded) != expected:
        raise ValueError("Expected %d preview images, found %d" % (expected, len(embedded)))

    with open(os.path.join(ROOT, "THIRD_PARTY.md"), encoding="utf-8") as notices:
        notice_text = html.escape(notices.read())
    with open(os.path.join(ROOT, "assets", "logos", "MANIFEST.json"), encoding="utf-8") as manifest:
        manifest_text = html.escape(manifest.read())
    footer = ('<footer><details><summary>Source and per-file license details (embedded)</summary>'
              '<h2>Third-party notices</h2><pre style="white-space:pre-wrap">' + notice_text + '</pre>'
              '<h2>Logo manifest</h2><pre style="white-space:pre-wrap">' + manifest_text + '</pre>'
              '</details></footer>')
    page, count = re.subn(r'<footer>.*?</footer>', lambda match: footer, page, count=1, flags=re.S)
    if count != 1 or re.search(r'\bhref\s*=', page) or re.search(r'<img\b[^>]*\bsrc="(?!data:)', page):
        raise ValueError("The standalone preview still has external file references")
    page = page.replace("<title>Case Covers · platform logo and frame preview</title>",
                        "<title>Case Covers · standalone platform preview</title>")
    with open(output, "w", encoding="utf-8", newline="\n") as target:
        target.write(page)
    print("wrote", output, "| embedded images:", len(embedded))


if __name__ == "__main__":
    main()
