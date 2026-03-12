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
            # will be written);
            app.script_dir = lambda: td
            # wipe any values that may have been populated from the workspace
            app.config = {"yt_dlp_path": "yt-dlp.exe", "last_options": {}}
            app.apply_last_options()
            app.sb_enabled_var.set(False)
            app.toggle_sb_frame()
            app.sb_mark_var.set("")
            app.sb_remove_var.set("")
            app.sb_title_template.set("")
            app.sb_api_var.set("")

            # set some options
            app.output_template.set("%(title)s.%(ext)s")
            app.format_var.set("mp4")
            app.resolution_var.set("1080")
            # choose a non-default preset so we verify it is recorded
            app.preset_var.set("Video 1080p")
            app.apply_preset()
            app.playlist_yes_var.set(True)
            app.playlist_items_var.set("1:3,5")
            app.playlist_random_var.set(True)
            app.skip_errors_var.set("2")

            # initially SponsorBlock is disabled - no flags should be generated
            opts = app.collect_options()
            self.assertNotIn("--sponsorblock-mark", opts)
            self.assertNotIn("--sponsorblock-remove", opts)

            # the options frame should not be managed initially
            self.assertEqual(app.sb_frame.winfo_manager(), "")

            # now enable and configure it
            # configure SB using a preset
            app.sb_preset_var.set("Mark+Remove Sponsors")
            app.apply_sb_preset()
            # clicking info should show a dialog (just exercise method)
            app.show_sb_info()
            # frame should now be packed automatically by apply_sb_preset
            self.assertEqual(app.sb_frame.winfo_manager(), "pack")
            # verify the preset filled the fields
            self.assertEqual(app.sb_mark_var.get(), "sponsor")
            self.assertEqual(app.sb_remove_var.get(), "sponsor")
            # make sure the SB section is above extras
            slaves = app.pack_slaves()
            self.assertLess(slaves.index(app.sb_frame), slaves.index(app.extra_frame))

            opts = app.collect_options()
            self.assertIn("--yes-playlist", opts)
            self.assertIn("--playlist-items", opts)
            self.assertIn("--playlist-random", opts)
            self.assertIn("--skip-playlist-after-errors", opts)
            self.assertIn("--sponsorblock-mark", opts)
            self.assertIn("--sponsorblock-remove", opts)
            # chapter-title/api are not provided by this preset

            # config should have been written, but playlist/SponsorBlock keys removed
            self.assertTrue(os.path.exists(cfg))
            with open(cfg, encoding="utf-8") as f:
                data = json.load(f)
            last = data.get("last_options", {})
            # only basic entries remain; the output template isn't saved by design
            self.assertNotIn("output_template", last)
            self.assertNotIn("playlist_yes", last)
            self.assertNotIn("sb_mark", last)
            # preset choice should be preserved
            self.assertEqual(last.get("preset"), "Video 1080p")

            app.destroy()
            # new GUI instance should restore the chosen preset
            app2 = YTDLPGui()
            # override directory, then force a reload so we read the temp config
            app2.script_dir = lambda: td
            from gui import DEFAULT_CONFIG
            app2.config = DEFAULT_CONFIG.copy()
            app2.load_config()
            app2.apply_last_options()
            self.assertEqual(app2.preset_var.get(), "Video 1080p")
            self.assertEqual(app2.format_var.get(), "mp4")
            self.assertEqual(app2.resolution_var.get(), "1080")
            app2.destroy()
