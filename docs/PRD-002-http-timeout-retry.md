# PRD-002: HTTP Timeout Consistency & Retry Logic

**Project:** Lyra Multi-Agent Protein Reasoning System  
**Priority:** Critical — Demo Killer  
**Estimated Effort:** 1–2 hours  
**Target Files:** `mcp_servers/alphafold_mcp.py`, `mcp_servers/uniprot_mcp.py`, all agent files with `requests.get()` or Azure OpenAI calls  
**Depends On:** None (can be done in parallel with PRD-001)

---

## Problem Statement

HTTP calls throughout Lyra have inconsistent or missing timeouts, and zero retry logic. Both code reviews flagged this independently:

- **Codex review:** `alphafold_mcp.py:23` and `:57` call `requests.get()` with no timeout — a stalled AlphaFold API hangs the entire pipeline indefinitely
- **Architecture review:** Some calls have 10–15s timeouts, others have none. No retry/backoff anywhere — a single transient 429 or 503 causes immediate failure

During a demo or judge evaluation, either of these scenarios is fatal: the system either freezes with no feedback, or dies on a temporary API hiccup that would have resolved in 2 seconds.

### Current Behavior

```
Orchestrator → Query Agent → AlphaFold API (no timeout)

Scenario A: API is slow
→ requests.get() blocks indefinitely
→ Pipeline frozen — no output, no error, no way to recover
→ Demo: presenter stares at screen

Scenario B: API returns 429 (rate limited)
→ requests.get() returns 429
→ Agent treats it as failure
→ Pipeline aborts for that protein
→ Demo: "Why did it fail? The API works fine when I curl it manually"
```

### Desired Behavior

```
Scenario A: API is slow
→ requests.get() times out after 30s
→ Raises requests.exceptions.Timeout
→ Caught by PRD-001 task isolation (or local handler)
→ Clear error: "AlphaFold API timed out after 30s for protein Q8I3H7"

Scenario B: API returns 429 (rate limited)
→ First attempt: 429 → wait 1s
→ Second attempt: 429 → wait 2s
→ Third attempt: 200 ✅ → continue normally
→ Demo: brief pause, then results appear — audience never notices
```

---

## Requirements

### R1: Enforce Timeouts on ALL HTTP Calls

Every `requests.get()`, `requests.post()`, or equivalent call in the codebase must have an explicit `timeout` parameter.

**Default timeouts by call type:**

| Call Type | Connect Timeout | Read Timeout | Rationale |
|-----------|----------------|--------------|-----------|
| AlphaFold metadata lookup | 10s | 20s | Small JSON responses, API can be slow |
| AlphaFold structure download (PDB/mmCIF) | 10s | 45s | Large files, allow more time |
| UniProt search | 10s | 20s | Search queries vary in complexity |
| UniProt annotation fetch | 10s | 15s | Single-record lookups are fast |
| Azure OpenAI completion | 10s | 60s | LLM inference can be slow on complex prompts |

**Implementation:** Use tuple timeouts `(connect, read)`:
```python
requests.get(url, timeout=(10, 20))
```

### R2: Centralize HTTP Configuration

Create a shared HTTP configuration module so timeouts and retry settings are defined once, not scattered across files.

**New file:** `config/http_config.py`

```python
"""Centralized HTTP configuration for all Lyra API calls."""

# Timeout defaults (connect_seconds, read_seconds)
TIMEOUTS = {
    "alphafold_metadata": (10, 20),
    "alphafold_structure": (10, 45),
    "uniprot_search": (10, 20),
    "uniprot_annotation": (10, 15),
    "azure_openai": (10, 60),
    "default": (10, 30),
}

# Retry configuration
RETRY = {
    "max_attempts": 3,
    "retry_on_status": [429, 500, 502, 503, 504],
    "backoff_base": 1.0,      # seconds
    "backoff_multiplier": 2.0, # exponential: 1s, 2s, 4s
    "backoff_max": 10.0,       # cap at 10 seconds
}
```

### R3: Add Retry with Exponential Backoff

Implement retry logic for transient failures. Use the `tenacity` library (add to `requirements.txt`) or implement a lightweight wrapper.

**Retry conditions — DO retry:**
- HTTP 429 (Too Many Requests)
- HTTP 500, 502, 503, 504 (Server errors)
- `requests.exceptions.ConnectionError`
- `requests.exceptions.Timeout` (on first occurrence — still worth one retry)

