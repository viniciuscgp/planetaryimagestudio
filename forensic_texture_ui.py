"""Optional analysis workspace; never changes the viewer's image or edit state."""
from datetime import datetime
from pathlib import Path
import threading

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QProgressBar, QPushButton, QSlider, QSplitter, QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from forensic_texture_analyzer import ForensicTextureAnalyzer, METRICS, colorize, write_png
from forensic_texture_presentation import FRIENDLY_METRICS, RegionPresentation, friendly_value


def highlight_texture(base, scores, threshold, opacity):
    """Presentation only: leave pixels below the threshold exactly unchanged."""
    strength = (np.clip((scores-threshold)/max(1-threshold, 1e-12), 0, 1)
                if threshold < 1 else np.ones_like(scores))
    # Fixed endpoints: visible yellow at the user's cutoff, dark red at 100%.
    # Opacity is constant, so values exactly at the cutoff do not fade away.
    start, end = np.array([255,235,80]), np.array([130,0,0])
    colors = start + strength[:, :, None]*(end-start)
    alpha = np.where(scores >= threshold, opacity, 0)[:, :, None]
    return np.uint8(np.rint(base*(1-alpha)+colors*alpha))


def strongest_mask(scores):
    """Top 5% by pixel value, including ties; do not invent peaks on flat maps."""
    if float(np.ptp(scores)) < 1e-6:
        return np.zeros(scores.shape, dtype=bool)
    return (scores >= np.percentile(scores, 95)) & (scores > max(0,float(scores.min())))


def spotlight_texture(base, mask, opacity):
    if not mask.any() or opacity == 0:
        return base.copy()
    gray = cv2.cvtColor(base,cv2.COLOR_RGB2GRAY)
    muted = np.repeat((gray*.35)[:, :, None],3,axis=2)
    target = muted
    target[mask] = base[mask]*.15 + np.array([255,25,10])*.85
    output = np.uint8(np.rint(base*(1-opacity)+target*opacity))
    contours,_ = cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(output,contours,-1,(255,255,255),1)
    return output


class AnalysisWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, image, sizes, parent=None):
        super().__init__(parent)
        self.image, self.sizes = image, sizes
        self.cancel = threading.Event()

    def run(self):
        try:
            result = ForensicTextureAnalyzer(self.sizes).analyze(
                self.image, self.progress.emit, self.cancel)
            if not self.cancel.is_set():
                self.completed.emit(result)
        except InterruptedError:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


class TextureView(QGraphicsView):
    clicked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = self.scene().addPixmap(QPixmap())
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._press = None

    def display(self, rgb, fit=False):
        rgb = np.ascontiguousarray(rgb)
        h,w = rgb.shape[:2]
        qimage = QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy()
        self.item.setPixmap(QPixmap.fromImage(qimage))
        self.setSceneRect(0,0,w,h)
        if fit:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if .01 < self.transform().m11()*factor < 64:
            self.scale(factor,factor)
        event.accept()

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        point = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None and (point-self._press).manhattanLength() < 4:
            pos = self.mapToScene(point)
            if self.sceneRect().contains(pos):
                self.clicked.emit(int(pos.x()),int(pos.y()))
        super().mouseReleaseEvent(event)


