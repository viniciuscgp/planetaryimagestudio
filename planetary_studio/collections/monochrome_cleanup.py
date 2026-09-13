"""Review and remove strictly achromatic originals; never infer from thumbnails."""
import hashlib
import os
from pathlib import Path
import threading

import numpy as np

from planetary_studio.collections.catalog import SUPPORTED_EXTENSIONS
from planetary_studio.collections.exact_duplicates import decoded_pixels,pixels,protected,within,read_registry,write_registry


def is_monochrome(path):
    """Any native RGB channel difference keeps the image, including hidden pixels."""
    image,_,_ = decoded_pixels(path)
    return bool(np.isfinite(image).all() and
                np.array_equal(image[:,:,0],image[:,:,1]) and
                np.array_equal(image[:,:,1],image[:,:,2]))


def scan_monochrome(root,folder=None,extra=(),cancel=None,progress=None):
    root = Path(root).resolve()
    scope = Path(folder).resolve() if folder else root
    if not scope.is_relative_to(root):
        raise ValueError('Pasta fora da missão.')
    extra = {Path(p).resolve() for p in extra}
    cancel = cancel or threading.Event()
    groups,errors = [],[]
    checked = 0
    for directory,children,filenames in os.walk(scope,followlinks=False):
        children[:] = sorted(c for c in children if not c.startswith('.') and not (Path(directory)/c).is_symlink())
        for name in sorted(filenames):
            if cancel.is_set():
                raise InterruptedError()
            path = Path(directory)/name
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS or path.is_symlink():
                continue
            checked += 1
            try:
                path = within(root,path)
                if is_monochrome(path):
                    groups.append(dict(copies=[path],digest=hashlib.sha256(pixels(path)).hexdigest(),
                                       protected=[path] if protected(path,extra) else []))
            except Exception as exc:
                errors.append(f'{path.name}: {exc}')
            if progress:
                progress(checked)
    return dict(groups=groups,errors=errors,checked=checked)


def remove_monochrome(root,groups,extra=(),cancel=None,progress=None):
    root = Path(root).resolve()
    registry = read_registry(root)
    extra = {Path(p).resolve() for p in extra}
    removed,errors = [],[]
    for group in groups:
        for candidate in group['copies']:
            if cancel is not None and cancel.is_set():
                return dict(removed=removed,errors=errors)
            try:
                if Path(candidate).is_symlink():
                    raise ValueError('Link simbólico: arquivo mantido.')
                path = within(root,candidate)
                if protected(path,extra):
                    continue
                if not is_monochrome(path) or hashlib.sha256(pixels(path)).hexdigest()!=group['digest']:
                    raise ValueError('Imagem mudou desde a busca; arquivo mantido.')
                if protected(path,extra):
                    continue
                registry['removed'][path.relative_to(root).as_posix()] = dict(
                    reason='black_and_white',pixel_sha256=group['digest'])
                # A failed write must never delete the original.
                write_registry(root,registry)
                if protected(path,extra):
                    continue
                path.unlink()
                removed.append(path)
                if progress:
                    progress(len(removed))
            except Exception as exc:
                errors.append(f'{candidate}: {exc}')
    return dict(removed=removed,errors=errors)
