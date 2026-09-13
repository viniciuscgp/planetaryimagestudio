import copy
import unittest
from unittest.mock import patch

import tests.test_download_navigation as navigation
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from planetary_studio.annotations.image_annotations import AnnotationDocument, image_transform


class AnnotationTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def draw(self, window, tool, start=(15, 15), end=(40, 30)):
        # Exercise backward compatibility with existing center/radius circles.
        if tool == "circle":
            window.image_view.drawing_tool = "circle"
        for action in window._drawing_tools.actions():
            if action.data() == tool:
                action.trigger()
        window._drawing_event("press", QPointF(*start))
        window._drawing_event("move", QPointF(*end))
        window._drawing_event("release", QPointF(*end))

    def test_sidecar_roundtrip_undo_redo_and_original_unchanged(self):
        path = self.image(10, "first.png")
        original_bytes = path.read_bytes()
        window = self.window()
        self.draw(window, "pencil")
        window.stroke_width.setValue(7)
        with patch("planetary_studio.annotations.image_annotations.QColorDialog.getColor", return_value=QColor("#00ff00")):
            window._choose_stroke_color()
        self.draw(window, "circle")
        with patch("planetary_studio.annotations.image_annotations.QInputDialog.getText", return_value=("Alvo α", True)):
            self.draw(window, "text", start=(5, 5))
        window._adjust_contrast(0.3)
        window._adjust_saturation(-0.2)
        window._rotate(90)
        expected_image = window.processed_qimage.copy()
        document = AnnotationDocument(path)
        self.assertIsNone(document.read_error)
        self.assertEqual(document.state["drawings"][0]["color"], "#ff0000")
        self.assertEqual(document.state["drawings"][0]["width"], 3)
        self.assertEqual(document.state["drawings"][1]["color"], "#00ff00")
        self.assertEqual(document.state["drawings"][1]["width"], 7)
        self.assertEqual(document.state["drawings"][2]["text"], "Alvo α")
        other = self.window()
        self.assertEqual(other.processed_qimage, expected_image)
        self.assertEqual(other._annotation_document.state, document.state)
        self.assertEqual(other.stroke_width.value(), 7)
        self.assertTrue(other.act_undo_annotation.isEnabled())
        other._undo_annotation()
        self.assertEqual(other.rotation, 0)
        reopened = self.window()
        self.assertTrue(reopened.act_redo_annotation.isEnabled())
        reopened._undo_annotation(redo=True)
        self.assertEqual(reopened.processed_qimage, expected_image)
        reopened._copy_image()
        self.assertEqual(QApplication.clipboard().image(), expected_image)
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_rotation_keeps_drawings_registered_to_original_pixels(self):
        self.image(10, "first.png")
        window = self.window()
        with patch("planetary_studio.annotations.image_annotations.QColorDialog.getColor", return_value=QColor("blue")):
            window._choose_stroke_color()
        self.draw(window, "pencil", start=(15, 15), end=(15, 15))
        unrotated = window.processed_qimage.copy()
        for angle in (90, 180, 270, 0):
            window._rotate(90)
            self.assertEqual(window.processed_qimage, unrotated.transformed(QTransform().rotate(angle)))
            point = image_transform(angle, 80, 60).map(QPointF(30, 20))
            self.draw(window, "pencil", start=(point.x(), point.y()), end=(point.x(), point.y()))
            self.assertEqual(window._annotation_document.state["drawings"][-1]["points"], [[30.0, 20.0]])
            window._undo_annotation()

    def test_mouse_drawing_at_zoom_and_navigation_isolation(self):
        first = self.image(10, "first.png")
        self.image(10, "second.png")
        window = self.window()
        window.show()
        QApplication.processEvents()
        window.image_view.actual_size()
        window.image_view.scale(3, 3)
        window._drawing_tools.actions()[1].trigger()
        view = window.image_view
        start = view.mapFromScene(QPointF(10, 10))
        end = view.mapFromScene(QPointF(30, 20))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        drawing = AnnotationDocument(first).state["drawings"][0]
        self.assertEqual(drawing["points"][0], [10.0, 10.0])
        self.assertEqual(drawing["points"][-1], [30.0, 20.0])
        self.assertEqual(drawing["width"], 3)
        rendered = window.processed_qimage.copy()
        window._next_image()
        self.assertEqual(window._annotation_document.state["drawings"], [])
        self.assertFalse(window.act_undo_annotation.isEnabled())
        window._previous_image()
        self.assertEqual(window.processed_qimage, rendered)
        self.assertTrue(window.act_undo_annotation.isEnabled())

    def test_cancel_text_and_reset_adjustments(self):
        self.image(10, "first.png")
        window = self.window()
        with patch("planetary_studio.annotations.image_annotations.QInputDialog.getText", return_value=("", False)):
            self.draw(window, "text")
        self.assertEqual(window._annotation_document.state["drawings"], [])
        self.draw(window, "circle")
        window._adjust_contrast(0.3)
        window._rotate(90)
        state = copy.deepcopy(window._annotation_document.state)
        window._reset_adjustments()
        self.assertEqual(len(window._annotation_document.state["drawings"]), 1)
        self.assertEqual((window.contrast, window.rotation), (1.0, 0))
        window._undo_annotation()
        self.assertEqual(window._annotation_document.state, state)

    def test_drawing_does_not_pan_zoomed_image(self):
        path = self.image(10, "first.png")
        Image.new("RGB", (1600, 1200), "gray").save(path)
        window = self.window()
        window.show()
        QApplication.processEvents()
        view = window.image_view
        view.actual_size()
        view.scale(1.2, 1.2)
        view.horizontalScrollBar().setValue(301)
        view.verticalScrollBar().setValue(203)
        transform = view.transform()
        scroll = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
        for action in window._drawing_tools.actions()[1:]:
            with self.subTest(tool=action.data()):
                action.trigger()
                start = view.viewport().rect().center()
                with patch("planetary_studio.annotations.image_annotations.QInputDialog.getText", return_value=("Alvo", True)):
                    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
                    for offset in range(1, 6):
                        end = start + QPoint(offset * 3, offset * 2)
                        QTest.mouseMove(view.viewport(), end)
                        self.assertEqual((view.horizontalScrollBar().value(), view.verticalScrollBar().value()), scroll)
                    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
                self.assertEqual(view.transform(), transform)
                self.assertEqual((view.horizontalScrollBar().value(), view.verticalScrollBar().value()), scroll)

        window._drawing_tools.actions()[0].trigger()
        start = QPoint(50, 50)
        end = start + QPoint(15, 10)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertNotEqual((view.horizontalScrollBar().value(), view.verticalScrollBar().value()), scroll)

    def test_bad_sidecar_is_not_overwritten(self):
        path = self.image(10, "first.png")
        document = AnnotationDocument(path)
        document.path.write_text("broken json", encoding="utf-8")
        broken = AnnotationDocument(path)
        self.assertIsNotNone(broken.read_error)
        with self.assertRaises(OSError):
            broken.save()
        self.assertEqual(document.path.read_text(encoding="utf-8"), "broken json")

    def test_atomic_save_failure_preserves_previous_file_and_unsaved_edits(self):
        path = self.image(10, "first.png")
        self.image(10, "second.png")
        window = self.window()
        self.draw(window, "pencil")
        saved_bytes = window._annotation_document.path.read_bytes()
        with patch("planetary_studio.annotations.image_annotations.Path.replace", side_effect=OSError("Disk full")), patch("planetary_studio.annotations.image_annotations.QMessageBox.warning"):
            self.draw(window, "circle")
        self.assertEqual(window._annotation_document.path.read_bytes(), saved_bytes)
        window._next_image()
        window._previous_image()
        self.assertEqual(len(window._annotation_document.state["drawings"]), 2)
        window._persist_annotations()
        self.assertEqual(len(AnnotationDocument(path).state["drawings"]), 2)

    def test_close_can_be_cancelled_when_saving_fails(self):
        self.image(10, "first.png")
        window = self.window()
        with patch("planetary_studio.annotations.image_annotations.AnnotationDocument.save", side_effect=OSError("Disk full")), patch(
            "planetary_studio.annotations.image_annotations.QMessageBox.warning", return_value=QMessageBox.StandardButton.Cancel
        ):
            self.draw(window, "pencil")
            self.assertFalse(window._confirm_annotation_close())
        self.assertTrue(window._confirm_annotation_close())
        self.assertFalse(window._annotation_documents)

    def test_download_does_not_change_annotation_or_history(self):
        self.image(10, "first.png")
        self.image(10, "second.png")
        window = self.window()
        window._next_image()
        self.draw(window, "circle")
        window._rotate(90)
        window.image_view.scale(2, 2)
        rendered = window.processed_qimage.copy()
        transform = window.image_view.transform()
        document = window._annotation_document
        saved = document.path.read_bytes()
        path = self.image(11, "download.png")
        window._on_download_sol_created(11, str(path.parent))
        window._on_download_file_downloaded(11, str(path))
        self.assertIs(window._annotation_document, document)
        self.assertEqual(window.processed_qimage, rendered)
        self.assertEqual(window.image_view.transform(), transform)
        self.assertEqual(document.path.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
