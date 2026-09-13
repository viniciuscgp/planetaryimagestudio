"""Review exact duplicates before explicitly removing unannotated copies."""
from pathlib import Path
import threading

from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,
                               QProgressBar,QTreeWidget,QTreeWidgetItem,QMessageBox)

from exact_duplicates import scan_duplicates,remove_duplicates,REGISTRY


class DuplicateWorker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self,operation,parent):
        super().__init__(parent)
        self.operation = operation
        self.cancel = threading.Event()

    def run(self):
        try:
            result = self.operation(self.cancel,self.progress.emit)
            self.done.emit(result)
        except InterruptedError:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


class DuplicateDialog(QDialog):
    def __init__(self,host,monochrome=False):
        super().__init__(host)
        self.monochrome = monochrome
        self.scan_operation,self.remove_operation = scan_duplicates,remove_duplicates
        if monochrome:
            from monochrome_cleanup import scan_monochrome,remove_monochrome
            self.scan_operation,self.remove_operation = scan_monochrome,remove_monochrome
        self.host = host
        self.root = host.root.resolve()
        self.worker = None
        self.groups = []
        self.removed = []
        self.pending_close = False
        self.removing = False
        self.setWindowTitle('Remover imagens em preto e branco' if monochrome else 'Remover duplicatas')
        self.resize(850,560)
        layout = QVBoxLayout(self)
        criterion = ('Analisa todos os pixels do original. Qualquer diferença entre os canais de cor mantém a imagem. '
                     'Ajustes de saturação e desenhos não influenciam a classificação. ' if monochrome else
                     'Somente pixels exatamente iguais. Diferenças de um pixel são mantidas. ')
        notice = QLabel(criterion+'Imagens com arquivo de anotações (inclusive histórico ou arquivo ilegível) e a imagem aberta são protegidas. '
                        'A busca não remove arquivos.')
        notice.setWordWrap(True);layout.addWidget(notice)
        row = QHBoxLayout()
        self.scope = QComboBox()
        if host.current_folder:
            self.scope.addItem(f'Pasta atual: {host.current_folder.name}',str(host.current_folder))
        self.scope.addItem('Missão inteira',None)
        row.addWidget(self.scope)
        self.scan = QPushButton('Buscar imagens em preto e branco' if monochrome else 'Buscar duplicatas');self.scan.clicked.connect(self.start_scan);row.addWidget(self.scan)
        self.cancel = QPushButton('Cancelar busca');self.cancel.clicked.connect(self.cancel_work);self.cancel.setEnabled(False);row.addWidget(self.cancel)
        layout.addLayout(row)
        self.status = QLabel('Escolha o escopo e clique em '+self.scan.text()+'.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress = QProgressBar();self.progress.setRange(0,1);layout.addWidget(self.progress)
        self.tree = QTreeWidget();self.tree.setHeaderLabels(['Arquivo / grupo','Destino']);layout.addWidget(self.tree,1)
        self.delete = QPushButton('Excluir imagens selecionadas' if monochrome else 'Excluir cópias selecionadas');self.delete.setEnabled(False);self.delete.clicked.connect(self.start_remove);layout.addWidget(self.delete)
        download_note = ('para impedir que esses nomes sejam baixados novamente.' if monochrome else
                         'para impedir downloads repetidos enquanto a cópia mantida existir.')
        footer = QLabel(f'Exclusão permanente somente após revisar e clicar em Excluir. Os nomes ficam em {REGISTRY}, '
                        'na pasta da missão, '+download_note)
        footer.setWordWrap(True);layout.addWidget(footer)

    def protected_paths(self):
        paths = list(self.host._annotation_documents)
        if self.host.current_path:
            paths.append(self.host.current_path)
        return paths

    def start(self,operation,callback):
        self.scan.setEnabled(False);self.delete.setEnabled(False);self.scope.setEnabled(False)
        self.cancel.setEnabled(True);self.progress.setRange(0,0)
        self.worker = DuplicateWorker(operation,self)
        self.worker.done.connect(callback)
        self.worker.failed.connect(lambda message: self.status.setText('Erro: '+message))
        self.worker.progress.connect(lambda n:self.status.setText(f'{n} arquivos processados…'))
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def start_scan(self):
        if self.worker:
            return
        self.tree.clear();self.groups=[]
        folder = self.scope.currentData()
        extra = self.protected_paths()
        self.status.setText('Comparando todos os pixels em segundo plano…')
        self.start(lambda cancel,progress:self.scan_operation(self.root,folder,extra,cancel,progress),self.scan_done)

    def scan_done(self,result):
        self.groups=result['groups']
        count=0
        for index,group in enumerate(self.groups):
            if not self.monochrome:
                parent=QTreeWidgetItem([str(group['keeper'].relative_to(self.root)),'MANTER'])
                parent.setToolTip(0,str(group['keeper']))
                self.tree.addTopLevelItem(parent)
            for path in group['copies']:
                protected=path in group['protected']
                destination = 'Excluir imagem' if self.monochrome else 'Excluir cópia'
                item=QTreeWidgetItem([str(path.relative_to(self.root)),'PROTEGIDA — manter' if protected else destination])
                item.setToolTip(0,str(path))
                item.setData(0,Qt.ItemDataRole.UserRole,(index,str(path)))
                if self.monochrome:
                    self.tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                if not protected:
                    item.setCheckState(0,Qt.CheckState.Checked);count+=1
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            if not self.monochrome:
                parent.setExpanded(True)
        self.tree.resizeColumnToContents(0)
        found = 'imagens em preto e branco' if self.monochrome else 'grupos de duplicatas'
        self.status.setText(f"{result['checked']} imagens lidas · {len(self.groups)} {found} · {count} arquivos removíveis. "
                            f"{len(result['errors'])} arquivos mantidos por erro/limitação de leitura.")
        self.status.setToolTip('\n'.join(result['errors']))

    def selected_groups(self):
        selected=[]
        for index,group in enumerate(self.groups):
            parent=self.tree.topLevelItem(index)
            items = [parent] if self.monochrome else [parent.child(i) for i in range(parent.childCount())]
            copies=[Path(item.data(0,Qt.ItemDataRole.UserRole)[1]) for item in items
                    if item.checkState(0)==Qt.CheckState.Checked]
            if copies:
                selected.append(dict(group,copies=copies))
        return selected

    def start_remove(self):
        if self.worker:
            return
        if self.host._download_thread is not None and self.host._download_thread.isRunning():
            QMessageBox.information(self,'Download em andamento','Pause o download antes de excluir imagens.')
            return
        groups=self.selected_groups()
        if not groups:
            return
        extra=self.protected_paths()
        self.removing = True
        self.cancel.setText('Interromper exclusão')
        self.status.setText('Reverificando pixels e anotações antes de excluir…')
        self.start(lambda cancel,progress:self.remove_operation(self.root,groups,extra,cancel,progress),self.remove_done)

    def remove_done(self,result):
        self.removed.extend(result['removed'])
        self.groups=[];self.tree.clear()
        self.status.setText(f"{len(result['removed'])} imagens excluídas e registradas. {len(result['errors'])} erros; esses arquivos foram mantidos.")
        self.status.setToolTip('\n'.join(result['errors']))

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText('Interrompendo; aguardando o arquivo atual…')

    def finished_work(self):
        self.worker.deleteLater();self.worker=None
        self.removing = False
        self.scan.setEnabled(True);self.scope.setEnabled(True);self.cancel.setEnabled(False)
        self.cancel.setText('Cancelar busca');self.progress.setRange(0,1);self.progress.setValue(1)
        self.delete.setEnabled(bool(self.selected_groups()))
        if self.pending_close:
            super().reject()

    def reject(self):
        if self.worker:
            self.pending_close=True;self.cancel_work()
        else:
            super().reject()

    def closeEvent(self,event):
        if self.worker:
            self.pending_close=True;self.cancel_work();event.ignore()
        else:
            super().closeEvent(event)
