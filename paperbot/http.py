"""Only idempotent reads retry automatically; uncertain writes reconcile next run."""
import time
import logging
import requests

log = logging.getLogger(__name__)


def error_summary(exc):
    """Never include exception text: it can contain credentials or webhook URLs."""
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    if type(status) is not int:
        status = getattr(exc, 'status_code', None)
    return type(exc).__name__ + (f'; HTTP {status}' if type(status) is int else '')


def read(url, service='HTTP', **kwargs):
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=(10, 30), **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 2 or (status is not None and status != 429 and status < 500):
                log.error('%s read failed after %s attempt(s) (%s)', service, attempt + 1, error_summary(exc))
                raise
            delay = 3 * (2 ** attempt)
            log.warning('%s read attempt %s failed (%s); retry in %ss', service, attempt + 1, error_summary(exc), delay)
            time.sleep(delay)
