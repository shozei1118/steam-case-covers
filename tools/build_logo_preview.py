#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a local, self-contained index of platform frames and SVG logo variants."""
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_catalog import ROOT, load_catalog


def escape(value):
    return html.escape(str(value), quote=True)


def logo_variants(platform):
    result = []
    for key, label in (("light", "Light / Just White"),
                       ("dark", "Dark / Just Black"), ("colored", "Colored")):
        path = platform["logos"].get(key)
        if path:
            background = "#1a2745" if key != "dark" else "#e6ebf0"
            result.append(f'<div class="variant" style="--chip:{background}"><span>{escape(label)}</span>'
                          f'<img src="{escape(path)}" alt="{escape(platform["name"])} {escape(label)}"></div>')
        else:
            result.append(f'<div class="variant absent"><span>{escape(label)}</span><em>Unavailable</em></div>')
    for key, label, background in (("light", "Genesis region / Light", "#1a2745"),
                                   ("dark", "Genesis region / Dark", "#e6ebf0"),
                                   ("colored", "Genesis region / Colored", "#1a2745")):
        path = platform.get("regional_logos", {}).get(key)
        if path:
            result.append(f'<div class="variant" style="--chip:{background}"><span>{label}</span>'
                          f'<img src="{escape(path)}" alt="{label} logo"></div>')
    return "".join(result)


def card(platform):
    notes = "".join(f'<li>{escape(note)}</li>' for note in platform["review"])
    status = "missing" if not platform["logo_default"] else ("review" if platform["review"] else "ready")
    selected = platform["logo_default"] or "missing"
    return f'''<article class="card" id="{escape(platform["id"])}">
  <div class="card-head"><div><small>{escape(platform["family"])}</small><h2>{escape(platform["name"])}</h2></div><b class="status {status}">{status}</b></div>
  <div class="frame"><img src="assets/frames/{escape(platform["id"])}.png" alt="{escape(platform["name"])} transparent frame"></div>
  <p class="meta"><span class="swatch" style="background:{escape(platform["frame_color"])}"></span>
     {escape(platform["frame_color"])} · selected: <strong>{escape(selected)}</strong></p>
  <div class="variants">{logo_variants(platform)}</div>
  {f'<ul class="notes">{notes}</ul>' if notes else ''}
</article>'''


def main():
    platforms = load_catalog()["platforms"]
    body = "\n".join(card(platform) for platform in platforms)
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Case Covers · platform logo and frame preview</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,Segoe UI,sans-serif;background:#0d1420;color:#edf3ff}}
*{{box-sizing:border-box}}body{{margin:0}}header{{padding:30px max(24px,4vw);background:linear-gradient(135deg,#17273d,#0d1420)}}
h1{{font-size:clamp(1.7rem,3vw,2.5rem);margin:0 0 8px}}header p{{max-width:760px;color:#bbcbdd;margin:0;line-height:1.5}}
main{{padding:24px max(20px,4vw) 50px;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}}
.card{{background:#172335;border:1px solid #2c425c;border-radius:16px;padding:18px;min-width:0}}
.card-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}}.card h2{{margin:3px 0 14px;font-size:1.2rem}}
.card small{{color:#9fb3c9}}.status{{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;padding:5px 8px;border-radius:20px;background:#1d644c}}
.status.review{{background:#754c20}}.status.missing{{background:#903c43}}.frame{{height:215px;display:grid;place-items:center;background:repeating-conic-gradient(#202c3b 0 25%,#172230 0 50%) 50%/20px 20px;border-radius:10px;overflow:hidden}}
.frame img{{height:198px;width:auto;object-fit:contain}}.meta{{display:flex;align-items:center;gap:7px;font-size:.82rem;color:#c7d3e0;margin:13px 0}}
.swatch{{width:17px;height:17px;border-radius:50%;border:1px solid #ffffff88;display:inline-block;flex:none}}.variants{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
.variant{{padding:7px;border:1px solid #3a5068;border-radius:8px;min-width:0}}.variant span{{display:block;font-size:.7rem;color:#bdcddd;margin-bottom:6px}}
.variant img{{display:block;width:100%;height:46px;object-fit:contain;background:var(--chip);padding:5px;border-radius:5px}}
.variant.absent{{opacity:.55}}.variant em{{font-size:.73rem}}.notes{{color:#ffcc81;font-size:.75rem;line-height:1.4;padding-left:18px;margin:13px 0 0}}
footer{{padding:0 max(24px,4vw) 30px;color:#9fb3c9;font-size:.8rem}}a{{color:#9ed0ff}}
</style></head><body>
<header><h1>Case Covers · platform preview</h1><p>{len(platforms)} platform configurations · 600 × 900 transparent PNG frames · original logo aspect ratios. The selected variant and available SVG alternatives are shown for each platform. Brand marks remain with their owners.</p></header>
<main>{body}</main><footer>Source and per-file license details: <a href="assets/logos/MANIFEST.json">logo manifest</a> and <a href="THIRD_PARTY.md">third-party notices</a>.</footer>
</body></html>'''
    output = os.path.join(ROOT, "logo-preview.html")
    with open(output, "w", encoding="utf-8") as target:
        target.write(page)
    print("wrote", output)


if __name__ == "__main__":
    main()
