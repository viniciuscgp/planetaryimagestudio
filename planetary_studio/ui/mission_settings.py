"""Mission configuration dialog. Editing stays isolated until Save."""

import copy
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from planetary_studio.collections.missions import GROUPINGS


class MissionSettingsDialog(QDialog):
    def __init__(self, registry, current_id, parent=None):
        super().__init__(parent)
        self.registry = copy.deepcopy(registry)
        self.active_id = current_id
        self.current_id = None
        self.open_mission_id = None
        self._loading = False
        self.setWindowTitle("Configurar planetas e missões")
        self.resize(1100, 710)
        layout = QVBoxLayout(self)
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("Pasta-base das coleções:"))
        self.base_folder = QLineEdit(self.registry.library_root)
        self.base_folder.setPlaceholderText("Ex.: D:\\ImagensPlanetarias")
        base_row.addWidget(self.base_folder, 1)
        browse_base = QPushButton("Escolher...")
        browse_base.clicked.connect(self._browse_base)
        base_row.addWidget(browse_base)
        layout.addLayout(base_row)
        layout.addWidget(QLabel("Estrutura padrão: pasta-base / planeta / missions / missão / SOLs, datas, órbitas ou pastas do acervo."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar planeta ou missão...")
        layout.addWidget(self.search)
        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Planeta / Missão", "Acesso às imagens"])
        self.tree.setColumnWidth(0, 230)
        splitter.addWidget(self.tree)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self.body = QLineEdit()
        self.name = QLineEdit()
        self.enabled = QCheckBox("Mostrar esta missão no menu")
        self.access = QLabel()
        self.access.setWordWrap(True)
        self.grouping = QComboBox()
        for key, label in GROUPINGS.items():
            self.grouping.addItem(label, key)
        self.custom_folder = QCheckBox("Usar uma pasta existente ou personalizada")
        path_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.browse_folder = QPushButton("Escolher...")
        self.browse_folder.clicked.connect(self._browse_folder)
        path_row.addWidget(self.folder, 1)
        path_row.addWidget(self.browse_folder)
        self.path_preview = QLabel()
        self.path_preview.setWordWrap(True)
        self.path_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.auto_download = QCheckBox("Atualizar automaticamente ao abrir esta missão")
        self.start_sol = QSpinBox()
        self.start_sol.setRange(0, 100000)
        self.start_sol.setToolTip("Usado em Verificar deste SOL em diante. A atualização automática continua do último SOL local.")
        self.archive = QLineEdit()
        self.archive_button = QPushButton("Abrir portal de imagens / acervo")
        self.archive_button.clicked.connect(self._open_archive)
        form.addRow("Imagens disponíveis:", self.access)
        form.addRow("Pasta das imagens:", self.path_preview)
        form.addRow("", self.auto_download)
        advanced_toggle = QCheckBox("Mostrar opções avançadas")
        form.addRow(advanced_toggle)
        advanced = QWidget()
        form.addRow(advanced)
        form = QFormLayout(advanced)
        advanced.setVisible(False)
        advanced_toggle.toggled.connect(advanced.setVisible)
        for label, control in (("Planeta / corpo:", self.body), ("Missão:", self.name), ("", self.enabled),
                               ("Organização:", self.grouping), ("", self.custom_folder)):
            form.addRow(label, control)
        form.addRow("Pasta personalizada:", path_row)
        form.addRow("SOL inicial da verificação:", self.start_sol)
        form.addRow("Portal de imagens:", self.archive)
        form.addRow("", self.archive_button)
        note = QLabel("Alterar o caminho não move arquivos existentes. As pastas padrão são criadas quando você abre a missão. "
                      "Missões sem download integrado usam imagens locais e o portal externo; o formato científico de cada acervo pode exigir conversão.")
        note.setWordWrap(True)
        form.addRow(note)
        splitter.addWidget(form_widget)
        splitter.setSizes([430, 650])
        layout.addWidget(splitter, 1)
        bottom = QHBoxLayout()
        add = QPushButton("Adicionar missão...")
        add.clicked.connect(self._add_custom)
        self.remove = QPushButton("Remover cadastro personalizado")
        self.remove.clicked.connect(self._remove_custom)
        bottom.addWidget(add)
        bottom.addWidget(self.remove)
        bottom.addStretch()
        layout.addLayout(bottom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Salvar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        open_button = QPushButton("Salvar e abrir missão")
        buttons.addButton(open_button, QDialogButtonBox.ButtonRole.ActionRole)
        open_button.clicked.connect(lambda: self._save(open_selected=True))
        layout.addWidget(buttons)
        self.tree.currentItemChanged.connect(self._selected)
        self.search.textChanged.connect(self._filter)
        self.base_folder.textChanged.connect(self._base_changed)
        for line in (self.body, self.name, self.folder, self.archive):
            line.textChanged.connect(self._form_changed)
        for check in (self.enabled, self.custom_folder, self.auto_download):
            check.toggled.connect(self._form_changed)
        self.grouping.currentIndexChanged.connect(self._form_changed)
        self.start_sol.valueChanged.connect(self._form_changed)
        self._populate(current_id)

    def _populate(self, selected_id):
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        selected = None
        for profile in sorted(self.registry.profiles.values(), key=lambda p: (p["body"], p["name"])):
            body = profile["body"]
            if body not in groups:
                groups[body] = QTreeWidgetItem(self.tree, [body])
            access = "Download integrado" if self.registry.source_for(profile["id"]).supports_downloads else "Local / acervo externo"
            item = QTreeWidgetItem(groups[body], [profile["name"], access])
            item.setData(0, Qt.ItemDataRole.UserRole, profile["id"])
            if profile["id"] == selected_id:
                selected = item
        self.tree.collapseAll()
        if selected:
            self.tree.expandItem(selected.parent())
        self.tree.blockSignals(False)
        if selected:
            self.tree.setCurrentItem(selected)
        self._filter()

    def _selected(self, item, previous):
        if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        self.current_id = item.data(0, Qt.ItemDataRole.UserRole)
        profile = self.registry.profiles[self.current_id]
        self._loading = True
        custom = self.current_id.startswith("custom_")
        self.body.setReadOnly(not custom)
        self.name.setReadOnly(not custom)
        self.archive.setReadOnly(not custom)
        self.body.setText(profile["body"])
        self.name.setText(profile["name"])
        self.enabled.setChecked(profile.get("enabled", True))
        self.enabled.setEnabled(self.current_id != self.active_id)
        self.enabled.setToolTip("Troque de missão antes de ocultar a missão atualmente aberta.")
        self.grouping.setCurrentIndex(self.grouping.findData(profile["grouping"]))
        self.custom_folder.setChecked(bool(profile.get("folder_override")))
        self.folder.setText(profile.get("folder_override", ""))
        downloads = self.registry.source_for(self.current_id).supports_downloads
        self.access.setText(self.registry.source_for(self.current_id).download_description if downloads else "Coleção local e portal externo. Download automático ainda não integrado.")
        self.auto_download.setText("Atualizar automaticamente ao abrir esta missão" if self.registry.source_for(self.current_id).uses_sols else "Baixar próximo lote ao abrir esta missão")
        self.auto_download.setEnabled(downloads)
        self.auto_download.setChecked(bool(profile.get("auto_download")))
        self.start_sol.setEnabled(downloads and self.registry.source_for(self.current_id).uses_sols)
        self.start_sol.setValue(profile.get("start_sol", 0))
        self.grouping.setEnabled(not downloads)
        self.archive.setText(profile.get("archive_url", ""))
        self.archive_button.setEnabled(bool(self.archive.text()))
        self.remove.setEnabled(custom and self.current_id != self.active_id)
        self._loading = False
        self._preview()

    def _form_changed(self, *args):
        if self._loading or self.current_id is None:
            return
        profile = self.registry.profiles[self.current_id]
        profile.update(body=self.body.text().strip(), name=self.name.text().strip(), enabled=self.enabled.isChecked(),
                       grouping=self.grouping.currentData(), folder_override=self.folder.text().strip() if self.custom_folder.isChecked() else "",
                       auto_download=self.auto_download.isChecked(), start_sol=self.start_sol.value(), archive_url=self.archive.text().strip())
        self.archive_button.setEnabled(bool(self.archive.text()))
        self._preview()

    def _base_changed(self):
        self.registry.library_root = self.base_folder.text().strip()
        self._preview()

    def _preview(self):
        self.folder.setEnabled(self.custom_folder.isChecked())
        self.browse_folder.setEnabled(self.custom_folder.isChecked())
        try:
            folder = self.registry.folder_for(self.current_id) if self.current_id else None
            text = str(folder) if folder else "Escolha a pasta-base ou uma pasta personalizada."
        except ValueError as exc:
            text = str(exc)
        self.path_preview.setText(text)

    def _browse_base(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta-base das coleções", self.base_folder.text())
        if folder:
            self.base_folder.setText(folder)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta existente desta missão", self.folder.text() or self.base_folder.text())
        if folder:
            self.folder.setText(folder)

    def _open_archive(self):
        from urllib.parse import urlparse
        url = self.archive.text().strip()
        if urlparse(url).scheme in ("https", "http"):
            webbrowser.open(url)

    def _filter(self):
        wanted = self.search.text().casefold().strip()
        for index in range(self.tree.topLevelItemCount()):
            body = self.tree.topLevelItem(index)
            visible = False
            for child_index in range(body.childCount()):
                child = body.child(child_index)
                match = wanted in (body.text(0) + " " + child.text(0)).casefold()
                child.setHidden(not match)
                visible |= match
            body.setHidden(not visible)
            if wanted:
                body.setExpanded(visible)

    def _add_custom(self):
        identifier = self.registry.add_custom(self.body.text().strip() or "Outros", "Nova missão")
        self.search.clear()
        self._populate(identifier)
        self.name.setFocus()
        self.name.selectAll()

    def _remove_custom(self):
        if self.current_id and self.current_id != self.active_id and self.current_id.startswith("custom_"):
            del self.registry.profiles[self.current_id]
            self._populate("curiosity")

    def _save(self, open_selected=False):
        self._form_changed()
        try:
            self.registry.validate()
            if open_selected and (not self.current_id or not self.registry.profiles[self.current_id].get("enabled")):
                raise ValueError("Escolha uma missão habilitada para abrir.")
            if open_selected and self.registry.folder_for(self.current_id) is None:
                raise ValueError("Configure a pasta-base ou a pasta desta missão antes de abrir.")
        except ValueError as exc:
            QMessageBox.warning(self, "Revise a configuração", str(exc))
            return
        self.open_mission_id = self.current_id if open_selected else None
        self.accept()
