#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export 600x900 transparent platform frame PNGs without Steam or the GUI.

Run: python tools/build_platform_frames.py --all
Or:  python tools/build_platform_frames.py --platform ps4 --variant colored --output ps4.png
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_catalog import get_platform, load_catalog, local_asset
from tools.build_frame import render_platform_frame


def export_frame(platform, output, variant=None, region=None):
    if platform["id"] == "steam" and variant is None and region is None:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        shutil.copyfile(local_asset(platform["legacy_frame"]), output)
        return
    if region and (region != "genesis" or platform["id"] != "mega_drive"):
        raise ValueError("Genesis is a regional option only for mega_drive")
    logos = platform.get("regional_logos", {}) if region else platform["logos"]
    selected = variant or platform["logo_default"]
    if selected and selected not in logos:
        raise ValueError("%s has no %s SVG logo" % (platform["id"], selected))
    logo_path = local_asset(logos[selected]) if selected else None
    render_platform_frame(platform["palette"], logo_path, output,
                          platform["template"]["logo_box"], platform["template"].get("logo_scale", 1.0))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="write the default PNG for every platform")
    target.add_argument("--platform", help="platform id from platforms/catalog.json")
    parser.add_argument("--variant", choices=("light", "dark", "colored"), help="override its default logo variant")
    parser.add_argument("--region", choices=("genesis",), help="use the Genesis regional wordmark")
    parser.add_argument("--output", help="PNG file (single platform only)")
    args = parser.parse_args(argv)
    if args.all:
        if args.variant or args.region or args.output:
            parser.error("--all does not accept --variant, --region or --output")
        for platform in load_catalog()["platforms"]:
            output = local_asset("assets/frames/%s.png" % platform["id"])
            export_frame(platform, output)
            print("wrote", output)
    else:
        platform = get_platform(args.platform)
        output = os.path.abspath(args.output or local_asset("assets/frames/%s.png" % platform["id"]))
        export_frame(platform, output, args.variant, args.region)
        print("wrote", output)


if __name__ == "__main__":
    main()
