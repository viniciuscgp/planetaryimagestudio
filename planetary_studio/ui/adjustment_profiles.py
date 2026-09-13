"""Three reusable pixel-adjustment presets stored with the application session."""
import copy

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QToolBar, QWidget

from planetary_studio.annotations.image_annotations import empty_state, validate_state


PROFILE_KEYS = tuple(key for key in empty_state() if key not in ('drawings','rotation'))


def load_profiles(value):
    profiles = [None,None,None]
    if not isinstance(value,list):
        return profiles
    for index,entry in enumerate(value[:3]):
        if not isinstance(entry,dict) or not all(key in entry for key in PROFILE_KEYS):
            continue
        try:
            state = empty_state()
            state.update({key:entry[key] for key in PROFILE_KEYS})
            validate_state(state)
            profiles[index] = {key:state[key] for key in PROFILE_KEYS}
        except (ValueError,TypeError,KeyError):
            pass
    return profiles


class AdjustmentProfilesMixin:
    def _build_adjustment_profiles(self):
        self._profile_buttons = []
        toolbar = self.profile_toolbar = QToolBar('Perfis de ajustes',self)
        toolbar.setObjectName('adjustment_profiles_toolbar')
        self.addToolBarBreak()
        self.addToolBar(toolbar)
        for index in range(3):
            group = QWidget()
            row = QHBoxLayout(group)
            row.setContentsMargins(4,2,8,2)
            row.setSpacing(3)
            apply = QPushButton(f'Perfil {index+1}')
            apply.setCheckable(True)
            save = QPushButton('Salvar')
            save.setToolTip(f'Gravar os ajustes atuais no Perfil {index+1}, substituindo o conteúdo anterior.')
            apply.clicked.connect(lambda checked=False,i=index:self._apply_adjustment_profile(i))
            save.clicked.connect(lambda checked=False,i=index:self._save_adjustment_profile(i))
            row.addWidget(apply);row.addWidget(save)
            toolbar.addWidget(group)
            self._profile_buttons.append((apply,save))
        toolbar.addWidget(QLabel('Clique no perfil para aplicar · Salvar guarda os ajustes atuais'))
        self._sync_adjustment_profiles()

    def _sync_adjustment_profiles(self):
        ready = self.original_image is not None and self._annotation_document is not None
        pending = getattr(self,'_inline_pending',{})
        for index,(apply,save) in enumerate(getattr(self,'_profile_buttons',[])):
            profile = self._adjustment_profiles[index]
            apply.setEnabled(ready and profile is not None)
            save.setEnabled(ready)
            matches = ready and profile is not None and all(
                pending.get(key,getattr(self,key)) == profile[key] for key in PROFILE_KEYS)
            apply.setChecked(bool(matches))
            apply.setToolTip(f'Aplicar Perfil {index+1}. Destaque indica ajustes iguais aos atuais.' if profile is not None
                             else f'Perfil {index+1} vazio. Use Salvar ao lado para gravar os ajustes.')

    def _save_adjustment_profile(self,index):
        if self.original_image is None or self._annotation_document is None:
            return
        self._flush_inline_adjustments()
        previous = copy.deepcopy(self._adjustment_profiles)
        self._adjustment_profiles[index] = {key:getattr(self,key) for key in PROFILE_KEYS}
        if not self._save_state():
            self._adjustment_profiles = previous
            self._state['adjustment_profiles'] = copy.deepcopy(previous)
            QMessageBox.warning(self,'Perfil não salvo','Não foi possível gravar o perfil. Verifique a pasta de configurações.')
        else:
            self.statusBar().showMessage(f'Perfil {index+1} salvo com os ajustes atuais.',4000)
        self._sync_adjustment_profiles()

    def _apply_adjustment_profile(self,index):
        profile = self._adjustment_profiles[index]
        if profile is None or self.original_image is None or self._annotation_document is None:
            return
        self._flush_inline_adjustments()
        state = copy.deepcopy(self._annotation_document.state)
        state.update(profile)
        self._annotation_document.commit(state)
        self._apply_annotation_state()
        self._render_current(fit=False)
        self._persist_annotations()
        self.statusBar().showMessage(f'Perfil {index+1} aplicado. Desfazer restaura os ajustes anteriores.',4000)
