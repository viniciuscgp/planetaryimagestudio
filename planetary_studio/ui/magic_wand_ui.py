"""Preview a connected selection and commit it through existing annotations."""
import numpy as np
import cv2
from PySide6.QtCore import Qt,QThread,Signal,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QSlider,QSpinBox,
    QComboBox,QCheckBox,QPushButton)
from planetary_studio.ui.forensic_texture_ui import TextureView
from planetary_studio.processing.magic_wand import select_connected,mask_to_annotation


class WandWorker(QThread):
    completed = Signal(int,object)
    failed = Signal(int,str)

    def __init__(self,image,seed,tolerance,luminosity,connectivity,token,parent):
        super().__init__(parent)
        self.image,self.seed,self.tolerance = image,seed,tolerance
        self.luminosity,self.connectivity,self.token = luminosity,connectivity,token

    def run(self):
        try:
            self.completed.emit(self.token,select_connected(self.image,self.seed,self.tolerance,
                                                            self.luminosity,self.connectivity))
        except Exception as exc:
            self.failed.emit(self.token,str(exc))


class MagicWandDialog(QDialog):
    def __init__(self,image,rotation=0,parent=None):
        super().__init__(parent)
        self.image = np.array(image.convert('RGB'),copy=True)
        self.rotation = rotation
        self.seed = None
        self.mask = None
        self.annotation = None
        self.worker = None
        self.token = 0
        self.running_token = None
        self._closing = False
        self.setWindowTitle('Varinha mágica · Selecionar por semelhança')
        self.resize(1050,750)
        layout = QVBoxLayout(self)
        notice = QLabel('Clique dentro da figura e ajuste a tolerância. Azul = seleção conectada ao ponto clicado. '
                        'Tolerância maior aceita mais variação; não há reconhecimento de objetos ou IA.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        row.addWidget(QLabel('Tolerância (0–255):'))
        self.tolerance = QSlider(Qt.Orientation.Horizontal)
        self.tolerance.setRange(0,255)
        self.tolerance.setValue(20)
        self.value = QSpinBox()
        self.value.setRange(0,255)
        self.value.setValue(20)
        self.tolerance.valueChanged.connect(self.value.setValue)
        self.value.valueChanged.connect(self.tolerance.setValue)
        self.tolerance.valueChanged.connect(self.request_selection)
        row.addWidget(self.tolerance,1)
        row.addWidget(self.value)
        self.mode = QComboBox()
        self.mode.addItems(['Cor RGB','Luminosidade'])
        self.mode.currentIndexChanged.connect(self.request_selection)
        row.addWidget(self.mode)
        self.diagonals = QCheckBox('Conectar diagonais')
        self.diagonals.toggled.connect(self.request_selection)
        row.addWidget(self.diagonals)
        layout.addLayout(row)
        self.status = QLabel('Clique na imagem para começar.')
        layout.addWidget(self.status)
        self.view = TextureView()
        self.view.clicked.connect(self.click_image)
        layout.addWidget(self.view,1)
        row = QHBoxLayout()
        self.preview = QCheckBox('Mostrar seleção')
        self.preview.setChecked(True)
        self.preview.toggled.connect(self.refresh)
        row.addWidget(self.preview)
        fit = QPushButton('Ajustar imagem')
        fit.clicked.connect(lambda:self.view.fitInView(self.view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio))
        row.addWidget(fit)
        row.addStretch()
        self.apply_button = QPushButton('Criar marcação')
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_selection)
        row.addWidget(self.apply_button)
        cancel = QPushButton('Cancelar')
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.start_selection)
        self.refresh()

    def showEvent(self,event):
        super().showEvent(event)
        self.view.fitInView(self.view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)

    def click_image(self,x,y):
        height,width = self.image.shape[:2]
        if self.rotation == 90:
            x,y = y,height-1-x
        elif self.rotation == 180:
            x,y = width-1-x,height-1-y
        elif self.rotation == 270:
            x,y = width-1-y,x
        self.seed = (x,y)
        self.request_selection()

    def request_selection(self,*args):
        if self.seed is None or self._closing:
            return
        self.token += 1
        self.mask = None
        self.annotation = None
        self.apply_button.setEnabled(False)
        self.status.setText('Calculando seleção…')
        self.refresh()
        self.timer.start(100)

    def start_selection(self):
        if self.worker is not None or self.seed is None or self._closing:
            return
        self.running_token = self.token
        self.worker = WandWorker(self.image,self.seed,self.tolerance.value(),self.mode.currentIndex()==1,
                                 8 if self.diagonals.isChecked() else 4,self.token,self)
        self.worker.completed.connect(self.selection_done)
        self.worker.failed.connect(self.selection_failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def selection_done(self,token,mask):
        if token != self.token or self._closing:
            return
        self.mask = mask
        area = int(mask.sum())
        self.status.setText(f'Ponto original: X={self.seed[0]} Y={self.seed[1]} · {area} pixels · '
                            f'{100*area/mask.size:.1f}% da imagem. A marcação preserva os vazios internos.')
        try:
            self.annotation = mask_to_annotation(mask)
        except ValueError as exc:
            self.status.setText(str(exc))
        self.refresh()

    def selection_failed(self,token,message):
        if token == self.token and not self._closing:
            self.status.setText(message)

    def worker_finished(self):
        stale = self.running_token != self.token
        self.worker.deleteLater()
        self.worker = None
        self.apply_button.setEnabled(not stale and self.annotation is not None and not self._closing)
        if self._closing:
            super().reject()
        elif stale:
            self.timer.start(0)

    def refresh(self,*args):
        output = self.image.copy()
        if self.mask is not None and self.preview.isChecked():
            selected = self.mask != 0
            output[selected] = np.uint8(output[selected]*.45+np.array([0,200,255])*.55)
            contours,_ = cv2.findContours(self.mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(output,contours,-1,(255,255,255),1)
        if self.rotation:
            output = np.rot90(output,-self.rotation//90).copy()
        self.view.display(output)

    def apply_selection(self):
        if self.annotation is not None and self.worker is None:
            self.timer.stop()
            self.accept()

    def reject(self):
        self._closing = True
        self.timer.stop()
        if self.worker is None:
            super().reject()

    def closeEvent(self,event):
        self._closing = True
        self.timer.stop()
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
