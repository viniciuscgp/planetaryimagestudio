"""Exact decoded-pixel deduplication and persistent download exclusions."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

import cv2
import numpy as np
from PIL import Image

from planetary_studio.collections.catalog import SUPPORTED_EXTENSIONS

REGISTRY = '.duplicate_registry.json'


def decoded_pixels(path):
    """Read native pixels and metadata without thumbnailing or losing bit depth."""
    data = Path(path).read_bytes()
    import io
    with Image.open(io.BytesIO(data)) as source:
        if getattr(source,'n_frames',1) != 1:
            raise ValueError('Imagem com múltiplos quadros: mantida por segurança.')
        orientation = source.getexif().get(274,1)
        icc = source.info.get('icc_profile',b'')
    decoded = cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise ValueError('Não foi possível decodificar todos os pixels.')
    if decoded.ndim == 2:
        decoded = np.repeat(decoded[:,:,None],3,axis=2)
    if decoded.shape[2] == 3:
        maximum = np.iinfo(decoded.dtype).max if np.issubdtype(decoded.dtype,np.integer) else 1
        alpha = np.full((*decoded.shape[:2],1),maximum,dtype=decoded.dtype)
        decoded = np.concatenate((decoded,alpha),axis=2)
    return decoded,orientation,icc


def pixels(path):
    """Retain native bit depth; never compare resized or lossy 8-bit thumbnails."""
    decoded,orientation,icc = decoded_pixels(path)
    header = json.dumps([decoded.shape,decoded.dtype.str,orientation,
                         hashlib.sha256(icc).hexdigest()]).encode()
    return header+b'\0'+decoded.tobytes()


def protected(path, extra=()):
    # Even empty/unreadable sidecars are preserved: never risk user annotations.
    return Path(str(path)+'.annotations.json').exists() or Path(path).resolve() in extra


def within(root,path):
    root,path = Path(root).resolve(),Path(path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Arquivo fora da pasta da missão.')
    return path


def scan_duplicates(root,folder=None,extra=(),cancel=None,progress=None):
    root = Path(root).resolve()
    scope = Path(folder).resolve() if folder else root
    if not scope.is_relative_to(root):
        raise ValueError('Pasta fora da missão.')
    cancel = cancel or threading.Event()
    extra = {Path(p).resolve() for p in extra}
    buckets,errors = {},[]
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
                digest = hashlib.sha256(pixels(path)).hexdigest()
                buckets.setdefault(digest,[]).append(path)
            except Exception as exc:
                errors.append(f'{path.name}: {exc}')
            if progress:
                progress(checked)
    groups = []
    for digest,paths in buckets.items():
        if len(paths)<2:
            continue
        paths.sort(key=lambda p:(not protected(p,extra),str(p).casefold()))
        # Hashes only shortlist candidates. Confirm actual pixel bytes as well.
        try:
            reference = pixels(paths[0])
            matches = [paths[0]]
            for path in paths[1:]:
                if cancel.is_set():
                    raise InterruptedError()
                if pixels(path)==reference:
                    matches.append(path)
            if len(matches)>1:
                groups.append(dict(keeper=matches[0],copies=matches[1:],digest=digest,
                                   protected=[p for p in matches if protected(p,extra)]))
        except InterruptedError:
            raise
        except Exception as exc:
            errors.append(str(exc))
    return dict(groups=groups,errors=errors,checked=checked)


def read_registry(root):
    path = Path(root)/REGISTRY
    if not path.exists():
        return dict(version=1,removed={})
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('removed'),dict):
        raise ValueError('Registro de exclusões inválido; nenhuma exclusão realizada.')
    return value


def write_registry(root,value):
    fd,name = tempfile.mkstemp(prefix='.duplicates_',suffix='.tmp',dir=root)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,Path(root)/REGISTRY)
    finally:
        Path(name).unlink(missing_ok=True)


def remove_duplicates(root,groups,extra=(),cancel=None,progress=None):
    root = Path(root).resolve()
    registry = read_registry(root)
    extra = {Path(p).resolve() for p in extra}
    removed,errors = [],[]
    for group in groups:
        for candidate in group['copies']:
            if cancel is not None and cancel.is_set():
                return dict(removed=removed,errors=errors)
            try:
                if Path(candidate).is_symlink() or Path(group['keeper']).is_symlink():
                    raise ValueError('Link simbólico: arquivo mantido.')
                keeper,path = within(root,group['keeper']),within(root,candidate)
                if path==keeper or protected(path,extra):
                    continue
                reference = pixels(keeper)
                if hashlib.sha256(reference).hexdigest()!=group['digest'] or pixels(path)!=reference:
                    raise ValueError('Pixels mudaram desde a busca; arquivo mantido.')
                if protected(path,extra):
                    continue
                key = path.relative_to(root).as_posix()
                registry['removed'][key] = dict(keeper=keeper.relative_to(root).as_posix(),pixel_sha256=group['digest'])
                # Persist first. On any write error, never delete the image.
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


def skip_removed_image(root,destination):
    """Honor explicit monochrome exclusions or verified retained duplicates."""
    try:
        root = Path(root).resolve()
        path = within(root,destination)
        if path.exists():
            return False
        entries = read_registry(root)['removed']
        entry = entries.get(path.relative_to(root).as_posix())
        if not isinstance(entry,dict):
            return False
        digest = entry['pixel_sha256']
        visited = set()
        while entry:
            # A retained duplicate may subsequently be explicitly removed as B&W.
            if entry.get('reason') == 'black_and_white':
                return (entry.get('pixel_sha256')==digest and isinstance(digest,str) and
                        len(digest)==64 and all(c in '0123456789abcdef' for c in digest))
            key = entry['keeper']
            if key in visited:
                return False
            visited.add(key)
            keeper = within(root,root/key)
            if keeper.is_file():
                return hashlib.sha256(pixels(keeper)).hexdigest()==digest
            entry = entries.get(key)
    except Exception:
        # A missing/corrupt record must never block recovering an image.
        return False
    return False


# Compatibility for callers using the original duplicate-only API.
skip_removed_duplicate = skip_removed_image
