"""Adjustable median noise reduction, preserving image dimensions and alpha."""
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
from value_control import ValueControl
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QSlider,QSpinBox,QDialogButtonBox


def smooth_image(image, strength):
    if not 0 <= strength <= 100:
        raise ValueError('Intensidade inválida: use 0 a 100.')
    if not strength:
        return image.copy()
    alpha=image.getchannel('A') if 'A' in image.getbands() else None
    rgb=image.convert('RGB')
    result=Image.blend(rgb,rgb.filter(ImageFilter.MedianFilter(3)),strength/100)
    if alpha is not None:result.putalpha(alpha)
    return result

class SmoothingDialog(QDialog):
    def __init__(self,image,strength,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Suavizar imagem')
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Reduz ruído e granulação. 0 = desativado; 100 = máxima intensidade.'))
        width,height=image.size
        crop_width,crop_height=min(width,640),min(height,420)
        left,top=(width-crop_width)//2,(height-crop_height)//2
        self.sample=image.crop((left,top,left+crop_width,top+crop_height))
        self.filtered=smooth_image(self.sample,100)
        self.preview=QLabel();self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)
        layout.addWidget(QLabel('Prévia da região central, em pixels originais. O ajuste será aplicado à imagem inteira.'))
        layout.addWidget(QLabel('Intensidade:'))
        self.intensity=QSpinBox();self.intensity.setRange(0,100);self.intensity.setSuffix(' %')
        self.value_control=ValueControl(self.intensity,100,0)
        self.slider=self.value_control.slider
        layout.addWidget(self.value_control)
        self.intensity.valueChanged.connect(self.update_preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Aplicar')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.intensity.setValue(int(strength));self.update_preview()

    def update_preview(self,*args):
        from image_adjustments import apply_adjustments
        parent=self.parent()
        state=dict(parent._annotation_document.state) if parent is not None else {}
        state['smoothing']=self.intensity.value()
        image=apply_adjustments(self.sample,state)
        image=image.convert('RGBA')
        qimage=QImage(image.tobytes(),image.width,image.height,image.width*4,QImage.Format.Format_RGBA8888).copy()
        self.preview.setPixmap(QPixmap.fromImage(qimage))