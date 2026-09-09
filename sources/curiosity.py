"""NASA Curiosity source: SOL discovery, metadata and resumable downloads."""
from __future__ import annotations
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import requests
from PySide6.QtCore import QObject, QThread, Signal

from config import APP_NAME, APP_VERSION, APP_AUTHOR
from .base import ImageSource
from .network import CancellableSession
from .catalog_cache import CatalogCache

NASA_API = "https://mars.nasa.gov/api/v1/raw_image_items/"
NASA_RAW_IMAGES = "https://mars.nasa.gov/msl/multimedia/raw-images/"
SOL_RE = re.compile(r"^SOL[\s_-]?(\d+)$", re.IGNORECASE)

def sol_number_from_name(name: str) -> int | None:
    match = SOL_RE.match(name)
    return int(match.group(1)) if match else None


def list_sol_folders(root: Path) -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return result
    for entry in entries:
        if not entry.is_dir():
            continue
        sol = sol_number_from_name(entry.name)
        if sol is not None:
            result.append((sol, entry))
    # Latest Sol first; this is usually the most useful order for rover images.
    result.sort(key=lambda x: x[0], reverse=True)
    return result


class MetadataClient:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.session = CancellableSession()
        self.session.headers.update({"User-Agent": f"{APP_NAME}/{APP_VERSION}"})

    @staticmethod
    def _extract_items(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []

        candidate_paths = [
            data.get("items"),
            data.get("images"),
            data.get("image"),
            data.get("results"),
        ]
        list_node = data.get("list")
        if isinstance(list_node, dict):
            candidate_paths.append(list_node.get("items"))

        for candidate in candidate_paths:
            if isinstance(candidate, list):
                return [x for x in candidate if isinstance(x, dict)]
            if isinstance(candidate, dict):
                return [candidate]
        return []

    @staticmethod
    def _candidate_ids(filename: str) -> list[str]:
        stem = Path(filename).stem
        candidates = [stem]

        # NASA browse products sometimes add common rendering suffixes.
        stripped = re.sub(r"(?i)([-_]br\d+|[-_]browse|[-_]thumb|[-_]thumbnail)$", "", stem)
        if stripped != stem:
            candidates.append(stripped)

        # imageid in the MSL API can sometimes end with an underscore.
        if stripped and not stripped.endswith("_"):
            candidates.append(stripped + "_")

        # Keep order, remove duplicates.
        seen: set[str] = set()
        return [x for x in candidates if not (x in seen or seen.add(x))]

    @staticmethod
    def _remote_filename(item: dict[str, Any]) -> str | None:
        urls: list[str] = []
        for key in ("url", "image_url", "image", "full_res"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)

        image_files = item.get("image_files")
        if isinstance(image_files, dict):
            for value in image_files.values():
                if isinstance(value, str) and value.startswith("http"):
                    urls.append(value)

        for url in urls:
            name = Path(urlparse(url).path).name
            if name:
                return name
        return None

    def _query(self, params: dict[str, str]) -> list[dict[str, Any]]:
        response = self.session.get(NASA_API, params=params, timeout=15)
        response.raise_for_status()
        return self._extract_items(response.json())

    def lookup(self, filename: str, sol: int) -> dict[str, Any]:
        key = (filename.lower(), sol)
        with self._lock:
            cached = self._cache.get(key)
        if cached:
            return cached

        # Fast path: query the MSL API by imageid extracted from the original filename.
        for image_id in self._candidate_ids(filename):
            try:
                items = self._query({"condition_1": f"{image_id}:imageid:eq", "per_page": "10"})
            except Exception:
                items = []
            if items:
                result = self._normalize(items[0], filename, sol)
                with self._lock:
                    self._cache[key] = result
                return result

        # Fallback: query all entries for the current sol and compare filenames/imageids.
        try:
            items = self._query({
                "condition_1": "msl:mission",
                "condition_2": f"{sol}:sol:gte",
                "condition_3": f"{sol}:sol:lte",
                "per_page": "2000",
                "page": "0",
                "order": "date_taken asc",
            })
        except Exception as exc:
            raise RuntimeError(f"Não foi possível consultar a NASA: {exc}") from exc

        wanted = filename.lower()
        wanted_stem = Path(filename).stem.lower()
        candidate_ids = {x.lower() for x in self._candidate_ids(filename)}

        for item in items:
            image_id = str(item.get("imageid") or item.get("image_id") or "").lower()
            remote_name = (self._remote_filename(item) or "").lower()
            remote_stem = Path(remote_name).stem.lower() if remote_name else ""
            if (
                remote_name == wanted
                or remote_stem == wanted_stem
                or image_id in candidate_ids
                or (image_id and wanted_stem.startswith(image_id.rstrip("_")))
            ):
                result = self._normalize(item, filename, sol)
                with self._lock:
                    self._cache[key] = result
                return result

        result = {
            "filename": filename,
            "sol": sol,
            "title": "Imagem do Curiosity",
            "caption": "A NASA não retornou um registro exato para este nome de arquivo.",
            "nasa_url": f"{NASA_RAW_IMAGES}?begin_sol={sol}&end_sol={sol}&mission=msl",
        }
        with self._lock:
            self._cache[key] = result
        return result

    @staticmethod
    def _normalize(item: dict[str, Any], filename: str, sol: int) -> dict[str, Any]:
        camera = item.get("camera") if isinstance(item.get("camera"), dict) else {}
        extended = item.get("extended") if isinstance(item.get("extended"), dict) else {}
        image_id = str(item.get("imageid") or item.get("image_id") or Path(filename).stem)

        nasa_url = (
            item.get("link")
            or item.get("url_page")
            or item.get("detail_url")
            or f"{NASA_RAW_IMAGES}?id={image_id}"
        )

        return {
            "filename": filename,
            "imageid": image_id,
            "sol": item.get("sol", sol),
            "title": item.get("title") or f"Curiosity Sol {item.get('sol', sol)}",
            "instrument": item.get("instrument") or camera.get("instrument") or item.get("camera_name"),
            "date_taken_utc": item.get("date_taken_utc") or item.get("date_taken"),
            "date_received": item.get("date_received"),
            "catalog_created_at": item.get("created_at"),
            "sample_type": item.get("sample_type"),
            "credit": item.get("credit") or item.get("credits"),
            "caption": item.get("caption") or item.get("description") or item.get("body"),
            "mars_time": item.get("date_taken_mars") or extended.get("localtime"),
            "nasa_url": nasa_url,
        }


class DownloaderWorker(QObject):
    """Atualiza as imagens do Curiosity sem bloquear a interface Qt."""

    message = Signal(str)
    catalog_progress = Signal(int, int)
    catalog_id = 'curiosity'
    sol_started = Signal(int, int, int)        # sol, posição, total de sols
    sol_catalogued = Signal(int, int)          # sol, total de registros/imagens
    sol_progress = Signal(int, int, int)       # sol, concluídos, total
    file_started = Signal(int, str, int, int)  # sol, arquivo, índice, total
    file_progress = Signal(int, str, int, int, int)  # sol, arquivo, %, bytes, total bytes
    file_downloaded = Signal(int, str)         # sol, caminho final
    sol_created = Signal(int, str)              # sol, pasta
    sol_finished = Signal(int, int, int, int)  # sol, total, novas, existentes
    failed = Signal(str)
    finished = Signal(str)

    def __init__(
        self,
        root: Path,
        only_sol: int | None = None,
        start_sol: int | None = None,
    ) -> None:
        super().__init__()
        self.root = root.resolve()
        self.only_sol = only_sol
        self.start_sol = start_sol
        self._stop_event = threading.Event()
        self.catalog_cache = CatalogCache(self.root, self.catalog_id)
        self.clear_catalog_cache = False
        self._catalog_checked = set()
        self.catalog_workers = 3
        self._catalog_abort = threading.Event()
        self._catalog_sessions_lock = threading.Lock()
        self._catalog_sessions = []
        self._catalog_session_local = None
        self.session = CancellableSession(retry_message=self.message.emit)
        self.session.headers.update({
            "User-Agent": f"{APP_NAME}/{APP_VERSION} - {APP_AUTHOR}"
        })

    def stop(self) -> None:
        self._stop_event.set()
        self.session.cancel()
        with self._catalog_sessions_lock:
            for session in self._catalog_sessions:
                session.cancel()

    def _stopped(self) -> bool:
        return self._stop_event.is_set() or self._catalog_abort.is_set() or QThread.currentThread().isInterruptionRequested()

    def _request_session(self):
        local = self._catalog_session_local
        if local is None:
            return self.session
        if not hasattr(local, 'session'):
            with self._catalog_sessions_lock:
                if self._stopped():
                    raise InterruptedError('Leitura do catálogo interrompida.')
                local.session = CancellableSession(retry_message=self.message.emit)
                local.session.headers.update(self.session.headers)
                self._catalog_sessions.append(local.session)
        return local.session

    def _cached_sol_items(self, sol, latest):
        if self._stopped():
            raise InterruptedError('Atualização interrompida.')
        age = 7 * 86400 if sol < latest - 7 else 300
        if sol in self._catalog_checked:
            age = float('inf')
        items = self.catalog_cache.read(sol, age)
        if items is None:
            items = self._sol_items(sol)
            if self._stopped():
                raise InterruptedError('Atualização interrompida.')
            if any(int(item.get('sol', -1)) != sol for item in items):
                raise RuntimeError(f'O catálogo retornou imagens de outro SOL ao consultar {sol}.')
            # Downloads need URLs and IDs, not the large scientific metadata
            # payload repeated for every image in the remote catalog.
            compact = [{'sol': sol, 'imageid': item.get('imageid'),
                        'image_files': {'full_res': self._image_url(item)}} for item in items]
            self.catalog_cache.save(sol, compact)
        self._catalog_checked.add(sol)
        return items

    def _prepare_catalog(self, latest):
        if self.clear_catalog_cache:
            self.message.emit('Limpando cache de catálogos; imagens e marcações serão preservadas...')
            self.catalog_cache.clear(self._stopped)
            self.clear_catalog_cache = False
        self.message.emit(f'Conferindo catálogo completo: SOL 0 até SOL {latest}, antes dos downloads...')
        if self.catalog_workers == 1:
            for sol in range(latest + 1):
                self.catalog_progress.emit(sol, latest + 1)
                self._cached_sol_items(sol, latest)
        else:
            self._prepare_catalog_parallel(latest)
        if self._stopped():
            raise InterruptedError('Atualização interrompida.')
        self.catalog_cache.complete(latest)
        self.catalog_progress.emit(latest + 1, latest + 1)
        self.message.emit(f'Catálogo completo conferido e salvo: {latest + 1} SOLs, incluindo os vazios.')

    def _prepare_catalog_parallel(self, latest):
        self._catalog_session_local = threading.local()
        self._catalog_abort.clear()
        def check(sol):
            self._cached_sol_items(sol, latest)
        sols = iter(range(latest + 1))
        completed = 0
        try:
            with ThreadPoolExecutor(max_workers=self.catalog_workers, thread_name_prefix='catalog') as pool:
                pending = {pool.submit(check, sol) for sol in [next(sols, None) for _ in range(self.catalog_workers)] if sol is not None}
                try:
                    while pending:
                        if self._stopped():
                            raise InterruptedError('Leitura do catálogo interrompida.')
                        done, pending = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                        for future in done:
                            future.result()
                            completed += 1
                            self.catalog_progress.emit(completed, latest + 1)
                            sol = next(sols, None)
                            if sol is not None:
                                pending.add(pool.submit(check, sol))
                except BaseException:
                    self._catalog_abort.set()
                    with self._catalog_sessions_lock:
                        for session in self._catalog_sessions:
                            session.cancel()
                    for future in pending:
                        future.cancel()
                    raise
        finally:
            for session in self._catalog_sessions:
                session.close()
            self._catalog_sessions.clear()
            self._catalog_session_local = None

    @staticmethod
    def _extract_items(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        list_node = data.get("list")
        if isinstance(list_node, dict):
            items = list_node.get("items", [])
        else:
            items = data.get("items", [])
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        if isinstance(items, dict):
            return [items]
        return []

    @staticmethod
    def _image_url(item: dict[str, Any]) -> str | None:
        for key in ("url", "full_res", "image_url", "image"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        image_files = item.get("image_files")
        if isinstance(image_files, dict):
            for key in ("full_res", "full", "original", "large", "medium", "small"):
                value = image_files.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in image_files.values():
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _filename(item: dict[str, Any], url: str | None, fallback_index: int) -> str:
        if url:
            name = os.path.basename(urlparse(url).path)
            if name:
                return name
        image_id = str(item.get("imageid") or f"imagem_{fallback_index}").strip()
        return (image_id or f"imagem_{fallback_index}") + ".jpg"

    def _request_json(self, params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(3):
            if self._stopped():
                raise InterruptedError("Atualização interrompida.")
            try:
                response = self._request_session().get(NASA_API, params=params, timeout=timeout)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError("Resposta inesperada da NASA.")
                return data
            except InterruptedError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and not self._stopped():
                    self.message.emit(f"Falha na NASA; nova tentativa {attempt + 2}/3...")
                    for _ in range(10):
                        if self._stopped():
                            raise InterruptedError("Atualização interrompida.")
                        time.sleep(0.2)
        raise RuntimeError(str(last_exc) if last_exc else "Falha consultando a NASA.")

    def _latest_nasa_sol(self) -> int:
        data = self._request_json({
            "order": "sol desc,date_taken desc",
            "per_page": 1,
            "page": 0,
            "condition_1": "msl:mission",
            "extended": "thumbnail::sample_type::noteq",
        })
        items = self._extract_items(data)
        if not items:
            raise RuntimeError("A NASA não retornou imagens do Curiosity.")
        return int(items[0]["sol"])

    def _local_last_sol(self) -> int | None:
        folders = list_sol_folders(self.root)
        return folders[0][0] if folders else None

    def _folder_for_sol(self, sol: int) -> Path:
        if not hasattr(self, '_known_sol_folders'):
            self._known_sol_folders = list_sol_folders(self.root)
        folders = self._known_sol_folders
        for existing_sol, folder in folders:
            if existing_sol == sol:
                return folder

        # Mantém o mesmo padrão de largura usado pelas pastas existentes.
        width = 0
        if folders:
            match = re.search(r"(\d+)$", folders[0][1].name)
            if match:
                width = len(match.group(1))
        if width > len(str(sol)):
            name = f"SOL{sol:0{width}d}"
        else:
            name = f"SOL{sol}"
        return self.root / name

    def _sol_items(self, sol: int) -> list[dict[str, Any]]:
        page = 0
        items_all: list[dict[str, Any]] = []
        seen: set[str] = set()

        while not self._stopped():
            data = self._request_json({
                "order": "sol asc,instrument_sort desc,sample_type_sort desc,date_taken asc",
                "per_page": 100,
                "page": page,
                "condition_1": "msl:mission",
                "extended": "thumbnail::sample_type::noteq",
                "condition_2": f"{sol}:sol:gte",
                "condition_3": f"{sol}:sol:lte",
            })
            items = self._extract_items(data)
            if not items:
                break

            for item in items:
                url = self._image_url(item) or ""
                image_id = str(item.get("imageid") or "")
                key = url or image_id or repr(sorted(item.items()))
                if key not in seen:
                    seen.add(key)
                    items_all.append(item)

            if len(items) < 100:
                break
            page += 1

        return items_all

    def _download_file(self, sol: int, url: str, destination: Path, filename: str) -> bool:
        attempt = 0
        while not self._stopped():
            try:
                return self._download_file_once(sol, url, destination, filename)
            except requests.RequestException as exc:
                attempt += 1
                self.session.wait_retry(exc, attempt)
        raise InterruptedError("Atualização interrompida.")

    def _download_file_once(self, sol: int, url: str, destination: Path, filename: str) -> bool:
        if url.startswith("/"):
            url = "https://mars.nasa.gov" + url

        part = destination.with_name(destination.name + ".part")
        part_size = 0
        try:
            if part.exists():
                part_size = max(0, part.stat().st_size)
        except OSError:
            part_size = 0

        headers: dict[str, str] = {}
        if part_size > 0:
            headers["Range"] = f"bytes={part_size}-"
            self.message.emit(
                f"Retomando {filename} a partir de {part_size / (1024 * 1024):.1f} MB..."
            )

        try:
            with self.session.get(
                url,
                stream=True,
                timeout=(20, 45),
                headers=headers,
            ) as response:
                # A .part can be larger than the remote file only if something changed.
                # In that case, discard it and retry once from byte zero.
                if response.status_code == 416 and part_size > 0:
                    try:
                        part.unlink()
                    except OSError:
                        pass
                    return self._download_file(sol, url, destination, filename)

                response.raise_for_status()

                if part_size > 0 and response.status_code == 206:
                    mode = "ab"
                    downloaded = part_size
                    content_range = response.headers.get("Content-Range", "")
                    match = re.search(r"/(\d+)$", content_range)
                    if match:
                        total = int(match.group(1))
                    else:
                        remaining = int(response.headers.get("Content-Length") or 0)
                        total = part_size + remaining if remaining > 0 else 0
                else:
                    # Server ignored Range (HTTP 200), so safely restart this file.
                    mode = "wb"
                    downloaded = 0
                    total = int(response.headers.get("Content-Length") or 0)

                last_percent = -2
                if downloaded:
                    percent = int(downloaded * 100 / total) if total > 0 else -1
                    self.file_progress.emit(sol, filename, percent, downloaded, total)
                    last_percent = percent

                with open(part, mode) as fh:
                    for block in response.iter_content(chunk_size=256 * 1024):
                        if self._stopped():
                            # Deliberately KEEP .part. The next run will use HTTP Range.
                            raise InterruptedError("Atualização interrompida.")
                        if not block:
                            continue
                        fh.write(block)
                        downloaded += len(block)
                        percent = int(downloaded * 100 / total) if total > 0 else -1
                        if percent != last_percent:
                            self.file_progress.emit(sol, filename, percent, downloaded, total)
                            last_percent = percent

            if not part.exists() or part.stat().st_size <= 0:
                raise RuntimeError("O arquivo recebido ficou vazio.")

            os.replace(part, destination)
            final_size = destination.stat().st_size
            self.file_progress.emit(sol, filename, 100, final_size, final_size)
            return True

        except InterruptedError:
            # Keep the partial file for the next session.
            raise
        except Exception:
            # Also keep a non-empty partial file after transient network failures.
            # If the server does not support Range, the next run restarts it safely.
            raise

    def run(self) -> None:
        try:
            self.message.emit('Consultando o último SOL disponível na NASA...')
            catalog_latest = self._latest_nasa_sol()
            self._prepare_catalog(catalog_latest)
            if self.only_sol is not None:
                start_sol = self.only_sol
                latest = self.only_sol
                total_sols = 1
                self.message.emit(f"Reverificando somente o SOL {self.only_sol}...")

            else:
                self.message.emit("Consultando o último SOL disponível na NASA...")
                latest = catalog_latest
                if self._stopped():
                    self.finished.emit("Atualização interrompida.")
                    return

                if self.start_sol is not None:
                    start_sol = self.start_sol
                    self.message.emit(
                        f"Reverificando do SOL {start_sol} até SOL {latest}..."
                    )
                else:
                    # The cached full catalog also reveals gaps in local SOLs.
                    start_sol = 0

                if start_sol > latest:
                    self.finished.emit(
                        f"Nada para verificar: SOL inicial {start_sol} é maior "
                        f"que o último SOL NASA ({latest})."
                    )
                    return

                total_sols = latest - start_sol + 1
                self.message.emit(f"Verificando SOL {start_sol} até SOL {latest}...")

            for sol_pos, sol in enumerate(range(start_sol, latest + 1), start=1):
                if self._stopped():
                    self.finished.emit("Atualização interrompida.")
                    return

                self.sol_started.emit(sol, sol_pos, total_sols)
                items = self._cached_sol_items(sol, catalog_latest)
                if self._stopped():
                    self.finished.emit("Atualização interrompida.")
                    return

                self.sol_catalogued.emit(sol, len(items))
                if not items:
                    self.sol_finished.emit(sol, 0, 0, 0)
                    continue

                folder = self._folder_for_sol(sol)
                existed_before = folder.exists()
                folder.mkdir(parents=True, exist_ok=True)
                if not existed_before:
                    self.sol_created.emit(sol, str(folder))

                new_count = 0
                existing_count = 0
                total = len(items)

                for index, item in enumerate(items, start=1):
                    if self._stopped():
                        self.finished.emit("Atualização interrompida.")
                        return

                    url = self._image_url(item)
                    filename = self._filename(item, url, index)
                    self.file_started.emit(sol, filename, index, total)

                    if not url:
                        self.message.emit(f"Sem URL: SOL {sol} / {filename}")
                        self.sol_progress.emit(sol, index, total)
                        continue

                    destination = folder / filename
                    try:
                        if destination.exists() and destination.stat().st_size > 0:
                            existing_count += 1
                            self.file_progress.emit(sol, filename, 100, destination.stat().st_size, destination.stat().st_size)
                        else:
                            if destination.exists():
                                try:
                                    destination.unlink()
                                except OSError:
                                    pass
                            self._download_file(sol, url, destination, filename)
                            new_count += 1
                            self.file_downloaded.emit(sol, str(destination))
                    except InterruptedError:
                        self.finished.emit("Atualização interrompida.")
                        return
                    except Exception as exc:
                        self.message.emit(f"Erro em {filename}: {exc}")

                    self.sol_progress.emit(sol, index, total)

                self.sol_finished.emit(sol, total, new_count, existing_count)

            if self.only_sol is not None:
                self.finished.emit(f"Reverificação do SOL {self.only_sol} concluída.")
            elif self.start_sol is not None:
                self.finished.emit(
                    f"Reverificação do SOL {self.start_sol} até SOL {latest} concluída."
                )
            else:
                self.finished.emit(f"Atualização concluída. Último SOL NASA: {latest}.")

        except InterruptedError:
            self.finished.emit("Atualização interrompida.")
        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit("Atualização encerrada com erro.")
        finally:
            try:
                self.session.close()
            except Exception:
                pass


class CuriositySource(ImageSource):
    id = "curiosity"
    name = "Curiosity (Marte)"
    supports_downloads = True
    collection_label = "SOL"

    def list_collections(self, root):
        return list_sol_folders(root)

    def create_metadata_client(self):
        return MetadataClient()

    def create_downloader(self, root, **options):
        return DownloaderWorker(root, **options)
