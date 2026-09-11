"""Non-destructive levels and sharpening, with a shared adjustment pipeline."""
import copy
from PIL import Image,ImageFilter,ImageEnhance,ImageOps,ImageStat
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QSpinBox,QDoubleSpinBox,QDialogButtonBox
from image_smoothing import smooth_image
from value_control import ValueControl


def balance_colors(image):
    """Conservative gray-world estimate; only channel gains, no spatial changes."""
    sample = image.copy()
    sample.thumbnail((256, 256))
    mask = sample.getchannel('A') if 'A' in sample.getbands() else None
    if mask is not None and not mask.getbbox():
        return image.copy()
    means = ImageStat.Stat(sample.convert('RGB'), mask=mask).mean
    # Missing channels cannot be reconstructed reliably.
    if min(means) < 1:
        return image.copy()
    target = sum(means) / 3
    gains = [1 + .75 * (max(.67, min(1.5, target / mean)) - 1) for mean in means]
    lut = [max(0, min(255, round(value * gain))) for gain in gains for value in range(256)]
    result = image.convert('RGB').point(lut)
    if 'A' in image.getbands():
        result.putalpha(image.getchannel('A'))
    return result


def percentile_stretch(image, low=1, high=99, valid_mask=None):
    """Per-channel linear stretch; black/transparent pixels do not set bounds."""
    import numpy as np
    if not 0 <= low < high <= 100:
        raise ValueError('O percentil inferior deve ser menor que o superior (0–100).')
    rgb = np.asarray(image.convert('RGB'))
    valid = rgb.max(axis=2) > 5 if valid_mask is None else np.array(valid_mask,dtype=bool,copy=True)
    if 'A' in image.getbands():
        valid &= np.asarray(image.getchannel('A')) > 0
    if not valid.any():
        return image.copy()
    bounds = np.percentile(rgb[valid],(low,high),axis=0)
    result = rgb.copy()
    for channel in range(3):
        lower,upper = bounds[:,channel]
        if upper > lower:
            result[:,:,channel] = np.rint(np.clip((rgb[:,:,channel].astype(float)-lower)*255/(upper-lower),0,255)).astype(np.uint8)
    output = Image.fromarray(result)
    if 'A' in image.getbands():
        output.putalpha(image.getchannel('A'))
    return output


def detect_useful_area(image):
    """Estimate the bright valid field; reject transparency and near-black vignette."""
    import cv2
    import numpy as np
    rgb = np.asarray(image.convert('RGB'))
    visible = np.ones(rgb.shape[:2],dtype=bool)
    if 'A' in image.getbands():
        visible &= np.asarray(image.getchannel('A')) > 0
    if not visible.any():
        return visible
    brightness = rgb.max(axis=2)
    cutoff = max(5,min(20,float(np.percentile(brightness[visible],95))*.06))
    valid = visible & (brightness > cutoff)
    count,labels,stats,_ = cv2.connectedComponentsWithStats(valid.astype(np.uint8),8)
    if count > 2:
        largest = 1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))
        if stats[largest,cv2.CC_STAT_AREA] >= .9*np.count_nonzero(valid):
            valid = labels == largest
    return valid


def protect_highlights(rgb):
    """Smooth shared RGB shoulder: retain ordering and hue instead of hard clipping."""
    import numpy as np
    peak = rgb.max(axis=2)
    compressed = 220+30*(-np.expm1(-np.maximum(peak-220,0)/30))
    scale = np.where(peak > 220,compressed/np.maximum(peak,1),1)
    return rgb*scale[:,:,None]


def natural_percentile_stretch(image, valid):
    """Gentle luminance stretch with a shared gain, preserving RGB proportions."""
    import numpy as np
    rgb = np.asarray(image.convert('RGB')).astype(np.float64)
    if not valid.any():
        return image.copy()
    luminance = rgb @ np.array([.2126,.7152,.0722])
    lower,upper = np.percentile(luminance[valid],[1,99])
    if upper > lower:
        expanded = 18+(luminance-lower)*min(2.0,202/(upper-lower))
        target = np.maximum(.35*luminance+.65*expanded,.65*luminance)
        gain = np.divide(target,luminance,out=np.ones_like(target),where=luminance > 1e-8)
        rgb = rgb*gain[:,:,None]
    rgb = protect_highlights(rgb)
    output = Image.fromarray(np.uint8(np.rint(np.clip(rgb,0,255))))
    if 'A' in image.getbands():
        output.putalpha(image.getchannel('A'))
    return output


