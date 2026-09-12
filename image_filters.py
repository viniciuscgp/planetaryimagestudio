"""Background image filtering; originals and annotations are never modified."""
import json
import threading
from pathlib import Path
from PIL import Image, ImageChops
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidgetItem, QWidget, QVBoxLayout, QProgressBar
from catalog import list_images


def changed(state):
    return bool(state.get('drawings') or state.get('auto_enhance_mars',False) or state.get('percentile_stretch',False) or state.get('contrast',1)!=1 or state.get('saturation',1)!=1
                or state.get('rotation',0)%360 or state.get('inverted',False) or state.get('smoothing',0) or state.get('sharpness',0)
                or state.get('black_point',0)!=0 or state.get('white_point',255)!=255 or state.get('gamma',1)!=1 or state.get('brightness',100)!=100)

def is_edited(path):
    try:
        data=json.loads(Path(str(path)+'.annotations.json').read_text(encoding='utf-8'))
        return any(changed(s) for s in [data.get('state',{}),*data.get('undo',[]),*data.get('redo',[])])
    except (OSError,ValueError,TypeError,AttributeError):
        return False


def is_color(path):
    # Inspect actual channel differences: RGB-encoded monochrome is not color.
    try:
        with Image.open(path) as image:
            if image.mode in ('1','L','I','F','I;16'):
                return False
            image.draft('RGB',(96,96))
            image.thumbnail((96,96))
            r,g,b=image.convert('RGB').split()
            spread=ImageChops.lighter(ImageChops.difference(r,g),ImageChops.difference(g,b))
            histogram=spread.histogram()
            return sum(histogram[9:]) >= max(1,image.width*image.height*0.01)
    except (OSError,ValueError,Image.DecompressionBombError):
        return False

class FilterSignals(QObject):
    done=Signal(int,object)
    progress=Signal(int,int)

class FilterJob(QRunnable):
    def __init__(self,token,folders,color,edited,cache):
        super().__init__()
        self.token,self.folders,self.color,self.edited,self.cache=token,folders,color,edited,cache
        self.cancel=threading.Event()
        self.signals=FilterSignals()
    def run(self):
        result=[];count=0
        try:
            for key,folder in self.folders:
                if self.cancel.is_set():return
                for path in list_images(folder, self.cancel):
                    if self.cancel.is_set():return
                    count+=1
                    if count%100==0:self.signals.progress.emit(self.token,count)
                    if self.edited and not is_edited(path):continue
                    if self.color:
                        try:
                            stat=path.stat();cache_key=(str(path),stat.st_mtime_ns,stat.st_size)
                            if cache_key not in self.cache:self.cache[cache_key]=is_color(path)
                            if not self.cache[cache_key]:continue
                        except OSError:continue
                    result.append((key,folder,path))
        finally:
            self.signals.done.emit(self.token,None if self.cancel.is_set() else result)

