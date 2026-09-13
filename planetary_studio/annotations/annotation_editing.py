"""Selection geometry and non-destructive manipulation of annotation objects."""

import copy
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainterPath, QPainterPathStroker, QTransform
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox


def image_transform(rotation, width, height):
    return QImage.trueMatrix(QTransform().rotate(rotation), width, height)


def drawing_shape(drawing):
    points = [QPointF(*xy) for xy in drawing["points"]]
    path = QPainterPath()
    if drawing["kind"] == "polygon":
        offset = 0
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for length in drawing['rings']:
            path.moveTo(points[offset])
            for point in points[offset+1:offset+length]:
                path.lineTo(point)
            path.closeSubpath()
            offset += length
    elif drawing["kind"] == "circle":
        radius = math.hypot(points[1].x() - points[0].x(), points[1].y() - points[0].y())
        path.addEllipse(points[0], max(radius, 0.5), max(radius, 0.5))
    elif drawing["kind"] in ("ellipse", "rectangle"):
        rect = QRectF(points[0], points[1]).normalized()
        if drawing["kind"] == "ellipse":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
    elif drawing["kind"] == "text":
        font = QFont(drawing["font_family"])
        font.setPixelSize(int(drawing["font_size"]))
        metrics = QFontMetricsF(font)
        rect = metrics.boundingRect(drawing["text"])
        rect.translate(0, metrics.ascent())
        path.addRect(rect)
        transform = QTransform().translate(points[0].x(), points[0].y()).rotate(-drawing.get("rotation", 0))
        path = transform.map(path)
    else:
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        if len(points) == 1:
            path.addEllipse(points[0], 0.5, 0.5)
    return path


def corners(rect):
    return [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]


