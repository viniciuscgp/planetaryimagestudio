import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from planetary_studio.sources.network import CancellableSession
from planetary_studio.sources.perseverance import PerseveranceWorker


class NetworkRetryTests(unittest.TestCase):
    def test_catalog_retries_more_than_three_times_then_succeeds(self):
        session = CancellableSession(retry_message=Mock())
        self.addCleanup(session.close)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"images": []}'
        response._content_consumed = True
        with patch('requests.Session.request', side_effect=[requests.Timeout('slow')] * 5 + [response]) as get, \
             patch.object(session.cancelled, 'wait', return_value=False) as wait:
            self.assertEqual(session.get('https://example.org', timeout=(15, 45)).json(), {'images': []})
        self.assertEqual(get.call_count, 6)
        self.assertEqual(wait.call_count, 5)
        self.assertEqual(get.call_args.kwargs['timeout'], (20, 60))

    def test_stop_interrupts_retry_wait(self):
        waiting = threading.Event()
        session = CancellableSession(retry_message=lambda message: waiting.set())
        self.addCleanup(session.close)
        result = []
        def run():
            try:
                session.get('https://example.org')
            except InterruptedError:
                result.append('stopped')
        with patch('requests.Session.request', side_effect=requests.Timeout('slow')) as get:
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(waiting.wait(1))
            finally:
                session.cancel()
                thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, ['stopped'])
            self.assertEqual(get.call_count, 1)

    def test_stream_failure_retries_same_file(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = PerseveranceWorker(Path(folder))
            self.addCleanup(worker.session.close)
            destination = Path(folder) / 'image.png'
            with patch.object(worker, '_download_file_once', side_effect=[requests.ConnectionError('lost')] * 4 + [True]) as download, \
                 patch.object(worker.session, 'wait_retry') as wait:
                self.assertTrue(worker._download_file(5, 'https://example.org/image.png', destination, 'image.png'))
            self.assertEqual(download.call_count, 5)
            self.assertEqual(wait.call_count, 4)
            self.assertTrue(all(call.args[2] == destination for call in download.call_args_list))
