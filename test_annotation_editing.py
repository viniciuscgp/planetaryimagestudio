import copy
import json
import math
import unittest
from unittest.mock import patch

import test_image_annotations as annotations
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from image_annotations import AnnotationDocument
from annotation_editing import drawing_shape


class EditingTests(unittest.TestCase):
    setUpClass = classmethod(annotations.AnnotationTests.setUpClass.__func__)
    setUp = annotations.AnnotationTests.setUp
    image = annotations.AnnotationTests.image
    window = annotations.AnnotationTests.window
    draw = annotations.AnnotationTests.draw

    def prepare(self):
        path = self.image(10, "first.png")
        Image.new("RGB", (600, 400), "gray").save(path)
        return path, self.window()

    def tool(self, window, tool):
        next(action for action in window._drawing_tools.actions() if action.data() == tool).trigger()

    def drag(self, window, start, end):
        window._drawing_event("press", start)
        window._drawing_event("move", end)
        window._drawing_event("release", end)

    def test_oval_and_rectangle_use_opposite_corners_in_both_directions(self):
        path, window = self.prepare()
        for kind in ('ellipse', 'rectangle'):
            for start, end in (((100, 100), (240, 160)), ((240, 160), (100, 100))):
                self.draw(window, kind, start, end)
                drawing = window._annotation_document.state['drawings'][-1]
                self.assertEqual(drawing['kind'], kind)
                bounds = drawing_shape(drawing).boundingRect()
                self.assertEqual((bounds.x(), bounds.y(), bounds.width(), bounds.height()), (100, 100, 140, 60))
                self.assertEqual(AnnotationDocument(path).state['drawings'][-1], drawing)
                window._undo_annotation()
                window._undo_annotation(redo=True)
                self.assertEqual(window._annotation_document.state['drawings'][-1], drawing)

    def test_new_shapes_resize_width_and_height_independently(self):
        path, window = self.prepare()
        for kind in ('ellipse', 'rectangle'):
            self.draw(window, kind, (100, 100), (200, 150))
            self.tool(window, 'select')
            self.drag(window, QPointF(150, 125), QPointF(150, 125))
            self.drag(window, QPointF(200, 150), QPointF(250, 170))
            drawing = window._annotation_document.state['drawings'][-1]
            bounds = drawing_shape(drawing).boundingRect()
            self.assertAlmostEqual(bounds.width(), 150)
            self.assertAlmostEqual(bounds.height(), 70)

    def test_circle_move_resize_persistence_and_undo(self):
        path, window = self.prepare()
        self.draw(window, "circle", (100, 100), (140, 100))
        self.tool(window, "select")
        self.drag(window, QPointF(100, 100), QPointF(130, 120))
        circle = window._annotation_document.state["drawings"][0]
        self.assertEqual(circle["points"], [[130.0, 120.0], [170.0, 120.0]])
        bounds = window.image_view.selection_rect
        self.drag(window, bounds.bottomRight(), bounds.bottomRight() + QPointF(40, 40))
        resized = copy.deepcopy(window._annotation_document.state)
        circle = resized["drawings"][0]
        radius = math.dist(*circle["points"])
        self.assertAlmostEqual(radius, 60)
        self.assertEqual(AnnotationDocument(path).state, resized)
        window._undo_annotation()
        self.assertAlmostEqual(math.dist(*window._annotation_document.state["drawings"][0]["points"]), 40)
        window._undo_annotation(redo=True)
        self.assertEqual(window._annotation_document.state, resized)

    def test_hand_selects_and_moves_without_panning_at_zoom(self):
        _, window = self.prepare()
        self.draw(window, "circle", (200, 150), (240, 150))
        window.show()
        QApplication.processEvents()
        self.tool(window, "pan")
        view = window.image_view
        view.actual_size()
        view.scale(3, 3)
        view.centerOn(200, 150)
        scroll = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
        start = view.mapFromScene(QPointF(200, 150))
        end = start + QPoint(30, 15)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual((view.horizontalScrollBar().value(), view.verticalScrollBar().value()), scroll)
        self.assertEqual(window._annotation_document.state["drawings"][0]["points"][0], [210.0, 155.0])
        self.assertIsNotNone(view.selection_rect)

    def test_rotated_text_move_resize_edit_and_delete(self):
        path, window = self.prepare()
        window._rotate(90)
        with patch("image_annotations.QInputDialog.getText", return_value=("Alvo", True)):
            self.draw(window, "text", (100, 100))
        self.tool(window, "select")
        drawing = window._annotation_document.state["drawings"][0]
        bounds = window._selection_bounds(drawing)
        before = copy.deepcopy(drawing)
        self.drag(window, bounds.center(), bounds.center() + QPointF(20, 10))
        drawing = window._annotation_document.state["drawings"][0]
        self.assertAlmostEqual(drawing["points"][0][0], before["points"][0][0] + 10)
        self.assertAlmostEqual(drawing["points"][0][1], before["points"][0][1] - 20)
        bounds = window.image_view.selection_rect
        self.drag(window, bounds.bottomRight(), bounds.bottomRight() + QPointF(bounds.width(), bounds.height()))
        self.assertEqual(window._annotation_document.state["drawings"][0]["font_size"], 48)
        with patch("annotation_editing.QInputDialog.getText", return_value=("Novo alvo", True)):
            window.act_edit_annotation_text.trigger()
        self.assertEqual(AnnotationDocument(path).state["drawings"][0]["text"], "Novo alvo")
        window.act_delete_annotation.trigger()
        self.assertEqual(AnnotationDocument(path).state["drawings"], [])
        window._undo_annotation()
        self.assertEqual(window._annotation_document.state["drawings"][0]["text"], "Novo alvo")

    def test_pencil_resize_and_image_change_clears_handles(self):
        _, window = self.prepare()
        second = self.image(10, "second.png")
        self.draw(window, "pencil", (80, 80), (120, 100))
        self.tool(window, "select")
        self.drag(window, QPointF(100, 90), QPointF(100, 90))
        bounds = window.image_view.selection_rect
        self.drag(window, bounds.bottomRight(), bounds.bottomRight() + QPointF(40, 20))
        self.assertEqual(window._annotation_document.state["drawings"][0]["points"], [[80.0, 80.0], [160.0, 120.0]])
        window._load_image(second)
        self.assertEqual(window.image_view.drawing_tool, "pan")
        self.assertIsNone(window.image_view.selection_rect)
        self.assertFalse(window.act_delete_annotation.isEnabled())

    def test_region_copy_export_contains_rendered_pixels_only(self):
        path, window = self.prepare()
        original = path.read_bytes()
        self.draw(window, "circle", (100, 100), (140, 100))
        window._toggle_invert()
        window._rotate(90)
        self.tool(window, "region")
        self.drag(window, QPointF(220, 60), QPointF(360, 180))
        expected = window.processed_qimage.copy(220, 60, 140, 120)
        window.act_copy_region.trigger()
        self.assertEqual(QApplication.clipboard().image(), expected)
        exported = self.root / "region.png"
        with patch("annotation_editing.QFileDialog.getSaveFileName", return_value=(str(exported), "PNG")):
            window.act_export_region.trigger()
        loaded = QImage(str(exported)).convertToFormat(QImage.Format.Format_ARGB32)
        self.assertEqual(loaded, expected.convertToFormat(QImage.Format.Format_ARGB32))
        self.assertEqual(path.read_bytes(), original)
        window._clear_region()
        self.assertFalse(window.act_export_region.isEnabled())
        self.assertIsNone(window._selected_region_image())

    def test_inversion_preserves_alpha_and_restores_with_undo(self):
        path = self.image(10, "first.png")
        Image.new("RGBA", (80, 60), (20, 50, 100, 120)).save(path)
        window = self.window()
        window.act_invert.trigger()
        self.assertEqual(window.processed_qimage.pixelColor(20, 20).getRgb(), (235, 205, 155, 120))
        self.assertTrue(AnnotationDocument(path).state["inverted"])
        window._undo_annotation()
        self.assertEqual(window.processed_qimage.pixelColor(20, 20).getRgb(), (20, 50, 100, 120))
        window._undo_annotation(redo=True)
        reopened = self.window()
        self.assertTrue(reopened.act_invert.isChecked())
        self.assertEqual(reopened.processed_qimage, window.processed_qimage)

    def test_old_sidecars_load_with_default_new_adjustments(self):
        path, window = self.prepare()
        self.draw(window, "circle")
        sidecar = window._annotation_document.path
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        for state in [data["state"]] + data["undo"] + data["redo"]:
            state.pop("inverted", None)
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        loaded = AnnotationDocument(path)
        self.assertIsNone(loaded.read_error)
        self.assertFalse(loaded.state["inverted"])
        self.assertEqual(len(loaded.state["drawings"]), 1)


if __name__ == "__main__":
    unittest.main()
