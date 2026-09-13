"""Vector toolbar icons and persistent button label preference."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QToolBar, QStyle


SHAPES = {
    'pan': '<path d="M8 12V6a2 2 0 0 1 4 0v5-7a2 2 0 0 1 4 0v7-5a2 2 0 0 1 4 0v10l-4 6H9l-6-8q0-3 3-1l2 2"/>',
    'pencil': '<path d="m4 16 12-12 4 4L8 20l-5 1zM13 7l4 4"/>',
    'ellipse': '<ellipse cx="12" cy="12" rx="9" ry="6"/>',
    'rectangle': '<rect x="3" y="5" width="18" height="14" rx="1"/>',
    'text': '<path d="M4 6V3h16v3M12 3v18M8 21h8"/>',
    'select': '<path d="m5 3 14 10-7 1-3 7z"/>',
    'wand': '<path d="m3 19 11-11 3 3L6 22zM11 11l3 3M17 2v4m-2-2h4M21 9v4m-2-2h4M7 3v4M5 5h4"/>',
    'region': '<rect x="3" y="3" width="18" height="18" stroke-dasharray="3 3"/>',
    'fit': '<path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6"/><rect x="7" y="7" width="10" height="10"/>',
    'actual': '<path d="m4 8 3-3v14m10-11 3-3v14M11 9h1m-1 6h1"/>',
    'original': '<rect x="3" y="4" width="18" height="16"/><path d="M12 4v16M4 17l5-5 3 3m1-4 3-3 4 5"/>',
    'left': '<path d="M4 10a8 8 0 1 1 1 8M4 3v7h7"/>',
    'right': '<path d="M20 10a8 8 0 1 0-1 8M20 3v7h-7"/>',
    'invert': '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/>',
    'balance': '<path d="M12 3v18M5 21h14M3 7h18M6 7l-4 8h8zm12 0-4 8h8z"/>',
    'copy': '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    'clear': '<rect x="3" y="3" width="18" height="18" stroke-dasharray="3 3"/><path d="m8 8 8 8m0-8-8 8"/>',
    'color': '<circle cx="8" cy="9" r="5" fill="#e57373"/><circle cx="16" cy="9" r="5" fill="#81c784"/><circle cx="12" cy="16" r="5" fill="#64b5f6"/>',
}


def toolbar_icon(kind, color):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" color="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{SHAPES[kind]}</g></svg>'
    icon = QIcon()
    for size in (24, 48, 72):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class ToolbarAppearanceMixin:
    def _init_toolbar_appearance(self):
        color = self.palette().windowText().color().name()
        self._toolbar_icons = {key: toolbar_icon(key, color) for key in SHAPES}
        custom = {'fit': 'fit', 'actual': 'actual', 'auto_zoom': 'fit', 'original': 'original',
                  'percentile_stretch': 'balance',
                  'auto_enhance_mars': 'color',
                  'rotate_left': 'left', 'rotate_right': 'right', 'reset_image': 'left',
                  'invert': 'invert', 'balance': 'balance', 'copy': 'copy', 'forensic_texture': 'region', 'morphological': 'ellipse', 'magic_wand': 'wand',
                  'undo_annotation': 'left', 'redo_annotation': 'right',
                  'edit_annotation_text': 'text', 'copy_region': 'copy', 'clear_region': 'clear'}
        for name, kind in custom.items():
            getattr(self, 'act_' + name).setIcon(self._toolbar_icons[kind])
        standard = {'open_root': 'SP_DirOpenIcon', 'mission_settings': 'SP_FileDialogDetailedView',
                    'delete_annotation': 'SP_TrashIcon', 'export_region': 'SP_DialogSaveButton'}
        for name, kind in standard.items():
            getattr(self, 'act_' + name).setIcon(self.style().standardIcon(getattr(QStyle.StandardPixmap, kind)))
        for action in self._drawing_tools.actions():
            action.setIcon(self._toolbar_icons[action.data()])
        self.stroke_color.setIcon(self._toolbar_icons['color'])
        for bar in self.findChildren(QToolBar):
            for action in bar.actions():
                shortcut = action.shortcut().toString()
                if shortcut:
                    action.setToolTip(f'{action.toolTip()} ({shortcut})')
        self.act_toolbar_text.setChecked(bool(self._state.get('toolbar_text', True)))
        self._set_toolbar_text(self.act_toolbar_text.isChecked())

    def _set_toolbar_text(self, visible):
        style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon if visible else Qt.ToolButtonStyle.ToolButtonIconOnly
        for bar in self.findChildren(QToolBar):
            bar.setToolButtonStyle(style)
        if hasattr(self, 'stroke_color'):
            self.stroke_color.setText('Cor' if visible else '')
        if getattr(self, '_state_ready', False):
            self._save_state()
