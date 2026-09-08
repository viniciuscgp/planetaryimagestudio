"""Non-destructive levels and sharpening, with a shared adjustment pipeline."""
import copy
from PIL import Image,ImageFilter,ImageEnhance,ImageOps
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QSpinBox,QDoubleSpinBox,QDialogButtonBox
from image_smoothing import smooth_image
from value_control import ValueControl


def apply_adjustments(image,state):
    image=smooth_image(image,state.get('smoothing',0))
    alpha=image.getchannel('A') if 'A' in image.getbands() else None
    image=image.convert('RGB')
    black,white,gamma=state.get('black_point',0),state.get('white_point',255),state.get('gamma',1)
    if (black,white,gamma)!=(0,255,1):
        lut=[round(255*(max(0,min(1,(v-black)/(white-black)))**(1/gamma))) for v in range(256)]
        image=image.point(lut*3)
    if state.get('contrast',1)!=1:image=ImageEnhance.Contrast(image).enhance(state['contrast'])
    if state.get('saturation',1)!=1:image=ImageEnhance.Color(image).enhance(state['saturation'])
    if state.get('inverted',False):image=ImageOps.invert(image)
    if state.get('sharpness',0):image=image.filter(ImageFilter.UnsharpMask(radius=1.5,percent=int(state['sharpness']),threshold=3))
    if alpha is not None:image.putalpha(alpha)
    return image

class AdjustmentDialog(QDialog):
    def __init__(self,image,state,kind,parent=None):
        super().__init__(parent)
        self.state=copy.deepcopy(state);self.controls={};self.value_controls={}
        self.setWindowTitle('Níveis' if kind=='levels' else 'Nitidez')
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Ajuste sombras, meios-tons e luzes.' if kind=='levels' else 'Realça bordas e texturas. 0 = desativado.'))
        w,h=image.size;cw,ch=min(w,640),min(h,420)
        self.sample=image.crop(((w-cw)//2,(h-ch)//2,(w-cw)//2+cw,(h-ch)//2+ch))
        self.preview=QLabel();self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.preview)
        layout.addWidget(QLabel('Prévia central em pixels originais, com os ajustes atuais.'))
        form=QFormLayout();layout.addLayout(form)
        fields=[('Preto','black_point',0,254),('Branco','white_point',1,255),('Meios-tons','gamma',0.1,5)] if kind=='levels' else [('Intensidade (%)','sharpness',0,300)]
        for label,key,low,high in fields:
            spin=QDoubleSpinBox() if key=='gamma' else QSpinBox()
            spin.setRange(low,high)
            if key=='gamma':spin.setSingleStep(0.1);spin.setDecimals(2)
            spin.setValue(self.state[key]);self.controls[key]=spin
            default={"black_point":0,"white_point":255,"gamma":1,"sharpness":0}[key]
            control=ValueControl(spin,high,default)
            self.value_controls[key]=control
            form.addRow(label,control)
            spin.valueChanged.connect(self.update_preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Aplicar');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.update_preview()
    def update_preview(self,*args):
        if 'black_point' in self.controls:
            self.controls['black_point'].setMaximum(self.controls['white_point'].value()-1)
            self.controls['white_point'].setMinimum(self.controls['black_point'].value()+1)
        for control in self.value_controls.values():control.refresh()
        self.state.update({key:spin.value() for key,spin in self.controls.items()})
        image=apply_adjustments(self.sample,self.state).convert('RGBA')
        result=QImage(image.tobytes(),image.width,image.height,image.width*4,QImage.Format.Format_RGBA8888).copy()
        self.preview.setPixmap(QPixmap.fromImage(result))