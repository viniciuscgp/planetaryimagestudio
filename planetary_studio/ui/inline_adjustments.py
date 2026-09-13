"""Compact toolbar controls that adjust the main image in place."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QToolBar, QWidget, QHBoxLayout, QLabel, QSlider, QDoubleSpinBox, QPushButton, QSizePolicy


FIELDS = (
    ('brightness', 'Brilho', 0, 200, 100, 1),
    ('contrast', 'Contraste', 0, 3, 1, 100),
    ('saturation', 'Cor', 0, 3, 1, 100),
    ('gamma', 'Meios-tons', .1, 5, 1, 100),
    ('black_point', 'Preto', 0, 254, 0, 1),
    ('white_point', 'Branco', 1, 255, 255, 1),
    ('sharpness', 'Nitidez', 0, 300, 0, 1),
    ('smoothing', 'Suavizar', 0, 100, 0, 1),
    ('percentile_low', 'Percentil inferior', 0, 99.99, 1, 100),
    ('percentile_high', 'Percentil superior', .01, 100, 99, 100),
)


class InlineAdjustmentsMixin:
    def _build_inline_adjustments(self):
        self._inline_controls = {}
        self._inline_pending = {}
        self._inline_timer = QTimer(self)
        self._inline_timer.setSingleShot(True)
        self._inline_timer.timeout.connect(self._flush_inline_adjustments)
        for i, (key, label, low, high, default, factor) in enumerate(FIELDS):
            if i % 4 == 0:
                self.addToolBarBreak()
                toolbar = QToolBar('Ajustes' if i == 0 else 'Percentis' if i == 8 else 'Detalhes', self)
                toolbar.setObjectName(f'inline_adjustments_{i}')
                self.addToolBar(toolbar)
                if i == 8:
                    toolbar.addAction(self.act_percentile_stretch)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.setSpacing(4)
            layout.addWidget(QLabel(label))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(round(low * factor), round(high * factor))
            slider.setSingleStep(2)
            slider.setFixedWidth(90)
            spin = QDoubleSpinBox()
            spin.setDecimals(2 if factor == 100 else 0)
            spin.setRange(low, high)
            spin.setSingleStep(2 / factor)
            spin.setKeyboardTracking(False)
            # Let Qt reserve space for the full value and the current theme's
            # arrow buttons, including font/display scaling on Windows.
            spin.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            reset = QPushButton('↺')
            reset.setFixedWidth(24)
            reset.setToolTip(f'Restaurar {label.lower()}: {default}')
            for control in (slider, spin, reset):
                layout.addWidget(control)
            toolbar.addWidget(widget)
            self._inline_controls[key] = (slider, spin, widget, toolbar, factor)
            slider.valueChanged.connect(lambda value, k=key, f=factor: self._inline_changed(k, value / f))
            spin.valueChanged.connect(lambda value, k=key: self._inline_changed(k, value))
            reset.clicked.connect(lambda checked=False, k=key, value=default: self._inline_changed(k, value))
        self._sync_inline_adjustments()

    def _inline_changed(self, key, value):
        if self.original_image is None:
            return
        factor = self._inline_controls[key][4]
        value = round(value, 2) if factor == 100 else round(value)
        if key == 'black_point':
            value = min(value, self._inline_pending.get('white_point', self.white_point) - 1)
        elif key == 'white_point':
            value = max(value, self._inline_pending.get('black_point', self.black_point) + 1)
        elif key == 'percentile_low':
            value = min(value, self._inline_pending.get('percentile_high', self.percentile_high) - .01)
        elif key == 'percentile_high':
            value = max(value, self._inline_pending.get('percentile_low', self.percentile_low) + .01)
        if key.startswith('percentile_'):
            self._inline_pending['percentile_stretch'] = True
        self._inline_pending[key] = value
        self._sync_inline_adjustments()
        # Coalesce drag events without postponing updates until release.
        if not self._inline_timer.isActive():
            self._inline_timer.start(60)

    def _flush_inline_adjustments(self):
        if not getattr(self, '_inline_pending', None):
            return
        self._inline_timer.stop()
        pending, self._inline_pending = self._inline_pending, {}
        if self.original_image is None or self._annotation_document is None:
            return
        for key, value in pending.items():
            setattr(self, key, value)
        self._render_current(fit=False)
        self._commit_adjustments()

    def _sync_inline_adjustments(self):
        self.act_auto_enhance_mars.setChecked(self.auto_enhance_mars)
        self.act_percentile_stretch.setChecked(self.percentile_stretch)
        for key, (slider, spin, widget, toolbar, factor) in getattr(self, '_inline_controls', {}).items():
            widget.setEnabled(self.original_image is not None and self._annotation_document is not None)
            value = self._inline_pending.get(key, getattr(self, key))
            for control in (slider, spin):
                control.blockSignals(True)
                control.setValue(round(value * factor) if control is slider else value)
                control.blockSignals(False)
        self._sync_adjustment_profiles()

    def _focus_inline_adjustment(self, key):
        slider, spin, widget, toolbar, factor = self._inline_controls[key]
        toolbar.show()
        slider.setFocus()
