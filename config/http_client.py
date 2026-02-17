"""Resilient HTTP client with consistent timeouts and retry logic."""

import time
import logging

import requests

from config.http_config import TIMEOUTS, RETRY

logger = logging.getLogger(__name__)


def resilient_get(url, timeout_key="default", params=None, headers=None):
    """
    HTTP GET with consistent timeouts and retry logic.

    Retries on transient failures (429, 5xx, connection errors, timeouts).
    Fails immediately on client errors (400, 401, 403, 404).

    Args:
        url: The URL to fetch
        timeout_key: Key from TIMEOUTS config (e.g., "alphafold_metadata")
        params: Query parameters
        headers: Request headers

    Returns:
        requests.Response on success

    Raises:
        requests.exceptions.Timeout: After all retries exhausted on timeout
        requests.exceptions.ConnectionError: After all retries exhausted
        requests.exceptions.HTTPError: After all retries exhausted on server error,
            or immediately on 4xx client errors (no retry)
    """
    timeout = TIMEOUTS.get(timeout_key, TIMEOUTS["default"])
    max_attempts = RETRY["max_attempts"]
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, timeout=timeout, params=params, headers=headers)

            # Retryable server errors
            if response.status_code in RETRY["retry_on_status"]:
                if attempt < max_attempts:
                    wait_time = _backoff_delay(attempt)
                    logger.warning(
                        f"{url} returned {response.status_code} — "
                        f"retrying in {wait_time:.1f}s (attempt {attempt}/{max_attempts})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(
                        f"{url} failed after {max_attempts} attempts — "
                        f"last status: {response.status_code}"
                    )
                    response.raise_for_status()

            # Non-retryable errors (4xx) — fail immediately
            response.raise_for_status()

            if attempt > 1:
                logger.info(f"{url} succeeded on attempt {attempt}")

            return response

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exception = e
            if attempt < max_attempts:
                wait_time = _backoff_delay(attempt)
                logger.warning(
                    f"{url} — {type(e).__name__} — "
                    f"retrying in {wait_time:.1f}s (attempt {attempt}/{max_attempts})"
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"{url} failed after {max_attempts} attempts — "
                    f"last error: {type(e).__name__}: {e}"
                )
                raise

    raise last_exception


def _backoff_delay(attempt):
    """Calculate exponential backoff delay for the given attempt number."""
    return min(
        RETRY["backoff_base"] * (RETRY["backoff_multiplier"] ** (attempt - 1)),
        RETRY["backoff_max"]
    )
