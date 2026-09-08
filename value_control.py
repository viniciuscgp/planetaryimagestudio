"""Slider, numeric input and tenths-of-maximum presets for image adjustments."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QSlider,QPushButton,QDoubleSpinBox

class ValueControl(QWidget):
    def __init__(self,spin,maximum,default,parent=None):
        super().__init__(parent)
        self.spin,self.maximum,self.default=spin,maximum,default
        self.factor=100 if isinstance(spin,QDoubleSpinBox) else 1
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        row=QHBoxLayout();layout.addLayout(row)
        self.slider=QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimumWidth(260);self.slider.setMinimumHeight(28)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(max(1,round(maximum*self.factor/10)))
        self.slider.setPageStep(max(1,round(maximum*self.factor/10)))
        self.slider.setSingleStep(round(spin.singleStep()*self.factor))
        self.slider.setTracking(False)
        self.slider.setToolTip('Arraste e solte para ajustar; use os botões abaixo para saltos de 10% do máximo.')
        self.slider.setStyleSheet('QSlider::groove:horizontal { height: 6px; background: palette(mid); border-radius: 3px; } QSlider::handle:horizontal { background: palette(highlight); width: 20px; margin: -7px 0; border-radius: 10px; } QSlider::sub-page:horizontal { background: palette(highlight); border-radius: 3px; }')
        spin.setMinimumWidth(90);spin.setMinimumHeight(30);spin.setKeyboardTracking(False)
        row.addWidget(self.slider,1);row.addWidget(spin)
        presets=QHBoxLayout();presets.setSpacing(3);layout.addLayout(presets)
        self.presets={}
        for percent in range(10,101,10):
            button=QPushButton(f'{percent}%');button.setMinimumHeight(27);button.setMinimumWidth(42);button.setAutoDefault(False)
            value=round(maximum*percent/100,2) if self.factor==100 else int(maximum*percent/100+0.5)
            button.setToolTip(f'{percent}% do máximo ({maximum:g}) = {value:g}')
            button.clicked.connect(lambda checked=False,target=value:self.spin.setValue(target))
            self.presets[percent]=(button,value);presets.addWidget(button)
        self.reset=QPushButton('Padrão');self.reset.setAutoDefault(False);self.reset.setMinimumHeight(27)
        self.reset.setToolTip(f'Restaurar valor neutro: {default:g}')
        self.reset.clicked.connect(lambda:self.spin.setValue(default));presets.addWidget(self.reset)
        self.slider.valueChanged.connect(lambda value:self.spin.setValue(value/self.factor if self.factor==100 else value))
        spin.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self,*args):
        self.slider.blockSignals(True)
        self.slider.setRange(round(self.spin.minimum()*self.factor),round(self.spin.maximum()*self.factor))
        self.slider.setValue(round(self.spin.value()*self.factor))
        self.slider.blockSignals(False)
        for button,value in self.presets.values():
            button.setEnabled(self.spin.minimum()<=value<=self.spin.maximum())
        self.reset.setEnabled(self.spin.minimum()<=self.default<=self.spin.maximum())