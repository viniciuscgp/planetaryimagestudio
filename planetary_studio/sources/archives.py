"""Public archive adapters. Catalog cursors are committed only after a complete observation.

These sources download published browse products, not PDS raw IMG/FITS/JP2 arrays.
Each update continues a bounded batch; restart_catalog explicitly checks from the beginning.
"""
import hashlib
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PIL import Image
from .base import ImageSource
from .curiosity import DownloaderWorker

BATCH_SIZE = 10
STATE_FILE = '.archive-download.json'

class Links(HTMLParser):
    def __init__(self, text, base):
        super().__init__()
        self.urls = []
        self.feed(text)
        self.urls = list(dict.fromkeys(urljoin(base, url) for url in self.urls))
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            attrs = dict(attrs)
            if attrs.get('href'):
                self.urls.append(attrs['href'])

def links(text, base):
    return Links(text, base).urls

def collection_id(name):
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], 'big') & 0x7fffffff

def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def safe_name(value):
    result = re.sub(r'[^A-Za-z0-9_.-]', '_', value).strip(' .')
    if not result or result in ('.', '..'):
        raise ValueError('Nome de produto inválido.')
    return result[:180]

class ArchiveProvider:
    def __init__(self, worker):
        self.worker = worker
    def text(self, url):
        if self.worker._stopped():
            raise InterruptedError('Atualização interrompida.')
        with self.worker.session.get(url, timeout=(15, 45)) as response:
            response.raise_for_status()
            return response.text
    def record(self, name, page, urls):
        if not urls:
            raise RuntimeError(f'Nenhum produto de imagem reconhecido em {page}. O formato do acervo pode ter mudado.')
        return {'folder':safe_name(name), 'page':page, 'urls':list(dict.fromkeys(urls))}

class HiriseProvider(ArchiveProvider):
    home = 'https://www.uahirise.org/catalog/'
    def records(self, cursor):
        page, index = cursor.get('page', 1), cursor.get('index', 0)
        while True:
            url = self.home + f'index.php?page={page}'
            text = self.text(url)
            ids = list(dict.fromkeys(re.findall(r'(?:ESP|PSP|TRA)_\d{6}_\d{4}', text)))
            if not ids:
                raise RuntimeError('Catálogo HiRISE sem observações reconhecidas.')
            for i in range(index, len(ids)):
                detail = 'https://www.uahirise.org/' + ids[i]
                files = [u.replace('http://', 'https://') for u in links(self.text(detail), detail)
                         if 'hirise-pds.lpl.arizona.edu/' in u and re.search(r'\.(?:a?browse)\.jpg$', u, re.I)]
                yield self.record(ids[i], detail, files), {'page':page, 'index':i+1}
            if not re.search(r'page=' + str(page+1) + r'(?:["\x27&])', text):
                return
            page, index = page+1, 0

class LrocProvider(ArchiveProvider):
    home = 'https://data.lroc.im-ldi.com'
    def records(self, cursor):
        phases = []
        for url in links(self.text(self.home+'/lroc/thumbnails'), self.home):
            match = re.search(r'phase=([^&]+)', url)
            if match and 'camera=NAC' in url:
                phases.append(match.group(1))
        phases = list(reversed(list(dict.fromkeys(phases)))) + ['PRI', 'COM']
        phase_index, page, index = cursor.get('phase', 0), cursor.get('page', 1), cursor.get('index', 0)
        for pi in range(phase_index, len(phases)):
            while True:
                url = self.home+f'/lroc/thumbnails?camera=NAC&phase={phases[pi]}&page={page}'
                text = self.text(url)
                details = [u for u in links(text, self.home) if re.search(r'/view_lroc/[^/]+/M\d+[LR]E$', u)]
                # C-prefixed products are calibration frames, intentionally excluded.
                for i in range(index, len(details)):
                    detail = details[i]
                    urls = [u for u in links(self.text(detail), detail) if u.lower().endswith('_pyr.tif')]
                    yield self.record(detail.rsplit('/',1)[-1], detail, urls), {'phase':pi,'page':page,'index':i+1}
                if not re.search(r'page=' + str(page+1) + r'(?:&|["\x27])', text):
                    if not details and page == 1:
                        raise RuntimeError('Catálogo LROC sem observações reconhecidas.')
                    break
                page, index = page+1, 0
            page, index = 1, 0

