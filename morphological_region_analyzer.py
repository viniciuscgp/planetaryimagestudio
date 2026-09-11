"""Classical, offline morphology inside an explicit user mask. No Qt or models."""
from dataclasses import dataclass
import math
import cv2
import numpy as np


@dataclass
class MorphologicalResult:
    origin: tuple
    mask: np.ndarray
    layers: dict
    metrics: dict
    structures: list
    summary: str


def contours(mask):
    found = cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
    return [c.reshape(-1,1,2) for c in found]


def geometry(mask):
    yy,xx = np.nonzero(mask)
    points = np.column_stack((xx,yy)).astype(np.float64)
    center = points.mean(axis=0)
    covariance = np.cov(points.T)
    values,vectors = np.linalg.eigh(covariance)
    axis = vectors[:,-1]
    angle = math.degrees(math.atan2(axis[1],axis[0])) % 180
    projected = (points-center) @ axis
    ends = np.array([center+axis*projected.min(), center+axis*projected.max()])
    elongation = math.sqrt(max(values[-1],1e-8)/max(values[0],1e-8))
    # Best reflection overlap across the two orthogonal PCA axes.
    symmetry = 0.0
    for reflection_axis in vectors.T:
        projection = (points-center) @ reflection_axis
        reflected = center + 2*np.outer(projection,reflection_axis) - (points-center)
        reflected = np.rint(reflected).astype(int)
        valid = ((reflected[:,0] >= 0)&(reflected[:,0] < mask.shape[1])&
                 (reflected[:,1] >= 0)&(reflected[:,1] < mask.shape[0]))
        intersection = int(mask[reflected[valid,1],reflected[valid,0]].sum())
        symmetry = max(symmetry,intersection/max(1,2*len(points)-intersection))
    return center,ends,angle,elongation,float(min(1,symmetry))