def gray_world_balance(image, valid):
    import numpy as np
    rgb = np.asarray(image.convert('RGB')).astype(np.float64)
    if not valid.any():
        return image.copy()
    means = rgb[valid].mean(axis=0)
    # A zero channel cannot be recovered by a multiplicative correction.
    if np.any(means <= 1e-8):
        return image.copy()
    gains = np.clip(means.mean()/means,.85,1.15)
    gains = 1+.15*(gains-1)
    result = Image.fromarray(np.uint8(np.rint(np.clip(protect_highlights(rgb*gains),0,255))))
    if 'A' in image.getbands():
        result.putalpha(image.getchannel('A'))
    return result


def auto_enhance_masks(image):
    """Keep display support separate from a conservative interior statistics mask."""
    import cv2
    import numpy as np
    support = detect_useful_area(image)
    if not support.any():
        return support,support.copy()
    # A gray camera surround can be well above the near-black cutoff. Accept
    # an Otsu component only when its outline actually fits an enclosed ellipse.
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    smooth = cv2.GaussianBlur(gray,(0,0),max(1,min(gray.shape)*.004))
    _,binary = cv2.threshold(smooth,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    contours,_ = cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        contour = max(contours,key=cv2.contourArea)
        if len(contour) >= 5:
            ellipse = cv2.fitEllipse(contour)
            (cx,cy),(ew,eh),angle = ellipse
            fitted = np.zeros(gray.shape,np.uint8)
            cv2.ellipse(fitted,ellipse,1,-1)
            filled = np.zeros_like(fitted)
            cv2.drawContours(filled,[contour],-1,1,-1)
            overlap = np.count_nonzero(fitted & filled)/max(1,np.count_nonzero(fitted | filled))
            bx,by,bw,bh = cv2.boundingRect(contour)
            if (.25 < fitted.mean() < .88 and overlap > .94 and
                    min(ew,eh)/max(ew,eh) > .75 and bx > 0 and by > 0 and
                    bx+bw < gray.shape[1] and by+bh < gray.shape[0]):
                support &= fitted.astype(bool)
    yy,xx = np.nonzero(support)
    w,h = xx.max()-xx.min()+1,yy.max()-yy.min()+1
    center_x,center_y = (xx.max()+xx.min())/2,(yy.max()+yy.min())/2
    gy,gx = np.ogrid[:support.shape[0],:support.shape[1]]
    # A dark surround suggests a circular camera field. Avoid cutting ordinary
    # full-frame rectangular photographs into a circle.
    if support.mean() < .9:
        # Follow the detected field, including an elliptical/off-center outline.
        # Trim its transition rim rather than sampling only the central hotspot.
        distance = cv2.distanceTransform(np.pad(support.astype(np.uint8),1),cv2.DIST_L2,5)[1:-1,1:-1]
        interior = distance > max(2,.06*min(w,h))
    else:
        margin = max(1,round(min(w,h)*.12))
        interior = ((gx >= xx.min()+margin)&(gx <= xx.max()-margin)&
                    (gy >= yy.min()+margin)&(gy <= yy.max()-margin))
    brightness = np.asarray(image.convert('RGB')).max(axis=2)
    cutoff = max(10,float(np.percentile(brightness[support],90))*.18)
    statistics = support & interior & (brightness > cutoff)
    # No fallback to the dark rim when the conservative interior is unusable.
    return support,statistics


def correct_illumination(image, statistics, support):
    """Broad normalized convolution of LAB L; bounded, partial gain correction."""
    import cv2
    import numpy as np
    rgb = np.array(image.convert('RGB'),copy=True)
    field = np.zeros(statistics.shape,np.float32)
    if not statistics.any():
        return image.copy(),field
    lab = cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
    luminance = lab[:,:,0].astype(np.float32)
    yy,xx = np.nonzero(statistics)
    sigma = max(3,.12*min(xx.max()-xx.min()+1,yy.max()-yy.min()+1))
    weights = statistics.astype(np.float32)
    numerator = cv2.GaussianBlur(luminance*weights,(0,0),sigma,borderType=cv2.BORDER_CONSTANT)
    denominator = cv2.GaussianBlur(weights,(0,0),sigma,borderType=cv2.BORDER_CONSTANT)
    field = np.divide(numerator,denominator,out=np.full_like(luminance,float(np.median(luminance[statistics]))),
                      where=denominator > 1e-6)
    target = float(np.percentile(field[statistics],40))
    gain = np.clip(target/np.maximum(field,1),.55,1.15)
    # A common RGB gain derived from L avoids chromatic shifts and LAB gamut clipping.
    corrected = np.uint8(np.rint(np.clip(protect_highlights(rgb.astype(float)*gain[:,:,None]),0,255)))
    rgb[support] = corrected[support]
    result = Image.fromarray(rgb)
    if 'A' in image.getbands():
        result.putalpha(image.getchannel('A'))
    field[~support] = 0
    return result,field


def masked_luminance_clahe(image, valid, feather=False):
    import cv2
    import numpy as np
    if not valid.any():
        return image.copy()
    rgb = np.array(image.convert('RGB'),copy=True)
    yy,xx = np.nonzero(valid)
    x0,x1,y0,y1 = xx.min(),xx.max()+1,yy.min(),yy.max()+1
    patch = rgb[y0:y1,x0:x1]
    mask = valid[y0:y1,x0:x1]
    lab = cv2.cvtColor(patch,cv2.COLOR_RGB2LAB)
    luminance = lab[:,:,0].copy()
    if not mask.all():
        # Extend valid luminance into holes/corners before CLAHE so invalid black
        # pixels never populate its histograms. Output outside the mask is restored.
        _,labels = cv2.distanceTransformWithLabels((~mask).astype(np.uint8),cv2.DIST_L2,5,
                                                  labelType=cv2.DIST_LABEL_PIXEL)
        lookup = np.zeros(int(labels.max())+1,dtype=np.uint8)
        lookup[labels[mask]] = luminance[mask]
        luminance = lookup[labels]
    proposal = cv2.createCLAHE(clipLimit=1.8,tileGridSize=(8,8)).apply(luminance)
    delta = np.clip(.65*(proposal.astype(float)-lab[:,:,0]),-18,18)
    # Limit positive L changes where any RGB channel already approaches highlights.
    headroom = np.maximum(240-patch.max(axis=2).astype(float),0)/3
    delta = np.minimum(delta,headroom)
    lab[:,:,0] = np.uint8(np.rint(np.clip(lab[:,:,0].astype(float)+delta,0,255)))
    enhanced = cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)
    if feather:
        padded = np.pad(mask.astype(np.uint8),1)
        distance = cv2.distanceTransform(padded,cv2.DIST_L2,5)[1:-1,1:-1]
        weight = np.clip(distance/max(2,min(mask.shape)*.03),0,1)[:,:,None]
        enhanced = np.uint8(np.rint(patch*(1-weight)+enhanced*weight))
    patch[mask] = enhanced[mask]
    output = Image.fromarray(rgb)
    if 'A' in image.getbands():
        output.putalpha(image.getchannel('A'))
    return output


