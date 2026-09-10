#!/usr/bin/env python3
"""Shared desktop interface for Planetary Image Studio. Run with main.py."""

from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFile, ImageOps

from image_annotations import AnnotationWindowMixin, composite_image
from image_filters import ImageFiltersMixin
from sol_annotations import SolAnnotationsMixin, AnnotationThumbnailDelegate
from image_smoothing import SmoothingDialog, smooth_image
from image_adjustments import AdjustmentDialog, apply_adjustments
from inline_adjustments import InlineAdjustmentsMixin
from toolbar_appearance import ToolbarAppearanceMixin

from PySide6.QtCore import QByteArray, QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon, QImage, QImageReader, QKeySequence, QPalette, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QComboBox,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollBar,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QSizePolicy,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME, APP_VERSION, APP_AUTHOR, PROJECT_ROOT, load_app_state, save_app_state
from catalog import list_images
from sources import get_source, SOURCES
from sources.base import ImageSource, MetadataProvider
from missions import MissionRegistry
from mission_settings import MissionSettingsDialog

ImageFile.LOAD_TRUNCATED_IMAGES = True


def pil_to_qimage(image: Image.Image) -> QImage:
    """Convert a Pillow RGB/RGBA image to an independent QImage."""
    if image.mode == "RGBA":
        data = image.tobytes("raw", "RGBA")
        qimage = QImage(
            data, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888
        )
    else:
        if image.mode != "RGB":
            image = image.convert("RGB")
        data = image.tobytes("raw", "RGB")
        qimage = QImage(
            data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
        )
    # copy() detaches Qt from the temporary Python bytes buffer.
    return qimage.copy()


def find_gimp() -> str | None:
    """Locate GIMP, including common Windows installs and registry entries."""
    candidates = ["gimp-3.0", "gimp", "gimp-2.10"]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found

    if sys.platform.startswith("win"):
        found_paths: list[Path] = []

        # Standard installers (GIMP 2.x and 3.x), system-wide and per-user.
        roots: list[Path] = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.environ.get(env_name)
            if value:
                roots.append(Path(value))

        patterns = (
            "GIMP*/bin/gimp*.exe",
            "Programs/GIMP*/bin/gimp*.exe",
            "Programs/GIMP*/gimp*.exe",
        )
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                try:
                    found_paths.extend(root.glob(pattern))
                except OSError:
                    pass

        # The Windows installer records the install location. This also covers
        # installations outside C:\Program Files.
        try:
            import winreg  # type: ignore

            registry_roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
            uninstall_keys = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            )
            for hive in registry_roots:
                for key_path in uninstall_keys:
                    try:
                        with winreg.OpenKey(hive, key_path) as parent:
                            count = winreg.QueryInfoKey(parent)[0]
                            for index in range(count):
                                try:
                                    sub_name = winreg.EnumKey(parent, index)
                                    with winreg.OpenKey(parent, sub_name) as sub:
                                        try:
                                            display_name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                                        except OSError:
                                            continue
                                        if "gimp" not in display_name.lower():
                                            continue

                                        try:
                                            install_location = str(winreg.QueryValueEx(sub, "InstallLocation")[0])
                                        except OSError:
                                            install_location = ""
                                        if install_location:
                                            base = Path(install_location.strip('"'))
                                            found_paths.extend(base.glob("bin/gimp*.exe"))
                                            found_paths.extend(base.glob("gimp*.exe"))

                                        try:
                                            icon = str(winreg.QueryValueEx(sub, "DisplayIcon")[0])
                                        except OSError:
                                            icon = ""
                                        if icon:
                                            icon_path = icon.split(",", 1)[0].strip().strip('"')
                                            if icon_path.lower().endswith(".exe"):
                                                found_paths.append(Path(icon_path))
                                except OSError:
                                    continue
                    except OSError:
                        continue
        except Exception:
            pass

        # Prefer the graphical executable over gimp-console.exe, then newer names.
        usable = [
            path for path in found_paths
            if path.is_file() and "console" not in path.name.lower()
        ]
        if usable:
            usable.sort(
                key=lambda path: (
                    "3.0" in path.name.lower() or "gimp 3" in str(path).lower(),
                    path.stat().st_mtime if path.exists() else 0,
                ),
                reverse=True,
            )
            return str(usable[0])

    if sys.platform == "darwin":
        mac = Path("/Applications/GIMP.app/Contents/MacOS/gimp")
        if mac.exists():
            return str(mac)

    return None