class MorphologicalRegionAnalyzer:
    def analyze(self, image, mask, cancel=None):
        def checkpoint():
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Análise cancelada')
        image,mask = np.asarray(image),np.asarray(mask)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('A imagem deve ser RGB uint8.')
        if mask.shape != image.shape[:2] or not np.isfinite(mask).all():
            raise ValueError('Máscara incompatível com a imagem.')
        if np.count_nonzero(mask) < 16:
            raise ValueError('Marque primeiro a área que deseja analisar.')
        checkpoint()
        yy,xx = np.nonzero(mask)
        x,y,w,h = int(xx.min()),int(yy.min()),int(xx.max()-xx.min()+1),int(yy.max()-yy.min()+1)
        if min(w,h) < 3:
            raise ValueError('Marque primeiro a área que deseja analisar.')
        roi = (mask[y:y+h,x:x+w] != 0).astype(np.uint8)
        gray = cv2.cvtColor(image[y:y+h,x:x+w],cv2.COLOR_RGB2GRAY)
        interior = cv2.erode(roi,np.ones((3,3),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)
        boundary = roi-interior
        values = gray[roi != 0]
        spread = float(values.std())
        # Normalized convolution avoids using pixels outside the user's selection.
        sigma = max(2,min(w,h)/12)
        blurred = cv2.GaussianBlur(gray.astype(np.float32)*roi,(0,0),sigma)
        support = cv2.GaussianBlur(roi.astype(np.float32),(0,0),sigma)
        background = blurred/np.maximum(support,1e-6)
        filled = gray.copy()
        filled[roi == 0] = np.uint8(np.median(values))
        edge_threshold = max(12,float(np.median(values))*.3)
        edges = cv2.Canny(filled,edge_threshold,edge_threshold*2) * interior
        checkpoint()
        # Foreground silhouette is an intensity-contrast estimate, not ROI geometry.
        silhouette = np.zeros_like(roi)
        if spread >= 3:
            threshold,_ = cv2.threshold(values.reshape(-1,1),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
            candidates = []
            for bright in (True,False):
                segmented = ((gray > threshold) if bright else (gray <= threshold)).astype(np.uint8)*roi
                count,labels,stats,_ = cv2.connectedComponentsWithStats(segmented,8)
                for label in range(1,count):
                    checkpoint()
                    area = int(stats[label,cv2.CC_STAT_AREA])
                    if area < max(16,.03*int(roi.sum())):
                        continue
                    component = (labels == label).astype(np.uint8)
                    contact = np.count_nonzero(component & boundary)/max(1,int(boundary.sum()))
                    # Prefer a substantial region enclosed by the selection.
                    candidates.append((area*(1-contact),component,contact))
            if candidates:
                _,candidate,contact = max(candidates,key=lambda v:v[0])
                if contact < .6 and candidate.sum() < roi.sum()*.95:
                    silhouette = candidate
        shape = silhouette if silhouette.any() else roi
        shape_source = 'silhueta estimada por contraste' if silhouette.any() else 'limite da marcação (silhueta não separável)'
        center,ends,angle,elongation,symmetry = geometry(shape)
        external = np.zeros_like(roi)
        concavities = np.zeros_like(roi)
        protrusions = np.zeros_like(roi)
        concavity_count = 0
        shape_contours = contours(shape)
        hull = np.zeros_like(roi)
        perimeter = 0.0
        for contour in shape_contours:
            perimeter += cv2.arcLength(contour,True)
            cv2.drawContours(hull,[cv2.convexHull(contour)],-1,1,-1)
            if silhouette.any():
                cv2.drawContours(external,[contour],-1,1,1)
                indices = cv2.convexHull(contour,returnPoints=False)
                if len(contour) >= 4 and len(indices) >= 3:
                    try:
                        defects = cv2.convexityDefects(contour,indices)
                    except cv2.error:
                        defects = None
                    if defects is not None:
                        for _,_,far,depth in defects.reshape(-1,4):
                            if depth/256 >= max(2,min(w,h)*.015):
                                point = tuple(contour[far,0])
                                cv2.circle(concavities,point,2,1,-1)
                                concavity_count += 1
                # Radial local maxima on a simplified contour are protrusion candidates.
                simplified = cv2.approxPolyDP(contour,max(1,perimeter*.005),True).reshape(-1,2)
                if len(simplified) >= 3:
                    radii = np.linalg.norm(simplified-center,axis=1)
                    for i,point in enumerate(simplified):
                        if radii[i] > max(radii[i-1],radii[(i+1)%len(radii)])*1.05:
                            cv2.circle(protrusions,tuple(point),2,1,-1)
        axis_layer = np.zeros_like(roi)
        cv2.line(axis_layer,tuple(np.rint(ends[0]).astype(int)),tuple(np.rint(ends[1]).astype(int)),1,1)
        checkpoint()
        dark = ((gray <= np.percentile(values,35)) &
                ((background-gray) >= max(6,spread*.35))).astype(np.uint8)*interior
        count,labels,stats,_ = cv2.connectedComponentsWithStats(dark,8)
        cavities = np.zeros_like(roi)
        fissures = np.zeros_like(roi)
        structures_layer = np.zeros_like(roi)
        structures = []
        _,support_labels,support_stats,_ = cv2.connectedComponentsWithStats(
            ((gray >= np.median(values)) & (roi != 0)).astype(np.uint8),8)
        for label in range(1,count):
            checkpoint()
            area = int(stats[label,cv2.CC_STAT_AREA])
            if area < 4:
                continue
            component = (labels == label).astype(np.uint8)
            cy,cx = np.nonzero(component)
            if len(cx) < 3:
                continue
            midpoint,endpoints,direction,ratio,_ = geometry(component)
            length = float(np.linalg.norm(endpoints[1]-endpoints[0])+1)
            ring = cv2.dilate(component,np.ones((5,5),np.uint8))*roi-component
            contrast = float(gray[ring != 0].mean()-gray[component != 0].mean()) if ring.any() else 0
            adjacent_labels = np.unique(support_labels[ring != 0])
            support_area = max((int(support_stats[i,cv2.CC_STAT_AREA]) for i in adjacent_labels if i > 0),default=0)
            is_fissure = ratio >= 3 and length >= 8
            target = fissures if is_fissure else cavities
            target[component != 0] = 1
            # Project into the PCA frame without clipping long vertical components.
            radians = np.deg2rad(direction)
            local_points = np.column_stack((cx,cy))-midpoint
            ax = np.rint(local_points @ np.array([np.cos(radians),np.sin(radians)])).astype(int)
            ay = local_points @ np.array([-np.sin(radians),np.cos(radians)])
            columns = np.unique(ax)
            top,bottom,valid_x = [],[],[]
            for column in columns:
                rows = ay[ax == column]
                if len(rows) >= 2:
                    valid_x.append(column);top.append(rows.min());bottom.append(rows.max())
            parallel = False
            side_error = None
            if len(valid_x) >= 8:
                upper = np.polyfit(valid_x,top,1)
                lower = np.polyfit(valid_x,bottom,1)
                side_error = float(max(np.std(np.array(top)-np.polyval(upper,valid_x)),
                                       np.std(np.array(bottom)-np.polyval(lower,valid_x))))
                parallel = abs(upper[0]-lower[0]) < .2 and side_error <= max(1.5,area/length*.3)
            touches_limit = bool(np.any(cv2.dilate(component,np.ones((3,3),np.uint8)) & boundary))
            opening = is_fissure and parallel and contrast >= 6 and not touches_limit
            if opening:
                structures_layer[component != 0] = 1
            structures.append(dict(kind='abertura geométrica' if opening else ('fissura candidata' if is_fissure else 'região escura'),
                x=int(cx.min()+x),y=int(cy.min()+y),area_px=area,length_px=length,
                width_px=float(area/max(length,1)),orientation_deg=direction,
                mean_intensity=float(gray[component != 0].mean()),contrast=contrast,
                parallel_edges=parallel,edge_fit_error_px=side_error,
                endpoints_defined=not touches_limit,
                adjacent_larger_light_region=support_area > 2*area,
                adjacent_light_region_area_px=support_area,
                surrounding_support=float(np.count_nonzero(ring))/max(1,int(area)),
                endpoints=[[float(p[0]+x),float(p[1]+y)] for p in endpoints]))
        checkpoint()
        # Internal divisions and linear structures, independent of dark components.
        lines = cv2.HoughLinesP(edges,1,np.pi/180,threshold=max(8,min(w,h)//8),
                                minLineLength=max(8,min(w,h)//8),maxLineGap=3)
        line_count = 0
        if lines is not None:
            for x1,y1,x2,y2 in lines.reshape(-1,4)[:200]:
                cv2.line(structures_layer,(x1,y1),(x2,y2),1,1)
                line_count += 1
        edge_components = sum(cv2.arcLength(c,False) >= 8 for c in contours(edges))
        curve_count = sum(cv2.arcLength(c,False) > max(8,1.5*max(cv2.boundingRect(c)[2:]))
                          for c in contours(edges))
        layers = dict(external=external,edges=(edges > 0).astype(np.uint8),fissures=fissures,
                      cavities=cavities,axis=axis_layer,concavities=concavities,
                      protrusions=protrusions,structures=structures_layer)
        layers = {k:v*roi for k,v in layers.items()}
        metrics = dict(selection_area_px=int(roi.sum()),shape_area_px=int(shape.sum()),
                       width_px=w,height_px=h,shape_source=shape_source,perimeter_px=float(perimeter),
                       solidity=float(shape.sum()/max(1,hull.sum())),symmetry=symmetry,
                       orientation_deg=angle,elongation=elongation,concavities=concavity_count,
                       protrusion_candidates=len(contours(protrusions)),line_segments=line_count,
                       internal_edge_structures=edge_components,
                       curved_edge_candidates=curve_count,
                       fissure_candidates=sum(s['kind'] != 'região escura' for s in structures),
                       dark_regions=sum(s['kind'] == 'região escura' for s in structures))
        openings = [s for s in structures if s['kind'] == 'abertura geométrica']
        form = 'alongada' if elongation >= 2 else 'pouco alongada'
        summary = f'A {"silhueta estimada" if silhouette.any() else "área marcada"} é {form}. '
        if openings:
            strongest = max(openings,key=lambda s:s['length_px'])
            horizontal = min(strongest['orientation_deg'],180-strongest['orientation_deg']) <= 20
            summary += (f"Foi detectada uma abertura {'aproximadamente horizontal' if horizontal else 'oblíqua ou vertical'} escura "
                        f"com {strongest['length_px']:.0f} px de comprimento e duas bordas aproximadamente paralelas. ")
            if strongest['adjacent_larger_light_region']:
                summary += 'Há uma região mais clara e de maior área junto ao seu entorno. '
        else:
            summary += f"Foram encontradas {metrics['fissure_candidates']} fissuras candidatas e {metrics['dark_regions']} regiões escuras. "
        if not silhouette.any():
            summary += 'A silhueta não pôde ser separada com segurança pelo contraste; as medidas de forma descrevem a marcação. '
        summary += 'Regiões escuras são candidatas a cavidades; uma imagem isolada não determina profundidade.'
        return MorphologicalResult((x,y),roi,layers,metrics,structures,summary)