def mars_scene_chroma(source_lab, valid):
    """Bounded aesthetic cast correction toward a slightly warm terrain palette.

    Estimate the global cast only from valid midtones, never the dark surround.
    A shared offset preserves local chroma differences; this is not calibration.
    """
    import numpy as np
    chroma = source_lab[:,:,1:].astype(float)-128
    samples = valid & (source_lab[:,:,0] > 30) & (source_lab[:,:,0] < 235)
    if samples.any():
        values = chroma[samples]
        median = np.median(values,axis=0)
        # Only correct a dominant green cast, not neutral or already warm scenes.
        if median[0] < -1 and np.mean(values[:,0] < -1) > .65:
            chroma[:,:,0] += min(12,3-median[0])
            chroma[:,:,1] += np.clip(8-median[1],-10,0)
    return np.uint8(np.rint(np.clip(128+chroma,0,255)))


def auto_enhance_mars_image(image, valid_mask=None, stages=None):
    """Approved preset: exactly the standalone RGB percentile stretch at 32/99."""
    import numpy as np
    rgb = np.asarray(image.convert('RGB'))
    valid = rgb.max(axis=2) > 5 if valid_mask is None else np.array(valid_mask,dtype=bool,copy=True)
    if 'A' in image.getbands():
        valid &= np.asarray(image.getchannel('A')) > 0
    result = percentile_stretch(image,32,99,valid)
    if stages is not None:
        # Retain export names for compatibility; disabled stages are passthrough.
        stages.update(original=image.copy(),valid_mask=Image.fromarray(np.uint8(valid)*255),
                      support_mask=Image.fromarray(np.uint8(valid)*255),
                      illumination=np.zeros(valid.shape,np.float32),illumination_corrected=image.copy(),
                      percentile=result.copy(),white_balance=result.copy(),final_clahe=result.copy())
    return result


