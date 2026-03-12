import os
import tempfile
import json
import unittest

from gui import YTDLPGui


class TestGui(unittest.TestCase):
    def test_collect_options_playlist_and_sponsorblock(self):
        # work in a temporary directory so config is isolated
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "config.json")

            app = YTDLPGui()
            # override script_dir to point at our temp directory (where config.json
            # will be written)
            app.script_dir = lambda: td

            # set some options
            app.output_template.set("%(title)s.%(ext)s")
            app.format_var.set("mp4")
            app.resolution_var.set("1080")
            app.playlist_yes_var.set(True)
            app.playlist_items_var.set("1:3,5")
            app.playlist_random_var.set(True)
            app.skip_errors_var.set("2")
            app.sb_mark_var.set("all,-preview")
            app.sb_remove_var.set("sponsor")
            app.sb_title_template.set("[SB] %(category_names)l")
            app.sb_api_var.set("https://example.com")

            opts = app.collect_options()
            self.assertIn("--yes-playlist", opts)
            self.assertIn("--playlist-items", opts)
            self.assertIn("--playlist-random", opts)
            self.assertIn("--skip-playlist-after-errors", opts)
            self.assertIn("--sponsorblock-mark", opts)
            self.assertIn("--sponsorblock-remove", opts)
            self.assertIn("--sponsorblock-chapter-title", opts)
            self.assertIn("--sponsorblock-api", opts)

            # config should have been written, but playlist/SponsorBlock keys removed
            self.assertTrue(os.path.exists(cfg))
            with open(cfg, encoding="utf-8") as f:
                data = json.load(f)
            last = data.get("last_options", {})
            # only basic entries remain
            self.assertEqual(last.get("output_template"), "%(title)s.%(ext)s")
            self.assertNotIn("playlist_yes", last)
            self.assertNotIn("sb_mark", last)

            app.destroy()
