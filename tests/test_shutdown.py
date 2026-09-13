import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QRunnable
from PySide6.QtTest import QTest
import tests.test_download_navigation as navigation
from planetary_studio.sources.network import CancellableSession


class WaitingJob(QRunnable):
    def __init__(self):
        super().__init__()
        self.cancel = threading.Event()
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(self):
        self.started.set()
        self.cancel.wait(3)
        self.stopped.set()


class ShutdownTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_close_cancels_pools_and_discards_queued_work(self):
        self.image(1, 'a.png')
        window = self.window()
        window.show()
        window.thread_pool.waitForDone(1000)
        self.app.processEvents()
        window.thread_pool.setMaxThreadCount(1)
        running, queued, filtering = WaitingJob(), WaitingJob(), WaitingJob()
        window._sol_summary_jobs[100] = running
        window._sol_summary_jobs[101] = queued
        window._filter_jobs[100] = filtering
        window.thread_pool.start(running)
        window.thread_pool.start(queued)
        window._filter_pool.start(filtering)
        self.assertTrue(running.started.wait(1))
        self.assertTrue(filtering.started.wait(1))
        start = time.monotonic()
        window.close()
        self.assertLess(time.monotonic() - start, .5)
        for _ in range(100):
            self.app.processEvents()
            if not window.isVisible():
                break
            QTest.qWait(10)
        self.assertFalse(window.isVisible())
        self.assertTrue(running.stopped.is_set())
        self.assertTrue(filtering.stopped.is_set())
        self.assertFalse(queued.started.is_set())
        self.assertFalse(window._background_tasks_running())
        for timer in (window._thumb_timer, window._thumb_resize_timer,
                      window._sol_summary_timer, window._filter_timer, window._inline_timer):
            self.assertFalse(timer.isActive())

    def test_cancelled_network_session_never_starts_another_request(self):
        session = CancellableSession()
        self.addCleanup(session.close)
        session.cancel()
        with patch('requests.Session.request') as request:
            with self.assertRaises(InterruptedError):
                session.get('https://example.org', timeout=45)
            request.assert_not_called()

    def test_repeated_close_does_not_save_again_after_shutdown_started(self):
        self.image(1, 'a.png')
        window = self.window()
        with patch.object(window, '_save_state') as save:
            window.close()
            for _ in range(20):
                self.app.processEvents()
                QTest.qWait(5)
            window.close()
            self.assertEqual(save.call_count, 1)
