"""Read SOL annotation summaries without blocking the GUI thread."""
import json
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QBrush, QColor, QPalette, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle

from planetary_studio.collections.catalog import SUPPORTED_EXTENSIONS


class AnnotationThumbnailDelegate(QStyledItemDelegate):
    """Highlight only the filename of annotated images."""
    def sizeHint(self, option, index):
        return super().sizeHint(option, index) + QSize(10, 10)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        marked = opt.backgroundBrush.color() == QColor('#f4d878') and opt.backgroundBrush.style() != Qt.BrushStyle.NoBrush
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if marked:
            # Native selection and stylesheets otherwise cover BackgroundRole.
            opt.state &= ~QStyle.StateFlag.State_Selected
            opt.state &= ~QStyle.StateFlag.State_MouseOver
            opt.palette.setColor(QPalette.ColorRole.Text, QColor('#302600'))
            opt.backgroundBrush = QBrush()
        opt.rect = opt.rect.adjusted(5, 5, -5, -5)
        style = option.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)
        if marked:
            text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, option.widget)
            painter.save()
            painter.setClipRect(opt.rect)
            painter.fillRect(text_rect, QColor('#f4d878'))
            painter.setPen(QColor('#302600'))
            painter.setFont(opt.font)
            text = opt.fontMetrics.elidedText(opt.text, opt.textElideMode, max(0, text_rect.width() - 4))
            painter.drawText(text_rect.adjusted(2, 0, -2, 0), Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
        if selected:
            painter.save()
            painter.setPen(QPen(option.palette.color(QPalette.ColorRole.Highlight), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(option.rect.adjusted(2, 2, -2, -2), 4, 4)
            painter.restore()


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def folder_marked(folder, overrides, cancel, marked_paths=None):
    marked_paths = marked_paths if marked_paths is not None else set()
    folder_key = path_key(folder)
    marked_paths.update(key for key, marked in overrides.items()
                        if marked and os.path.dirname(key) == folder_key)
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if cancel.is_set():
                    return bool(marked_paths)
                if not entry.name.endswith('.annotations.json'):
                    continue
                image = Path(entry.path[:-len('.annotations.json')])
                if image.suffix.lower() not in SUPPORTED_EXTENSIONS or not image.is_file():
                    continue
                key = path_key(image)
                if key in overrides:
                    continue
                try:
                    data = json.loads(Path(entry.path).read_text(encoding='utf-8'))
                    if data.get('state', {}).get('drawings'):
                        marked_paths.add(key)
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
    except OSError:
        pass
    return bool(marked_paths)


class SummarySignals(QObject):
    result = Signal(int, str, int, bool)
    images = Signal(int, str, int, object)
    done = Signal(int)


class SummaryJob(QRunnable):
    def __init__(self, token, folders, overrides):
        super().__init__()
        self.token, self.folders, self.overrides = token, folders, overrides
        self.cancel = threading.Event()
        self.signals = SummarySignals()

    def run(self):
        try:
            for folder, revision in self.folders:
                if self.cancel.is_set():
                    break
                marked_paths = set()
                marked = folder_marked(folder, self.overrides, self.cancel, marked_paths)
                if not self.cancel.is_set():
                    self.signals.result.emit(self.token, folder, revision, marked)
                    self.signals.images.emit(self.token, folder, revision, marked_paths)
        finally:
            self.signals.done.emit(self.token)


class SolAnnotationsMixin:
    def _init_sol_annotations(self):
        self._marked_images_by_folder = {}
        self._sol_summary_token = 0
        self._sol_summary_jobs = {}
        self._sol_summary_revisions = {}
        self._sol_summary_items = {}
        self._sol_summary_timer = QTimer(self)
        self._sol_summary_timer.setInterval(5000)
        self._sol_summary_timer.timeout.connect(self._poll_sol_annotations)
        self._sol_summary_timer.start()

    def _poll_sol_annotations(self):
        # Let a slow scan finish instead of accumulating periodic work.
        if self._closing or self._sol_summary_jobs:
            return
        folders = [self.sol_list.item(row).data(Qt.ItemDataRole.UserRole)[1]
                   for row in range(self.sol_list.count())]
        self._queue_sol_annotations(folders)

    def _cancel_sol_annotations(self):
        if self._closing:
            self._sol_summary_timer.stop()
        for job in self._sol_summary_jobs.values():
            job.cancel.set()
        self._marked_images_by_folder.clear()
        self._sol_summary_revisions.clear()
        self._sol_summary_items.clear()

    def _queue_sol_annotations(self, folders):
        if not folders or self._closing:
            return
        for row in range(self.sol_list.count()):
            item = self.sol_list.item(row)
            self._sol_summary_items[item.data(Qt.ItemDataRole.UserRole)[1]] = item
        overrides = {path_key(key): bool(doc.state.get('drawings'))
                     for key, doc in self._annotation_documents.items()}
        if self.current_path is not None and self._annotation_document is not None:
            overrides[path_key(self.current_path)] = bool(self._annotation_document.state.get('drawings'))
        self._sol_summary_token += 1
        token = self._sol_summary_token
        for folder in folders:
            self._sol_summary_revisions[folder] = token
        job = SummaryJob(token, [(folder, token) for folder in folders], overrides)
        self._sol_summary_jobs[token] = job
        job.signals.result.connect(self._sol_annotation_result)
        job.signals.images.connect(self._thumbnail_annotation_result)
        job.signals.done.connect(self._sol_annotation_done)
        self.thread_pool.start(job)

    def _sol_annotation_done(self, token):
        self._sol_summary_jobs.pop(token, None)

    def _sol_annotation_result(self, token, folder, revision, marked):
        if self._closing or self._sol_summary_revisions.get(folder) != revision:
            return
        item = self._sol_summary_items.get(folder)
        if item is None:
            return
        item.setBackground(QBrush(QColor('#f4d878')) if marked else QBrush())
        item.setForeground(QBrush(QColor('#302600')) if marked else QBrush())
        item.setToolTip(folder + ('\nContém imagem com marcações' if marked else ''))

    def _update_sol_annotation_highlight(self, item):
        self._queue_sol_annotations([item.data(Qt.ItemDataRole.UserRole)[1]])

    def _refresh_sol_annotation_highlight(self):
        if self.current_path is not None:
            for row in range(self.thumb_list.count()):
                item = self.thumb_list.item(row)
                path = item.data(Qt.ItemDataRole.UserRole)
                if path and path_key(path) == path_key(self.current_path):
                    self._highlight_thumbnail(item, path)
            self._queue_sol_annotations([str(self.current_path.parent)])

    def _thumbnail_annotation_result(self, token, folder, revision, marked_paths):
        if self._closing or self._sol_summary_revisions.get(folder) != revision:
            return
        folder_key = path_key(folder)
        self._marked_images_by_folder[folder_key] = marked_paths
        for row in range(self.thumb_list.count()):
            item = self.thumb_list.item(row)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and path_key(Path(path).parent) == folder_key:
                self._highlight_thumbnail(item, path)

    def _highlight_thumbnail(self, item, path):
        key = path_key(path)
        marked = key in self._marked_images_by_folder.get(path_key(Path(path).parent), set())
        if self.current_path is not None and key == path_key(self.current_path) and self._annotation_document is not None:
            marked = bool(self._annotation_document.state.get('drawings'))
        item.setBackground(QBrush(QColor('#f4d878')) if marked else QBrush())
        item.setForeground(QBrush(QColor('#302600')) if marked else QBrush())
