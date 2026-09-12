import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_download_navigation as navigation
from PIL import Image

import config
from app import MainWindow
from sources import get_source
from sources.curiosity import DownloaderWorker


class MigrationTests(unittest.TestCase):
    def test_migrates_old_session_without_changing_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "curiosity_viewer_state.json"
            new = root / config.STATE_FILENAME
            state = {"root": "research", "selected_sol": 1401, "selected_image": "sample.jpg", "download": {"pending_resume": True, "resume_sol": 1500}}
            old.write_text(json.dumps(state), encoding="utf-8")
            backup = old.read_bytes()
            with patch.object(config, "_state_file_candidates", return_value=[new]), patch.object(config, "_legacy_state_candidates", return_value=[old]):
                migrated = config.load_app_state()
                self.assertEqual(migrated, dict(state, source="curiosity"))
                self.assertEqual(json.loads(new.read_text(encoding="utf-8")), migrated)
                self.assertEqual(old.read_bytes(), backup)
                new_state = dict(migrated, source="local", selected_image="moon.png")
                config.save_app_state(new_state)
                self.assertEqual(config.load_app_state(), new_state)

    def test_state_falls_back_when_project_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "blocked" / config.STATE_FILENAME
            primary.parent.write_text("not a directory", encoding="utf-8")
            fallback = root / "home_state.json"
            with patch.object(config, "_state_file_candidates", return_value=[primary, fallback]), patch.object(config, "_legacy_state_candidates", return_value=[]):
                self.assertEqual(config.save_app_state({"source": "local"}), fallback)
                self.assertEqual(config.load_app_state(), {"source": "local"})


class SourceTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_local_source_opens_images_without_sols_or_network(self):
        Image.new("RGB", (80, 60), "gray").save(self.root / "moon.png")
        subfolder = self.root / "crateras"
        subfolder.mkdir()
        Image.new("RGB", (80, 60), "gray").save(subfolder / "crater.png")
        with patch("requests.Session.get", side_effect=AssertionError("Local source must remain offline")):
            window = MainWindow(self.root, {"source": "local", "download": {"pending_resume": True}})
            self.addCleanup(window.close)
            self.assertEqual(window.current_path, self.root / "moon.png")
            self.assertEqual(window.sol_list.count(), 2)
            self.assertFalse(window.act_download_now.isEnabled())
            self.assertTrue(window.download_shell.isHidden())
            self.assertFalse(window._download_pending_resume)
            window._start_downloader()
            self.assertIsNone(window._download_worker)
            self.assertEqual(window.metadata_client.lookup("moon.png", 0)["filename"], "moon.png")
            window.sol_list.setCurrentRow(1)
            from PySide6.QtTest import QTest
            for _ in range(400):
                self.app.processEvents()
                if not window._filter_jobs:
                    break
                QTest.qWait(5)
            self.assertFalse(window._filter_jobs)
            self.assertEqual(window.current_path, subfolder / "crater.png")
            window._adjust_contrast(0.2)
            self.assertTrue(Path(str(window.current_path) + ".annotations.json").exists())

    def test_source_switch_restores_collection_and_selected_image(self):
        self.image(10, "first.png")
        selected = self.image(10, "second.png")
        window = self.window()
        window._next_image()
        moon = self.root / "Moon"
        moon.mkdir()
        Image.new("RGB", (80, 60), "gray").save(moon / "moon.png")
        with patch("app.QFileDialog.getExistingDirectory", return_value=str(moon)):
            window._choose_source("local")
        self.assertEqual(window.source.id, "local")
        self.assertEqual(window.current_path, moon / "moon.png")
        with patch("app.QFileDialog.getExistingDirectory", return_value=str(self.root)):
            window._choose_source("curiosity")
        self.assertEqual(window.current_path, selected)
        self.assertTrue(window.act_download_now.isEnabled())
        state = window._build_state()
        self.assertEqual(state["source"], "curiosity")
        self.assertEqual(state["source_sessions"]["local"]["root"], str(moon))

    def test_curiosity_worker_still_downloads_and_skips_existing_files(self):
        worker = get_source("curiosity").create_downloader(self.root, only_sol=10)
        self.assertIsInstance(worker, DownloaderWorker)
        downloaded, finished, failures = [], [], []
        worker.file_downloaded.connect(lambda sol, path: downloaded.append(Path(path)))
        worker.finished.connect(finished.append)
        worker.failed.connect(failures.append)
        items = [{"sol": 10, "url": "https://example.invalid/sample.jpg"}]
        def download(sol, url, destination, filename):
            destination.write_bytes(b"test image data")
            return True
        with patch.object(worker, "_prepare_catalog"), patch.object(worker, "_latest_nasa_sol", return_value=10), patch.object(worker, "_sol_items", return_value=items), patch.object(worker, "_download_file", side_effect=download) as fetch:
            worker.run()
            self.assertEqual(fetch.call_count, 1)
            worker.run()
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(downloaded, [self.root / "SOL10" / "sample.jpg"])
        self.assertFalse(failures)
        self.assertEqual(len(finished), 2)


if __name__ == "__main__":
    unittest.main()