**DO NOT retry:**
- HTTP 400 (Bad Request — our fault, retrying won't help)
- HTTP 401, 403 (Auth issues — retrying won't help)
- HTTP 404 (Not Found — protein doesn't exist, retrying won't help)
- `json.JSONDecodeError` (response was garbage, unlikely to change)

**Backoff schedule:**
```
Attempt 1: immediate
Attempt 2: wait 1s
Attempt 3: wait 2s
→ After 3 failures: raise with clear error message
```

### R4: Create a Resilient HTTP Client Wrapper

Build a single wrapper function that all MCP servers and agents use for HTTP calls. This ensures consistent behavior everywhere.

```python
def resilient_get(url, timeout_key="default", params=None, headers=None):
    """
    HTTP GET with consistent timeouts and retry logic.
    
    Args:
        url: The URL to fetch
        timeout_key: Key from TIMEOUTS config (e.g., "alphafold_metadata")
        params: Query parameters
        headers: Request headers
    
    Returns:
        requests.Response on success
    
    Raises:
        requests.exceptions.Timeout: After all retries exhausted on timeout
        requests.exceptions.HTTPError: After all retries exhausted on server error
        requests.exceptions.HTTPError: Immediately on 4xx client errors (no retry)
    """
```

### R5: Surface Timeout/Retry Events in Logs

When a retry occurs, log it so it's visible during demos and debugging:

```
[WARN] AlphaFold API returned 429 for Q8I3H7 — retrying in 1s (attempt 2/3)
[WARN] AlphaFold API returned 429 for Q8I3H7 — retrying in 2s (attempt 3/3)
[INFO] AlphaFold API succeeded for Q8I3H7 on attempt 3
```

Or on final failure:
```
[ERROR] AlphaFold API failed for Q8I3H7 after 3 attempts — last error: 429 Too Many Requests
```

Use Python's `logging` module (not `print()`). If `logging` isn't already configured in the project, add a basic configuration:

```python
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
```

### R6: Update requirements.txt

Add `tenacity` to `requirements.txt` if using it for retry logic:

```
tenacity>=8.2.0
```

If implementing retry manually (no external dependency), skip this — but `tenacity` is battle-tested and saves time.

---

## Implementation Guidance

### Step 1: Create the HTTP Config Module

```
lyra-protein-reasoning/
├── config/
│   ├── __init__.py
│   └── http_config.py      ← NEW
```

Define all timeout and retry constants here. Every other file imports from this one location.

### Step 2: Build the Resilient HTTP Wrapper

**Option A: Using `tenacity` (recommended)**

```python
# config/http_client.py

import requests
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_result
from config.http_config import TIMEOUTS, RETRY

logger = logging.getLogger(__name__)

def _is_retryable_status(response):
    """Return True if the response status code should trigger a retry."""
    return response.status_code in RETRY["retry_on_status"]

def _log_retry(retry_state):
    """Log retry attempts."""
    exception = retry_state.outcome.exception()
    attempt = retry_state.attempt_number
    logger.warning(
        f"HTTP request failed (attempt {attempt}/{RETRY['max_attempts']}): "
        f"{type(exception).__name__ if exception else 'retryable status'} — "
        f"retrying in {retry_state.next_action.sleep:.1f}s"
    )

@retry(
    stop=stop_after_attempt(RETRY["max_attempts"]),
    wait=wait_exponential(
        multiplier=RETRY["backoff_base"],
        max=RETRY["backoff_max"]
    ),
    retry=(
        retry_if_exception_type((requests.exceptions.Timeout, requests.exceptions.ConnectionError))
        | retry_if_result(_is_retryable_status)
    ),
    before_sleep=_log_retry,
    reraise=True,
)
def _get_with_retry(url, timeout, params=None, headers=None):
    """Internal: GET with retry. Called by resilient_get()."""
    response = requests.get(url, timeout=timeout, params=params, headers=headers)
    if response.status_code in RETRY["retry_on_status"]:
        return response  # triggers retry via retry_if_result
    response.raise_for_status()  # raises immediately on 4xx
    return response


def resilient_get(url, timeout_key="default", params=None, headers=None):
    """
    Public API: HTTP GET with consistent timeouts and retry.
    
    Raises clear errors with context on final failure.
    """
    timeout = TIMEOUTS.get(timeout_key, TIMEOUTS["default"])
    try:
        return _get_with_retry(url, timeout=timeout, params=params, headers=headers)
    except requests.exceptions.Timeout:
        raise requests.exceptions.Timeout(
            f"Request to {url} timed out after {RETRY['max_attempts']} attempts "
            f"(timeout: {timeout[0]}s connect, {timeout[1]}s read)"
        )
    except requests.exceptions.ConnectionError:
        raise requests.exceptions.ConnectionError(
            f"Could not connect to {url} after {RETRY['max_attempts']} attempts"
        )
```

**Option B: Manual implementation (no dependencies)**

```python
import time
import requests
import logging
from config.http_config import TIMEOUTS, RETRY

logger = logging.getLogger(__name__)

def resilient_get(url, timeout_key="default", params=None, headers=None):
    timeout = TIMEOUTS.get(timeout_key, TIMEOUTS["default"])
    last_exception = None
    
    for attempt in range(1, RETRY["max_attempts"] + 1):
        try:
            response = requests.get(url, timeout=timeout, params=params, headers=headers)
            
            if response.status_code in RETRY["retry_on_status"] and attempt < RETRY["max_attempts"]:
                wait_time = min(
                    RETRY["backoff_base"] * (RETRY["backoff_multiplier"] ** (attempt - 1)),
                    RETRY["backoff_max"]
                )
                logger.warning(
                    f"{url} returned {response.status_code} — "
                    f"retrying in {wait_time:.1f}s (attempt {attempt}/{RETRY['max_attempts']})"
                )
                time.sleep(wait_time)
                continue
            
            response.raise_for_status()
            return response
            
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exception = e
            if attempt < RETRY["max_attempts"]:
                wait_time = min(
                    RETRY["backoff_base"] * (RETRY["backoff_multiplier"] ** (attempt - 1)),
                    RETRY["backoff_max"]
                )
                logger.warning(
                    f"{url} — {type(e).__name__} — "
                    f"retrying in {wait_time:.1f}s (attempt {attempt}/{RETRY['max_attempts']})"
                )
                time.sleep(wait_time)
            else:
                raise
    
    raise last_exception
```

### Step 3: Replace All Raw HTTP Calls

Search the entire codebase for `requests.get` and `requests.post`:

```bash
grep -rn "requests\.get\|requests\.post" agents/ mcp_servers/
```

Replace each one with `resilient_get()` using the appropriate timeout key.

**Example — alphafold_mcp.py:**

```python
# BEFORE (line ~23)
response = requests.get(f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}")

# AFTER
from config.http_client import resilient_get
response = resilient_get(
    f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}",
    timeout_key="alphafold_metadata"
)
```

**Example — alphafold_mcp.py (structure download, line ~57):**

```python
# BEFORE
response = requests.get(structure_url)

# AFTER
response = resilient_get(structure_url, timeout_key="alphafold_structure")
```

**Example — uniprot_mcp.py:**

```python
# BEFORE
response = requests.get("https://rest.uniprot.org/uniprotkb/search", params=params)

# AFTER
response = resilient_get(
    "https://rest.uniprot.org/uniprotkb/search",
    timeout_key="uniprot_search",
    params=params
)
```

### Step 4: Handle Azure OpenAI Timeouts

Azure OpenAI client calls may not use `requests.get()` directly — they use the `openai` SDK. Check how timeouts are configured:

```python
# If using openai SDK, set timeout in client init:
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    timeout=60.0,        # ← ADD THIS
    max_retries=3,       # ← ADD THIS (openai SDK has built-in retry)
)
```

The `openai` Python SDK (v1.x+) has built-in retry with backoff for 429/500/503. You just need to ensure `timeout` and `max_retries` are set explicitly rather than relying on defaults.

---

## Files to Modify

| File | Changes |
|------|---------|
| `config/__init__.py` | **NEW** — empty init |
| `config/http_config.py` | **NEW** — timeout and retry constants |
| `config/http_client.py` | **NEW** — `resilient_get()` wrapper |
| `mcp_servers/alphafold_mcp.py` | Replace all `requests.get()` with `resilient_get()` |
| `mcp_servers/uniprot_mcp.py` | Replace all `requests.get()` with `resilient_get()` |
| `agents/query_agent.py` | Replace any direct HTTP calls with `resilient_get()` |
| `agents/structure_agent.py` | Replace any direct HTTP calls with `resilient_get()` |
| `agents/critic_agent.py` | Replace any direct HTTP calls with `resilient_get()` |
| All agent files with Azure OpenAI | Add `timeout=60.0, max_retries=3` to client init |
| `requirements.txt` | Add `tenacity>=8.2.0` (if using Option A) |

---

## Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| AC1 | Zero `requests.get()` or `requests.post()` calls without explicit timeout | `grep -rn "requests\.\(get\|post\)" agents/ mcp_servers/` — all should be replaced with `resilient_get()` or have explicit `timeout=` |
| AC2 | Transient 429 errors are retried and recovered from | Simulate by hitting AlphaFold API rapidly — retries should appear in logs, final result succeeds |
| AC3 | Permanent failures (404, 400) fail immediately without retry | Pass a nonexistent protein ID — should see one attempt, immediate clear error |
| AC4 | Timeout produces a clear error message within expected time | Simulate slow API (or set timeout to 1s) — should fail with timeout message, not hang |
| AC5 | Retry attempts are logged with attempt count and wait time | Check log output during retried requests |
| AC6 | All timeout values are defined in one config file | `config/http_config.py` is the single source of truth |
| AC7 | Azure OpenAI calls have explicit timeout and max_retries | Grep agent files for `AzureOpenAI(` — all should have `timeout=` and `max_retries=` |
| AC8 | Existing tests still pass | Run `test_agent.py` and `test_proteins.py` — no regressions |
| AC9 | `tenacity` (if used) is in `requirements.txt` | `grep tenacity requirements.txt` returns a match |

---

## Test Cases

### Test 1: Normal Operation — No Retries Needed
```
Input: Valid protein ID (Q8I3H7), APIs responsive
Expected: Single attempt per call, no retry logs, normal results
```

### Test 2: Transient 429 Recovery
```
Simulate: AlphaFold returns 429 on first attempt, 200 on second
Expected: Log shows retry, final result is successful, total delay ~1s
```

### Test 3: Persistent Server Error
```
Simulate: AlphaFold returns 503 on all 3 attempts
Expected: 3 attempts logged, clear error after ~3s total (1s + 2s backoff), no hang
```

### Test 4: Timeout Recovery
```
Simulate: Set alphafold_metadata timeout to (1, 2), API responds in 1.5s
Expected: First attempt times out, retry succeeds on second attempt
```

### Test 5: Permanent Timeout
```
Simulate: Set timeout to (1, 1), API always takes 5s+
Expected: 3 timeout attempts, clear error message, total time ~9s (3 attempts + backoff)
```

### Test 6: Client Error — No Retry
```
Input: Invalid protein ID → AlphaFold returns 404
Expected: Single attempt, immediate failure, no retry, clear "not found" message
```

### Test 7: Connection Refused
```
Simulate: Point URL to localhost:1 (nothing listening)
Expected: 3 connection attempts with backoff, then clear connection error
```

### Test 8: Azure OpenAI Timeout
```
Simulate: Set Azure OpenAI timeout to 1s, send complex prompt
Expected: SDK retries internally, or fails with clear timeout message
```

---

## Out of Scope

- Circuit breaker pattern (overkill for competition scope)
- Per-endpoint rate limit tracking
- Response caching (that's a separate enhancement)
- Async HTTP calls (defer to post-competition)
- Custom retry strategies per agent

---

## Interaction with PRD-001

PRD-001 (Task Isolation) and PRD-002 (Timeouts & Retry) work together as a two-layer defense:

```
Layer 1 (PRD-002): resilient_get() retries transient failures automatically
   ↓ (if all retries exhausted)
Layer 2 (PRD-001): Orchestrator catches the exception, logs it, skips downstream, continues other proteins
```

This means:
- A brief API hiccup → PRD-002 handles it silently, nobody notices
- A sustained API outage → PRD-002 exhausts retries, raises → PRD-001 catches it, reports failure, continues with other proteins
- Demo keeps running either way

---

## Notes for Implementation Agent

- Start by running `grep -rn "requests\.get\|requests\.post" agents/ mcp_servers/` to find ALL HTTP calls — don't miss any
- Check if `import requests` appears in agent files that don't make direct HTTP calls (they might be using it indirectly)
- The Azure OpenAI SDK (`openai` package) handles its own retries — you just need to set `timeout` and `max_retries` in the client constructor, don't wrap SDK calls in `resilient_get()`
- If the project doesn't have a `config/` directory yet, create it with an `__init__.py`
- Preserve existing response parsing logic — only the HTTP call mechanism changes
- Run existing tests after changes to confirm no regressions
