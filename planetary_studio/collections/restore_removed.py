"""Restore recorded originals through the existing download worker and signals."""
import json
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from planetary_studio.collections.exact_duplicates import within


def validated_paths(root,paths):
    return sorted({within(root,Path(root)/name).relative_to(Path(root).resolve()).as_posix()
                   for name in paths})


def run_restore(worker):
    """Use original catalogs, request only recorded names, keep normal stop/retry."""
    try:
        paths=validated_paths(worker.root,worker.restore_paths)
        folders={}
        for name in paths:
            path=worker.root/name
            folders.setdefault(path.parent,[]).append(path)
        archive=hasattr(worker,'provider')
        if archive:
            from planetary_studio.sources.archives import STATE_FILE,safe_name,collection_id
            state_path=worker.root/STATE_FILE
            state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            records={safe_name(r['folder']):r for r in state.get('records',{}).values()}
        else:
            from planetary_studio.sources.curiosity import sol_number_from_name
            latest=worker._latest_nasa_sol()
            worker._prepare_catalog(latest)
        restored=errors=0
        for position,(folder,images) in enumerate(folders.items(),1):
            if worker._stopped():raise InterruptedError()
            if folder.parent != worker.root:
                errors+=len(images)
                worker.message.emit(f'Pasta sem catálogo compatível: {folder.name}; restauração pendente.')
                continue
            key=collection_id(folder.name) if archive else sol_number_from_name(folder.name)
            if key is None:
                errors+=len(images)
                worker.message.emit(f'Pasta sem SOL reconhecido: {folder.name}; restauração pendente.')
                continue
            worker.sol_started.emit(key,position,len(folders))
            try:
                if archive:
                    record=records.get(folder.name,{})
                    urls={safe_name(Path(urlparse(url).path).name):url for url in record.get('urls',[])}
                else:
                    items=worker._cached_sol_items(key,latest)
                    urls={worker._filename(item,worker._image_url(item),i):worker._image_url(item)
                          for i,item in enumerate(items,1)}
            except InterruptedError:
                raise
            except Exception as exc:
                errors+=len(images);worker.message.emit(f'{folder.name}: {exc}');continue
            folder.mkdir(parents=True,exist_ok=True)
            worker.sol_created.emit(key,str(folder))
            worker.sol_catalogued.emit(key,len(images))
            new=existing=0
            for index,path in enumerate(images,1):
                if worker._stopped():raise InterruptedError()
                worker.file_started.emit(key,path.name,index,len(images))
                try:
                    # Restoring never overwrites a file that has returned since removal.
                    if path.is_file() and path.stat().st_size>0:
                        existing+=1
                    else:
                        url=urls.get(path.name)
                        if not url:
                            raise ValueError('Nome não encontrado no catálogo de origem.')
                        worker._download_file(key,url,path,path.name)
                        try:
                            with Image.open(path) as image:
                                image.verify()
                        except Exception:
                            # Only a newly downloaded invalid file is discarded.
                            path.unlink(missing_ok=True)
                            raise
                        new+=1;restored+=1
                        worker.file_downloaded.emit(key,str(path))
                except InterruptedError:
                    raise
                except Exception as exc:
                    errors+=1;worker.message.emit(f'Falha ao restaurar {path.name}: {exc}')
                worker.sol_progress.emit(key,index,len(images))
            worker.sol_finished.emit(key,len(images),new,existing)
        if errors:
            worker.failed.emit(f'{errors} imagens pendentes. Use Continuar para tentar novamente.')
            worker.finished.emit(f'Restauração pendente: {restored} imagens baixadas; {errors} falhas.')
        else:
            worker.finished.emit(f'Restauração concluída: {restored} imagens baixadas novamente.')
    except InterruptedError:
        worker.finished.emit('Restauração interrompida. Use Continuar para retomar.')
    except Exception as exc:
        worker.failed.emit(str(exc))
        worker.finished.emit('Restauração encerrada com erro; lista preservada para continuar.')
    finally:
        worker.session.close()
