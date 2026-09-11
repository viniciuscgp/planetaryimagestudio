"""Reuse existing annotation geometry to supply an explicit analysis mask."""
import copy
import threading
import html

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,
    QPushButton,QTextBrowser,QSplitter,QWidget,QComboBox)

from annotation_editing import drawing_shape, image_transform
from forensic_texture_ui import TextureView
from morphological_region_analyzer import MorphologicalRegionAnalyzer, contours


LAYER_NAMES = {
    'external': ('Contorno externo estimado',(255,220,0)),
    'edges': ('Bordas internas',(0,255,255)),
    'fissures': ('Fissuras candidatas',(255,60,70)),
    'cavities': ('Cavidades / regiões escuras',(90,130,255)),
    'axis': ('Eixo principal',(255,255,255)),
    'concavities': ('Concavidades',(255,0,255)),
    'protrusions': ('Saliências candidatas',(255,150,20)),
    'structures': ('Estruturas / divisões internas',(70,255,80)),
}


def annotation_mask(drawing, size):
    """Use the same QPainterPath as annotation selection; fill its interior."""
    if drawing.get('kind') not in ('circle','ellipse','rectangle','pencil','polygon'):
        return None
    if drawing['kind'] == 'pencil' and len(drawing.get('points',[])) < 3:
        return None
    path = drawing_shape(drawing)
    path.closeSubpath()
    if min(path.boundingRect().width(),path.boundingRect().height()) < 3:
        return None
    width,height = size
    canvas = QImage(width,height,QImage.Format.Format_Grayscale8)
    canvas.fill(0)
    painter = QPainter(canvas)
    painter.fillPath(path,Qt.GlobalColor.white)
    painter.end()
    mask = np.frombuffer(canvas.constBits(),np.uint8).reshape(height,canvas.bytesPerLine())[:,:width].copy()
    return (mask != 0).astype(np.uint8) if np.count_nonzero(mask) >= 16 else None


def marked_regions(window):
    """Read-only adapter. Active element wins; otherwise area selection, then latest."""
    if window.original_image is None:
        return [],None
    drawings = window._annotation_document.state['drawings'] if window._annotation_document else []
    choices = []
    active_index = None
    selected_index = window._selected_drawing
    for index,drawing in enumerate(drawings):
        drawing = copy.deepcopy(window._selected_annotation() if index == selected_index else drawing)
        if drawing is None:
            continue
        mask = annotation_mask(drawing,window.original_image.size)
        if mask is None:
            continue
        label = f'Marcação {index+1} · {drawing["kind"]}'
        if drawing['kind'] == 'polygon':
            label = f'Marcação {index+1} · varinha mágica'
        if drawing['kind'] == 'pencil':
            label += ' · traçado fechado entre início e fim'
        choices.append((label,mask))
        if index == selected_index:
            active_index = len(choices)-1
    rect = window.image_view.region_rect
    if rect is not None and rect.width() >= 1 and rect.height() >= 1:
        inverse,_ = image_transform(window.rotation,*window.original_image.size).inverted()
        original_rect = inverse.mapRect(QRectF(rect))
        drawing = dict(kind='rectangle',points=[[original_rect.left(),original_rect.top()],
                                               [original_rect.right(),original_rect.bottom()]])
        mask = annotation_mask(drawing,window.original_image.size)
        if mask is not None:
            choices.append(('Seleção de área atual',mask))
            if active_index is None:
                active_index = len(choices)-1
    if active_index is None and choices:
        active_index = len(choices)-1
    return choices,active_index


class MorphologyWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self,image,mask,parent=None):
        super().__init__(parent)
        self.image,self.mask = image,mask
        self.cancel = threading.Event()

    def run(self):
        try:
            result = MorphologicalRegionAnalyzer().analyze(self.image,self.mask,self.cancel)
            if not self.cancel.is_set():
                self.completed.emit(result)
        except InterruptedError:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