class ImageFiltersMixin:
    def _build_image_filters(self,layout):
        self._filter_token=0;self._filter_jobs={};self._color_cache={};self._filter_results={}
        self._filter_pool=QThreadPool(self);self._filter_pool.setMaxThreadCount(2)
        self._filter_timer=QTimer(self);self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(lambda: self._request_image_filter(background=True))
        row=QHBoxLayout()
        row.addWidget(QLabel('Filtros:'))
        self.filter_color=QCheckBox('Coloridas')
        self.filter_color.setToolTip('Detecta cores no arquivo original por amostragem; RGB em preto e branco não conta como colorido.')
        self.filter_edited=QCheckBox('Editadas')
        self.filter_edited.setToolTip('Marcações, textos ou ajustes atuais ou no histórico salvo. Alterar apenas a ferramenta/cor do lápis não conta.')
        self.filter_scope=QComboBox();self.filter_scope.addItems(['Pasta','Missão'])
        self.filter_scope.setToolTip('Pasta atual ou todas as imagens da missão de trabalho.')
        self.filter_count=QLabel()
        for widget in (self.filter_color,self.filter_edited,self.filter_scope,self.filter_count):row.addWidget(widget)
        row.addStretch();layout.addLayout(row)
        self.filter_color.toggled.connect(self._image_filters_changed)
        self.filter_edited.toggled.connect(self._image_filters_changed)
        self.filter_scope.currentIndexChanged.connect(self._image_filters_changed)
        self.thumbnail_loading = QWidget()
        loading_layout = QVBoxLayout(self.thumbnail_loading)
        loading_layout.setContentsMargins(8,4,8,4)
        loading_layout.setSpacing(3)
        self.thumbnail_loading_label = QLabel()
        self.thumbnail_loading_label.setWordWrap(True)
        self.thumbnail_loading_label.setStyleSheet('font-weight: bold; font-size: 13px;')
        self.thumbnail_loading_progress = QProgressBar()
        self.thumbnail_loading_progress.setFixedHeight(14)
        self.thumbnail_loading_progress.setTextVisible(False)
        loading_layout.addWidget(self.thumbnail_loading_label)
        loading_layout.addWidget(self.thumbnail_loading_progress)
        layout.addWidget(self.thumbnail_loading)
        self.thumbnail_loading.hide()
        self._thumbnail_loading_total = 0
        self._thumbnail_loading_name = 'imagens'

    def _begin_thumbnail_loading(self):
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self.current_images = []
        self._filter_results = {}
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        self.thumb_list.blockSignals(False)
        self._thumbnail_loading_total = 0
        self._thumbnail_loading_name = (self.source.name if self.filter_scope.currentIndex()==1 else
                                        self.current_folder.name if self.current_folder else 'imagens')
        self.thumbnail_loading_label.setText(f'Carregando {self._thumbnail_loading_name} — lendo arquivos…')
        self.thumbnail_loading_progress.setRange(0,0)
        self.thumbnail_loading.show()

    def _thumbnail_loading_results(self):
        self._thumbnail_loading_total = len(self._thumb_queue)
        if self._thumbnail_loading_total:
            self.thumbnail_loading_progress.setRange(0,self._thumbnail_loading_total)
            self._update_thumbnail_loading()
        else:
            self.thumbnail_loading_label.setText('Nenhuma imagem encontrada para esta pasta ou estes filtros.')
            self.thumbnail_loading_progress.setRange(0,1)
            self.thumbnail_loading_progress.setValue(0)

    def _update_thumbnail_loading(self):
        if not self._thumbnail_loading_total:
            return
        done = self._thumbnail_loading_total-len(self._thumb_queue)
        self.thumbnail_loading_progress.setValue(max(0,done))
        self.thumbnail_loading_label.setText(
            f'{self._thumbnail_loading_name} — miniaturas: {max(0,done)} de {self._thumbnail_loading_total}')
        if not self._thumb_queue:
            self._thumbnail_loading_total = 0
            self.thumbnail_loading.hide()

    def _image_filter_state(self):
        return dict(color=self.filter_color.isChecked(),edited=self.filter_edited.isChecked(),
                    scope='mission' if self.filter_scope.currentIndex()==1 else 'folder')

    def _restore_image_filters(self):
        saved = self._state.get('image_filters',{})
        if not isinstance(saved,dict):
            saved = {}
        was_active = self._filters_active()
        for widget,value in ((self.filter_color,saved.get('color') is True),
                             (self.filter_edited,saved.get('edited') is True),
                             (self.filter_scope,1 if saved.get('scope')=='mission' else 0)):
            widget.blockSignals(True)
            if widget is self.filter_scope:
                widget.setCurrentIndex(value)
            else:
                widget.setChecked(value)
            widget.blockSignals(False)
        if was_active or self._filters_active():
            self._request_image_filter()

    def _image_filters_changed(self,*args):
        self._save_state()
        self._request_image_filter()

    def _filters_active(self):
        return self.filter_color.isChecked() or self.filter_edited.isChecked() or self.filter_scope.currentIndex()==1

    def _cancel_image_filters(self):
        self._filter_timer.stop();self._filter_token+=1
        for job in self._filter_jobs.values():job.cancel.set()
        self._thumbnail_loading_total = 0
        self.thumbnail_loading.hide()

    def _request_image_filter(self,*args,background=False):
        if self._closing:return
        # A download refresh must not turn a pending explicit folder switch into
        # an append-only update with no selection when its replacement finishes.
        if background and self._filter_token in self._filter_jobs and not self._filter_background:
            background = False
        self._cancel_image_filters()
        self._filter_background = background
        if not background:
            self._begin_thumbnail_loading()
        if self.filter_scope.currentIndex()==1:
            folders=self.source.list_collections(self.root)
        else:
            folders=[(self.current_sol,self.current_folder)] if self.current_folder else []
        if not background:self.filter_count.setText('Buscando…')
        job=FilterJob(self._filter_token,folders,self.filter_color.isChecked(),self.filter_edited.isChecked(),self._color_cache)
        self._filter_jobs[self._filter_token]=job
        job.signals.done.connect(self._image_filter_done)
        job.signals.progress.connect(self._image_filter_progress)
        self._filter_pool.start(job)

    def _image_filter_progress(self,token,count):
        if token==self._filter_token and not self._filter_background:
            self.filter_count.setText(f'{count} verificadas…')
            self.thumbnail_loading_label.setText(f'Carregando {self._thumbnail_loading_name} — {count} arquivos verificados…')

    def _image_filter_done(self,token,rows):
        self._filter_jobs.pop(token,None)
        if token!=self._filter_token or rows is None or self._closing:return
        if getattr(self, '_filter_background', False) and self.current_path is not None:
            # Downloads must not rebuild/reselect a list that the user is browsing.
            known={str(path) for path in self.current_images}
            scroll=self.thumb_list.horizontalScrollBar().value()
            added = False
            for key,folder,path in rows:
                if str(path) in known:continue
                known.add(str(path));self._filter_results[str(path)]=(key,folder)
                self.current_images.append(path)
                item=QListWidgetItem(path.name);item.setData(Qt.ItemDataRole.UserRole,str(path));item.setToolTip(str(path))
                self._highlight_thumbnail(item,path)
                self.thumb_list.addItem(item);self._thumb_queue.append((item,path))
                added = True
            if not added:return
            self.thumb_list.doItemsLayout()
            self.thumb_list.horizontalScrollBar().setValue(scroll)
            self.filter_count.setText(f'{len(self.current_images)} imagens')
            if self._thumb_queue:self._thumb_timer.start(1)
            return
        selected=self.current_path
        self._filter_results={str(path):(key,folder) for key,folder,path in rows}
        self.current_images=[path for _,_,path in rows]
        self._thumb_timer.stop();self._thumb_queue.clear()
        self.thumb_list.blockSignals(True);self.thumb_list.clear()
        chosen=None
        for key,folder,path in rows:
            item=QListWidgetItem(path.name);item.setData(Qt.ItemDataRole.UserRole,str(path))
            self._highlight_thumbnail(item,path)
            item.setToolTip(str(path));self.thumb_list.addItem(item);self._thumb_queue.append((item,path))
            if path==selected:chosen=item
        if chosen is None and self.thumb_list.count():chosen=self.thumb_list.item(0)
        self.thumb_list.setCurrentItem(chosen)
        self.thumb_list.blockSignals(False)
        self.filter_count.setText(f'{len(rows)} imagens')
        if not getattr(self,'_filter_background',False):
            self._thumbnail_loading_results()
        if self._thumb_queue:self._thumb_timer.start(1)
        if chosen:self._thumb_changed(chosen,None)
        else:
            self.current_path=None;self.original_image=None;self.processed_qimage=None
            self._clear_annotations();self.image_view.set_pixmap(QPixmap())
            if getattr(self,'_forensic_dock',None) is not None:
                self._forensic_dock.sync_source()
            self.statusBar().showMessage('Nenhuma imagem corresponde aos filtros.')

    def _refresh_filters_after_edit(self):
        if self.filter_edited.isChecked():self._filter_timer.start(300)
