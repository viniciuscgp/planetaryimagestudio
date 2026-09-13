import json
import tempfile
import unittest
import threading
import time
from pathlib import Path
from unittest.mock import patch
from planetary_studio.sources.perseverance import PerseveranceWorker


class CatalogCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def worker(self):
        worker = PerseveranceWorker(self.root)
        worker.catalog_workers = 1
        self.addCleanup(worker.session.close)
        return worker

    def test_complete_first_scan_includes_missing_and_empty_sols_then_reuses_cache(self):
        (self.root / 'SOL3').mkdir()
        w = self.worker()
        with patch.object(w, '_sol_items', return_value=[]) as fetch:
            w._prepare_catalog(3)
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [0, 1, 2, 3])
        self.assertEqual(json.loads((w.catalog_cache.folder / 'complete.json').read_text())['latest'], 3)
        reopened = self.worker()
        with patch.object(reopened, '_sol_items') as fetch:
            reopened._prepare_catalog(3)
            fetch.assert_not_called()

    def test_interrupted_scan_resumes_without_claiming_completion(self):
        w = self.worker()
        with patch.object(w, '_sol_items', side_effect=[[], InterruptedError()]):
            with self.assertRaises(InterruptedError):
                w._prepare_catalog(3)
        self.assertFalse((w.catalog_cache.folder / 'complete.json').exists())
        reopened = self.worker()
        with patch.object(reopened, '_sol_items', return_value=[]) as fetch:
            reopened._prepare_catalog(3)
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [1, 2, 3])

    def test_clear_refetches_every_sol_preserving_images_and_annotations(self):
        image = self.root / 'image.png';image.write_bytes(b'image')
        notes = self.root / 'image.png.annotations.json';notes.write_text('{}')
        w = self.worker()
        with patch.object(w, '_sol_items', return_value=[]):
            w._prepare_catalog(2)
        reopened = self.worker();reopened.clear_catalog_cache = True
        with patch.object(reopened, '_sol_items', return_value=[]) as fetch:
            reopened._prepare_catalog(2)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(image.read_bytes(), b'image')
        self.assertEqual(notes.read_text(), '{}')

    def test_download_waits_for_full_catalog_and_fills_missing_sol(self):
        (self.root / 'SOL3').mkdir()
        w = self.worker();events = []
        def catalog(sol):
            events.append(('catalog', sol))
            return [{'sol':sol, 'image_files':{'full_res':f'https://example.org/{sol}.png'}}] if sol == 1 else []
        def download(sol, url, destination, filename):
            events.append(('download', sol));destination.write_bytes(b'image');return True
        errors=[];w.failed.connect(errors.append)
        with patch.object(w, '_latest_nasa_sol', return_value=3), patch.object(w, '_sol_items', side_effect=catalog), patch.object(w, '_download_file', side_effect=download):
            w.run()
        self.assertFalse(errors)
        self.assertEqual(events, [('catalog',0),('catalog',1),('catalog',2),('catalog',3),('download',1)])
        self.assertTrue((self.root / 'SOL1' / '1.png').exists())

    def test_parallel_scan_has_three_independent_sessions_and_no_missing_sols(self):
        w = self.worker();w.catalog_workers = 3
        barrier = threading.Barrier(3)
        lock = threading.Lock()
        seen = []; sessions = set(); active = 0; peak = 0
        def fetch(sol):
            nonlocal active, peak
            session = w._request_session()
            with lock:
                sessions.add(id(session));seen.append(sol);active += 1;peak = max(peak, active)
            if sol < 3:
                barrier.wait(2)
            time.sleep(.01)
            with lock:
                active -= 1
            return []
        with patch.object(w, '_sol_items', side_effect=fetch):
            w._prepare_catalog(8)
        self.assertEqual(sorted(seen), list(range(9)))
        self.assertEqual(peak, 3)
        self.assertEqual(len(sessions), 3)
        self.assertFalse(w._catalog_sessions)
        self.assertTrue((w.catalog_cache.folder / 'complete.json').exists())

    def test_stop_cancels_all_parallel_sessions_without_completing_cache(self):
        w = self.worker();w.catalog_workers = 3
        ready = threading.Barrier(4)
        def fetch(sol):
            session = w._request_session()
            ready.wait(2)
            session.cancelled.wait(2)
            raise InterruptedError()
        stopped = []
        def run():
            try:
                w._prepare_catalog(20)
            except InterruptedError:
                stopped.append(True)
        with patch.object(w, '_sol_items', side_effect=fetch):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                ready.wait(2)
            finally:
                w.stop()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(stopped, [True])
        self.assertFalse(w._catalog_sessions)
        self.assertFalse((w.catalog_cache.folder / 'complete.json').exists())
