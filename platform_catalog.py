# SPDX-License-Identifier: GPL-3.0-or-later
"""Data-only platform catalog. Importing this module never needs Steam or a GUI."""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(ROOT, "platforms", "catalog.json")


def load_catalog():
    with open(CATALOG, encoding="utf-8") as source:
        data = json.load(source)
    if data.get("size") != [600, 900] or data.get("art_window") != [14, 96, 586, 872]:
        raise ValueError("Unsupported frame geometry in platform catalog")
    ids = [item["id"] for item in data["platforms"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate platform id")
    return data


def get_platform(identifier):
    for item in load_catalog()["platforms"]:
        if item["id"] == identifier:
            return item
    raise KeyError("Unknown platform: " + identifier)


def local_asset(path):
    return os.path.join(ROOT, *path.split("/"))