class EsaHrscProvider(ArchiveProvider):
    home = 'https://www.esa.int'
    def records(self, cursor):
        offset, index = cursor.get('offset', 0), cursor.get('index', 0)
        while True:
            url=self.home+f'/ESA_Multimedia/Missions/Mars_Express/(offset)/{offset}/(sortBy)/published/(result_type)/images'
            text=self.text(url)
            details=[u for u in links(text,self.home) if re.search(r'/ESA_Multimedia/Images/\d{4}/\d{2}/',u)]
            if not details:
                raise RuntimeError('Catálogo ESA sem imagens reconhecidas.')
            for i in range(index,len(details)):
                detail=details[i]
                body=self.text(detail)
                description = re.search(r'<div class="modal__tab-description">(.*?)</div>', body, re.S)
                if not description or not re.search(r'HRSC|High Resolution Stereo Camera',description[1],re.I):
                    continue
                urls=[u for u in links(body,self.home) if '/var/esa/storage/images/' in u and u.lower().endswith('.jpg') and not re.search(r'_(?:card_\w+|pillars)\.jpg$',u)]
                if not urls:
                    continue
                date=re.search(r'/Images/(\d{4})/(\d{2})/',detail)
                name=f'{date[1]}-{date[2]}_'+detail.rsplit('/',1)[-1]
                yield self.record(name,detail,urls), {'offset':offset,'index':i+1}
            if f'/(offset)/{offset+50}/' not in text:
                return
            offset,index=offset+50,0

class KaguyaProvider(ArchiveProvider):
    home='https://data.darts.isas.jaxa.jp/pub/pds3/sln-l_e-hdtv-2-edr-v1.0/browse/large/'
    def records(self,cursor):
        months=sorted([u for u in links(self.text(self.home),self.home) if re.search(r'/\d{6}/$',u)],reverse=True)
        if not months:
            raise RuntimeError('Catálogo Kaguya sem meses reconhecidos.')
        month,index=cursor.get('month',0),cursor.get('index',0)
        for mi in range(month,len(months)):
            sessions=sorted([u for u in links(self.text(months[mi]),months[mi]) if re.search(r'/sh_\d{8}T\d{6}_[wt]i1/$',u)],reverse=True)
            for i in range(index,len(sessions)):
                detail=sessions[i]
                urls=[u for u in links(self.text(detail),detail) if u.lower().endswith('.jpg')]
                yield self.record(detail.rstrip('/').rsplit('/',1)[-1],detail,urls), {'month':mi,'index':i+1}
            index=0