def save_auto_enhance_stages(image, folder):
    """Create a fresh debug folder; never overwrite the original or old exports."""
    from pathlib import Path
    import tempfile
    import json
    import numpy as np
    stages = {}
    auto_enhance_mars_image(image,stages=stages)
    destination = Path(tempfile.mkdtemp(prefix='auto_enhance_stages_',dir=folder))
    for index,(name,value) in enumerate(stages.items()):
        if name == 'illumination':
            np.save(destination/'illumination_lab_l.npy',value)
            value = Image.fromarray(np.uint8(np.rint(np.clip(value,0,255))))
        value.save(destination/f'{index:02}_{name}.png')
    (destination/'parameters.json').write_text(json.dumps({
        'source':'clean EXIF-oriented original, before all manual adjustments and drawings',
        'preset':'manual_percentile_32_99',
        'statistics':'same as standalone: max(R,G,B)>5 and alpha>0; gray surround may remain in samples',
        'percentiles':[32,99], 'stretch':'exact standalone per-channel RGB formula, original image',
        'illumination':'disabled; exported zero field is a placeholder, not an estimate',
        'correction':'disabled; illumination_corrected equals original',
        'white_balance':'disabled; passthrough from percentile',
        'clahe':{'enabled':False,'export':'final_clahe is a compatibility name for the final result'},
        'stage_statistics':{key:{'near_white_channel_fraction':float(np.mean(np.asarray(value.convert('RGB'))[
            np.asarray(stages['valid_mask']) > 0] >= 254)) if np.asarray(stages['valid_mask']).any() else 0}
            for key,value in stages.items() if isinstance(value,Image.Image) and value.mode in ('RGB','RGBA')},
        'gamma':1.0, 'illumination_units':'LAB L encoded as 0..255; NPY float32, PNG rounded',
    },indent=2),encoding='utf-8')
    return destination


def apply_adjustments(image,state):
    valid = None
    if state.get('percentile_stretch',False):
        import numpy as np
        valid = np.asarray(image.convert('RGB')).max(axis=2) > 5
        if 'A' in image.getbands():
            valid &= np.asarray(image.getchannel('A')) > 0
    if state.get('auto_enhance_mars',False):
        image = auto_enhance_mars_image(image)
    if state.get('color_balance', False):
        image = balance_colors(image)
    image=smooth_image(image,state.get('smoothing',0))
    alpha=image.getchannel('A') if 'A' in image.getbands() else None
    image=image.convert('RGB')
    black,white,gamma=state.get('black_point',0),state.get('white_point',255),state.get('gamma',1)
    if (black,white,gamma)!=(0,255,1):
        lut=[round(255*(max(0,min(1,(v-black)/(white-black)))**(1/gamma))) for v in range(256)]
        image=image.point(lut*3)
    if state.get('brightness',100)!=100:image=ImageEnhance.Brightness(image).enhance(state['brightness']/100)
    if state.get('contrast',1)!=1:image=ImageEnhance.Contrast(image).enhance(state['contrast'])
    if state.get('saturation',1)!=1:image=ImageEnhance.Color(image).enhance(state['saturation'])
    if state.get('inverted',False):image=ImageOps.invert(image)
    if state.get('sharpness',0):image=image.filter(ImageFilter.UnsharpMask(radius=1.5,percent=int(state['sharpness']),threshold=3))
    if alpha is not None:image.putalpha(alpha)
    if state.get('percentile_stretch',False):
        image = percentile_stretch(image,state.get('percentile_low',1),state.get('percentile_high',99),valid)
    return image

class AdjustmentDialog(QDialog):
    def __init__(self,image,state,kind,parent=None):
        super().__init__(parent)
        self.state=copy.deepcopy(state);self.controls={};self.value_controls={}
        self.setWindowTitle({'levels':'Níveis','sharpness':'Nitidez','brightness':'Brilho'}[kind])
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel({'levels':'Ajuste sombras, meios-tons e luzes.', 'sharpness':'Realça bordas e texturas. 0 = desativado.', 'brightness':'100% = original; abaixo escurece, acima clareia.'}[kind]))
        w,h=image.size;cw,ch=min(w,640),min(h,420)
        self.sample=image.crop(((w-cw)//2,(h-ch)//2,(w-cw)//2+cw,(h-ch)//2+ch))
        self.preview=QLabel();self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.preview)
        layout.addWidget(QLabel('Prévia central em pixels originais, com os ajustes atuais.'))
        form=QFormLayout();layout.addLayout(form)
        fields=[('Preto','black_point',0,254),('Branco','white_point',1,255),('Meios-tons','gamma',0.1,5)] if kind=='levels' else [('Brilho (%)','brightness',0,200)] if kind=='brightness' else [('Intensidade (%)','sharpness',0,300)]
        for label,key,low,high in fields:
            spin=QDoubleSpinBox() if key=='gamma' else QSpinBox()
            spin.setRange(low,high)
            if key=='gamma':spin.setSingleStep(0.1);spin.setDecimals(2)
            spin.setValue(self.state[key]);self.controls[key]=spin
            default={"black_point":0,"white_point":255,"gamma":1,"sharpness":0,"brightness":100}[key]
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
