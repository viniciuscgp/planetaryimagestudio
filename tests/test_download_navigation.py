import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from planetary_studio.app import MainWindow


class DownloadNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Keep tests offline and avoid changing the user's saved session.
        for target in (
            "planetary_studio.app.QTimer.singleShot",
            "planetary_studio.app.MainWindow._save_state",
        ):
            mock = patch(target)
            mock.start()
            self.addCleanup(mock.stop)

    def image(self, sol, filename):
        folder = self.root / f"SOL{sol}"
        folder.mkdir(exist_ok=True)
        path = folder / filename
        Image.new("RGB", (80, 60), "red").save(path)
        return path

    def window(self):
        window = MainWindow(self.root, initial_state={"download": {}})
        def close_window():
            # Complete asynchronous shutdown before restoring mocks and deleting
            # the temporary image directory. No callbacks may leak to another test.
            import time
            window.close()
            deadline = time.monotonic() + 3
            while window._background_tasks_running() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.app.processEvents()
            window.close()
        self.addCleanup(close_window)
        return window

    def test_new_sols_and_downloads_preserve_view(self):
        self.image(10, "first.png")
        selected_path = self.image(10, "second.png")
        window = self.window()
        window.thumb_list.setCurrentRow(1)
        window._adjust_contrast(0.3)
        window._adjust_saturation(0.2)
        window._rotate(90)
        window.image_view.scale(2, 2)
        transform = window.image_view.transform()
        original = window.original_image
        selected_thumb = window.thumb_list.currentItem()
        selected_sol = window.sol_list.currentItem()
        queued_thumbs = list(window._thumb_queue)

        with patch.object(window, "_load_image", wraps=window._load_image) as load:
            for sol in (12, 9, 11, 12):
                path = self.image(sol, "download.png")
                window._on_download_sol_started(sol, 1, 4)
                window._on_download_sol_created(sol, str(path.parent))
                window._on_download_file_downloaded(sol, str(path))
                window._on_download_sol_finished(sol, 1, 1, 0)
            load.assert_not_called()
            self.assertEqual(window._thumb_queue, queued_thumbs)
            self.assertTrue(window._thumb_timer.isActive())
            new_path = self.image(10, "third.png")
            window._on_download_file_downloaded(10, str(new_path))
            window._on_downloader_finished("Atualização concluída")
            load.assert_not_called()

        self.assertEqual(window.current_path, selected_path)
        self.assertIs(window.original_image, original)
        self.assertIs(window.thumb_list.currentItem(), selected_thumb)
        self.assertIs(window.sol_list.currentItem(), selected_sol)
        self.assertEqual(window.image_view.transform(), transform)
        self.assertEqual((window.contrast, window.saturation, window.rotation), (1.3, 1.2, 90))
        self.assertEqual(window.thumb_list.count(), 3)
        self.assertEqual([
            window.sol_list.item(i).data(Qt.ItemDataRole.UserRole)[0]
            for i in range(window.sol_list.count())
        ], [12, 11, 10, 9])
        window._next_image()
        self.assertEqual(window.current_path, new_path)

    def test_first_download_in_empty_library_opens_image(self):
        window = self.window()
        folder = self.root / "SOL10"
        folder.mkdir()
        window._on_download_sol_created(10, str(folder))
        path = self.image(10, "first.png")
        window._on_download_file_downloaded(10, str(path))
        self.assertEqual(window.current_sol, 10)
        self.assertEqual(window.current_path, path)
        self.assertEqual(window.thumb_list.currentRow(), 0)


if __name__ == "__main__":
    unittest.main()