class ArchiveWorker(DownloaderWorker):
    def __init__(self, root, provider, only_sol=None, start_sol=None, batch_size=BATCH_SIZE):
        super().__init__(root,only_sol,start_sol)
        self.provider=provider(self)
        self.batch_size=batch_size

    def run(self):
        if self.restore_paths is not None:
            from planetary_studio.collections.restore_removed import run_restore
            return run_restore(self)
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            state_path=self.root/STATE_FILE
            state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'cursor':{},'records':{}}
            if self.only_sol is not None:
                record=state['records'].get(str(self.only_sol))
                if not record:
                    raise RuntimeError('Esta pasta não tem uma observação registrada para baixar novamente.')
                iterator=iter([(record,None)])
            else:
                cursor={} if self.start_sol == 0 else state.get('cursor',{})
                iterator=self.provider.records(cursor)
            completed=0
            self.message.emit(f'Consultando acervo; lote de até {self.batch_size} observações. JPG/PNG/TIFF publicados, sem miniaturas.')
            for record,next_cursor in iterator:
                if self._stopped():
                    raise InterruptedError('Atualização interrompida.')
                key=collection_id(record['folder'])
                previous=state['records'].get(str(key))
                if previous and previous['folder'] != record['folder']:
                    raise RuntimeError('Conflito de identificadores de observação.')
                folder=self.root/safe_name(record['folder'])
                folder.mkdir(exist_ok=True)
                self.sol_created.emit(key,str(folder))
                self.sol_started.emit(key,completed+1,self.batch_size)
                state['records'][str(key)]=record
                atomic_json(state_path,state)
                total=len(record['urls'])
                self.sol_catalogued.emit(key,total)
                new=existing=0
                for i,url in enumerate(record['urls'],1):
                    if self._stopped():
                        raise InterruptedError('Atualização interrompida.')
                    filename=safe_name(Path(urlparse(url).path).name)
                    destination=folder/filename
                    self.file_started.emit(key,filename,i,total)
                    from planetary_studio.collections.exact_duplicates import skip_removed_image
                    if skip_removed_image(self.root,destination):
                        existing+=1
                        self.message.emit(f'Imagem já removida e registrada: {filename} (download ignorado).')
                    elif destination.exists() and destination.stat().st_size:
                        existing+=1
                    else:
                        self._download_file(key,url,destination,filename)
                        try:
                            with Image.open(destination) as image:
                                width,height=image.size
                                image.verify()
                        except Exception:
                            destination.unlink(missing_ok=True)
                            raise RuntimeError(f'{filename}: o servidor não entregou uma imagem válida.')
                        atomic_json(destination.with_name(filename+'.source.json'),{'title':record['folder'],'nasa_url':record['page'],'download_url':url,'width':width,'height':height})
                        new+=1
                        self.file_downloaded.emit(key,str(destination))
                    self.sol_progress.emit(key,i,total)
                if next_cursor is not None:
                    state['cursor']=next_cursor
                    state['complete']=False
                atomic_json(state_path,state)
                self.sol_finished.emit(key,total,new,existing)
                completed+=1
                if completed>=self.batch_size:
                    break
            else:
                if self.only_sol is None:
                    state['cursor']={}
                    state['complete']=True
                    atomic_json(state_path,state)
            self.finished.emit(f'Atualização concluída: {completed} observações. Atualizar novamente continua o próximo lote do acervo.')
        except InterruptedError:
            self.finished.emit('Atualização interrompida; o próximo lote retoma os arquivos pendentes.')
        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit('Atualização encerrada com erro; posição do acervo preservada.')
        finally:
            self.session.close()

class ArchiveMetadata:
    def __init__(self,source):
        self.source=source
    def lookup(self,filename,collection):
        for key,folder in self.source.list_collections(self.source.root):
            if key==collection:
                path=folder/(filename+'.source.json')
                if path.exists():
                    return {'filename':filename,**json.loads(path.read_text(encoding='utf-8'))}
        return {'filename':filename,'title':self.source.name,'caption':self.source.download_description}

class ArchiveSource(ImageSource):
    supports_downloads=True
    uses_sols=False
    collection_label='Observações'
    root=Path('.')
    def list_collections(self,root):
        self.root=root
        return sorted([(collection_id(p.name),p) for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')],key=lambda x:x[1].name,reverse=True) if root.exists() else []
    def create_metadata_client(self):
        return ArchiveMetadata(self)
    def create_downloader(self,root,**options):
        self.root=root
        return ArchiveWorker(root,self.provider,**options)

class HiriseSource(ArchiveSource):
    id='hirise'
    name='MRO / HiRISE'
    provider=HiriseProvider
    download_description='HiRISE: JPEGs browse do PDS (cores e vermelho), por observação. São versões de visualização; a resolução científica nativa está nos JP2 externos. Lotes de 10 observações, com continuação automática ao abrir.'

class LrocSource(ArchiveSource):
    id='lroc'
    name='LRO / LROC NAC'
    provider=LrocProvider
    download_description='LROC NAC: TIFF CDR de múltipla resolução, com compressão com perdas, por observação. Exclui calibração e miniaturas. Lotes de 10 observações na ordem do catálogo, com continuação ao abrir.'

class EsaHrscSource(ArchiveSource):
    id='esa_hrsc'
    name='Mars Express / HRSC'
    provider=EsaHrscProvider
    download_description='ESA: JPEGs HRSC processados publicados na galeria oficial, em tamanho original, por publicação. Inclui perspectivas e mapas; não é o acervo científico completo. Lotes de 10 observações, com continuação ao abrir.'

class KaguyaSource(ArchiveSource):
    id='kaguya'
    name='Kaguya / HDTV'
    provider=KaguyaProvider
    download_description='JAXA/NHK: JPEGs grandes das sequências de fotografias HDTV, por observação (mais recentes primeiro). Não inclui vídeos nem FITS. Lotes de 10 observações, com continuação ao abrir.'
