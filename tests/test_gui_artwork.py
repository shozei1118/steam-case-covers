"""Thumbnail conversion stays off the Tk thread and reports results as events."""
import io
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import gui


class ThumbnailWorker(unittest.TestCase):
    def test_cached_image_becomes_a_small_png_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cached.png"
            Image.new("RGB", (600, 900), (70, 110, 180)).save(path)
            target = SimpleNamespace(events=queue.Queue())
            with patch.object(gui.cw, "ArtworkClient", return_value=SimpleNamespace(image=lambda url: path)):
                gui.App._manual_thumb_worker(target, 4, 2, "https://example.com/art.png")
            event = target.events.get_nowait()
            self.assertEqual(event[:4], ("manual_thumb", 4, 2, "https://example.com/art.png"))
            self.assertIsNone(event[5])
            with Image.open(io.BytesIO(event[4])) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 0)
                self.assertGreater(image.height, image.width)

    def test_failed_image_reports_an_error_for_its_tile(self):
        target = SimpleNamespace(events=queue.Queue())
        def unavailable(_url):
            raise gui.sc.SteamcaseError("Image unavailable")
        with patch.object(gui.cw, "ArtworkClient", return_value=SimpleNamespace(image=unavailable)):
            gui.App._manual_thumb_worker(target, 9, 0, "https://example.com/missing.png")
        event = target.events.get_nowait()
        self.assertEqual(event[:4], ("manual_thumb", 9, 0, "https://example.com/missing.png"))
        self.assertIsNone(event[4])
        self.assertIn("Image unavailable", event[5])


if __name__ == "__main__":
    unittest.main()
