"""Non-destructive image annotations, sidecar storage and drawing toolbar."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QColorDialog, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QSpinBox, QToolBar

from annotation_editing import AnnotationEditingMixin, image_transform


HISTORY_LIMIT = 50


def empty_state():
    return {"drawings": [], "contrast": 1.0, "saturation": 1.0, "rotation": 0, "inverted": False, "smoothing": 0, "black_point": 0, "white_point": 255, "gamma": 1.0, "sharpness": 0, "brightness": 100}


def number(value, minimum, maximum):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("Valor numérico inválido nas anotações")
    return value


def validate_state(state):
    number(state.setdefault("brightness", 100), 0, 200)
    number(state.setdefault("black_point", 0), 0, 254)
    number(state.setdefault("white_point", 255), 1, 255)
    number(state.setdefault("gamma", 1.0), 0.1, 5)
    number(state.setdefault("sharpness", 0), 0, 300)
    if state["black_point"] >= state["white_point"]:
        raise ValueError("O ponto preto deve ser menor que o ponto branco.")
    number(state.setdefault("smoothing", 0), 0, 100)
    if not isinstance(state.setdefault("inverted", False), bool):
        raise ValueError("Inversão de cores inválida")
    number(state["contrast"], 0, 3)
    number(state["saturation"], 0, 3)
    if state["rotation"] not in (0, 90, 180, 270):
        raise ValueError("Rotação inválida")
    if not isinstance(state["drawings"], list):
        raise ValueError("Lista de desenhos inválida")
    for drawing in state["drawings"]:
        if drawing["kind"] not in ("pencil", "circle", "text") or not QColor(drawing["color"]).isValid():
            raise ValueError("Desenho inválido")
        number(drawing["width"], 1, 200)
        points = drawing["points"]
        if not isinstance(points, list) or not points or (drawing["kind"] == "circle" and len(points) != 2):
            raise ValueError("Pontos inválidos")
        for x, y in points:
            number(x, -1e7, 1e7)
            number(y, -1e7, 1e7)
        if drawing["kind"] == "text":
            number(drawing["font_size"], 6, 400)
            if not isinstance(drawing["text"], str) or not isinstance(drawing["font_family"], str):
                raise ValueError("Texto inválido")
    return state


class AnnotationDocument:
    def __init__(self, image_path):
        self.path = Path(str(image_path) + ".annotations.json")
        self.state = empty_state()
        self.pen = {"color": "#ff0000", "width": 3, "font_size": 24}
        self.undo = []
        self.redo = []
        self.read_error = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data["version"] != 1:
                    raise ValueError("Versão de anotações não suportada")
                state = validate_state(data["state"])
                undo = [validate_state(s) for s in data.get("undo", [])[-HISTORY_LIMIT:]]
                redo = [validate_state(s) for s in data.get("redo", [])[-HISTORY_LIMIT:]]
                pen = data["pen"]
                if not QColor(pen["color"]).isValid():
                    raise ValueError("Cor inválida")
                number(pen["width"], 1, 200)
                number(pen["font_size"], 6, 400)
                self.state, self.undo, self.redo, self.pen = state, undo, redo, pen
            except (OSError, ValueError, KeyError, TypeError) as exc:
                # Never replace an unreadable sidecar with empty annotations.
                self.read_error = str(exc)

    def commit(self, state):
        if state == self.state:
            return
        self.undo.append(copy.deepcopy(self.state))
        self.undo = self.undo[-HISTORY_LIMIT:]
        self.redo.clear()
        self.state = copy.deepcopy(state)

    def step(self, redo=False):
        source, destination = (self.redo, self.undo) if redo else (self.undo, self.redo)
        if source:
            destination.append(copy.deepcopy(self.state))
            self.state = source.pop()

    def save(self):
        if self.read_error:
            raise OSError(f"Arquivo de anotações não foi sobrescrito: {self.read_error}")
        data = {"version": 1, "state": self.state, "pen": self.pen, "undo": self.undo, "redo": self.redo}
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.path)


def composite_image(base, drawings, rotation):
    """Draw in original image pixels, then rotate image and annotations together."""
    result = base.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for drawing in drawings:
        pen = QPen(QColor(drawing["color"]), drawing["width"])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        points = [QPointF(x, y) for x, y in drawing["points"]]
        if drawing["kind"] == "pencil":
            if len(points) == 1:
                painter.drawPoint(points[0])
            else:
                path = QPainterPath(points[0])
                for point in points[1:]:
                    path.lineTo(point)
                painter.drawPath(path)
        elif drawing["kind"] == "circle":
            radius = math.hypot(points[1].x() - points[0].x(), points[1].y() - points[0].y())
            painter.drawEllipse(points[0], radius, radius)
        else:
            painter.save()
            painter.translate(points[0])
            # Text entered on a rotated image is upright at the moment of entry.
            painter.rotate(-drawing.get("rotation", 0))
            font = QFont(drawing["font_family"])
            font.setPixelSize(int(drawing["font_size"]))
            painter.setFont(font)
            painter.drawText(QPointF(0, painter.fontMetrics().ascent()), drawing["text"])
            painter.restore()
    painter.end()
    if rotation:
        result = result.transformed(QTransform().rotate(rotation))
    return result


class AnnotationWindowMixin(AnnotationEditingMixin):
    def _build_annotation_toolbar(self):
        self._annotation_document = None
        self._annotation_documents = {}
        self._draft_drawing = None
        self._annotation_base = None
        self._annotation_error = None
        self._init_annotation_editing()
        self._clear_region()
        self.addToolBarBreak()
        toolbar = QToolBar("Desenho", self)
        toolbar.setObjectName("drawing_toolbar")
        self.addToolBar(toolbar)
        self._drawing_tools = QActionGroup(self)
        for label, tool in (("Hand (Navegar)", "pan"), ("Lápis", "pencil"), ("Círculo", "circle"), ("Texto", "text")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(tool)
            self._drawing_tools.addAction(action)
            toolbar.addAction(action)
            if tool == "pan":
                action.setChecked(True)
        self._drawing_tools.triggered.connect(self._drawing_tool_changed)
        toolbar.setToolTip("Lápis: arraste para desenhar. Círculo: arraste do centro à borda. Texto: clique para inserir. Navegar: arraste para mover a imagem.")
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Traço (px): "))
        self.stroke_width = QSpinBox()
        self.stroke_width.setRange(1, 200)
        self.stroke_width.setValue(3)
        self.stroke_width.setToolTip("Espessura em pixels da imagem, independente do zoom")
        toolbar.addWidget(self.stroke_width)
        self.stroke_color = QPushButton("Cor")
        self.stroke_color.clicked.connect(self._choose_stroke_color)
        toolbar.addWidget(self.stroke_color)
        toolbar.addWidget(QLabel("Texto (px): "))
        self.text_size = QSpinBox()
        self.text_size.setRange(6, 400)
        self.text_size.setValue(24)
        toolbar.addWidget(self.text_size)
        self.stroke_width.valueChanged.connect(self._save_pen_settings)
        self.text_size.valueChanged.connect(self._save_pen_settings)
        toolbar.addSeparator()
        self.act_undo_annotation = self._make_action("Desfazer", lambda: self._undo_annotation(), "Ctrl+Z")
        self.act_redo_annotation = self._make_action("Refazer", lambda: self._undo_annotation(redo=True), "Ctrl+Shift+Z")
        toolbar.addAction(self.act_undo_annotation)
        toolbar.addAction(self.act_redo_annotation)
        self.act_copy.setText("Copiar imagem final")
        toolbar.addAction(self.act_copy)
        self.annotation_status = QLabel("")
        toolbar.addWidget(self.annotation_status)
        self.image_view.drawing_event.connect(self._drawing_event)
        self._build_selection_toolbar()
        self._sync_annotation_controls()
        self._reset_drawing_tool()
        self._build_annotation_menu(toolbar)

    def _build_selection_toolbar(self):
        self.addToolBarBreak()
        toolbar = QToolBar("Seleção e recorte", self)
        toolbar.setObjectName("selection_toolbar")
        self.addToolBar(toolbar)
        for label, tool in (("Selecionar elemento", "select"), ("Selecionar área", "region")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(tool)
            self._drawing_tools.addAction(action)
            toolbar.addAction(action)
        self.act_edit_annotation_text = self._make_action("Editar texto...", self._edit_selected_text)
        self.act_delete_annotation = self._make_action("Excluir elemento", self._delete_selected_annotation, "Delete")
        toolbar.addAction(self.act_edit_annotation_text)
        toolbar.addAction(self.act_delete_annotation)
        toolbar.addSeparator()
        self.act_copy_region = self._make_action("Copiar área", self._copy_region)
        self.act_export_region = self._make_action("Exportar área PNG...", self._export_region)
        self.act_clear_region = self._make_action("Limpar seleção", self._clear_region)
        for action in (self.act_copy_region, self.act_export_region, self.act_clear_region):
            toolbar.addAction(action)
        self._selection_toolbar = toolbar
        self._sync_edit_actions()
        self._sync_region_actions()

    def _build_annotation_menu(self, toolbar):
        self.drawing_menu = QMenu("Desenho", self)
        self.menuBar().insertMenu(self.menuBar().actions()[-1], self.drawing_menu)
        # Reuse the toolbar actions so checked/enabled states stay synchronized.
        for action in self._drawing_tools.actions():
            self.drawing_menu.addAction(action)
        self.drawing_menu.addSeparator()
        self.drawing_menu.addAction(self._make_action("Cor do traço e texto...", self._choose_stroke_color))
        self.drawing_menu.addAction(self._make_action(
            "Espessura do traço...", lambda: self._choose_annotation_size(self.stroke_width, "Espessura do traço")
        ))
        self.drawing_menu.addAction(self._make_action(
            "Tamanho do texto...", lambda: self._choose_annotation_size(self.text_size, "Tamanho do texto")
        ))
        self.drawing_menu.addSeparator()
        for action in (self.act_undo_annotation, self.act_redo_annotation, self.act_copy):
            self.drawing_menu.addAction(action)
        self.drawing_menu.addSeparator()
        for action in (self.act_edit_annotation_text, self.act_delete_annotation, self.act_copy_region, self.act_export_region, self.act_clear_region):
            self.drawing_menu.addAction(action)
        self.drawing_menu.addSeparator()
        self.drawing_menu.addAction(toolbar.toggleViewAction())
        self.drawing_menu.addAction(self._selection_toolbar.toggleViewAction())

    def _choose_annotation_size(self, spin, title):
        value, accepted = QInputDialog.getInt(self, title, "Pixels:", spin.value(), spin.minimum(), spin.maximum())
        if accepted:
            spin.setValue(value)

    def _reset_drawing_tool(self):
        hand = self._drawing_tools.actions()[0]
        hand.setChecked(True)
        self._drawing_tool_changed(hand, render=False)

    def _drawing_tool_changed(self, action, *, render=True):
        self.act_original.setChecked(False)
        self._clear_annotation_selection()
        self._clear_region()
        self._draft_drawing = None
        self.image_view._drawing = False
        self.image_view._middle_panning = False
        self.image_view._middle_pan_start = None
        self.image_view._panning = False
        self.image_view._pan_start = None
        self.image_view.drawing_tool = action.data()
        self.image_view.viewport().setCursor(
            Qt.CursorShape.OpenHandCursor if action.data() == "pan" else (Qt.CursorShape.ArrowCursor if action.data() == "select" else Qt.CursorShape.CrossCursor)
        )
        if render:
            self._show_annotations()

    def _load_annotations(self, path):
        self._reset_drawing_tool()
        key = str(path.resolve())
        # Retain unsaved edits if a disk error occurs and the user navigates away.
        document = self._annotation_documents.get(key)
        if document is None:
            document = AnnotationDocument(path)
        self._annotation_document = document
        self._annotation_error = document.read_error
        self._apply_annotation_state()
        self.annotation_status.setText("Não salvo — erro" if key in self._annotation_documents else ("Salvo" if document.path.exists() else ""))
        self.annotation_status.setToolTip(str(document.path))
        if document.read_error:
            self.annotation_status.setText("Erro ao ler anotações")
            self.annotation_status.setToolTip(document.read_error)

    def _clear_annotations(self):
        self._reset_drawing_tool()
        self._annotation_document = None
        self._annotation_base = None
        self._draft_drawing = None
        self.image_view._drawing = False
        self.annotation_status.clear()
        self._sync_annotation_controls()

    def _confirm_annotation_close(self):
        self._finish_drawing()
        for key, document in list(self._annotation_documents.items()):
            try:
                document.save()
                del self._annotation_documents[key]
            except OSError:
                pass
        if not self._annotation_documents:
            return True
        answer = QMessageBox.warning(
            self, "Anotações não salvas",
            "Não foi possível salvar as anotações destes arquivos:\n\n"
            + "\n".join(self._annotation_documents)
            + "\n\nFechar e descartar as alterações não salvas?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _apply_annotation_state(self):
        state = self._annotation_document.state
        self.contrast, self.saturation, self.rotation = state["contrast"], state["saturation"], state["rotation"]
        self.inverted = state["inverted"]
        self.smoothing = state["smoothing"]
        for key in ("black_point", "white_point", "gamma", "sharpness", "brightness"):
            setattr(self, key, state[key])
        self._sync_annotation_controls()

    def _sync_annotation_controls(self):
        document = self._annotation_document
        self.act_smooth.setEnabled(document is not None)
        for action in (self.act_levels, self.act_sharpen, self.act_original, self.act_brightness):
            action.setEnabled(document is not None)
        self.act_invert.setChecked(bool(document and document.state["inverted"]))
        self.act_undo_annotation.setEnabled(bool(document and document.undo))
        self.act_redo_annotation.setEnabled(bool(document and document.redo))
        pen = document.pen if document else {"color": "#ff0000", "width": 3, "font_size": 24}
        for spin, key in ((self.stroke_width, "width"), (self.text_size, "font_size")):
            spin.blockSignals(True)
            spin.setValue(int(pen[key]))
            spin.blockSignals(False)
        self.stroke_color.setStyleSheet(f"border: 3px solid {pen['color']}; padding: 3px 8px;")
        self.stroke_color.setToolTip(f"Cor do traço e texto: {pen['color']}")

    def _persist_annotations(self):
        document = self._annotation_document
        if document is None or self.current_path is None:
            return
        try:
            document.save()
            self._annotation_documents.pop(str(self.current_path.resolve()), None)
            self._annotation_error = None
            self.annotation_status.setText("Salvo")
            self.annotation_status.setToolTip(str(document.path))
        except OSError as exc:
            self._annotation_documents[str(self.current_path.resolve())] = document
            self.annotation_status.setText("Não salvo — erro")
            self.annotation_status.setToolTip(str(exc))
            if self._annotation_error != str(exc):
                self._annotation_error = str(exc)
                QMessageBox.warning(self, "Não foi possível salvar anotações", str(exc))
        self._sync_annotation_controls()
        self._refresh_filters_after_edit()

    def _save_pen_settings(self):
        if self._annotation_document is None or self.original_image is None:
            return
        self._annotation_document.pen.update(width=self.stroke_width.value(), font_size=self.text_size.value())
        self._persist_annotations()

    def _choose_stroke_color(self):
        if self._annotation_document is None or self.original_image is None:
            return
        color = QColorDialog.getColor(QColor(self._annotation_document.pen["color"]), self, "Cor do traço e texto")
        if color.isValid():
            self._annotation_document.pen["color"] = color.name()
            self._persist_annotations()

    def _commit_adjustments(self):
        if self._annotation_document is None:
            return
        state = copy.deepcopy(self._annotation_document.state)
        state.update(contrast=self.contrast, saturation=self.saturation, rotation=self.rotation, inverted=self.inverted, smoothing=self.smoothing, black_point=self.black_point, white_point=self.white_point, gamma=self.gamma, sharpness=self.sharpness, brightness=self.brightness)
        self._annotation_document.commit(state)
        self._persist_annotations()

    def _undo_annotation(self, redo=False):
        if self._annotation_document is None or self.original_image is None:
            return
        self._draft_drawing = None
        self._clear_annotation_selection()
        self.image_view._drawing = False
        old_rotation = self.rotation
        self._annotation_document.step(redo=redo)
        self._apply_annotation_state()
        if old_rotation != self.rotation:
            self._clear_region()
        self._render_current(fit=old_rotation != self.rotation)
        self._persist_annotations()

    def _show_annotations(self, fit=False):
        if self.original_image is None or self._annotation_base is None or self._annotation_document is None:
            return
        drawings = self._annotation_document.state["drawings"]
        if self._edit_preview is not None and self._selected_drawing is not None:
            drawings = list(drawings)
            drawings[self._selected_drawing] = self._edit_preview
        if self._draft_drawing:
            drawings = drawings + [self._draft_drawing]
        self.processed_qimage = composite_image(self._annotation_base, drawings, self.rotation)
        self._display_image_version(fit=fit)
        self._update_annotation_handles()

    def _drawing_event(self, phase, scene_point):
        if self.act_original.isChecked():
            return
        if self.original_image is None or self._annotation_document is None:
            return
        tool = self.image_view.drawing_tool
        if phase == "hand_press":
            self.image_view._drawing = self._edit_event("press", scene_point)
            return
        if phase == "double_click" and tool in ("pan", "select"):
            self._edit_original = self._edit_preview = None
            self._selected_drawing = self._hit_annotation(scene_point)
            self._edit_selected_text()
            return
        if tool in ("pan", "select"):
            self._edit_event(phase, scene_point)
            return
        if tool == "region":
            self._region_event(phase, scene_point)
            return
        inverse, _ = image_transform(self.rotation, *self.original_image.size).inverted()
        point = inverse.map(scene_point)
        width, height = self.original_image.size
        if phase == "press" and not QRectF(0, 0, width, height).contains(point):
            return
        xy = [max(0.0, min(width - 1.0, point.x())), max(0.0, min(height - 1.0, point.y()))]
        if phase == "press":
            pen = self._annotation_document.pen
            tool = self.image_view.drawing_tool
            self._draft_drawing = {"kind": tool, "color": pen["color"], "width": pen["width"], "points": [xy]}
            if tool == "circle":
                self._draft_drawing["points"].append(xy)
            if tool == "text":
                text, accepted = QInputDialog.getText(self, "Texto na imagem", "Texto:")
                if not accepted or not text.strip():
                    self._draft_drawing = None
                    return
                self._draft_drawing.update(text=text, font_size=pen["font_size"], font_family=self.font().family(), rotation=self.rotation)
                self._finish_drawing()
                return
        elif self._draft_drawing:
            if self._draft_drawing["kind"] == "circle":
                self._draft_drawing["points"][1] = xy
            elif self._draft_drawing["points"][-1] != xy:
                self._draft_drawing["points"].append(xy)
            if phase == "release":
                self._finish_drawing()
                return
        self._show_annotations()

    def _finish_drawing(self):
        if self._draft_drawing is None:
            return
        state = copy.deepcopy(self._annotation_document.state)
        state["drawings"].append(self._draft_drawing)
        self._annotation_document.commit(state)
        self._draft_drawing = None
        self._show_annotations()
        self._persist_annotations()