class AnnotationEditingMixin:
    def _init_annotation_editing(self):
        self._selected_drawing = None
        self._edit_original = None
        self._edit_preview = None
        self._edit_start = None
        self._edit_handle = None
        self.image_view.selection_rect = None

    def _clear_annotation_selection(self):
        self._init_annotation_editing()
        self.image_view.viewport().update()
        self._sync_edit_actions()

    def _sync_edit_actions(self):
        selected = self._selected_annotation()
        self._sync_pen_controls()
        if hasattr(self, "act_delete_annotation"):
            self.act_delete_annotation.setEnabled(selected is not None)
            self.act_edit_annotation_text.setEnabled(bool(selected and selected["kind"] == "text"))

    def _selected_annotation(self):
        if self._annotation_document is None or self._selected_drawing is None:
            return None
        drawings = self._annotation_document.state["drawings"]
        if not 0 <= self._selected_drawing < len(drawings):
            return None
        return self._edit_preview or drawings[self._selected_drawing]

    def _annotation_scene_transform(self):
        return image_transform(self.rotation, *self.original_image.size)

    def _selection_bounds(self, drawing):
        rect = self._annotation_scene_transform().map(drawing_shape(drawing)).boundingRect()
        # A single pencil dot or horizontal line still needs usable handles.
        if rect.width() < 1:
            rect.adjust(-0.5, 0, 0.5, 0)
        if rect.height() < 1:
            rect.adjust(0, -0.5, 0, 0.5)
        return rect

    def _update_annotation_handles(self):
        selected = self._selected_annotation()
        self.image_view.selection_rect = self._selection_bounds(selected) if selected else None
        self.image_view.viewport().update()
        self._sync_edit_actions()

    def _hit_annotation(self, point):
        tolerance = 6 / max(0.02, abs(self.image_view.transform().m11()))
        transform = self._annotation_scene_transform()
        drawings = self._annotation_document.state["drawings"]
        for index in range(len(drawings) - 1, -1, -1):
            drawing = drawings[index]
            shape = transform.map(drawing_shape(drawing))
            stroke = QPainterPathStroker()
            stroke.setWidth(drawing["width"] + tolerance * 2)
            if (drawing["kind"] != "pencil" and shape.contains(point)) or stroke.createStroke(shape).contains(point):
                return index
        return None

    def _edit_event(self, phase, point):
        if phase == "press":
            self._edit_handle = None
            selected = self._selected_annotation()
            if selected:
                tolerance = 8 / max(0.02, abs(self.image_view.transform().m11()))
                for index, handle in enumerate(corners(self._selection_bounds(selected))):
                    if math.hypot(point.x() - handle.x(), point.y() - handle.y()) <= tolerance:
                        self._edit_handle = index
                        break
            if self._edit_handle is None:
                self._selected_drawing = self._hit_annotation(point)
            self._edit_original = copy.deepcopy(self._selected_annotation())
            self._edit_preview = None
            self._edit_start = point
            self._update_annotation_handles()
            return self._edit_original is not None
        if self._edit_original is None:
            return False
        transform = self._annotation_scene_transform()
        inverse, _ = transform.inverted()
        drawing = copy.deepcopy(self._edit_original)
        mapped = [transform.map(QPointF(*xy)) for xy in drawing["points"]]
        if self._edit_handle is None:
            delta = point - self._edit_start
            mapped = [p + delta for p in mapped]
        else:
            rect = self._selection_bounds(self._edit_original)
            anchor = corners(rect)[(self._edit_handle + 2) % 4]
            handle = corners(rect)[self._edit_handle]
            moved = handle + point - self._edit_start
            sx = max(0.02, min(100, (moved.x() - anchor.x()) / (handle.x() - anchor.x())))
            sy = max(0.02, min(100, (moved.y() - anchor.y()) / (handle.y() - anchor.y())))
            if drawing["kind"] in ("circle", "text"):
                sx = sy = max(sx, sy)
            if drawing["kind"] == "text":
                drawing["font_size"] = max(6, min(400, round(drawing["font_size"] * sx)))
                sx = sy = drawing["font_size"] / self._edit_original["font_size"]
            mapped = [QPointF(anchor.x() + (p.x() - anchor.x()) * sx, anchor.y() + (p.y() - anchor.y()) * sy) for p in mapped]
        original_points = [inverse.map(p) for p in mapped]
        drawing["points"] = [[p.x(), p.y()] for p in original_points]
        self._edit_preview = drawing
        if phase == "release":
            state = copy.deepcopy(self._annotation_document.state)
            state["drawings"][self._selected_drawing] = drawing
            self._annotation_document.commit(state)
            self._edit_original = self._edit_preview = None
            self._persist_annotations()
        self._show_annotations()
        return True

    def _delete_selected_annotation(self):
        if self._selected_annotation() is None:
            return
        state = copy.deepcopy(self._annotation_document.state)
        del state["drawings"][self._selected_drawing]
        self._annotation_document.commit(state)
        self._clear_annotation_selection()
        self._show_annotations()
        self._persist_annotations()

    def _edit_selected_text(self):
        selected = self._selected_annotation()
        if selected is None or selected["kind"] != "text":
            return
        text, accepted = QInputDialog.getText(self, "Editar texto", "Texto:", text=selected["text"])
        if not accepted or not text.strip():
            return
        state = copy.deepcopy(self._annotation_document.state)
        state["drawings"][self._selected_drawing]["text"] = text
        self._annotation_document.commit(state)
        self._show_annotations()
        self._persist_annotations()

    def _clear_region(self):
        self._region_start = None
        self.image_view.region_rect = None
        self._sync_region_actions()
        self.image_view.viewport().update()

    def _sync_region_actions(self):
        rect = self.image_view.region_rect
        enabled = bool(rect and rect.width() >= 1 and rect.height() >= 1)
        if hasattr(self, "act_copy_region"):
            for action in (self.act_copy_region, self.act_export_region, self.act_clear_region):
                action.setEnabled(enabled)

    def _region_event(self, phase, point):
        if self.processed_qimage is None:
            return
        point = QPointF(max(0, min(self.processed_qimage.width(), point.x())), max(0, min(self.processed_qimage.height(), point.y())))
        if phase == "press":
            self._region_start = point
        if self._region_start is not None:
            self.image_view.region_rect = QRectF(self._region_start, point).normalized()
            self._sync_region_actions()
            self.image_view.viewport().update()
        if phase == "release":
            self._region_start = None

    def _selected_region_image(self):
        rect = self.image_view.region_rect
        if self.processed_qimage is None or not rect or rect.width() < 1 or rect.height() < 1:
            return None
        pixels = rect.toAlignedRect().intersected(self.processed_qimage.rect())
        return self.processed_qimage.copy(pixels) if not pixels.isEmpty() else None

    def _copy_region(self):
        image = self._selected_region_image()
        if image is not None:
            QApplication.clipboard().setImage(image)
            self.statusBar().showMessage(f"Área copiada: {image.width()} × {image.height()} pixels", 3000)

    def _export_region(self):
        image = self._selected_region_image()
        if image is None or self.current_path is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar área selecionada", str(self.current_path.with_name(self.current_path.stem + "_recorte.png")), "Imagem PNG (*.png)"
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".png":
            path = Path(str(path) + ".png")
        if path.resolve() == self.current_path.resolve():
            QMessageBox.warning(self, "Preservar original", "Escolha outro nome para exportar sem substituir a imagem original.")
            return
        if not image.save(str(path), "PNG"):
            QMessageBox.warning(self, "Erro ao exportar", f"Não foi possível salvar:\n{path}")
            return
        self.statusBar().showMessage(f"Área exportada: {path.name}", 4000)