class ThumbnailList(QListWidget):
    """Horizontal thumbnail strip that can be scrolled by click-dragging."""

    height_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_start = None
        self._scroll_start = 0
        self._dragging = False
        self._pressed_item: QListWidgetItem | None = None
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def doItemsLayout(self):
        scroll = self.horizontalScrollBar().value()
        self._passive_layout = True
        try:
            super().doItemsLayout()
            self.horizontalScrollBar().setValue(scroll)
        finally:
            self._passive_layout = False

    def resizeEvent(self, event):
        scroll = self.horizontalScrollBar().value()
        self._passive_layout = True
        try:
            super().resizeEvent(event)
            self.horizontalScrollBar().setValue(scroll)
        finally:
            self._passive_layout = False
        if event.oldSize().height() != event.size().height():
            self.height_changed.emit()

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        if not getattr(self, "_passive_layout", False):
            super().scrollTo(index, hint)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._scroll_start = self.horizontalScrollBar().value()
            self._dragging = False
            self._pressed_item = self.itemAt(self._drag_start)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.position().toPoint()
            delta = current - self._drag_start
            if not self._dragging and abs(delta.x()) >= QApplication.startDragDistance():
                self._dragging = True
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._dragging:
                self.horizontalScrollBar().setValue(self._scroll_start - delta.x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            if not self._dragging and self._pressed_item is not None:
                self.setCurrentItem(self._pressed_item)
            self._drag_start = None
            self._pressed_item = None
            self._dragging = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ImageView(QGraphicsView):
    """Image canvas with mouse-wheel zoom and left-button pan."""

    context_requested = Signal(object)
    drawing_event = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        # Interpolate only while painting the scaled view; keep source pixels,
        # image geometry, annotations, and export data unchanged.
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_request)

        self._middle_panning = False
        self._middle_pan_start = None
        self._panning = False
        self._pan_start = None
        self._has_image = False
        self._fit_mode = True
        self._fitting_image = False
        self.drawing_tool = "pan"
        self._drawing = False
        self.selection_rect = None
        self.region_rect = None

    def _emit_context_request(self, pos) -> None:
        self.context_requested.emit(self.viewport().mapToGlobal(pos))

    def has_image(self) -> bool:
        return self._has_image

    def set_pixmap(self, pixmap: QPixmap, fit: bool = True) -> None:
        old_transform = self.transform()
        old_horizontal = self.horizontalScrollBar().value()
        old_vertical = self.verticalScrollBar().value()

        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._has_image = not pixmap.isNull()
        self._fit_mode = fit

        if not self._has_image:
            self.resetTransform()
            return

        if fit:
            QTimer.singleShot(0, lambda: self.fit_image() if self._fit_mode else None)
        else:
            # Restore exact scroll positions. Repeated centerOn(mapToScene(...))
            # rounds the viewport center and shifts the image on each drawing update.
            self.setTransform(old_transform)
            self.horizontalScrollBar().setValue(old_horizontal)
            self.verticalScrollBar().setValue(old_vertical)

    def fit_image(self) -> None:
        if not self._has_image or self._fitting_image:
            return
        self._fitting_image = True
        try:
            bounds = self._pixmap_item.boundingRect()
            available = self.maximumViewportSize()
            if bounds.isEmpty() or available.width() <= 4 or available.height() <= 4:
                return
            # Apply the final scale directly. Resetting to 1:1 can toggle the
            # scrollbars and recursively trigger resizeEvent while fitting.
            scale = min((available.width() - 4) / bounds.width(),
                        (available.height() - 4) / bounds.height())
            self._fit_mode = True
            self.setTransform(QTransform.fromScale(scale, scale))
            self.centerOn(bounds.center())
        finally:
            self._fitting_image = False

    def actual_size(self) -> None:
        if not self._has_image:
            return
        self.resetTransform()
        self.centerOn(self._pixmap_item)
        self._fit_mode = False

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API name)
        if self._has_image and event.angleDelta().y() != 0:
            factor = 1.20 if event.angleDelta().y() > 0 else 1 / 1.20
            current = self.transform().m11()
            new_scale = current * factor
            # Avoid absurd zoom values that can make Qt sluggish.
            if 0.02 <= new_scale <= 80.0:
                self.scale(factor, factor)
                self._fit_mode = False
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._has_image:
            if self._drawing:
                self._drawing = False
                self.drawing_event.emit("release", self.mapToScene(event.position().toPoint()))
            self._panning = False
            self._pan_start = None
            self._middle_panning = True
            self._middle_pan_start = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self._middle_panning:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._has_image and self.drawing_tool != "pan":
            self._drawing = True
            self.drawing_event.emit("press", self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._has_image:
            self.drawing_event.emit("hand_press", self.mapToScene(event.position().toPoint()))
            if self._drawing:
                event.accept()
                return
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._middle_panning and self._middle_pan_start is not None:
            current = event.position().toPoint()
            delta = current - self._middle_pan_start
            self._middle_pan_start = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self._drawing:
            self.drawing_event.emit("move", self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        if self.drawing_tool == "pan" and self._panning and self._pan_start is not None:
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._middle_panning:
            self._middle_panning = False
            self._middle_pan_start = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if self.drawing_tool == "pan" else
                                      Qt.CursorShape.ArrowCursor if self.drawing_tool == "select" else Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if self._middle_panning:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False
            self.drawing_event.emit("release", self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._has_image and self.drawing_tool in ("pan", "select"):
            self.drawing_event.emit("double_click", self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def drawForeground(self, painter, rect) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        painter.save()
        for box, color in ((self.region_rect, Qt.GlobalColor.yellow), (self.selection_rect, Qt.GlobalColor.cyan)):
            if box is None:
                continue
            pen = QPen(color, 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(box)
            if box is self.selection_rect:
                half = 4 / max(0.02, abs(self.transform().m11()))
                painter.setBrush(Qt.GlobalColor.white)
                for corner in (box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft()):
                    painter.drawRect(QRectF(corner - QPointF(half, half), corner + QPointF(half, half)))
        painter.restore()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_image()


class MetadataWorkerSignals(QObject):
    finished = Signal(dict)
    error = Signal(str)


class MetadataWorker(QRunnable):
    def __init__(self, client: MetadataProvider, filename: str, sol: int) -> None:
        super().__init__()
        self.client = client
        self.filename = filename
        self.sol = sol
        self.signals = MetadataWorkerSignals()
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            if self.cancel.is_set():
                return
            info = self.client.lookup(self.filename, self.sol)
            if not self.cancel.is_set():
                self.signals.finished.emit(info)
        except Exception as exc:
            if not self.cancel.is_set():
                self.signals.error.emit(str(exc))


class ImageAboutDialog(QDialog):
    def __init__(self, info: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("About image")
        self.resize(700, 520)

        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)

        rows = []
        labels = [
            ("Arquivo", "filename"),
            ("Image ID", "imageid"),
            ("Sol", "sol"),
            ("Instrumento", "instrument"),
            ("Capturada (UTC)", "date_taken_utc"),
            ("Hora em Marte", "mars_time"),
            ("Recebida pela NASA (UTC)", "date_received"),
            ("Registro no catálogo (UTC)", "catalog_created_at"),
            ("Tipo", "sample_type"),
            ("Créditos", "credit"),
        ]
        for label, key in labels:
            value = info.get(key)
            if value not in (None, ""):
                rows.append(f"<b>{html.escape(label)}:</b> {html.escape(str(value))}<br>")

        caption = info.get("caption")
        title = html.escape(str(info.get("title") or "Imagem da coleção"))
        caption_html = html.escape(str(caption)).replace("\n", "<br>") if caption else "Sem descrição adicional."
        nasa_url = str(info.get("nasa_url") or "")
        link_html = f'<p><a href="{html.escape(nasa_url)}">Abrir esta imagem no site da NASA</a></p>' if nasa_url else ""

        browser.setHtml(
            f"<h2>{title}</h2>"
            + "".join(rows)
            + f"<hr><p>{caption_html}</p>"
            + link_html
        )
        layout.addWidget(browser)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if nasa_url:
            open_button = QPushButton("Abrir NASA")
            open_button.clicked.connect(lambda: webbrowser.open(nasa_url))
            buttons.addWidget(open_button)
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)


class MainWindow(ToolbarAppearanceMixin, InlineAdjustmentsMixin, SolAnnotationsMixin, ImageFiltersMixin, AnnotationWindowMixin, QMainWindow):
    def __init__(self, root: Path, initial_state: dict[str, Any] | None = None, source: ImageSource | str | None = None) -> None:
        super().__init__()
        self._state = dict(initial_state or load_app_state())
        self.missions = MissionRegistry(self._state, current_root=root)
        requested = source.id if isinstance(source, ImageSource) else (source or self._state.get("active_mission_id") or self._state.get("source", "curiosity"))
        if requested not in self.missions.profiles:
            requested = "curiosity"
        self.source = source if isinstance(source, ImageSource) else self.missions.source_for(requested)
        self._source_sessions = dict(self._state.get("source_sessions") or {})
        self._state_ready = False
        self.root = root.resolve()
        self.current_sol: int | None = None
        self.current_folder: Path | None = None
        self.current_path: Path | None = None
        self.current_images: list[Path] = []
        self._last_viewed = (None, None, None)
        self._reveal_restored_path = None
        self.original_image: Image.Image | None = None
        self.processed_qimage: QImage | None = None

        self.contrast = 1.0
        self.saturation = 1.0
        self.rotation = 0
        self.inverted = False
        self.smoothing = 0
        self.color_balance = False
        self.black_point, self.white_point, self.gamma, self.sharpness = 0, 255, 1.0, 0
        self.brightness = 100

        self.metadata_client = self.source.create_metadata_client()
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(2)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.timeout.connect(self._load_thumb_batch)
        self._thumb_queue: list[tuple[QListWidgetItem, Path]] = []
        self._metadata_workers: list[MetadataWorker] = []

        self._download_thread: QThread | None = None
        self._download_worker: QObject | None = None
        self._download_restart_pending = False
        self._catalog_reload_requested = False
        self._download_panel_open = bool(self._state.get("download_panel_open", True))
        self._download_panel_width = int(self._state.get("download_panel_width", 330) or 330)
        self._download_mode: str | None = None
        self._download_requested_start_sol: int | None = None
        self._download_resume_sol: int | None = None
        self._download_current_file: str | None = None
        self._download_pending_resume = bool(
            (self._state.get("download") or {}).get("pending_resume", False)
            if isinstance(self._state.get("download"), dict)
            else False
        )
        self._download_user_stop_requested = False
        self._download_paused = bool((self._state.get("download") or {}).get("paused", False))
        self._closing = False
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(50)
        self._shutdown_timer.timeout.connect(self._finish_shutdown)

        self.setWindowTitle(f"{APP_NAME} — {APP_AUTHOR} — {self.root}")
        saved_size = self._state.get("window_size")
        if isinstance(saved_size, list) and len(saved_size) == 2:
            try:
                self.resize(max(900, int(saved_size[0])), max(600, int(saved_size[1])))
            except Exception:
                self.resize(1450, 900)
        else:
            self.resize(1450, 900)
        self.setMinimumSize(900, 600)

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_annotation_toolbar()
        self._build_inline_adjustments()
        self._init_toolbar_appearance()
        self._init_sol_annotations()
        self._load_sol_list()
        self._restore_saved_ui_state()
        self._update_source_controls()
        self._state_ready = True
        self._save_state(pending_resume=self._download_pending_resume)

        # Retoma exatamente o trabalho pendente da sessão anterior. Se não houver
        # nada pendente, mantém o comportamento de atualização automática.
        if self.source.supports_downloads and self._auto_download_enabled() and self._download_pending_resume:
            QTimer.singleShot(700, self._resume_saved_download)
        elif self.source.supports_downloads and self._auto_download_enabled():
            QTimer.singleShot(700, self._start_downloader)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.sol_list = QListWidget()
        self.sol_list.setMinimumWidth(125)
        self.sol_list.setMaximumWidth(240)
        self.sol_list.setAlternatingRowColors(True)
        self.sol_list.currentItemChanged.connect(self._sol_changed)

        self.image_view = ImageView()
        self.image_view.context_requested.connect(self._show_image_context_menu)

        self.thumb_list = ThumbnailList()
        self.thumb_list.setItemDelegate(AnnotationThumbnailDelegate(self.thumb_list))
        self.thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumb_list.setFlow(QListWidget.Flow.LeftToRight)
        self.thumb_list.setWrapping(False)
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumb_list.setMovement(QListWidget.Movement.Static)
        self.thumb_list.setIconSize(QSize(128, 96))
        self.thumb_list.setGridSize(QSize(150, 124))
        self.thumb_list.setMinimumHeight(70)
        self.thumb_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.thumb_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumb_list.currentItemChanged.connect(self._thumb_changed)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(2)
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self.center_splitter.setObjectName("image_thumbnail_splitter")
        self.center_splitter.setHandleWidth(8)
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.setStyleSheet("QSplitter#image_thumbnail_splitter::handle:vertical { background: palette(mid); }")
        self.image_view.setMinimumHeight(150)
        self.thumbnail_panel = QWidget()
        thumb_layout = QVBoxLayout(self.thumbnail_panel)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setSpacing(2)
        self._build_image_filters(thumb_layout)
        thumb_layout.addWidget(self.thumb_list, 1)
        self.thumbnail_panel.setMinimumHeight(100)
        self.thumbnail_panel.setMaximumHeight(500)
        self.center_splitter.addWidget(self.image_view)
        self.center_splitter.addWidget(self.thumbnail_panel)
        self.center_splitter.setStretchFactor(0, 1)
        self.center_splitter.setStretchFactor(1, 0)
        self._thumb_panel_height = 175
        self.center_splitter.setSizes([600, self._thumb_panel_height])
        self.center_splitter.handle(1).setToolTip("Arraste para cima para ampliar as miniaturas; para baixo para liberar espaço à imagem.")
        self.center_splitter.splitterMoved.connect(self._thumbnail_divider_moved)
        self._thumb_resize_timer = QTimer(self)
        self._thumb_resize_timer.setSingleShot(True)
        self._thumb_resize_timer.timeout.connect(self._reload_resized_thumbnails)
        self.thumb_list.height_changed.connect(self._resize_thumbnail_icons)
        center_layout.addWidget(self.center_splitter, 1)

        # Painel lateral do downloader. O botão < / > fica sempre visível.
        self.download_shell = QWidget()
        download_shell_layout = QHBoxLayout(self.download_shell)
        download_shell_layout.setContentsMargins(0, 0, 0, 0)
        download_shell_layout.setSpacing(0)

        self.download_toggle = QPushButton("<")
        self.download_toggle.setFixedWidth(22)
        self.download_toggle.setToolTip("Ocultar painel de downloads")
        self.download_toggle.clicked.connect(self._toggle_download_panel)
        download_shell_layout.addWidget(self.download_toggle, 0)

        self.download_panel = QWidget()
        self.download_panel.setMinimumWidth(290)
        self.download_panel.setMaximumWidth(430)
        download_layout = QVBoxLayout(self.download_panel)
        download_layout.setContentsMargins(8, 6, 8, 6)
        download_layout.setSpacing(6)

        self.download_title = QLabel(f"<b>{self.source.name}</b><br><small>Download de imagens · {APP_AUTHOR}</small>")
        download_layout.addWidget(self.download_title)

        self.download_status = QLabel("Aguardando atualização...")
        self.download_status.setWordWrap(True)
        download_layout.addWidget(self.download_status)

        self.download_sol_label = QLabel("SOL: —")
        download_layout.addWidget(self.download_sol_label)

        self.download_sol_progress = QProgressBar()
        self.download_sol_progress.setRange(0, 100)
        self.download_sol_progress.setValue(0)
        self.download_sol_progress.setFormat("SOL: %p%")
        download_layout.addWidget(self.download_sol_progress)

        self.download_file_label = QLabel("Arquivo: —")
        self.download_file_label.setWordWrap(True)
        self.download_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        download_layout.addWidget(self.download_file_label)

        self.download_file_progress = QProgressBar()
        self.download_file_progress.setRange(0, 100)
        self.download_file_progress.setValue(0)
        self.download_file_progress.setFormat("Arquivo: %p%")
        download_layout.addWidget(self.download_file_progress)

        self.download_stats = QLabel("0 arquivos novos")
        # Progress text must not change the space available to the image/thumbnail strip.
        for control in (self.download_title, self.download_status, self.download_sol_label,
                        self.download_file_label, self.download_stats, self.download_sol_progress,
                        self.download_file_progress):
            control.setSizePolicy(QSizePolicy.Policy.Ignored, control.sizePolicy().verticalPolicy())

        self.download_stats.setWordWrap(True)
        download_layout.addWidget(self.download_stats)

        history_title = QLabel("<b>Atividade</b>")
        download_layout.addWidget(history_title)

        self.download_history = QListWidget()
        self.download_history.setAlternatingRowColors(True)
        download_layout.addWidget(self.download_history, 1)

        start_sol_row = QHBoxLayout()
        start_sol_label = self.start_sol_label = QLabel("SOL inicial:")
        start_sol_row.addWidget(start_sol_label)

        self.download_start_sol = QSpinBox()
        self.download_start_sol.setRange(0, 100000)
        self.download_start_sol.valueChanged.connect(self._on_download_start_sol_changed)
        self.download_start_sol.setToolTip(
            "Reverifica deste SOL até o último disponível na NASA. "
            "Arquivos existentes não são baixados novamente."
        )
        local_sols = self.source.list_collections(self.root)
        if local_sols:
            self.download_start_sol.setValue(local_sols[0][0])
        start_sol_row.addWidget(self.download_start_sol, 1)
        download_layout.addLayout(start_sol_row)

        self.download_from_button = QPushButton("Verificar deste SOL em diante")
        self.download_from_button.setToolTip(
            "Percorre todos os SOLs a partir do número informado e completa "
            "somente as imagens que estiverem faltando."
        )
        self.download_from_button.clicked.connect(self._start_from_sol)
        download_layout.addWidget(self.download_from_button)

        self.download_selected_button = QPushButton("Reverificar SOL selecionado")
        self.download_selected_button.clicked.connect(self._start_selected_sol)
        download_layout.addWidget(self.download_selected_button)

        button_row = QHBoxLayout()
        self.download_now_button = QPushButton("Atualizar agora")
        self.download_now_button.clicked.connect(self._start_downloader)
        button_row.addWidget(self.download_now_button)
        self.download_stop_button = QPushButton("Parar")
        self.download_stop_button.setEnabled(False)
        self.download_stop_button.clicked.connect(self._toggle_download_pause)
        button_row.addWidget(self.download_stop_button)
        download_layout.addLayout(button_row)

        download_shell_layout.addWidget(self.download_panel, 1)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(3)
        self.main_splitter.addWidget(self.sol_list)
        self.main_splitter.addWidget(center)
        self.main_splitter.addWidget(self.download_shell)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, False)
        self.main_splitter.setSizes([160, 970, 330])
        self.setCentralWidget(self.main_splitter)

        self.setStatusBar(QStatusBar(self))
        self.brand_label = QLabel(f"  {APP_AUTHOR}  ")
        self.brand_label.setToolTip("Desenvolvido por NaRede Labs")
        self.statusBar().addPermanentWidget(self.brand_label)
        self.statusBar().showMessage(str(self.root))

    def _make_action(self, text: str, slot, shortcut: str | QKeySequence | None = None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def _build_actions(self) -> None:
        self.act_open_root = self._make_action("Abrir coleção...", self._choose_root, QKeySequence.StandardKey.Open)
        self.act_refresh = self._make_action("Atualizar", self._load_sol_list, "F5")
        self.act_exit = self._make_action("Sair", self.close, QKeySequence.StandardKey.Quit)

        self.act_fit = self._make_action("Ajustar à janela", self.image_view.fit_image, "F")
        self.act_actual = self._make_action("Tamanho real (1:1)", self.image_view.actual_size, "1")
        self.act_auto_zoom = self._make_action("Auto Zoom", self._save_auto_zoom)
        self.act_auto_zoom.setCheckable(True)
        self.act_auto_zoom.setChecked(bool(self._state.get("auto_zoom", False)))
        self.act_auto_zoom.setToolTip("Manter o zoom e a posição da área visualizada ao trocar de imagem")

        self.act_brightness = self._make_action("Brilho…", lambda: self._focus_inline_adjustment("brightness"))
        self.act_levels = self._make_action("Níveis…", lambda: self._focus_inline_adjustment("gamma"))
        self.act_sharpen = self._make_action("Nitidez…", lambda: self._focus_inline_adjustment("sharpness"))
        self.act_original = self._make_action("Comparar original", self._toggle_original, "Ctrl+Shift+O")
        self.act_original.setCheckable(True)
        self.act_balance = self._make_action("Equilibrar cores", self._toggle_color_balance, "E")
        self.act_balance.setCheckable(True)
        self.act_balance.setToolTip("Reduz automaticamente a dominante de cor. Estimativa visual; clique novamente para desativar.")
        self.act_smooth = self._make_action("Suavizar imagem", lambda: self._focus_inline_adjustment("smoothing"))
        self.act_contrast_up = self._make_action("Contraste +", lambda: self._adjust_contrast(0.02), "]")
        self.act_contrast_down = self._make_action("Contraste -", lambda: self._adjust_contrast(-0.02), "[")
        self.act_color_up = self._make_action("Cor +", lambda: self._adjust_saturation(0.02))
        self.act_color_down = self._make_action("Cor -", lambda: self._adjust_saturation(-0.02))
        self.act_rotate_left = self._make_action("Girar 90° à esquerda", lambda: self._rotate(-90), "Ctrl+Left")
        self.act_rotate_right = self._make_action("Girar 90° à direita", lambda: self._rotate(90), "Ctrl+Right")
        self.act_reset_image = self._make_action("Resetar ajustes", self._reset_adjustments, "Ctrl+0")
        self.act_invert = self._make_action("Inverter cores", self._toggle_invert)
        self.act_invert.setCheckable(True)

        self.act_copy = self._make_action("Copy", self._copy_image, QKeySequence.StandardKey.Copy)
        self.act_gimp = self._make_action("Open with GIMP", self._open_in_gimp)
        self.act_about_image = self._make_action("About", self._about_current_image)

        self.act_prev = self._make_action("Imagem anterior", self._previous_image, "Left")
        self.act_next = self._make_action("Próxima imagem", self._next_image, "Right")
        self.act_prev.setShortcuts([QKeySequence("B"), QKeySequence("Left")])
        self.act_next.setShortcuts([QKeySequence("N"), QKeySequence("Right")])

        self.act_download_now = self._make_action("Atualizar imagens da NASA", self._start_downloader)
        self.act_download_from = self._make_action(
            "Verificar desde o SOL inicial",
            self._start_from_sol,
        )
        self.act_download_selected = self._make_action("Reverificar SOL selecionado", self._start_selected_sol)
        self.act_download_stop = self._make_action("Parar downloader", self._toggle_download_pause)
        self.act_download_stop.setEnabled(False)
        self.act_download_panel = self._make_action("Mostrar/ocultar painel", self._toggle_download_panel)
        self.act_clear_catalog_cache = self._make_action("Limpar cache de catálogos e reler tudo", self._clear_catalog_cache)

        self.act_about_app = self._make_action("Sobre o programa", self._about_app)

    def _build_menus(self) -> None:
        menu_file = self.menuBar().addMenu("Arquivo")
        menu_file.addAction(self.act_open_root)
        menu_file.addAction(self.act_refresh)
        menu_file.addSeparator()
        menu_file.addAction(self.act_exit)

        self._mission_menu = self.menuBar().addMenu("Missões")
        self._source_actions = QActionGroup(self)
        self.act_mission_settings = self._make_action("Configurar planetas e missões...", self._configure_missions, "Ctrl+,")
        self.act_mission_archive = self._make_action("Abrir portal da missão atual", self._open_mission_archive)
        self._rebuild_mission_menu()

        menu_view = self.menuBar().addMenu("Visualizar")
        menu_view.addAction(self.act_fit)
        menu_view.addAction(self.act_actual)
        menu_view.addAction(self.act_auto_zoom)
        menu_view.addSeparator()
        menu_view.addAction(self.act_prev)
        menu_view.addAction(self.act_next)
        menu_view.addSeparator()
        self.act_toolbar_text = QAction("Mostrar texto nos bot?es das barras", self)
        self.act_toolbar_text.setCheckable(True)
        self.act_toolbar_text.toggled.connect(self._set_toolbar_text)
        menu_view.addAction(self.act_toolbar_text)

        menu_image = self.menuBar().addMenu("Imagem")
        menu_image.addAction(self.act_contrast_up)
        menu_image.addAction(self.act_contrast_down)
        menu_image.addSeparator()
        menu_image.addAction(self.act_color_up)
        menu_image.addAction(self.act_color_down)
        menu_image.addAction(self.act_balance)
        menu_image.addSeparator()
        menu_image.addAction(self.act_rotate_left)
        menu_image.addAction(self.act_rotate_right)
        menu_image.addSeparator()
        menu_image.addAction(self.act_reset_image)
        menu_image.addAction(self.act_invert)
        menu_image.addAction(self.act_smooth)
        menu_image.addAction(self.act_levels)
        menu_image.addAction(self.act_sharpen)
        menu_image.addAction(self.act_brightness)
        menu_image.addSeparator()
        menu_image.addAction(self.act_original)

        menu_download = self.menuBar().addMenu("Downloader")
        menu_download.addAction(self.act_download_now)
        menu_download.addAction(self.act_download_from)
        menu_download.addAction(self.act_download_selected)
        menu_download.addAction(self.act_download_stop)
        menu_download.addSeparator()
        menu_download.addAction(self.act_clear_catalog_cache)
        menu_download.addSeparator()
        menu_download.addAction(self.act_download_panel)

        menu_help = self.menuBar().addMenu("Ajuda")
        menu_help.addAction(self.act_about_app)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Ferramentas", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(True)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        mission_toolbar = QToolBar("Missão de trabalho", self)
        mission_toolbar.setObjectName("mission_toolbar")
        self.addToolBar(mission_toolbar)
        mission_toolbar.addWidget(QLabel("Missão de trabalho: "))
        self.mission_selector = QComboBox()
        self.mission_selector.setMinimumWidth(290)
        mission_toolbar.addWidget(self.mission_selector)
        self._refresh_mission_selector()
        self.mission_selector.activated.connect(self._select_mission_from_toolbar)
        toolbar.addAction(self.act_open_root)
        toolbar.addAction(self.act_mission_settings)
        toolbar.addSeparator()
        toolbar.addAction(self.act_fit)
        toolbar.addAction(self.act_actual)
        toolbar.addAction(self.act_auto_zoom)
        toolbar.addAction(self.act_original)
        toolbar.addSeparator()
        toolbar.addAction(self.act_rotate_left)
        toolbar.addAction(self.act_rotate_right)
        toolbar.addAction(self.act_reset_image)
        toolbar.addAction(self.act_invert)
        toolbar.addAction(self.act_balance)

    def _thumbnail_divider_moved(self, position, index):
        self._thumb_panel_height = self.center_splitter.sizes()[1]
        self._resize_thumbnail_icons()
        self._save_state()

    def _resize_thumbnail_icons(self):
        height = max(32, self.thumb_list.viewport().height() - self.thumb_list.fontMetrics().height() - 20)
        icon_size = QSize(round(height * 4 / 3), height)
        if icon_size == self.thumb_list.iconSize():
            return
        bar = self.thumb_list.horizontalScrollBar()
        old_width = max(1, self.thumb_list.gridSize().width())
        anchor = bar.value() / old_width
        self._thumb_timer.stop()
        self.thumb_list.setIconSize(icon_size)
        self.thumb_list.setGridSize(QSize(icon_size.width() + 22, height + self.thumb_list.fontMetrics().height() + 16))
        self.thumb_list.doItemsLayout()
        bar.setValue(round(anchor * self.thumb_list.gridSize().width()))
        self._thumb_resize_timer.start(120)

    def _reload_resized_thumbnails(self):
        self._thumb_queue = []
        for row in range(self.thumb_list.count()):
            item = self.thumb_list.item(row)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                self._thumb_queue.append((item, Path(path)))
        if self._thumb_queue:
            self._thumb_timer.start(1)
        if self._reveal_restored_path is not None:
            if self.current_path == self._reveal_restored_path:
                self.thumb_list.doItemsLayout()
                self.thumb_list.scrollToItem(self.thumb_list.currentItem())
                self.sol_list.scrollToItem(self.sol_list.currentItem())
            self._reveal_restored_path = None

    # ---------- Downloader ----------
    def _toggle_download_panel(self) -> None:
        self._set_download_panel_open(not self._download_panel_open)

    def _set_download_panel_open(self, opened: bool, persist: bool = True) -> None:
        self._download_panel_open = bool(opened)
        sizes = self.main_splitter.sizes()
        if len(sizes) != 3:
            sizes = [160, max(600, self.width() - 490), 330]

        left, center, right = sizes
        available_center_right = max(250, center + right)

        if self._download_panel_open:
            if right > 80:
                self._download_panel_width = right
            target = max(300, min(430, int(self._download_panel_width or 330)))
            self.download_shell.setMinimumWidth(0)
            self.download_shell.setMaximumWidth(460)
            self.download_panel.show()
            self.download_toggle.setText("<")
            self.download_toggle.setToolTip("Ocultar painel de downloads")
            self.main_splitter.setSizes([
                max(125, left),
                max(300, available_center_right - target),
                target,
            ])
        else:
            if right > 80:
                self._download_panel_width = right
            self.download_panel.hide()
            self.download_shell.setMinimumWidth(22)
            self.download_shell.setMaximumWidth(22)
            self.download_toggle.setText(">")
            self.download_toggle.setToolTip("Mostrar painel de downloads")
            # Explicitly give the space back to the image area. Merely hiding the
            # contents is not enough because QSplitter remembers the old width.
            self.main_splitter.setSizes([
                max(125, left),
                max(300, available_center_right - 22),
                22,
            ])

        if persist:
            self._save_state()

    def _on_download_start_sol_changed(self, value: int) -> None:
        if not getattr(self, "_state_ready", False):
            return
        self.missions.profiles[self.source.id]["start_sol"] = int(value)
        self._save_state()

    def _save_auto_zoom(self) -> None:
        if getattr(self, "_state_ready", False):
            self._save_state()

    def _restore_saved_ui_state(self) -> None:
        layout = self._state.get("toolbar_layout")
        if isinstance(layout, str):
            try:
                self.restoreState(QByteArray(bytes.fromhex(layout)), 1)
            except ValueError:
                pass
        height = self._state.get("thumbnail_panel_height", self._thumb_panel_height)
        if isinstance(height, (int, float)):
            self._thumb_panel_height = max(100, min(500, int(height)))
            total = sum(self.center_splitter.sizes())
            self.center_splitter.setSizes([max(150, total - self._thumb_panel_height), self._thumb_panel_height])
        start_sol = self._state.get("download_start_sol")
        if isinstance(start_sol, int):
            self.download_start_sol.blockSignals(True)
            self.download_start_sol.setValue(start_sol)
            self.download_start_sol.blockSignals(False)

        splitter_sizes = self._state.get("splitter_sizes")
        if isinstance(splitter_sizes, list) and len(splitter_sizes) == 3:
            try:
                self.main_splitter.setSizes([max(1, int(v)) for v in splitter_sizes])
            except Exception:
                pass

        self._set_download_panel_open(self._download_panel_open, persist=False)

        selected_sol = self._state.get("selected_sol")
        selected_folder = self._state.get("selected_folder")
        selected_image = self._state.get("selected_image")
        relative = self._state.get("selected_image_path")
        if isinstance(relative, str) and relative:
            candidate = self.root / relative
            if candidate.is_file() and candidate.resolve().is_relative_to(self.root):
                selected_folder, selected_image = str(candidate.parent), candidate.name
        if selected_folder or isinstance(selected_sol, int):
            for row in range(self.sol_list.count()):
                item = self.sol_list.item(row)
                data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
                if data and (str(data[1]) == selected_folder if selected_folder else int(data[0]) == selected_sol):
                    self.sol_list.setCurrentRow(row)
                    break

        if isinstance(selected_image, str) and selected_image:
            for row in range(self.thumb_list.count()):
                item = self.thumb_list.item(row)
                path_text = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
                if path_text and Path(path_text).name == selected_image:
                    self.thumb_list.setCurrentRow(row)
                    self._reveal_restored_path = Path(path_text)
                    self._thumb_resize_timer.start(0)
                    break

        if bool(self._state.get("window_maximized", False)):
            QTimer.singleShot(0, self.showMaximized)

        saved_history = self._state.get("download_history")
        if isinstance(saved_history, list):
            self.download_history.clear()
            for text in reversed(saved_history[:100]):
                if isinstance(text, str) and text:
                    self.download_history.insertItem(0, text)

        saved_status = self._state.get("download_status")
        if isinstance(saved_status, str) and saved_status:
            self.download_status.setText(saved_status)

        download_state = self._state.get("download")
        if isinstance(download_state, dict):
            mode = download_state.get("mode")
            self._download_mode = str(mode) if mode in ("update", "from_sol", "only_sol") else None
            requested = download_state.get("requested_start_sol")
            resume_sol = download_state.get("resume_sol")
            current_file = download_state.get("current_file")
            self._download_requested_start_sol = int(requested) if isinstance(requested, int) else None
            self._download_resume_sol = int(resume_sol) if isinstance(resume_sol, int) else None
            self._download_current_file = str(current_file) if current_file else None
            if self._download_pending_resume and self._download_resume_sol is not None:
                self.download_status.setText(
                    f"Retomada pendente a partir do SOL {self._download_resume_sol}."
                )
                if self._download_current_file:
                    self.download_file_label.setText(
                        f"Último arquivo: {self._download_current_file}"
                    )

    def _build_state(self, pending_resume: bool | None = None) -> dict[str, Any]:
        running = (
            self._download_thread is not None
            and self._download_thread.isRunning()
        )
        if pending_resume is None:
            pending_resume = self._download_pending_resume or running

        sizes = self.main_splitter.sizes() if hasattr(self, "main_splitter") else [160, 970, 330]
        if len(sizes) != 3:
            sizes = [160, 970, 330]

        viewed_sol, viewed_folder, viewed_path = (
            (self.current_sol, self.current_folder, self.current_path) if self.current_path is not None
            else self._last_viewed
        )
        relative_path = str(viewed_path.relative_to(self.root)) if viewed_path is not None and viewed_path.is_relative_to(self.root) else None
        return {
            "version": 1,
            "source": self.source.id,
            "active_mission_id": self.source.id,
            "mission_config": self.missions.serialize(),
            "source_sessions": self._source_sessions,
            "root": str(self.root),
            "window_size": [int(self.width()), int(self.height())],
            "window_maximized": bool(self.isMaximized()),
            "toolbar_layout": bytes(self.saveState(1)).hex(),
            "toolbar_text": self.act_toolbar_text.isChecked(),
            "auto_zoom": self.act_auto_zoom.isChecked(),
            "splitter_sizes": [int(v) for v in sizes],
            "thumbnail_panel_height": self._thumb_panel_height,
            "download_panel_open": bool(self._download_panel_open),
            "download_panel_width": int(self._download_panel_width),
            "download_start_sol": int(self.download_start_sol.value()) if hasattr(self, "download_start_sol") else 0,
            "selected_sol": viewed_sol,
            "selected_folder": str(viewed_folder) if viewed_folder else None,
            "selected_image": viewed_path.name if viewed_path is not None else None,
            "selected_image_path": relative_path,
            "download_status": self.download_status.text() if hasattr(self, "download_status") else "",
            "download_history": [
                self.download_history.item(i).text()
                for i in range(min(self.download_history.count(), 100))
                if self.download_history.item(i) is not None
            ] if hasattr(self, "download_history") else [],
            "download": {
                "pending_resume": bool(pending_resume),
                "paused": self._download_paused,
                "mode": self._download_mode,
                "requested_start_sol": self._download_requested_start_sol,
                "resume_sol": self._download_resume_sol,
                "current_file": self._download_current_file,
            },
        }

    def _save_state(self, pending_resume: bool | None = None) -> bool:
        if not getattr(self, "_state_ready", False):
            return
        state = self._build_state(pending_resume=pending_resume)
        saved = save_app_state(state)
        self._state = state
        return saved is not None

    def _resume_saved_download(self) -> None:
        download_state = self._state.get("download")
        if not isinstance(download_state, dict) or not (download_state.get("pending_resume") or download_state.get("paused")):
            self._download_pending_resume = False
            self._start_downloader()
            return

        mode = download_state.get("mode")
        resume_sol = download_state.get("resume_sol")
        requested = download_state.get("requested_start_sol")
        if not isinstance(resume_sol, int):
            resume_sol = requested if isinstance(requested, int) else int(self.download_start_sol.value())

        if not getattr(self.source, "uses_sols", True) and mode != "only_sol":
            self._launch_downloader()
            return
        self._download_add_history(f"↻ Retomando sessão anterior: {self._collection_text(resume_sol)}")
        if mode == "only_sol":
            self._launch_downloader(only_sol=resume_sol)
        else:
            # Both normal update and 'from SOL' can safely resume from the last SOL,
            # because existing files are skipped and any .part is continued.
            self._launch_downloader(start_sol=resume_sol)

    def _download_add_history(self, text: str) -> None:
        self.download_history.insertItem(0, text)
        while self.download_history.count() > 150:
            self.download_history.takeItem(self.download_history.count() - 1)

    def _start_downloader(self) -> None:
        self._launch_downloader()

    def _start_from_sol(self) -> None:
        start_sol = int(self.download_start_sol.value()) if getattr(self.source, "uses_sols", True) else 0
        self._launch_downloader(start_sol=start_sol)

    def _start_selected_sol(self) -> None:
        if self.current_sol is None:
            QMessageBox.information(
                self,
                "Reverificar SOL",
                "Selecione um SOL na coluna da esquerda primeiro.",
            )
            return
        self._launch_downloader(only_sol=self.current_sol)

    def _launch_downloader(
        self,
        only_sol: int | None = None,
        start_sol: int | None = None,
    ) -> None:
        if self._closing or not self.source.supports_downloads:
            return
        if self._download_thread is not None and self._download_thread.isRunning():
            self.download_status.setText("O downloader já está em execução.")
            return

        self._download_restart_pending = False
        self._download_user_stop_requested = False
        self._download_paused = False
        self.download_stop_button.setText("Parar")
        self.act_download_stop.setText("Parar downloader")
        self._download_pending_resume = True
        if only_sol is not None:
            self._download_mode = "only_sol"
            self._download_requested_start_sol = only_sol
            self._download_resume_sol = only_sol
        elif start_sol is not None:
            self._download_mode = "from_sol"
            self._download_requested_start_sol = start_sol
            self._download_resume_sol = start_sol
        else:
            self._download_mode = "update"
            self._download_requested_start_sol = None
            self._download_resume_sol = None

        if only_sol is not None:
            self.download_status.setText(f"Reverificando o SOL {only_sol} em segundo plano...")
            self.download_sol_label.setText(f"SOL {only_sol}")
            history_text = f"▶ Reverificação do SOL {only_sol} iniciada"
        elif start_sol is not None:
            self.download_status.setText(
                f"Preparando reverificação a partir do SOL {start_sol}..."
            )
            self.download_sol_label.setText(f"SOL inicial: {start_sol}")
            history_text = f"▶ Reverificação desde o SOL {start_sol} iniciada"
        else:
            self.download_status.setText("Iniciando atualização em segundo plano...")
            self.download_sol_label.setText("SOL: consultando NASA...")
            history_text = "▶ Atualização iniciada"

        if not getattr(self.source, "uses_sols", True):
            self.download_sol_label.setText("Consultando acervo...")
            self.download_status.setText("Preparando lote de observações...")
            history_text = "▶ Lote de observações iniciado"
        self.download_file_label.setText("Arquivo: —")
        self.download_stats.setText("Verificando imagens faltantes...")
        self.download_sol_progress.setRange(0, 0)
        self.download_file_progress.setRange(0, 100)
        self.download_file_progress.setValue(0)
        self.download_now_button.setEnabled(False)
        self.download_from_button.setEnabled(False)
        self.download_start_sol.setEnabled(False)
        self.download_selected_button.setEnabled(False)
        self.download_stop_button.setEnabled(True)
        if hasattr(self, "act_download_now"):
            self.act_download_now.setEnabled(False)
            self.act_download_from.setEnabled(False)
            self.act_download_selected.setEnabled(False)
            self.act_download_stop.setEnabled(True)

        thread = QThread(self)
        worker = self.source.create_downloader(
            self.root,
            only_sol=only_sol,
            start_sol=start_sol,
        )
        worker.moveToThread(thread)
        if self._catalog_reload_requested:
            worker.clear_catalog_cache = True
            self._catalog_reload_requested = False

        thread.started.connect(worker.run)
        worker.message.connect(self._on_download_message)
        worker.sol_started.connect(self._on_download_sol_started)
        worker.sol_catalogued.connect(self._on_download_sol_catalogued)
        worker.catalog_progress.connect(self._on_catalog_progress)
        worker.sol_progress.connect(self._on_download_sol_progress)
        worker.file_started.connect(self._on_download_file_started)
        worker.file_progress.connect(self._on_download_file_progress)
        worker.file_downloaded.connect(self._on_download_file_downloaded)
        worker.sol_created.connect(self._on_download_sol_created)
        worker.sol_finished.connect(self._on_download_sol_finished)
        worker.failed.connect(self._on_download_failed)
        worker.finished.connect(self._on_downloader_finished)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_download_thread_finished)

        self._download_thread = thread
        self._download_worker = worker
        self._source_actions.setEnabled(False)
        self.act_mission_settings.setEnabled(False)
        self.mission_selector.setEnabled(False)
        self.act_open_root.setEnabled(False)
        self._download_add_history(history_text)
        self._save_state(pending_resume=True)
        thread.start()

    def _sync_download_pause_button(self):
        running = self._download_thread is not None and self._download_thread.isRunning()
        resumable = self.source.supports_downloads and (self._download_paused or self._download_pending_resume)
        label = "Continuar" if not running and resumable else "Parar"
        enabled = (running and not self._download_user_stop_requested) or (not running and resumable)
        self.download_stop_button.setText(label)
        self.download_stop_button.setEnabled(enabled)
        self.act_download_stop.setText(label + " downloader")
        self.act_download_stop.setEnabled(enabled)

    def _toggle_download_pause(self):
        self._catalog_reload_requested = False
        if self._download_thread is not None and self._download_thread.isRunning():
            self._stop_downloader()
        elif self._download_paused or self._download_pending_resume:
            self._resume_saved_download()

    def _stop_downloader(self) -> None:
        worker = self._download_worker
        thread = self._download_thread
        if worker is None or thread is None or not thread.isRunning():
            return
        self._download_user_stop_requested = True
        self._download_paused = True
        self._save_state(pending_resume=False)
        self.download_status.setText("Interrompendo após o bloco atual...")
        self.download_stop_button.setEnabled(False)
        if hasattr(self, "act_download_stop"):
            self.act_download_stop.setEnabled(False)
        worker.stop()
        thread.requestInterruption()

    def _on_download_message(self, message: str) -> None:
        self.download_status.setText(message)
        self._download_add_history(message)

    def _on_catalog_progress(self, completed, total):
        if self._closing:
            return
        self.download_sol_label.setText(f'Catálogo completo: {completed}/{total} SOLs')
        self.download_sol_progress.setRange(0, max(1, total))
        self.download_sol_progress.setValue(completed)
        self.download_sol_progress.setFormat('Catálogo: %v/%m (%p%)')
        self.download_file_label.setText('Conferindo catálogos antes de baixar imagens...')

    def _clear_catalog_cache(self):
        if self._closing:
            return
        self._catalog_reload_requested = True
        if self._download_thread is not None and self._download_thread.isRunning():
            self.download_status.setText('Parando a consulta atual para reler o catálogo completo...')
            self._download_worker.stop()
            self._download_thread.requestInterruption()
        else:
            self._launch_downloader(start_sol=0)

    def _collection_text(self, key):
        if getattr(self.source, "uses_sols", True):
            return f"SOL {key}"
        for index in range(self.sol_list.count()):
            item = self.sol_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole)[0] == key:
                return item.text()
        return "Observação"

    def _on_download_sol_started(self, sol: int, position: int, total_sols: int) -> None:
        self._download_resume_sol = sol
        self._download_current_file = None
        self._download_pending_resume = True
        self._save_state(pending_resume=True)
        self.download_sol_label.setText(f"{self._collection_text(sol)}  ({position}/{total_sols})")
        self.download_status.setText(f"Lendo catálogo do {self._collection_text(sol)}...")
        self.download_sol_progress.setRange(0, 0)
        self.download_file_label.setText("Arquivo: aguardando catálogo...")
        self.download_file_progress.setRange(0, 100)
        self.download_file_progress.setValue(0)
        self._download_add_history(f"● {self._collection_text(sol)}: verificando catálogo")

    def _on_download_sol_catalogued(self, sol: int, total: int) -> None:
        self.download_status.setText(f"{self._collection_text(sol)}: {total} imagens encontradas no acervo")
        self.download_sol_progress.setRange(0, max(1, total))
        self.download_sol_progress.setValue(0)
        self.download_sol_progress.setFormat(f"{self._collection_text(sol)}: %v/%m  (%p%)")
        if total == 0:
            self.download_sol_progress.setValue(1)

    def _on_download_sol_progress(self, sol: int, completed: int, total: int) -> None:
        self.download_sol_progress.setRange(0, max(1, total))
        self.download_sol_progress.setValue(completed if total else 1)
        self.download_sol_progress.setFormat(f"{self._collection_text(sol)}: %v/%m  (%p%)")

    def _on_download_file_started(self, sol: int, filename: str, index: int, total: int) -> None:
        self._download_current_file = filename
        self.download_file_label.setText(f"Arquivo {index}/{total}: {filename}")
        self.download_file_progress.setRange(0, 100)
        self.download_file_progress.setValue(0)
        self.download_file_progress.setFormat("Arquivo: %p%")

    def _on_download_file_progress(
        self,
        sol: int,
        filename: str,
        percent: int,
        downloaded: int,
        total_bytes: int,
    ) -> None:
        if percent < 0:
            self.download_file_progress.setRange(0, 0)
            mb = downloaded / (1024 * 1024)
            self.download_file_progress.setFormat(f"{mb:.1f} MB")
        else:
            self.download_file_progress.setRange(0, 100)
            self.download_file_progress.setValue(max(0, min(100, percent)))
            if total_bytes > 0:
                done_mb = downloaded / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                self.download_file_progress.setFormat(f"%p%  ({done_mb:.1f}/{total_mb:.1f} MB)")
            else:
                self.download_file_progress.setFormat("Arquivo: %p%")

    def _on_download_file_downloaded(self, sol: int, path_text: str) -> None:
        if self._closing:
            return
        path = Path(path_text)
        self._download_add_history(f"✓ {self._collection_text(sol)}: {path.name}")
        if self._filters_active():
            if self.filter_scope.currentIndex() == 1 or path.parent == self.current_folder:
                self._filter_timer.start(500)
            return

        # Se o usuário estiver olhando este SOL, a nova imagem aparece nas
        # thumbnails imediatamente, sem precisar apertar F5.
        if self.current_sol == sol and path.exists():
            resolved = path.resolve()
            if all(existing.resolve() != resolved for existing in self.current_images if existing.exists()):
                self.current_images.append(path)
                item = QListWidgetItem(path.name)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(path.name)
                scroll = self.thumb_list.horizontalScrollBar().value()
                self.thumb_list.addItem(item)
                self.thumb_list.doItemsLayout()
                self.thumb_list.horizontalScrollBar().setValue(scroll)
                self._thumb_queue.append((item, path))
                if not self._thumb_timer.isActive():
                    self._thumb_timer.start(1)

                if self.original_image is None:
                    if self._load_image(path, show_error=False):
                        self.thumb_list.blockSignals(True)
                        self.thumb_list.setCurrentItem(item)
                        self.thumb_list.blockSignals(False)

    def _on_download_sol_created(self, sol: int, folder_text: str) -> None:
        if self._closing:
            return
        self._download_add_history(f"＋ Criada pasta {Path(folder_text).name}")
        # Inserir sem reconstruir a lista: selecionar novamente o mesmo SOL
        # dispara _sol_changed e abre a primeira imagem, perdendo a visualização.
        row = self.sol_list.count()
        for index in range(self.sol_list.count()):
            existing_sol, _ = self.sol_list.item(index).data(Qt.ItemDataRole.UserRole)
            if existing_sol == sol:
                return
            if existing_sol < sol and row == self.sol_list.count():
                row = index

        folder = Path(folder_text)
        item = QListWidgetItem(folder.name)
        item.setData(Qt.ItemDataRole.UserRole, (sol, str(folder)))
        item.setToolTip(str(folder))
        self.sol_list.insertItem(row, item)
        self._update_sol_annotation_highlight(item)
        if self.current_sol is None:
            self.sol_list.setCurrentItem(item)

    def _on_download_sol_finished(self, sol: int, total: int, new_count: int, existing_count: int) -> None:
        self._download_current_file = None
        if self._download_mode != "only_sol":
            self._download_resume_sol = sol + 1
        self._save_state(pending_resume=True)
        self.download_stats.setText(
            f"{self._collection_text(sol)}: {new_count} novas • {existing_count} já existentes • {total} registros"
        )
        self._download_add_history(
            f"■ {self._collection_text(sol)}: {new_count} novas, {existing_count} já existentes"
        )

    def _on_download_failed(self, message: str) -> None:
        self.download_status.setText(f"Erro: {message}")
        self._download_add_history(f"ERRO: {message}")

    def _on_downloader_finished(self, message: str) -> None:
        self.download_status.setText(message)
        self._download_add_history(f"■ {message}")

        lower_message = message.lower()
        completed = (
            "concluída" in lower_message
            or "concluido" in lower_message
            or "concluído" in lower_message
            or "nada para" in lower_message
        )

        if self._closing:
            # closeEvent writes a final pending state after the worker stops.
            self._download_pending_resume = True
        elif self._download_user_stop_requested:
            # The user explicitly pressed Stop; do not auto-resume next startup.
            self._download_pending_resume = False
            self._save_state(pending_resume=False)
        elif completed:
            self._download_pending_resume = False
            self._download_current_file = None
            self._save_state(pending_resume=False)
        else:
            # Network/API failure: preserve the restart point for the next session.
            self._download_pending_resume = True
            self._save_state(pending_resume=True)

        self.download_stop_button.setEnabled(False)
        self.download_now_button.setEnabled(True)
        self.download_from_button.setEnabled(True)
        self.download_start_sol.setEnabled(True)
        self.download_selected_button.setEnabled(True)
        if hasattr(self, "act_download_now"):
            self.act_download_now.setEnabled(True)
            self.act_download_from.setEnabled(True)
            self.act_download_selected.setEnabled(True)
            self.act_download_stop.setEnabled(False)

    def _on_download_thread_finished(self) -> None:
        old_thread = self._download_thread
        self._download_worker = None
        self._download_thread = None
        if self._closing:
            if old_thread is not None:
                old_thread.deleteLater()
            return
        self._sync_download_pause_button()
        self._source_actions.setEnabled(True)
        self.act_mission_settings.setEnabled(True)
        self.mission_selector.setEnabled(True)
        self.act_open_root.setEnabled(True)
        if old_thread is not None:
            old_thread.deleteLater()

        if self._catalog_reload_requested:
            self._launch_downloader(start_sol=0)
        elif self._download_restart_pending:
            self._download_restart_pending = False
            QTimer.singleShot(100, self._start_downloader)

    # ---------- Folder/Sol/Image loading ----------
    def _update_source_controls(self) -> None:
        downloads = self.source.supports_downloads
        self.act_clear_catalog_cache.setEnabled(downloads and getattr(self.source, 'uses_sols', True))
        self._sync_download_pause_button()
        if not downloads:
            self._download_pending_resume = False
        sols = getattr(self.source, "uses_sols", downloads)
        self.start_sol_label.setVisible(sols)
        self.download_start_sol.setVisible(sols)
        self.download_now_button.setText("Atualizar imagens" if sols else "Baixar próximo lote (10 observações)")
        self.download_from_button.setText("Verificar deste SOL em diante" if sols else "Reverificar início do catálogo")
        self.download_from_button.setToolTip("Reverifica desde o SOL informado." if sols else "Recomeça o catálogo, preservando arquivos já baixados; cada lote tem até 10 observações.")
        self.act_download_from.setText(self.download_from_button.text())
        self.act_download_now.setText(self.download_now_button.text())
        self.download_selected_button.setText("Reverificar SOL selecionado" if sols else "Reverificar observação selecionada")
        self.act_download_selected.setText(self.download_selected_button.text())
        self.download_shell.setVisible(downloads)
        for action in (self.act_download_now, self.act_download_from, self.act_download_selected, self.act_download_panel):
            action.setEnabled(downloads)
        for control in (self.download_now_button, self.download_from_button, self.download_selected_button, self.download_start_sol):
            control.setEnabled(downloads)
        for action in self._source_actions.actions():
            action.setChecked(action.data() == self.source.id)
        self._refresh_mission_selector()
        self.act_mission_archive.setEnabled(bool(self.missions.profiles[self.source.id].get("archive_url")))
        self.download_title.setText(f"<b>{html.escape(self.source.name)}</b><br><small>Download de imagens · {APP_AUTHOR}</small>")
        self.sol_list.setToolTip(f"{self.source.collection_label}: {self.source.name}")
        self.setWindowTitle(f"{APP_NAME} — {self.source.name} — {self.root}")

    def _auto_download_enabled(self) -> bool:
        return bool(self.missions.profiles[self.source.id].get("auto_download", False)) and not self._download_paused

    def _rebuild_mission_menu(self) -> None:
        for action in self._source_actions.actions():
            self._source_actions.removeAction(action)
            action.deleteLater()
        self._mission_menu.clear()
        self._mission_menu.addAction(self.act_mission_settings)
        self._mission_menu.addAction(self.act_mission_archive)
        self._mission_menu.addSeparator()
        bodies = {}
        for profile in sorted(self.missions.profiles.values(), key=lambda p: (p["body"], p["name"])):
            if not profile.get("enabled", True):
                continue
            if profile["body"] not in bodies:
                bodies[profile["body"]] = self._mission_menu.addMenu(profile["body"])
            action = self._make_action(profile["name"], lambda checked=False, key=profile["id"]: self._choose_source(key))
            action.setCheckable(True)
            action.setData(profile["id"])
            self._source_actions.addAction(action)
            bodies[profile["body"]].addAction(action)

    def _refresh_mission_selector(self) -> None:
        if not hasattr(self, "mission_selector"):
            return
        self.mission_selector.blockSignals(True)
        self.mission_selector.clear()
        for profile in sorted(self.missions.profiles.values(), key=lambda p: (p["body"], p["name"])):
            if profile.get("enabled", True):
                self.mission_selector.addItem(f"{profile['body']} — {profile['name']}", profile["id"])
        self.mission_selector.setCurrentIndex(self.mission_selector.findData(self.source.id))
        self.mission_selector.blockSignals(False)

    def _select_mission_from_toolbar(self, index) -> None:
        mission_id = self.mission_selector.itemData(index)
        if mission_id:
            self._choose_source(mission_id)
        self._refresh_mission_selector()

    def _open_mission_archive(self) -> None:
        url = self.missions.profiles[self.source.id].get("archive_url", "")
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def _configure_missions(self) -> None:
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        dialog = MissionSettingsDialog(self.missions, self.source.id, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        was_auto = self._auto_download_enabled()
        self.missions = dialog.registry
        self._rebuild_mission_menu()
        profile = self.missions.profiles.get(self.source.id)
        selected = dialog.open_mission_id or self.source.id
        if profile is None or not profile.get("enabled", True):
            selected = next(p["id"] for p in self.missions.profiles.values() if p.get("enabled", True))
        folder = self.missions.folder_for(selected)
        if selected != self.source.id or (folder is not None and folder.resolve() != self.root):
            self._choose_source(selected)
        else:
            self.source = self.missions.source_for(selected)
            self.download_start_sol.setValue(self.missions.profiles[selected].get("start_sol", 0))
            self._update_source_controls()
            if self.source.supports_downloads and self._auto_download_enabled() and not was_auto:
                QTimer.singleShot(100, self._start_downloader)
        if not self._save_state():
            QMessageBox.warning(self, "Configuração não salva", "Não foi possível gravar as preferências. Verifique a permissão de escrita na pasta do aplicativo.")

    def _activate_mission(self, mission_id: str, folder: Path) -> None:
        self._flush_inline_adjustments()
        previous = self._build_state()
        previous.pop("source_sessions", None)
        previous.pop("mission_config", None)
        self._source_sessions[self.source.id] = previous
        target = dict(self._source_sessions.get(mission_id) or {})
        if target.get("root") and Path(target["root"]).resolve() != folder.resolve():
            target = {}
        target["toolbar_layout"] = previous["toolbar_layout"]
        target["toolbar_text"] = previous["toolbar_text"]
        target["auto_zoom"] = previous["auto_zoom"]
        self._state_ready = False
        self.source = self.missions.source_for(mission_id)
        self.root = folder.resolve()
        self.metadata_client = self.source.create_metadata_client()
        target.setdefault("download", {})
        target["download_start_sol"] = self.missions.profiles[mission_id].get("start_sol", 0)
        self._state = target
        self._last_viewed = (None, None, None)
        self._reveal_restored_path = None
        self._download_paused = bool(target["download"].get("paused", False))
        self._download_user_stop_requested = False
        self._download_pending_resume = bool(target["download"].get("pending_resume", False)) and self.source.supports_downloads
        self.current_sol = None
        self.current_folder = None
        self.current_path = None
        self.original_image = None
        self.download_history.clear()
        self._load_sol_list()
        self._restore_saved_ui_state()
        self._update_source_controls()
        self._state_ready = True
        self._save_state()
        if self.source.supports_downloads and self._auto_download_enabled():
            QTimer.singleShot(100, self._resume_saved_download if self._download_pending_resume else self._start_downloader)

    def _choose_source(self, source_id: str) -> None:
        if self._download_thread is not None and self._download_thread.isRunning():
            for action in self._source_actions.actions():
                action.setChecked(action.data() == self.source.id)
            return
        folder = self.missions.folder_for(source_id)
        if folder is not None and source_id == self.source.id and folder.resolve() == self.root:
            return
        if folder is None:
            selected = QFileDialog.getExistingDirectory(self, f"Pasta da missão — {self.missions.profiles[source_id]['name']}", str(self.root))
            if not selected:
                self._update_source_controls()
                return
            folder = Path(selected)
            self.missions.profiles[source_id]["folder_override"] = str(folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Não foi possível abrir a missão", str(exc))
            self._update_source_controls()
            return
        self._activate_mission(source_id, folder)

    def _choose_root(self) -> None:
        if self._download_thread is not None and self._download_thread.isRunning():
            return
        folder = QFileDialog.getExistingDirectory(self, f"Pasta da missão — {self.source.name}", str(self.root))
        if not folder:
            return
        self.missions.profiles[self.source.id]["folder_override"] = str(Path(folder).resolve())
        self._activate_mission(self.source.id, Path(folder))

    def _load_sol_list(self) -> None:
        self._cancel_sol_annotations()
        self._cancel_image_filters()
        self._filter_results = {}
        previous_folder = self.current_folder
        self._thumb_timer.stop()
        self.sol_list.blockSignals(True)
        self.sol_list.clear()
        sol_folders = self.source.list_collections(self.root)

        selected_row = 0
        for row, (sol, folder) in enumerate(sol_folders):
            label = folder.name if self.source.supports_downloads or folder == self.root else str(folder.relative_to(self.root))
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (sol, str(folder)))
            item.setToolTip(str(folder))
            self.sol_list.addItem(item)
            if previous_folder == folder:
                selected_row = row
        self.sol_list.blockSignals(False)
        self._queue_sol_annotations([str(folder) for _, folder in sol_folders])

        if not sol_folders:
            self.current_sol = None
            self.current_folder = None
            self.current_path = None
            self.current_images = []
            self.original_image = None
            self.processed_qimage = None
            self._clear_annotations()
            self.thumb_list.clear()
            self.image_view.set_pixmap(QPixmap())
            message = "Nenhuma pasta SOLxxxx" if getattr(self.source, "uses_sols", self.source.supports_downloads) else "Nenhuma imagem ou pasta com imagens"
            self.statusBar().showMessage(f"{message} encontrada em {self.root}")
            return

        self.sol_list.setCurrentRow(selected_row)

    def _sol_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        self._flush_inline_adjustments()
        if current is None:
            return
        data = current.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        sol, folder = data
        self.current_sol = int(sol)
        self.current_folder = Path(folder)
        self._cancel_image_filters()
        self._filter_results = {}
        self.filter_scope.blockSignals(True)
        self.filter_scope.setCurrentIndex(0)
        self.filter_scope.blockSignals(False)
        if self._filters_active():
            self._request_image_filter()
            return
        self.filter_count.setText("")
        self.current_images = list_images(self.current_folder)
        if hasattr(self, "main_splitter"):
            self._save_state()

        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()

        for path in self.current_images:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(path.name)
            self.thumb_list.addItem(item)
            self._thumb_queue.append((item, path))
        self.thumb_list.blockSignals(False)

        if self._thumb_queue:
            self._thumb_timer.start(1)

        if self.current_images:
            # During startup, silently skip an unreadable first file instead of
            # showing an error dialog before the main window is ready. A bad file
            # clicked manually later will still show a normal warning.
            first_valid = -1
            for index, path in enumerate(self.current_images):
                if self._load_image(path, show_error=False):
                    first_valid = index
                    break

            if first_valid >= 0:
                self.thumb_list.blockSignals(True)
                self.thumb_list.setCurrentRow(first_valid)
                self.thumb_list.blockSignals(False)
            else:
                self.current_path = None
                self.original_image = None
                self.processed_qimage = None
                self._clear_annotations()
                self.image_view.set_pixmap(QPixmap())
                self.statusBar().showMessage(f"{current.text()}: não foi possível abrir nenhuma imagem")
        else:
            self.current_path = None
            self.original_image = None
            self.processed_qimage = None
            self._clear_annotations()
            self.image_view.set_pixmap(QPixmap())
            self.statusBar().showMessage(f"{current.text()}: nenhuma imagem encontrada")

    def _load_thumb_batch(self) -> None:
        # Load just a few per timer tick so large Sols do not freeze the interface.
        batch = 5
        for _ in range(batch):
            if not self._thumb_queue:
                self._thumb_timer.stop()
                return
            item, path = self._thumb_queue.pop(0)
            self._highlight_thumbnail(item, path)
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(self.thumb_list.iconSize(), Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
            if not image.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _thumb_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        if path:
            if str(path) in self._filter_results:
                self.current_sol, self.current_folder = self._filter_results[str(path)]
                self.sol_list.blockSignals(True)
                for row in range(self.sol_list.count()):
                    if self.sol_list.item(row).data(Qt.ItemDataRole.UserRole)[0] == self.current_sol:
                        self.sol_list.setCurrentRow(row)
                        break
                self.sol_list.blockSignals(False)
            self._load_image(Path(path))
            self._save_state()

    def _load_image(self, path: Path, show_error: bool = True) -> bool:
        self._flush_inline_adjustments()
        keep_zoom = (getattr(self, "_state_ready", False)
                     and self.act_auto_zoom.isChecked() and self.image_view.has_image())
        if self.current_path == path and self.original_image is not None:
            return True
        try:
            with Image.open(path) as src:
                # Force decoding while the source file is still open. Combined with
                # LOAD_TRUNCATED_IMAGES this accepts many otherwise usable raw JPEGs.
                src.load()
                image = ImageOps.exif_transpose(src)
                # Preserve alpha where it exists; otherwise use RGB.
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                self.original_image = image.copy()
        except Exception as exc:
            if show_error:
                QMessageBox.warning(self, "Erro na imagem", f"Não foi possível abrir:\n{path}\n\n{exc}")
            return False

        self.current_path = path
        self._last_viewed = (self.current_sol, self.current_folder, path)
        self._load_annotations(path)
        self._render_current(fit=not keep_zoom)
        return True

    def _render_current(self, fit: bool = False) -> None:
        if self.original_image is None or self.current_path is None:
            return

        self.act_original.setChecked(False)
        state = {key: getattr(self, key) for key in ("color_balance", "smoothing", "contrast", "saturation", "inverted", "black_point", "white_point", "gamma", "sharpness", "brightness")}
        image = apply_adjustments(self.original_image, state)
        self._annotation_base = pil_to_qimage(image)
        self._show_annotations(fit=fit)

        width, height = self.processed_qimage.width(), self.processed_qimage.height()
        sol_text = f"SOL{self.current_sol}" if getattr(self.source, "uses_sols", self.source.supports_downloads) else (self.current_folder.name if self.current_folder else "")
        self.statusBar().showMessage(
            f"{sol_text}  |  {self.current_path.name}  |  {width}×{height}  |  "
            f"Contraste {self.contrast:.1f}  |  Cor {self.saturation:.1f}  |  Rotação {self.rotation % 360}°"
        )

    # ---------- Image operations ----------
    def _adjust_detail(self, kind):
        if self.original_image is None:
            return
        dialog = AdjustmentDialog(self.original_image, self._annotation_document.state, kind, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        keys = ("black_point", "white_point", "gamma") if kind == "levels" else (kind,)
        if all(getattr(self, key) == dialog.state[key] for key in keys):
            return
        for key in keys:
            setattr(self, key, dialog.state[key])
        self._render_current(fit=False)
        self._commit_adjustments()

    def _display_image_version(self, fit=False):
        image = self.processed_qimage
        if self.act_original.isChecked() and self.original_image is not None:
            image = composite_image(pil_to_qimage(self.original_image), [], self.rotation)
        if image is not None:
            self.image_view.set_pixmap(QPixmap.fromImage(image), fit=fit)

    def _toggle_original(self):
        self._flush_inline_adjustments()
        if self.original_image is None:
            self.act_original.setChecked(False)
            return
        enabled = self.act_original.isChecked()
        self._reset_drawing_tool()
        self.act_original.setChecked(enabled)
        self._display_image_version()
        self.statusBar().showMessage("Original — sem ajustes ou marcações (Ctrl+Shift+O para voltar)" if enabled else "Imagem com ajustes e marcações")

    def _smooth_image(self):
        if self.original_image is None:
            return
        dialog = SmoothingDialog(self.original_image, self.smoothing, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        strength = dialog.intensity.value()
        if strength == self.smoothing:
            return
        self.smoothing = strength
        self._render_current(fit=False)
        self._commit_adjustments()

    def _toggle_color_balance(self) -> None:
        self._flush_inline_adjustments()
        if self.original_image is None or self._annotation_document is None:
            self.act_balance.setChecked(False)
            return
        self.color_balance = not self.color_balance
        self._render_current(fit=False)
        self._commit_adjustments()

    def _toggle_invert(self) -> None:
        if self.original_image is None:
            self.act_invert.setChecked(False)
            return
        self.inverted = not self.inverted
        self._render_current(fit=False)
        self._commit_adjustments()

    def _adjust_contrast(self, delta: float) -> None:
        if self.original_image is None:
            return
        self.contrast = min(3.0, max(0.0, round(self.contrast + delta, 2)))
        self._render_current(fit=False)
        self._commit_adjustments()

    def _adjust_saturation(self, delta: float) -> None:
        if self.original_image is None:
            return
        self.saturation = min(3.0, max(0.0, round(self.saturation + delta, 2)))
        self._render_current(fit=False)
        self._commit_adjustments()

    def _rotate(self, degrees: int) -> None:
        if self.original_image is None:
            return
        self.rotation = (self.rotation + degrees) % 360
        self._clear_region()
        self._render_current(fit=True)
        self._commit_adjustments()

    def _reset_adjustments(self) -> None:
        self._flush_inline_adjustments()
        if self.original_image is None:
            return
        self.contrast = 1.0
        self.saturation = 1.0
        self.rotation = 0
        self.inverted = False
        self.smoothing = 0
        self.color_balance = False
        self.black_point, self.white_point, self.gamma, self.sharpness = 0, 255, 1.0, 0
        self.brightness = 100
        self._clear_region()
        self._render_current(fit=True)
        self._commit_adjustments()

    def _copy_image(self) -> None:
        if self.original_image is None or self.processed_qimage is None:
            return
        QApplication.clipboard().setImage(self.processed_qimage)
        self.statusBar().showMessage("Imagem copiada para o clipboard", 2500)

    def _open_in_gimp(self) -> None:
        if self.current_path is None:
            return
        gimp = find_gimp()
        if not gimp:
            QMessageBox.warning(
                self,
                "GIMP não encontrado",
                "O GIMP não foi encontrado neste computador.\n\n"
                "O Planetary Image Studio procurou no PATH, nas pastas padrão do Windows "
                "e nas informações de instalação do Registro.",
            )
            return
        try:
            kwargs: dict[str, Any] = {}
            if sys.platform.startswith("win"):
                # Do not open an extra console window when launching GIMP on Windows.
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([gimp, str(self.current_path)], **kwargs)
            self.statusBar().showMessage(f"Abrindo no GIMP: {self.current_path.name}", 2500)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Erro ao abrir GIMP",
                f"Encontrei o GIMP em:\n{gimp}\n\nMas não consegui abrir a imagem.\n\n{exc}",
            )

    def _show_image_context_menu(self, global_pos) -> None:
        if self.current_path is None:
            return
        menu = QMenu(self)
        menu.addAction(self.act_levels)
        menu.addAction(self.act_sharpen)
        menu.addAction(self.act_brightness)
        menu.addAction(self.act_smooth)
        menu.addSeparator()
        menu.addAction(self.act_contrast_up)
        menu.addAction(self.act_contrast_down)
        menu.addAction(self.act_color_up)
        menu.addAction(self.act_color_down)
        menu.addAction(self.act_invert)
        menu.addSeparator()
        menu.addAction(self.act_rotate_left)
        menu.addAction(self.act_rotate_right)
        menu.addAction(self.act_reset_image)
        menu.addAction(self.act_original)
        menu.addSeparator()
        menu.addAction(self.act_copy)
        menu.addAction(self.act_gimp)
        menu.addSeparator()
        menu.addAction(self.act_about_image)
        menu.exec(global_pos)

    def _about_current_image(self) -> None:
        if self.current_path is None or self.current_sol is None:
            return
        self.statusBar().showMessage("Consultando informações da imagem na NASA...")
        worker = MetadataWorker(self.metadata_client, self.current_path.name, self.current_sol)
        self._metadata_workers.append(worker)

        def done(info: dict[str, Any]) -> None:
            if worker in self._metadata_workers:
                self._metadata_workers.remove(worker)
            if self._closing:
                return
            self.statusBar().showMessage("Informações recebidas da NASA", 2500)
            dialog = ImageAboutDialog(info, self)
            dialog.exec()

        def failed(message: str) -> None:
            if worker in self._metadata_workers:
                self._metadata_workers.remove(worker)
            if self._closing:
                return
            self.statusBar().showMessage("Falha ao consultar a NASA", 2500)
            QMessageBox.warning(self, "About image", message)

        worker.signals.finished.connect(done)
        worker.signals.error.connect(failed)
        self.thread_pool.start(worker)

    def _previous_image(self) -> None:
        row = self.thumb_list.currentRow()
        if row > 0:
            self.thumb_list.setCurrentRow(row - 1)

    def _next_image(self) -> None:
        row = self.thumb_list.currentRow()
        if 0 <= row < self.thumb_list.count() - 1:
            self.thumb_list.setCurrentRow(row + 1)

    def _about_app(self) -> None:
        QMessageBox.about(
            self,
            f"Sobre {APP_NAME}",
            f"<b>{APP_NAME} {APP_VERSION}</b><br>"
            f"<b>Desenvolvido por {APP_AUTHOR}</b><br><br>"
            "Visualização, ajustes e marcações para imagens de planetas e luas.<br>"
            "Fontes: Curiosity (Marte) e coleções locais (Lua e outros).<br><br>"
            "Zoom: roda do mouse sobre a imagem<br>"
            "Pan da imagem: botão esquerdo + arrastar<br>"
            "Thumbnails: segure e arraste para a esquerda/direita<br>"
            "Menu da imagem: botão direito<br><br>"
            "Downloader NASA integrado: atualização automática em segundo plano, "
            "painel retrátil, retomada automática e reverificação desde qualquer SOL.<br><br>"
            "Metadados e imagens: NASA Mars Exploration / Mars Science Laboratory.",
        )

    def _background_tasks_running(self):
        thread = self._download_thread
        return bool((thread is not None and thread.isRunning())
                    or self.thread_pool.activeThreadCount()
                    or self._filter_pool.activeThreadCount())

    def _finish_shutdown(self):
        if self._background_tasks_running():
            return
        self._shutdown_timer.stop()
        self._metadata_workers.clear()
        self._filter_jobs.clear()
        self._sol_summary_jobs.clear()
        session = getattr(self.metadata_client, "session", None)
        if session is not None:
            session.close()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._closing:
            self._flush_inline_adjustments()
            if not self._confirm_annotation_close():
                event.ignore()
                return
            self._closing = True
            worker, thread = self._download_worker, self._download_thread
            running = thread is not None and thread.isRunning()
            self._shutdown_pending_resume = bool(running or self._download_pending_resume)
            self._save_state(pending_resume=self._shutdown_pending_resume)
            # Discard queued work before cancellation lets running jobs finish
            # and immediately pick up another queued task.
            self.thread_pool.clear()
            self._filter_pool.clear()
            self._cancel_image_filters()
            self._cancel_sol_annotations()
            self._thumb_timer.stop()
            self._thumb_resize_timer.stop()
            self._inline_timer.stop()
            self._thumb_queue.clear()
            self._download_restart_pending = False
            for metadata in self._metadata_workers:
                metadata.cancel.set()
                session = getattr(metadata.client, 'session', None)
                if hasattr(session, 'cancel'):
                    session.cancel()
            if worker is not None:
                worker.stop()
            if running:
                thread.requestInterruption()
                thread.quit()
        if self._background_tasks_running():
            event.ignore()
            self.statusBar().showMessage("Encerrando tarefas em segundo plano?")
            self.setEnabled(False)
            self._shutdown_timer.start()
            return
        self._shutdown_timer.stop()
        super().closeEvent(event)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "root",
        nargs="?",
        help="Pasta da coleção. Usa a sessão salva ou a pasta pai do projeto quando omitida.",
    )
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--source", choices=tuple(SOURCES), help="Compatibilidade: curiosity ou local.")
    choice.add_argument("--mission", help="Identificador da missão cadastrada, por exemplo perseverance.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    saved_state = load_app_state()
    registry = MissionRegistry(saved_state)
    requested = args.mission or args.source or saved_state.get("active_mission_id") or saved_state.get("source", "curiosity")
    if requested not in registry.profiles:
        raise SystemExit("Missão desconhecida. Cadastre-a em Missões > Configurar planetas e missões.")
    if requested != saved_state.get("source", "curiosity"):
        sessions = dict(saved_state.get("source_sessions") or {})
        previous = dict(saved_state)
        previous.pop("source_sessions", None)
        previous.pop("mission_config", None)
        sessions[saved_state.get("source", "curiosity")] = previous
        saved_state = dict(sessions.get(requested, {}))
        saved_state.update(source=requested, active_mission_id=requested, source_sessions=sessions)
    if args.root:
        root = Path(args.root).expanduser().resolve()
        registry.profiles[requested]["folder_override"] = str(root)
    else:
        root = registry.folder_for(requested)
        if root is None:
            root = Path(saved_state["root"]).expanduser() if saved_state.get("root") else PROJECT_ROOT.parent
    saved_state["mission_config"] = registry.serialize()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    window = MainWindow(root, initial_state=saved_state, source=requested)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
