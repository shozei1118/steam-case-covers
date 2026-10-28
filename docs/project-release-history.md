# Earlier Shozei project releases

These entries describe the project’s own releases before the Platinum branch was integrated. Version numbers overlap with the original project history retained in CHANGELOG.md.

## [1.2.1] - 2026-10-24
- Release workflow: skip signed build provenance while the repository is private, so the release files are published. No app changes since 1.2.0.

## [1.2.0] - 2026-10-24
- Fixed: Apply in the Tkinter fallback failed on a fresh install because the artwork cache folder did not exist yet.
- Security: Pillow 13.0.0 and certifi 2026.10.19 (known vulnerabilities in the previous pins). Running from source now needs Python 3.11 or newer.
- CI: Qt tests and selftest also run on Linux, the security scan covers the new modules, logo SVGs keep identical bytes on Windows checkouts, and the GUI fuzzer no longer touches the real credential store, network or file dialogs.
- Reuse artwork-grid tiles between games so repeatedly loading large SteamGridDB result sets cannot trigger a native PySide6 access violation while adding covers to Batch. Added persistent Qt/Python and native crash logs plus a 60-cover stress check.
- Strengthened the PlayStation 5 and Wii case rims and lower lips so their platform colors remain visible around dark artwork; frame geometry and header logos are unchanged.
- Arranged the three Steam steps beside a full-height manual search/export panel, with a stacked layout on narrow windows. Artwork choices now appear as a scrollable thumbnail grid with background loading and cache reuse; the selected image still shows its final platform frame.
- Renamed the app and release artifacts to Case Covers, with a new original multi-cover icon.
- Removed the update-check button and its GitHub request; Settings now occupies the upper-right action position. The `--version` CLI option remains available.
