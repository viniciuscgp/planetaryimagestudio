import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PIL import Image

import test_image_annotations as annotations

REAL_SINGLE_SHOT = QTimer.singleShot


class SolAnnotationTests(unittest.TestCase):
    setUpClass = classmethod(annotations.AnnotationTests.setUpClass.__func__)
    setUp = annotations.AnnotationTests.setUp
    image = annotations.AnnotationTests.image
    window = annotations.AnnotationTests.window
    draw = annotations.AnnotationTests.draw

    def test_switch_sols_with_large_images_and_real_fit_events(self):
        paths = []
        for sol, size in ((10, (1600, 1200)), (9, (1200, 2400)), (8, (3000, 1000))):
            path = self.image(sol, 'large.png')
            Image.new('RGB', size, 'red').save(path)
            paths.append(path)
        # Existing fixtures disable singleShot; enable actual fit callbacks,
        # while keeping automatic network downloads disabled.
        with patch('app.QTimer.singleShot', side_effect=lambda delay, callback:
                   REAL_SINGLE_SHOT(delay, callback) if delay == 0 else None):
            window = self.window()
            window.show()
            for row in (1, 2, 0, 2):
                window.sol_list.setCurrentRow(row)
                self.wait_summaries(window)
                for _ in range(20):
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertEqual(window.current_path, paths[row])
                self.assertTrue(window.image_view.has_image())
                self.assertFalse(window.thumb_list.item(0).icon().isNull())
                transform = window.image_view.transform()
                for _ in range(10):
                    self.app.processEvents()
                self.assertEqual(window.image_view.transform(), transform)
                self.assertFalse(window.image_view.horizontalScrollBar().isVisible())
                self.assertFalse(window.image_view.verticalScrollBar().isVisible())

    def wait_summaries(self, window):
        deadline = time.monotonic() + 5
        while window._sol_summary_jobs and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertFalse(window._sol_summary_jobs)

    def test_scan_does_not_block_startup_and_ignores_stale_result(self):
        self.image(10, 'first.png')
        started, release = threading.Event(), threading.Event()
        threads = []

        def slow_scan(*args):
            threads.append(threading.get_ident())
            started.set()
            release.wait(5)
            return True

        with patch('sol_annotations.folder_marked', side_effect=slow_scan):
            try:
                window = self.window()
                self.assertTrue(started.wait(2))
                self.assertNotEqual(threads[0], threading.get_ident())
                self.assertFalse(release.is_set())
                old_token = window._sol_summary_token
                window._cancel_sol_annotations()
                window._sol_annotation_result(old_token, str(self.root / 'SOL10'), old_token, True)
                self.assertEqual(window.sol_list.item(0).background().style(), Qt.BrushStyle.NoBrush)
            finally:
                release.set()
            self.wait_summaries(window)

    def test_highlight_after_edit_undo_redo_and_reload(self):
        self.image(10, 'first.png')
        self.image(10, 'second.png')
        window = self.window()
        self.wait_summaries(window)
        window._adjust_contrast(0.2)
        self.wait_summaries(window)
        self.assertEqual(window.sol_list.item(0).background().style(), Qt.BrushStyle.NoBrush)
        window.thumb_list.setCurrentRow(1)
        self.draw(window, 'circle')
        self.assertEqual(window.thumb_list.item(1).background().color().name(), '#f4d878')
        self.assertEqual(window.thumb_list.item(0).background().style(), Qt.BrushStyle.NoBrush)
        self.wait_summaries(window)
        self.assertEqual(window.sol_list.item(0).background().color().name(), '#f4d878')
        window._undo_annotation()
        self.assertEqual(window.thumb_list.item(1).background().style(), Qt.BrushStyle.NoBrush)
        self.wait_summaries(window)
        self.assertEqual(window.sol_list.item(0).background().style(), Qt.BrushStyle.NoBrush)
        window._undo_annotation(redo=True)
        window.thumb_list.setCurrentRow(0)
        window._load_sol_list()
        self.wait_summaries(window)
        self.assertEqual(window.sol_list.item(0).background().color().name(), '#f4d878')
        self.assertEqual(window.thumb_list.item(1).background().color().name(), '#f4d878')
        self.assertEqual(window.thumb_list.item(0).background().style(), Qt.BrushStyle.NoBrush)

    def test_periodic_scan_detects_changes_without_reloading(self):
        self.image(10, 'first.png')
        path = self.image(9, 'other.png')
        window = self.window()
        self.wait_summaries(window)
        item = window.sol_list.item(1)
        self.assertTrue(window._sol_summary_timer.isActive())
        document = annotations.AnnotationDocument(path)
        document.state['drawings'] = [{'kind': 'pencil', 'color': '#ff0000',
                                      'width': 3, 'points': [[1, 1]]}]
        document.save()
        window._sol_summary_timer.timeout.emit()
        self.wait_summaries(window)
        self.assertEqual(item.background().color().name(), '#f4d878')
        document.state['drawings'] = []
        document.save()
        window._sol_summary_timer.timeout.emit()
        self.wait_summaries(window)
        self.assertEqual(item.background().style(), Qt.BrushStyle.NoBrush)
        window.close()
        self.assertFalse(window._sol_summary_timer.isActive())

    def test_selected_marked_thumbnail_renders_yellow_only_behind_text(self):
        self.image(10, 'marked.png')
        self.image(10, 'plain.png')
        window = self.window()
        window.show()
        while window._thumb_queue:
            window._load_thumb_batch()
        self.draw(window, 'circle')
        self.wait_summaries(window)
        window.thumb_list.doItemsLayout()
        self.app.processEvents()
        for selected in (0, 1):
            window.thumb_list.setCurrentRow(selected)
            self.app.processEvents()
            rendered = window.thumb_list.viewport().grab().toImage()
            for row, expected in ((0, True), (1, False)):
                rect = window.thumb_list.visualItemRect(window.thumb_list.item(row))
                color = rendered.pixelColor(rect.left() + 4, rect.center().y()).name()
                self.assertNotEqual(color, '#f4d878')
                yellow = [(x, y) for y in range(rect.top(), rect.bottom() + 1)
                          for x in range(rect.left(), rect.right() + 1)
                          if rendered.pixelColor(x, y).name() == '#f4d878']
                self.assertEqual(bool(yellow), expected)
                if yellow:
                    self.assertGreater(min(y for x, y in yellow), rect.center().y())
