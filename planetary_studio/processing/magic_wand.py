"""Connected fixed-range pixel selection. Never alters the input image."""
import cv2
import numpy as np


def select_connected(image, seed, tolerance=20, luminosity=False, connectivity=4):
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('A imagem deve ser RGB uint8.')
    x,y = seed
    height,width = image.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError('Clique dentro da imagem.')
    if not 0 <= tolerance <= 255 or connectivity not in (4,8):
        raise ValueError('Tolerância ou conectividade inválida.')
    data = cv2.cvtColor(image,cv2.COLOR_RGB2GRAY) if luminosity else image.copy()
    flood_mask = np.zeros((height+2,width+2),np.uint8)
    difference = int(tolerance) if luminosity else (int(tolerance),)*3
    flags = connectivity | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (1 << 8)
    cv2.floodFill(data,flood_mask,(int(x),int(y)),0,difference,difference,flags)
    return flood_mask[1:-1,1:-1].copy()


def mask_to_annotation(mask, color='#00c8ff', width=2):
    """Convert the mask to editable closed contours, retaining interior holes."""
    found,_ = cv2.findContours(np.uint8(mask),cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
    points,rings = [],[]
    for contour in found:
        contour = contour.reshape(-1,2)
        if len(contour) < 3 or abs(cv2.contourArea(contour)) < 1:
            continue
        # Pixel-center contours; polygon rasterization can differ at edge pixels.
        ring = contour.astype(float).tolist()
        points.extend(ring)
        rings.append(len(ring))
    if not rings or np.count_nonzero(mask) < 16:
        raise ValueError('Seleção pequena demais. Aumente a tolerância ou clique em outra área.')
    return dict(kind='polygon',points=points,rings=rings,color=color,width=width)
