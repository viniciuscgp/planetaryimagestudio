"""Perseverance public raw-image feed (independent of the MSL API)."""
from pathlib import Path
from .curiosity import CuriositySource, DownloaderWorker, MetadataClient

API = 'https://mars.nasa.gov/rss/api/'
PARAMS = dict(feed='raw_images', category='mars2020,ingenuity', feedtype='json',
              ver='1.2', condition_1='mars2020:mission', order='sol desc')


def sol_filter(sol):
    # The legacy `sol` endpoint falls back to the latest images for empty SOLs.
    # Use the same explicit range and API version as NASA's raw-image gallery.
    return dict(condition_2=f'{sol}:sol:gte', condition_3=f'{sol}:sol:lte')

class PerseveranceWorker(DownloaderWorker):
    catalog_id = 'perseverance'
    def query(self, **params):
        if self._stopped():
            raise InterruptedError()
        with self._request_session().get(API, params={**PARAMS, **params}, timeout=(15, 45)) as response:
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('images'), list):
            raise RuntimeError('Formato inesperado no catálogo do Perseverance.')
        return data

    def _latest_nasa_sol(self):
        items = self.query(num=1, page=0)['images']
        if not items:
            raise RuntimeError('Catálogo do Perseverance vazio.')
        return max(int(item['sol']) for item in items)

    @staticmethod
    def _image_url(item):
        return item.get('image_files', {}).get('full_res')

    def _sol_items(self, sol):
        result, seen, page = [], set(), 0
        while not self._stopped():
            data = self.query(**sol_filter(sol), num=100, page=page)
            items = data['images']
            if not items:
                break
            added = 0
            for item in items:
                if int(item.get('sol', -1)) != sol:
                    raise RuntimeError('O servidor ignorou o filtro de SOL do Perseverance.')
                key = self._image_url(item)
                if key and key not in seen and str(item.get('sample_type', '')).lower() != 'thumbnail':
                    seen.add(key)
                    result.append(item)
                    added += 1
            # The per-SOL feed returns the complete SOL in one response (num_images),
            # while the general list feed uses total_results/page.
            if 'num_images' in data:
                if len(items) != int(data['num_images']):
                    raise RuntimeError('Catálogo do SOL incompleto.')
                break
            if len(items) < 100 or (page + 1) * 100 >= int(data.get('total_results', 2**31)):
                break
            if not added:
                raise RuntimeError('O catálogo repetiu a página; download interrompido para evitar um loop.')
            page += 1
        return result

class PerseveranceMetadata(MetadataClient):
    def lookup(self, filename, sol):
        key = (filename, sol)
        if key in self._cache:
            return self._cache[key]
        page = 0
        seen_pages = set()
        while True:
            with self.session.get(API, params={**PARAMS, **sol_filter(sol), 'num':100, 'page':page}, timeout=20) as response:
                response.raise_for_status()
                data = response.json()
                items = data.get('images', [])
            signature = tuple(item.get('image_files', {}).get('full_res') for item in items)
            if not items or signature in seen_pages:
                break
            seen_pages.add(signature)
            for item in items:
                if int(item.get('sol', -1)) != sol:
                    raise RuntimeError('O servidor ignorou o filtro de SOL do Perseverance.')
                if self._remote_filename({'full_res':item.get('image_files', {}).get('full_res')}) == filename:
                    result=self._normalize(item, filename, sol)
                    self._cache[key]=result
                    return result
            if len(items) < 100 or (page + 1) * 100 >= int(data.get('total_results', 2**31)):
                break
            page += 1
        return {'filename':filename, 'sol':sol, 'title':'Perseverance', 'nasa_url':'https://mars.nasa.gov/mars2020/multimedia/raw-images/'}

class PerseveranceSource(CuriositySource):
    id = 'perseverance'
    name = 'Perseverance (Marte)'
    download_description = 'NASA/JPL: PNG/JPEG na resolução completa publicada no catálogo de imagens raw; organizado por SOL.'
    def create_downloader(self, root, **options):
        return PerseveranceWorker(root, **options)
    def create_metadata_client(self):
        return PerseveranceMetadata()
