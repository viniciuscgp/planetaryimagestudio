"""HTTP sessions with cooperative cancellation and bounded idle waits."""
import threading
import requests


class CancellableSession(requests.Session):
    def __init__(self, retry_message=None):
        super().__init__()
        self.cancelled = threading.Event()
        self.retry_message = retry_message

    def cancel(self):
        self.cancelled.set()

    def request(self, method, url, **kwargs):
        attempt = 0
        while True:
            try:
                return self._request_once(method, url, **kwargs)
            except requests.RequestException as exc:
                if self.retry_message is None:
                    raise
                attempt += 1
                self.wait_retry(exc, attempt)

    def wait_retry(self, error, attempt):
        if self.cancelled.is_set():
            raise InterruptedError('Download interrompido.')
        delay = min(30, 2 ** min(attempt, 5))
        if self.retry_message is not None:
            self.retry_message(f'Falha de conexão: {error}. Nova tentativa em {delay}s (tentativa {attempt + 1}). Use Parar para interromper.')
        if self.cancelled.wait(delay):
            raise InterruptedError('Download interrompido.')

    def _request_once(self, method, url, **kwargs):
        if self.cancelled.is_set():
            raise InterruptedError('Consulta interrompida.')
        timeout = kwargs.get('timeout') or (20, 60)
        if not isinstance(timeout, tuple):
            timeout = (timeout, timeout)
        if self.retry_message is not None:
            timeout = (max(timeout[0] or 20, 20), max(timeout[1] or 60, 60))
        kwargs['timeout'] = timeout
        streaming = kwargs.get('stream', False)
        kwargs['stream'] = True
        response = super().request(method, url, **kwargs)
        try:
            if self.cancelled.is_set():
                raise InterruptedError('Consulta interrompida.')
            if self.retry_message is not None and not (streaming and response.status_code == 416):
                response.raise_for_status()
            if not streaming:
                chunks = []
                for chunk in response.iter_content(64 * 1024):
                    if self.cancelled.is_set():
                        raise InterruptedError('Consulta interrompida.')
                    chunks.append(chunk)
                response._content = b''.join(chunks)
                response._content_consumed = True
            return response
        except BaseException:
            response.close()
            raise
