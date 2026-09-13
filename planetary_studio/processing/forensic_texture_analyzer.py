"""Offline texture measurements. Arrays are RGB uint8, in original image coordinates.

Scores describe statistical differences, not evidence or probabilities of editing.
No Qt dependencies and no writes to the input image or its source file.
"""
from dataclasses import dataclass
import csv
import json
from pathlib import Path

import cv2
import numpy as np


METRICS = {
    'high_frequency': 'High frequency',
    'fine_coarse': 'Fine/coarse',
    'gradient': 'Gradient',
    'fft': 'FFT',
    'compression': 'Compression grid',
    'rgb': 'RGB correlation',
    'boundary': 'Boundary',
}


@dataclass
class TextureResult:
    image: np.ndarray
    regions: list
    maps: dict
    scale_maps: dict
    weights: dict
    top_regions: list

    def region_at(self, x, y):
        candidates = [r for r in self.regions if r['x'] <= x < r['x'] + r['width']
                      and r['y'] <= y < r['y'] + r['height']]
        return max(candidates, key=lambda r: r['score']) if candidates else None

    def export_csv(self, path):
        with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.regions[0]))
            writer.writeheader()
            writer.writerows(self.regions)

    def export_maps(self, folder):
        """Lossless numeric float32 maps plus fixed 0..1 color previews, per scale too."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        arrays = dict(self.maps)
        for size, maps in self.scale_maps.items():
            arrays.update({f'{size}_{key}': value for key, value in maps.items()})
        np.savez_compressed(folder / 'metric_maps.npz', **arrays)
        for key, value in arrays.items():
            write_png(folder / f'{key}.png', colorize(value))
        raw_fields = ('high_frequency_rms', 'fine_coarse_ratio', 'mean_gradient',
                      'fft_peak', 'compression_strength', 'rgb_rg', 'rgb_rb', 'rgb_gb',
                      'boundary_difference')
        raw_ranges = {}
        for size in self.scale_maps:
            regions = [r for r in self.regions if r['window_size'] == size]
            raw = {key: ForensicTextureAnalyzer.build_anomaly_map(
                regions, [r[key] for r in regions], self.image.shape[:2], clip=False)
                   for key in raw_fields}
            np.savez_compressed(folder / f'raw_metrics_{size}.npz', **raw)
            for key, value in raw.items():
                low, high = float(value.min()), float(value.max())
                raw_ranges[f'{size}_{key}'] = [low, high]
                preview = (value-low)/(high-low) if high > low else np.zeros_like(value)
                write_png(folder / f'raw_{size}_{key}.png', colorize(preview))
        (folder / 'analysis.json').write_text(json.dumps({
            'version': 1, 'shape': list(self.image.shape), 'scales': list(self.scale_maps),
            'weights': self.weights, 'coordinates': 'EXIF-oriented original; x/y top-left, zero based',
            'score': 'Relative texture anomaly, not manipulation probability',
            'normalization': 'robust global / brightness peers / immediate neighbors: 0.2 / 0.3 / 0.5',
            'fusion': 'equal scale mean blended 50% with maximum scale response',
            'raw_preview_ranges': raw_ranges,
            'raw_units': 'RMS/gradient in 8-bit gray levels; energies in squared levels; ratios dimensionless',
        }, indent=2), encoding='utf-8')


def colorize(values):
    return cv2.cvtColor(cv2.applyColorMap(np.uint8(np.clip(values, 0, 1) * 255),
                                         cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)


def write_png(path, rgb):
    # imencode + Python IO supports Unicode paths on Windows.
    ok, data = cv2.imencode('.png', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise OSError('Unable to encode PNG')
    Path(path).write_bytes(data.tobytes())


class ForensicTextureAnalyzer:
    def __init__(self, window_sizes=(32, 64, 128), weights=None):
        self.window_sizes = tuple(sorted(set(window_sizes)))
        if not self.window_sizes or any(s not in (32, 64, 128) for s in self.window_sizes):
            raise ValueError('Select one or more window sizes: 32, 64, 128')
        self.weights = {key: float((weights or {}).get(key, 1)) for key in METRICS}
        if any(not np.isfinite(v) or v < 0 for v in self.weights.values()):
            raise ValueError('Weights must be finite and nonnegative')

    @staticmethod
    def high_frequency_analysis(gray):
        residual = gray - cv2.GaussianBlur(gray, (0, 0), 1)
        return residual

    @staticmethod
    def fine_coarse_analysis(gray):
        return cv2.GaussianBlur(gray, (0, 0), 2) - cv2.GaussianBlur(gray, (0, 0), 4)

    @staticmethod
    def fft_analysis(block):
        h, w = block.shape
        tapered = (block - block.mean()) * np.outer(np.hanning(h), np.hanning(w))
        power = np.abs(np.fft.fftshift(np.fft.fft2(tapered))) ** 2
        yy, xx = np.meshgrid(np.fft.fftshift(np.fft.fftfreq(h)),
                             np.fft.fftshift(np.fft.fftfreq(w)), indexing='ij')
        radius = np.hypot(xx, yy)
        power[radius == 0] = 0
        total = power.sum()
        if total < 1e-10:
            return np.zeros(9)
        power /= total
        bands = [power[(radius > lo) & (radius <= hi)].sum()
                 for lo, hi in zip((0, .08, .16, .28), (.08, .16, .28, .71))]
        angle = np.mod(np.arctan2(yy, xx), np.pi)
        sectors = [power[(angle >= i*np.pi/4) & (angle < (i+1)*np.pi/4)].sum()
                   for i in range(4)]
        return np.array([*bands, *sectors, power.max()])

    @staticmethod
    def compression_grid_analysis(block, x=0, y=0):
        signature = []
        for axis, origin in ((1, x), (0, y)):
            delta = np.abs(np.diff(block, axis=axis))
            profile = delta.mean(axis=1-axis) if delta.size else np.array([])
            phases = (np.arange(profile.size) + origin + 1) % 8
            means = np.array([profile[phases == phase].mean() if np.any(phases == phase)
                              else 0 for phase in range(8)])
            signature.extend(means / (profile.mean() + 0.25) if profile.size else means)
        return np.asarray(signature)

    @staticmethod
    def rgb_correlation_analysis(block):
        channels = block.reshape(-1, 3).astype(np.float64)
        channels -= channels.mean(axis=0)
        norm = np.sqrt(np.sum(channels**2, axis=0))
        valid = norm > 1e-6
        pairs = [(0, 1), (0, 2), (1, 2)]
        corr = [float(np.clip(np.dot(channels[:, a], channels[:, b]) / (norm[a]*norm[b]), -1, 1))
                if valid[a] and valid[b] else 0.0 for a, b in pairs]
        return np.array(corr), all(valid)

    @staticmethod
    def boundary_analysis(residual, gradient, x, y, w, h):
        pad = max(2, min(w, h)//4)
        y0, y1 = max(0, y-pad), min(residual.shape[0], y+h+pad)
        x0, x1 = max(0, x-pad), min(residual.shape[1], x+w+pad)
        mask = np.ones((y1-y0, x1-x0), dtype=bool)
        mask[y-y0:y-y0+h, x-x0:x-x0+w] = False
        if not mask.any():
            return np.zeros(2)
        inside = (residual[y:y+h, x:x+w], gradient[y:y+h, x:x+w])
        outside = (residual[y0:y1, x0:x1][mask], gradient[y0:y1, x0:x1][mask])
        return np.array([abs(np.log((np.sqrt(np.mean(a*a))+.25) /
                                    (np.sqrt(np.mean(b*b))+.25))) for a, b in zip(inside, outside)])

    @staticmethod
    def _positions(length, size):
        return sorted(set([*range(0, max(1, length-size+1), size//2), max(0, length-size)]))

    @staticmethod
    def _normalize(features, brightness, shape, cancel=None):
        """Robust deviations with nonzero floors: constant images stay zero."""
        f = np.asarray(features, dtype=np.float64)
        if f.ndim == 1:
            f = f[:, None]
        center = np.median(f, axis=0)
        spread = np.maximum(1.4826*np.median(np.abs(f-center), axis=0), .05)
        global_z = np.mean(np.minimum(np.abs(f-center)/spread, 12), axis=1)
        output = []
        rows, cols = shape
        for i, value in enumerate(f):
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Analysis cancelled')
            row, col = divmod(i, cols)
            neighbors = [r*cols+c for r in range(max(0,row-1), min(rows,row+2))
                         for c in range(max(0,col-1), min(cols,col+2)) if r*cols+c != i]
            # A luminance band and nearest peers prevent empty reference bins.
            peers = np.flatnonzero(np.abs(brightness-brightness[i]) <= 16)
            peers = peers[peers != i]
            if peers.size < 4:
                peers = np.argsort(np.abs(brightness-brightness[i]), kind='stable')
                peers = peers[peers != i][:max(4, min(32, len(f)//4))]
            def deviation(indices):
                if len(indices) == 0:
                    return 0.0
                ref = f[indices]
                median = np.median(ref, axis=0)
                scale = np.maximum(1.4826*np.median(np.abs(ref-median), axis=0), spread*.5)
                return float(np.mean(np.minimum(np.abs(value-median)/scale, 12)))
            z = .2*global_z[i] + .3*deviation(peers) + .5*deviation(neighbors)
            output.append(1 - np.exp(-z/3))
        return np.asarray(output, dtype=np.float32)

    def analyze(self, image, progress=None, cancel=None):
        rgb = np.asarray(image)
        if rgb.dtype != np.uint8 or rgb.ndim not in (2, 3) or min(rgb.shape[:2]) < 2:
            raise ValueError('Expected uint8 grayscale/RGB/RGBA image, at least 2×2')
        if rgb.ndim == 2:
            rgb = np.repeat(rgb[:, :, None], 3, axis=2)
        if rgb.shape[2] not in (3, 4):
            raise ValueError('Expected RGB or RGBA channels')
        rgb = rgb[:, :, :3].copy()
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        residual = self.high_frequency_analysis(gray)
        coarse = self.fine_coarse_analysis(gray)
        gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3),
                                 cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
        height, width = gray.shape
        regions, scale_maps = [], {}
        total = sum(len(self._positions(height, s))*len(self._positions(width, s)) for s in self.window_sizes)
        done = 0
        for size in self.window_sizes:
            xs, ys = self._positions(width, size), self._positions(height, size)
            features = {key: [] for key in METRICS}
            local, brightness = [], []
            for y in ys:
                for x in xs:
                    if cancel is not None and cancel.is_set():
                        raise InterruptedError('Analysis cancelled')
                    w, h = min(size, width), min(size, height)
                    block = gray[y:y+h, x:x+w]
                    rms = float(np.sqrt(np.mean(residual[y:y+h, x:x+w]**2)))
                    coarse_energy = float(np.mean(coarse[y:y+h, x:x+w]**2))
                    ratio = rms*rms/(coarse_energy+.0625)
                    grad = float(gradient[y:y+h, x:x+w].mean())
                    fft = self.fft_analysis(block)
                    compression = self.compression_grid_analysis(block, x, y)
                    corr, valid = self.rgb_correlation_analysis(rgb[y:y+h, x:x+w])
                    boundary = self.boundary_analysis(residual, gradient, x, y, w, h)
                    values = [np.log1p(rms), np.log1p(ratio), np.log1p(grad), fft, compression, corr, boundary]
                    for key, value in zip(METRICS, values):
                        features[key].append(value)
                    brightness.append(float(block.mean()))
                    record = dict(x=x, y=y, width=w, height=h, window_size=size,
                                  brightness=brightness[-1], high_frequency_rms=rms,
                                  fine_coarse_ratio=ratio, coarse_energy=coarse_energy,
                                  mean_gradient=grad, fft_peak=float(fft[-1]),
                                  compression_strength=float(np.std(compression)),
                                  rgb_rg=float(corr[0]), rgb_rb=float(corr[1]), rgb_gb=float(corr[2]),
                                  rgb_valid=valid, boundary_difference=float(boundary.mean()))
                    record.update({f'fft_feature_{i}': float(v) for i, v in enumerate(fft)})
                    record.update({f'compression_{axis}_phase_{phase}': float(compression[j*8+phase])
                                   for j, axis in enumerate(('x', 'y')) for phase in range(8)})
                    local.append(record)
                    done += 1
                    if progress and (done % 20 == 0 or done == total):
                        progress(done, total)
            normalized = {key: self._normalize(value, np.array(brightness), (len(ys),len(xs)), cancel)
                          for key, value in features.items()}
            for i, record in enumerate(local):
                record.update({f'{key}_anomaly': float(value[i]) for key, value in normalized.items()})
            scale_maps[size] = {key: self.build_anomaly_map(local, value, (height,width))
                                for key, value in normalized.items()}
            regions.extend(local)
        maps = {}
        for key in METRICS:
            stack = np.stack([m[key] for m in scale_maps.values()])
            maps[key] = .5*stack.mean(axis=0) + .5*stack.max(axis=0)
        result = TextureResult(rgb, regions, maps, scale_maps, dict(self.weights), [])
        self.recombine(result, self.weights)
        return result

    @staticmethod
    def build_anomaly_map(regions, values, shape, clip=True):
        # Rectangle accumulation with difference arrays: all edge pixels covered.
        sums = np.zeros((shape[0]+1,shape[1]+1), np.float32)
        counts = np.zeros_like(sums)
        for r, value in zip(regions, values):
            x,y,w,h = (r[k] for k in ('x','y','width','height'))
            for target, amount in ((sums,value),(counts,1)):
                target[y,x] += amount
                target[y+h,x] -= amount
                target[y,x+w] -= amount
                target[y+h,x+w] += amount
        sums = sums.cumsum(0).cumsum(1)[:-1,:-1]
        counts = counts.cumsum(0).cumsum(1)[:-1,:-1]
        result = sums / np.maximum(counts,1)
        return np.clip(result, 0, 1) if clip else result

    @staticmethod
    def recombine(result, weights):
        weights = {k: float(weights.get(k, 0)) for k in METRICS}
        if any(not np.isfinite(v) or v < 0 for v in weights.values()):
            raise ValueError('Invalid metric weights')
        denominator = sum(weights.values()) or 1
        result.weights = weights
        for maps in [result.maps, *result.scale_maps.values()]:
            maps['score'] = sum(maps[k]*v for k,v in weights.items()) / denominator
        for r in result.regions:
            r['score'] = sum(r[f'{k}_anomaly']*v for k,v in weights.items()) / denominator
        result.top_regions = ForensicTextureAnalyzer.find_top_regions(result.regions)

    @staticmethod
    def find_top_regions(regions, count=10):
        selected = []
        for r in sorted(regions, key=lambda item: item['score'], reverse=True):
            def overlaps(s):
                area = max(0,min(r['x']+r['width'],s['x']+s['width'])-max(r['x'],s['x'])) * max(
                    0,min(r['y']+r['height'],s['y']+s['height'])-max(r['y'],s['y']))
                return area / min(r['width']*r['height'], s['width']*s['height']) > .25
            if not any(overlaps(s) for s in selected):
                selected.append(r)
                if len(selected) == count:
                    break
        return selected