class ForensicTextureDialog(QDialog):
    def __init__(self, image, source_path, parent=None):
        super().__init__(parent)
        self.source_path = Path(source_path)
        self.image = np.array(image.convert('RGB'), dtype=np.uint8, copy=True)
        self.result = None
        self.worker = None
        self.selected = None
        self.clicked_point = None
        self.presentation = None
        self._close_pending = False
        self.setWindowTitle(f'Forensic Texture Analysis — {self.source_path.name}')
        self.resize(1200,800)
        layout = QVBoxLayout(self)
        notice = QLabel('Anomalia geral: diferença estatística de textura. '
                        'Iluminação, foco, distância, rocha e compressão também produzem anomalias.\n'
                        'Fonte: cópia do original, antes dos ajustes. Coordenadas X/Y começam em 0, após orientação EXIF.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        row.addWidget(QLabel('Janelas (multiescala):'))
        self.sizes = []
        for size in (32,64,128):
            check = QCheckBox(f'{size}×{size}')
            check.setChecked(True)
            self.sizes.append((size,check))
            row.addWidget(check)
        self.run_button = QPushButton('Analisar')
        self.run_button.clicked.connect(self.start_analysis)
        row.addWidget(self.run_button)
        self.cancel_button = QPushButton('Cancelar')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        row.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        row.addWidget(self.progress)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.overlay = QCheckBox('Aplicar heatmap')
        self.overlay.setChecked(False)
        self.overlay.toggled.connect(self.refresh)
        row.addWidget(self.overlay)
        self.metric_choice = QComboBox()
        self.metric_choice.addItem('Anomalia geral','score')
        for key,label in FRIENDLY_METRICS.items():
            self.metric_choice.addItem(label,key)
        self.metric_choice.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.metric_choice)
        self.scale_choice = QComboBox()
        self.scale_choice.addItem('Multiescala',None)
        self.scale_choice.currentIndexChanged.connect(self.scale_changed)
        row.addWidget(self.scale_choice)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0,100)
        self.opacity.setValue(45)
        self.opacity.valueChanged.connect(self.refresh)
        row.addWidget(QLabel('Opacidade'))
        row.addWidget(self.opacity)
        self.opacity_label = QLabel('45%')
        row.addWidget(self.opacity_label)
        self.mark = QCheckBox('Mostrar janelas de medição')
        self.mark.setToolTip('Os quadrados delimitam janelas de cálculo, não o contorno exato das anomalias.')
        self.mark.setChecked(False)
        self.mark.toggled.connect(self.refresh)
        row.addWidget(self.mark)
        fit = QPushButton('Ajustar')
        fit.clicked.connect(lambda: self.view.fitInView(self.view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio))
        row.addWidget(fit)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.highlight = QCheckBox('Destacar áreas mais anômalas')
        self.highlight.setChecked(True)
        self.highlight.setToolTip('Camada independente, usando a métrica e escala selecionadas. '
                                 'Desative Aplicar heatmap para ver somente os destaques sobre o original.')
        self.highlight.toggled.connect(self.refresh)
        row.addWidget(self.highlight)
        self.highlight_mode = QComboBox()
        self.highlight_mode.addItems(['Mais fortes nesta imagem (5%)','Limite manual'])
        self.highlight_mode.setCurrentIndex(1)
        self.highlight_mode.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.highlight_mode)
        row.addWidget(QLabel('Intensidade mínima'))
        self.highlight_threshold = QSlider(Qt.Orientation.Horizontal)
        self.highlight_threshold.setRange(0,100)
        self.highlight_threshold.setValue(40)
        self.highlight_threshold.setEnabled(True)
        self.highlight_threshold.valueChanged.connect(self.refresh)
        row.addWidget(self.highlight_threshold)
        self.highlight_threshold_label = QLabel('40%')
        row.addWidget(self.highlight_threshold_label)
        row.addWidget(QLabel('Opacidade da camada'))
        self.highlight_opacity = QSlider(Qt.Orientation.Horizontal)
        self.highlight_opacity.setRange(0,100)
        self.highlight_opacity.setValue(85)
        self.highlight_opacity.valueChanged.connect(self.refresh)
        row.addWidget(self.highlight_opacity)
        self.highlight_opacity_label = QLabel('85%')
        row.addWidget(self.highlight_opacity_label)
        self.highlight_save = QPushButton('Salvar original + destaques')
        self.highlight_save.clicked.connect(lambda: self.export('highlights'))
        self.highlight_save.setEnabled(False)
        row.addWidget(self.highlight_save)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.peak_button = QPushButton('Ir ao maior valor')
        self.peak_button.setEnabled(False)
        self.peak_button.clicked.connect(self.inspect_peak)
        row.addWidget(self.peak_button)
        self.highlight_status = QLabel('Camada de destaque: amarelo no corte → vermelho escuro em 100%; '
                                       'áreas abaixo do limite ficam transparentes.')
        self.highlight_status.setWordWrap(True)
        row.addWidget(self.highlight_status,1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Incluir na anomalia geral:'))
        self.metrics = {}
        for key,label in FRIENDLY_METRICS.items():
            check = QCheckBox(label)
            check.setChecked(True)
            check.toggled.connect(self.recombine)
            row.addWidget(check)
            self.metrics[key] = check
        layout.addLayout(row)
        splitter = QSplitter()
        self.view = TextureView()
        self.view.clicked.connect(self.inspect_pixel)
        splitter.addWidget(self.view)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel('<h3>Resumo da análise</h3>'))
        self.summary = QTextBrowser()
        self.summary.setHtml('Analise a imagem e clique em uma região para ver o resumo.')
        side_layout.addWidget(self.summary,3)
        self.technical_toggle = QToolButton()
        self.technical_toggle.setText('Detalhes técnicos')
        self.technical_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.technical_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.toggled.connect(self.toggle_technical)
        side_layout.addWidget(self.technical_toggle)
        self.details = QTextBrowser()
        self.details.setVisible(False)
        side_layout.addWidget(self.details,2)
        self.legend = QLabel('Amarelo: corte de 40% → vermelho escuro: 100%.')
        side_layout.addWidget(self.legend)
        side_layout.addWidget(QLabel('Até 10 regiões, evitando sobreposição:'))
        self.top = QListWidget()
        self.top.currentRowChanged.connect(self.inspect_top)
        self.top.setMaximumHeight(145)
        side_layout.addWidget(self.top,1)
        splitter.addWidget(side)
        splitter.setSizes([750,450])
        layout.addWidget(splitter,1)
        row = QHBoxLayout()
        self.exports = [self.highlight_save, self.peak_button]
        for title,kind in [('Exportar CSV','csv'),('Salvar heatmap puro','heatmap'),
                           ('Salvar original + heatmap','overlay'),('Salvar regiões marcadas','regions'),
                           ('Salvar todos os mapas','maps')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False,k=kind: self.export(k))
            button.setEnabled(False)
            self.exports.append(button)
            row.addWidget(button)
        layout.addLayout(row)
        self.view.display(self.image)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)

    def start_analysis(self):
        sizes = [size for size,check in self.sizes if check.isChecked()]
        if not sizes:
            QMessageBox.information(self,'Janelas','Selecione ao menos um tamanho de janela.')
            return
        if self.worker is not None:
            return
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setFormat('%p%')
        self.progress.setValue(0)
        for _,check in self.sizes:
            check.setEnabled(False)
        self.worker = AnalysisWorker(self.image,sizes,self)
        self.worker.completed.connect(self.analysis_done)
        self.worker.failed.connect(lambda message: QMessageBox.warning(self,'Falha na análise',message))
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def update_progress(self, done, total):
        self.progress.setValue(round(90*done/total))
        if done == total:
            self.progress.setFormat('Normalizando e combinando…')

    def cancel_analysis(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        for _,check in self.sizes:
            check.setEnabled(True)
        if self._close_pending:
            self.reject()

    def reject(self):
        if self.worker is not None:
            self._close_pending = True
            self.cancel_analysis()
            return
        super().reject()

    def closeEvent(self,event):
        if self.worker is not None:
            self._close_pending = True
            self.cancel_analysis()
            event.ignore()
        else:
            super().closeEvent(event)

    def analysis_done(self,result):
        self.progress.setFormat('%p%')
        self.progress.setValue(100)
        self.result = result
        self.selected = None
        self.clicked_point = None
        self.technical_toggle.setChecked(False)
        self.scale_choice.blockSignals(True)
        self.scale_choice.clear()
        self.scale_choice.addItem('Multiescala',None)
        for size in result.scale_maps:
            self.scale_choice.addItem(f'{size}×{size}',size)
        self.scale_choice.blockSignals(False)
        for button in self.exports:
            button.setEnabled(True)
        self.recombine()
        self.inspect_peak()

    def recombine(self,*args):
        if self.result is None:
            return
        ForensicTextureAnalyzer.recombine(self.result,{k:int(c.isChecked()) for k,c in self.metrics.items()})
        self.presentation = RegionPresentation(self.result.regions)
        self.top.clear()
        for i,r in enumerate(self.result.top_regions,1):
            self.top.addItem(f"{i}. ({r['x']}, {r['y']}) · {r['width']}×{r['height']} · {friendly_value(r['score'])}")
        if self.selected:
            self.show_details(self.selected)
        self.refresh()

    def current_map(self):
        size = self.scale_choice.currentData()
        maps = self.result.maps if size is None else self.result.scale_maps[size]
        return maps[self.metric_choice.currentData()]

    def overlay_image(self):
        alpha = self.opacity.value()/100
        return cv2.addWeighted(self.image,1-alpha,colorize(self.current_map()),alpha,0)

    def highlight_image(self, base=None):
        if self.highlight_mode.currentIndex() == 0:
            return spotlight_texture(self.image if base is None else base, strongest_mask(self.current_map()),
                                     self.highlight_opacity.value()/100)
        return highlight_texture(self.image if base is None else base, self.current_map(),
                                 self.highlight_threshold.value()/100, self.highlight_opacity.value()/100)

    def marked_image(self,base):
        output = base.copy()
        for i,r in enumerate(self.result.top_regions,1):
            x,y,w,h = (r[k] for k in ('x','y','width','height'))
            cv2.rectangle(output,(x,y),(x+w-1,y+h-1),(255,255,255),2)
            cv2.putText(output,str(i),(x+2,y+min(18,h-1)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),3)
            cv2.putText(output,str(i),(x+2,y+min(18,h-1)),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
        return output

    def refresh(self,*args):
        relative = self.highlight_mode.currentIndex() == 0
        self.legend.setText(
            'Vermelho: maiores valores desta imagem.\nCruz branca: ponto de maior valor no mapa.'
            if relative and self.highlight.isChecked() else
            f'Amarelo: corte de {self.highlight_threshold.value()}% → vermelho escuro: 100%.'
            if self.highlight.isChecked() else
            'Heatmap: 0% (azul) → 100% (vermelho). Intensidade relativa.'
            if self.overlay.isChecked() else 'Camadas de cor desligadas: imagem original.')
        self.highlight_threshold.setEnabled(not relative)
        self.opacity_label.setText(f'{self.opacity.value()}%')
        self.highlight_threshold_label.setText(f'{self.highlight_threshold.value()}%')
        self.highlight_opacity_label.setText(f'{self.highlight_opacity.value()}%')
        output = self.image
        if self.result:
            if self.overlay.isChecked():
                output = self.overlay_image()
            if self.highlight.isChecked():
                output = self.highlight_image(output)
                scores = self.current_map()
                mask = strongest_mask(scores) if relative else (scores >= self.highlight_threshold.value()/100)
                covered = np.mean(mask)*100
                self.highlight_status.setText(
                    (f'VERMELHO = áreas de maior valor nesta imagem ({covered:.1f}% da área, incluindo empates). '
                     'O restante fica escurecido. Destaque relativo: pode corresponder a anomalia baixa.'
                     if covered else 'Sem diferenças suficientes para destacar: o mapa é uniforme.') if relative else (
                    f'Destaque de {self.metric_choice.currentText()} · {self.scale_choice.currentText()}: '
                    f'{covered:.1f}% da área. Amarelo visível no corte de {self.highlight_threshold.value()}%; '
                    'a cor escurece até vermelho escuro em 100%.'
                    if covered else f'Nenhum valor do mapa atinge o corte de {self.highlight_threshold.value()}%. '
                    f'Maior valor do mapa: {float(scores.max()):.1%}.'))
                if covered:
                    y,x = np.unravel_index(np.argmax(scores),scores.shape)
                    if relative and self.highlight_opacity.value() > 0:
                        cv2.drawMarker(output,(int(x),int(y)),(0,0,0),cv2.MARKER_CROSS,17,3)
                        cv2.drawMarker(output,(int(x),int(y)),(255,255,255),cv2.MARKER_CROSS,15,1)
                    self.highlight_status.setText(self.highlight_status.text()+
                        f' Maior valor do mapa: X={x} Y={y} · {friendly_value(scores[y,x])}.')
                    if min(x,y,scores.shape[1]-1-x,scores.shape[0]-1-y) < 16:
                        self.highlight_status.setText(self.highlight_status.text()+
                            ' Pico próximo à borda: a vizinhança disponível é menor nessa área.')
            else:
                self.highlight_status.setText('Camada de destaque desligada. Amarelo → vermelho = intensidade crescente; '
                                              'áreas abaixo do limite ficam transparentes.')
            if self.mark.isChecked():
                output = self.marked_image(output)
            if self.selected:
                self.show_details(self.selected)
                if self.mark.isChecked():
                    output = output.copy()
                    r = self.selected
                    cv2.rectangle(output,(r['x'],r['y']),(r['x']+r['width']-1,r['y']+r['height']-1),(255,0,255),2)
        self.view.display(output)

    def inspect_peak(self):
        if self.result is None:
            return
        scores = self.current_map()
        if float(np.ptp(scores)) < 1e-6:
            return
        y,x = np.unravel_index(np.argmax(scores),scores.shape)
        self.inspect_pixel(int(x),int(y))
        self.view.centerOn(int(x),int(y))

    def inspect_top(self,index):
        if self.result and 0 <= index < len(self.result.top_regions):
            self.clicked_point = None
            self.selected = self.result.top_regions[index]
            self.show_details(self.selected)
            r = self.selected
            self.view.centerOn(r['x']+r['width']/2,r['y']+r['height']/2)
            self.refresh()

    def inspect_pixel(self,x,y):
        if self.result is None:
            return
        size = self.scale_choice.currentData()
        candidates = [r for r in self.result.regions if (size is None or size == r['window_size'])
                      and r['x'] <= x < r['x']+r['width'] and r['y'] <= y < r['y']+r['height']]
        if candidates:
            self.clicked_point = (x,y)
            self.selected = max(candidates,key=lambda r:r['score'])
            self.top.blockSignals(True)
            selected_index = next((i for i,r in enumerate(self.result.top_regions)
                                   if r is self.selected), -1)
            self.top.setCurrentRow(selected_index)
            self.top.blockSignals(False)
            self.refresh()

    def scale_changed(self,*args):
        if self.clicked_point is not None:
            self.inspect_pixel(*self.clicked_point)
        else:
            self.refresh()

    def toggle_technical(self, opened):
        self.details.setVisible(opened)
        self.technical_toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)

    def show_details(self,r):
        coordinates = (f"<b>Região analisada:</b> X={r['x']} Y={r['y']}<br>"
                       f"<b>Tamanho da região:</b> {r['width']}x{r['height']}<br>")
        heatmap = ''
        if self.clicked_point is not None:
            x,y = self.clicked_point
            coordinates = f'<b>Ponto clicado:</b> X={x} Y={y}<br>' + coordinates
            value = self.current_map()[y,x]
            heatmap = (f'<b>Valor visual do heatmap:</b> {friendly_value(value)} '
                       f'({self.metric_choice.currentText()}, {self.scale_choice.currentText()})<br>')
        self.summary.setHtml(self.presentation.summary_html(r,self.result.weights) +
            f'<p>{coordinates}</p><p>{heatmap}<b>Score real da região:</b> {friendly_value(r["score"])}<br>'
            'O heatmap agrega janelas sobrepostas; o score da região corresponde apenas à janela selecionada.</p>'
            f'<p>Comparação com {max(0,self.presentation.count-1)} outras janelas da imagem, em todas as escalas analisadas. '
            'Empates não contam como valores menores.</p>')
        rows = [('Escala da janela',str(r['window_size'])),
                ('Texture Anomaly Score',f"{r['score']:.5f}"),('High frequency RMS',f"{r['high_frequency_rms']:.5f}"),
                ('Fine/coarse ratio',f"{r['fine_coarse_ratio']:.5f}"),('Gradiente médio',f"{r['mean_gradient']:.5f}"),
                ('RGB R/G, R/B, G/B',f"{r['rgb_rg']:.4f}, {r['rgb_rb']:.4f}, {r['rgb_gb']:.4f}"),
                ('RGB válido',str(r['rgb_valid'])),('Periodicidade (dispersão)',f"{r['compression_strength']:.5f}"),
                ('FFT pico espectral',f"{r['fft_peak']:.5f}"),('Boundary diferença',f"{r['boundary_difference']:.5f}")]
        rows += [(f'{label} anomaly',f"{r[key+'_anomaly']:.5f}") for key,label in METRICS.items()]
        if self.clicked_point is not None:
            rows.insert(0,('Valor visual do heatmap (valor original)',f'{self.current_map()[y,x]:.5f}'))
        rows.insert(0,('Score real da região (valor original)',f'{r["score"]:.5f}'))
        self.details.setHtml(coordinates+'<br>'.join(f'<b>{label}:</b> {value}' for label,value in rows)+
                             '<p>O score da janela difere do pixel, que agrega janelas sobrepostas.</p>')

    def export(self,kind):
        folder = QFileDialog.getExistingDirectory(self,'Pasta de destino (será criada uma subpasta nova)')
        if not folder:
            return
        try:
            target = Path(folder) / f'{self.source_path.stem}_texture_{datetime.now():%Y%m%d_%H%M%S_%f}'
            target.mkdir(exist_ok=False)
            if kind == 'csv':
                self.result.export_csv(target/'regions.csv')
            elif kind == 'maps':
                self.result.export_maps(target)
                self.result.export_csv(target/'regions.csv')
            else:
                rgb = {'heatmap':lambda:colorize(self.current_map()),'overlay':self.overlay_image,
                       'highlights':self.highlight_image,
                       'regions':lambda:self.marked_image(self.image)}[kind]()
                write_png(target/f'{kind}.png',rgb)
            QMessageBox.information(self,'Exportação concluída',str(target))
        except (OSError,ValueError,cv2.error) as exc:
            QMessageBox.warning(self,'Erro ao exportar',str(exc))