class MorphologicalRegionDialog(QDialog):
    def __init__(self,image,choices,active_index,rotation=0,parent=None):
        super().__init__(parent)
        self.image = np.array(image.convert('RGB'),copy=True)
        self.choices = choices
        self.rotation = rotation
        self.result = None
        self.worker = None
        self._closing = False
        self.setWindowTitle('Morphological Analysis · Área marcada')
        self.resize(1200,800)
        layout = QVBoxLayout(self)
        notice = QLabel('A marcação analisada aparece em ciano; somente seu interior entra nos cálculos. '
                        'Fonte: original sem filtros ou desenhos. A rotação de visualização é preservada.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        self.selection = QComboBox()
        for label,_ in choices:
            self.selection.addItem(label)
        self.selection.setCurrentIndex(active_index)
        self.selection.currentIndexChanged.connect(self.selection_changed)
        row.addWidget(self.selection,1)
        self.analyze_button = QPushButton('Analisar área marcada')
        self.analyze_button.clicked.connect(self.start_analysis)
        row.addWidget(self.analyze_button)
        self.cancel_button = QPushButton('Cancelar análise')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        row.addWidget(self.cancel_button)
        fit = QPushButton('Ajustar imagem')
        fit.clicked.connect(lambda: self.view.fitInView(self.view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio))
        row.addWidget(fit)
        layout.addLayout(row)
        self.status = QLabel('Pronto para analisar a marcação indicada.')
        layout.addWidget(self.status)
        splitter = QSplitter()
        self.view = TextureView()
        splitter.addWidget(self.view)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel('<h3>Resumo da forma</h3>'))
        self.summary = QTextBrowser()
        self.summary.setText('Clique em Analisar área marcada.')
        side_layout.addWidget(self.summary,2)
        side_layout.addWidget(QLabel('Sobreposições (ligar/desligar):'))
        self.layers = {}
        for key,(label,color) in LAYER_NAMES.items():
            check = QCheckBox(label)
            check.setChecked(key in ('external','fissures','cavities'))
            check.setStyleSheet(f'QCheckBox {{ color: rgb{color}; background: #252525; padding: 3px; }}')
            check.toggled.connect(self.refresh)
            side_layout.addWidget(check)
            self.layers[key] = check
        self.technical_toggle = QPushButton('Detalhes técnicos')
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.toggled.connect(lambda value:self.details.setVisible(value))
        side_layout.addWidget(self.technical_toggle)
        self.details = QTextBrowser()
        self.details.setVisible(False)
        side_layout.addWidget(self.details,2)
        splitter.addWidget(side)
        splitter.setSizes([800,400])
        layout.addWidget(splitter,1)
        self.refresh()
        QTimer.singleShot(0,self.start_analysis)

    def showEvent(self,event):
        super().showEvent(event)
        self.view.fitInView(self.view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)

    def selection_changed(self,*args):
        self.result = None
        self.summary.setText('Marcação alterada. Clique em Analisar área marcada.')
        self.details.clear()
        self.refresh()

    def start_analysis(self):
        if self.worker is not None or self._closing:
            return
        self.selection.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText('Analisando somente a área marcada…')
        mask = self.choices[self.selection.currentIndex()][1]
        self.worker = MorphologyWorker(self.image,mask,self)
        self.worker.completed.connect(self.analysis_done)
        self.worker.failed.connect(lambda text:self.status.setText('Não foi possível analisar: '+text))
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def analysis_done(self,result):
        self.result = result
        self.summary.setText(result.summary)
        rows = [f'<b>{html.escape(key)}:</b> {html.escape(str(value))}' for key,value in result.metrics.items()]
        rows.insert(0,'Unidades: pixels; orientação 0° = horizontal, 90° = vertical (original). '
                    'Solidez = área/fecho convexo; simetria = melhor sobreposição após reflexão nos dois eixos PCA. '
                    'Comprimento de fissura = extensão projetada no seu eixo, não percurso de uma curva.')
        for index,structure in enumerate(result.structures,1):
            rows.append(f'<hr><b>Estrutura {index}</b>')
            rows.extend(f'{html.escape(key)}: {html.escape(str(value))}' for key,value in structure.items())
        self.details.setHtml('<br>'.join(rows))
        self.status.setText(self.choices[self.selection.currentIndex()][0]+' · análise concluída')
        self.refresh()

    def refresh(self,*args):
        mask = self.choices[self.selection.currentIndex()][1]
        output = self.image.copy()
        if self.result is not None:
            x,y = self.result.origin
            h,w = self.result.mask.shape
            patch = output[y:y+h,x:x+w]
            for key,check in self.layers.items():
                if check.isChecked():
                    active = self.result.layers[key] != 0
                    color = np.array(LAYER_NAMES[key][1])
                    patch[active] = np.uint8(patch[active]*.25+color*.75)
        # Always show which original annotation supplied the analysis mask.
        cv2.drawContours(output,contours(mask),-1,(0,220,220),1)
        if self.rotation:
            output = np.rot90(output,-self.rotation//90).copy()
        self.view.display(output)

    def cancel_analysis(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText('Cancelando análise…')

    def worker_finished(self):
        cancelled = self.worker.cancel.is_set()
        self.worker.deleteLater()
        self.worker = None
        self.selection.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if cancelled:
            self.status.setText('Análise cancelada.')
        if self._closing:
            super().reject()

    def reject(self):
        self._closing = True
        if self.worker:
            self.cancel_analysis()
        else:
            super().reject()

    def closeEvent(self,event):
        self._closing = True
        if self.worker:
            self.cancel_analysis()
            event.ignore()
        else:
            super().closeEvent(event)
