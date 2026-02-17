# PRD-003: Query Agent Defensive Response Handling

**Project:** Lyra Multi-Agent Protein Reasoning System  
**Priority:** High — Demo Killer  
**Estimated Effort:** 30–60 minutes  
**Target Files:** `agents/query_agent.py`, `agents/orchestrator.py`
**Related Files:** `mcp_servers/alphafold_mcp.py`, `mcp_servers/uniprot_mcp.py`
**Depends On:** PRD-001 (orchestrator task isolation must be in place)

---

## Problem Statement

The Query Agent crashes with a `KeyError` when it receives error responses or incomplete data from MCP servers. Both code reviews flagged this:

- **Codex review (Finding #1, High):** `query_agent.py:87` appends raw `summarize_protein()` output, then `:95` directly indexes `p['description']`, `p['organism']`, and `p['drug_target_assessment']`. If `summarize_protein()` returns `{"error": ...}`, this raises `KeyError`.
- **Architecture review (Finding #3, Medium):** Silent JSON parse failures — agents fall back to incomplete data without surfacing warnings.

This is the most common crash path in the system because it triggers on any invalid, misspelled, or nonexistent protein ID — the single most likely user error.

**Critical integration note:** The main demo pipeline (`LyraOrchestrator.execute_task`) currently calls `summarize_protein()` directly from `mcp_servers/alphafold_mcp.py` (line 179), bypassing `query_agent.py` entirely. PRD-003 must wire the defensive layer into both the query agent AND the orchestrator's `fetch_protein` path. Otherwise the defensive handling exists but never executes in the main pipeline.

### Current Behavior

There are **two** crash paths:

**Path A — via query_agent.py (standalone/test usage):**
```
User asks: "Analyze proteins Q8I3H7 and FAKE_PROTEIN"

→ Query Agent calls summarize_protein("Q8I3H7")
   → Returns {"description": "...", "organism": "...", ...}  ✅

→ Query Agent calls summarize_protein("FAKE_PROTEIN")
   → AlphaFold returns 404
   → MCP server returns {"error": "Protein not found"}

→ Query Agent tries to access result['description']
   → KeyError: 'description'
   → CRASH — no output for any protein
```

**Path B — via orchestrator (main demo pipeline):**
```
User asks: "Analyze proteins Q8I3H7 and FAKE_PROTEIN"

→ Orchestrator calls summarize_protein("FAKE_PROTEIN") directly
   → Returns {"error": "Protein not found"}
   → PRD-001 catches this as soft failure ✅ (no crash)
   → BUT: no input validation, no format checking, no logging of why
```

Path B doesn't crash (PRD-001 catches it), but it also has no input validation — garbage strings, injection attempts, and empty IDs all make unnecessary API calls before failing.

### Desired Behavior

```
User asks: "Analyze proteins Q8I3H7 and FAKE_PROTEIN"

→ Orchestrator's fetch_protein calls process_protein("Q8I3H7")
   → Input validated ✅ → MCP called → returns valid data ✅

→ Orchestrator's fetch_protein calls process_protein("FAKE_PROTEIN")
   → Input validated ✅ → MCP called → error dict returned
   → Logged with context → PRD-001 handles skip logic

→ Query Agent (standalone) also uses process_protein() with same safety

→ Output: 1 valid protein result + 1 clear failure with context
```

---

## Requirements

### R1: Validate MCP Server Responses Before Accessing Fields

Every response from `summarize_protein()`, AlphaFold MCP, or UniProt MCP must be validated before field access.

**Validation checks (in order):**

1. **Is it None?** — MCP server returned nothing
2. **Is it a dict with "error" key?** — MCP server returned an explicit error
3. **Does it have required keys?** — Confirm expected fields exist before indexing

```python
# Required fields for a valid protein summary
REQUIRED_PROTEIN_FIELDS = ["description", "organism"]

# Required fields for a drug target assessment
REQUIRED_ASSESSMENT_FIELDS = ["drug_target_assessment"]
```

**Do NOT assume any field exists.** Use `.get()` with defaults or explicit key checks.

### R2: Replace Direct Dict Indexing with Safe Access

Every instance of `result['key']` on MCP server output must be replaced with safe access.

**Pattern to find:**
```bash
grep -n "\['" agents/query_agent.py
```

**Replace with one of:**

```python
# Option A: .get() with default
description = result.get("description", "No description available")

# Option B: Explicit check + early return
if "description" not in result:
    return {"error": f"Missing 'description' field for protein {protein_id}"}
description = result["description"]
```

**Prefer Option B for required fields** (description, organism) — these indicate a fundamentally broken response. **Use Option A for optional/nice-to-have fields** that shouldn't block the pipeline.

### R3: Define Required vs Optional Fields

Split protein data fields into required (must be present for analysis to proceed) and optional (use defaults if missing):

**Required — fail the protein if missing:**
- `description` — can't analyze without knowing what the protein is
- `organism` — critical for biological context

If any required field is missing, return a structured error dict for that protein. Do NOT attempt partial-data handling — a response missing `description` or `organism` indicates a fundamentally broken response and should fail cleanly so PRD-001 can skip downstream tasks.

**Optional — use defaults if missing:**
- `drug_target_assessment` — default to `"Assessment unavailable"`
- `gene` — default to `"Unknown"`
- `length` — default to `None`
- `confidence` — default to `None`
- Any other metadata fields

**Note:** Field names must match the existing `summarize_protein()` return schema (`gene`, `length`, `confidence`, `uniprot_id`) — not renamed alternatives.

### R4: Return Structured Errors, Don't Raise

When the Query Agent encounters bad data for a protein, it should return a structured error dict — **not** raise an exception. This is consistent with how the MCP servers already handle errors and works with PRD-001's dual detection model.

```python
# On validation failure, return:
{
    "uniprot_id": protein_id,
    "error": "Protein not found in AlphaFold database",
    "source": "query_agent",
}
```

The error dict MUST contain an `"error"` key (for PRD-001 soft-failure detection) and SHOULD contain `"uniprot_id"` (matching existing codebase conventions, not `"protein_id"`).

**Type safety:** Before accessing `.items()`, `.get()`, or any dict method on an MCP response, verify `isinstance(result, dict)` first. Non-dict responses (None, lists, strings) must be caught and converted to error dicts.

### R5: Validate Input Protein IDs Before API Calls

Add basic format validation on protein IDs before making any API calls:

```python
import re

UNIPROT_ID_PATTERN = re.compile(r'^[A-Za-z0-9]{1,15}$')

def validate_protein_id(protein_id):
    """
    Basic format check. Not a guarantee the protein exists,
    just catches obvious garbage before wasting an API call.
    """
    if not protein_id or not isinstance(protein_id, str):
        return False, "Protein ID must be a non-empty string"
    if not UNIPROT_ID_PATTERN.match(protein_id):
        return False, f"Invalid protein ID format: '{protein_id}'"
    return True, None
```

**Note:** The regex is intentionally loose (`[A-Za-z0-9]{1,15}`) — it catches obvious junk (empty strings, special characters, SQL injection attempts) without rejecting valid but unusual IDs. The API is the ultimate validator.

### R6: Handle Optional Missing Fields Gracefully

When required fields are present but optional fields are missing, use `.get()` with sensible defaults. Do NOT fail the protein over missing optional fields.

```python
# After confirming required fields (description, organism) are present:
protein_summary = {
    "uniprot_id": protein_id,
    "description": result["description"],
    "organism": result["organism"],
    "gene": result.get("gene", "Unknown"),
    "length": result.get("length", None),
    "confidence": result.get("confidence", None),
    "drug_target_assessment": result.get("drug_target_assessment", "Assessment unavailable"),
}
```

**Note:** Field names match existing `summarize_protein()` return schema exactly. No renaming.

### R7: Log All Validation Failures

Every validation failure should be logged with context:

```python
import logging
logger = logging.getLogger(__name__)

# On error dict from MCP server:
logger.warning(f"AlphaFold returned error for {protein_id}: {result.get('error', 'unknown')}")

# On missing required field:
logger.warning(f"Missing required field '{field}' in response for {protein_id}")

# On invalid protein ID format:
logger.warning(f"Invalid protein ID format rejected: '{protein_id}'")
```

Use `getLogger(__name__)` — do NOT call `basicConfig()` here (per PRD-001 v2 R7).

---

## Implementation Guidance

### Step 1: Add Input Validation

At the top of the Query Agent's main function, before any API calls:

```python
import re
import logging

logger = logging.getLogger(__name__)

UNIPROT_ID_PATTERN = re.compile(r'^[A-Za-z0-9]{1,15}$')
REQUIRED_PROTEIN_FIELDS = ["description", "organism"]

def validate_protein_id(protein_id):
    if not protein_id or not isinstance(protein_id, str):
        return False, "Protein ID must be a non-empty string"
    protein_id = protein_id.strip()
    if not UNIPROT_ID_PATTERN.match(protein_id):
        return False, f"Invalid protein ID format: '{protein_id}'"
    return True, None
```

### Step 2: Create the Defensive Wrapper

Create `process_protein()` in `query_agent.py`. This function is the single defensive entry point — used by both the query agent's own `execute_query()` and the orchestrator's `fetch_protein` task.

```python
def process_protein(protein_id):
    """Query and validate a single protein. Returns structured result or error dict."""

    # Input validation
    valid, error_msg = validate_protein_id(protein_id)
    if not valid:
        logger.warning(f"Rejected invalid protein ID: {protein_id} — {error_msg}")
        return {"uniprot_id": protein_id, "error": error_msg, "source": "query_agent"}

    # Fetch from MCP server
    result = summarize_protein(protein_id)

    # Type check: ensure we got a dict back
    if result is None:
        logger.warning(f"No response from MCP server for {protein_id}")
        return {"uniprot_id": protein_id, "error": "No response from protein database", "source": "query_agent"}

    if not isinstance(result, dict):
        logger.warning(f"Unexpected response type for {protein_id}: {type(result).__name__}")
        return {"uniprot_id": protein_id, "error": f"Unexpected response type: {type(result).__name__}", "source": "query_agent"}

    # Check for error dict from MCP server
    if "error" in result:
        logger.warning(f"MCP server error for {protein_id}: {result['error']}")
        return {"uniprot_id": protein_id, "error": result["error"], "source": "query_agent"}

    # Validate required fields — fail cleanly per R3
    missing = [f for f in REQUIRED_PROTEIN_FIELDS if f not in result]
    if missing:
        logger.warning(f"Missing required fields for {protein_id}: {missing}")
        return {
            "uniprot_id": protein_id,
            "error": f"Incomplete data — missing: {', '.join(missing)}",
            "source": "query_agent",
        }

    # Return the validated result as-is (preserving original field names)
    # Optional fields get defaults via .get() only where accessed downstream
    return result
```

**Key design decisions:**
- Returns the original `summarize_protein()` dict on success — no field renaming, no schema drift. This preserves compatibility with all downstream agents that expect `gene`, `length`, `confidence`, `uniprot_id`.
- On failure, returns error dict with `"error"` key (PRD-001 compatible) and `"uniprot_id"` (matching codebase conventions).
- Type-checks `result` with `isinstance(result, dict)` before calling `.get()` or checking keys — non-dict responses cannot crash.

### Step 3: Replace the Protein Processing Loop and Fix All Unsafe Access

**3a. Replace `summarize_protein()` calls with `process_protein()`** in `execute_query()`:

```python
# BEFORE (line ~89)
data = summarize_protein(uid)
results["proteins"].append(data)

# AFTER
data = process_protein(uid)
results["proteins"].append(data)
```

**3b. Fix the `analyze_confidence` path too.** The `get_plddt_scores()` call (line ~86) can also return error dicts. Wrap it with the same input validation:

```python
# BEFORE
if intent == "analyze_confidence":
    data = get_plddt_scores(uid)
    results["proteins"].append({"uniprot_id": uid, "plddt_scores": data})

# AFTER
if intent == "analyze_confidence":
    valid, error_msg = validate_protein_id(uid)
    if not valid:
        results["proteins"].append({"uniprot_id": uid, "error": error_msg, "source": "query_agent"})
        continue
    data = get_plddt_scores(uid)
    if isinstance(data, dict) and "error" in data:
        results["proteins"].append({"uniprot_id": uid, "error": data["error"], "source": "query_agent"})
        continue
    results["proteins"].append({"uniprot_id": uid, "plddt_scores": data})
```

**3c. Fix the summary generation** (line ~95-97) — replace direct indexing with safe access:

```python
# BEFORE
p = results["proteins"][0]
results["summary"] = f"{p['description']} from {p['organism']}. Drug target potential: {p['drug_target_assessment']}"

# AFTER
p = results["proteins"][0]
if isinstance(p, dict) and "error" not in p:
    results["summary"] = (
        f"{p.get('description', 'Unknown protein')} from {p.get('organism', 'Unknown organism')}. "
        f"Drug target potential: {p.get('drug_target_assessment', 'Assessment unavailable')}"
    )
else:
    results["summary"] = f"Failed to fetch protein: {p.get('error', 'Unknown error')}"
```

**3d. Fix `_generate_comparison()`** — `p['uniprot_id']` (line 108) is direct indexing:

```python
# BEFORE
lines.append(f"- {p['uniprot_id']}: confidence={conf}, {assessment}")

# AFTER
lines.append(f"- {p.get('uniprot_id', 'Unknown')}: confidence={conf}, {assessment}")
```

### Step 4: Fix Any Other Unsafe Field Access

Search for all direct dict indexing in the file:

```bash
grep -n "\['" agents/query_agent.py
grep -n '\["' agents/query_agent.py
```

For each match, determine:
1. Is this accessing MCP server output? → Make safe
2. Is this accessing internally-constructed data? → Probably fine, but verify
3. Is this accessing user input? → Validate first

### Step 5: Wire `process_protein()` into the Orchestrator

**This is critical.** The main demo pipeline (`LyraOrchestrator.execute_task`) currently calls `summarize_protein()` directly at line 179, bypassing query_agent.py entirely. Without this step, the defensive layer exists but never runs in the primary execution path.

In `agents/orchestrator.py`:

**5a. Change the import** (line 21):
```python
# BEFORE
from mcp_servers.alphafold_mcp import summarize_protein, get_protein_prediction

# AFTER
from mcp_servers.alphafold_mcp import get_protein_prediction
from query_agent import process_protein
```

**5b. Replace the `fetch_protein` handler** in `execute_task()` (line 177-181):
```python
# BEFORE
if task_type == "fetch_protein":
    self.log(f"\n📡 QUERY AGENT: Fetching {protein}...")
    result = summarize_protein(protein)
    self.results[f"{protein}_summary"] = result
    return result

# AFTER
if task_type == "fetch_protein":
    self.log(f"\n📡 QUERY AGENT: Fetching {protein}...")
    result = process_protein(protein)
    self.results[f"{protein}_summary"] = result
    return result
```

This is a one-line change (`summarize_protein` → `process_protein`) but it routes all protein fetches through the defensive layer. The rest of `execute_all()` (PRD-001) then handles the error dict if `process_protein` returns one.

**Note:** `summarize_protein` is still imported by other agents (reasoning_agent.py calls it indirectly). Those paths are protected by PRD-001's exception handling. Only the orchestrator's direct call needs this change.

---

## Files to Modify

| File | Changes |
|------|---------|
| `agents/query_agent.py` | Main changes — `process_protein()`, `validate_protein_id()`, safe access, structured errors, logging |
| `agents/orchestrator.py` | Integration — import `process_protein`, replace `summarize_protein` call in `fetch_protein` handler |

**Files that should NOT change:**
- `mcp_servers/alphafold_mcp.py` — error dict returns are fine, the Query Agent just needs to handle them
- `mcp_servers/uniprot_mcp.py` — same
- Other agents (structure, reasoning, critic, synthesis) — they receive validated data from the orchestrator

---

## Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| AC1 | Nonexistent protein ID returns structured error dict, not KeyError crash | Call `process_protein("TOTALLY_FAKE_ID")` — should get `{"error": "...", "uniprot_id": "TOTALLY_FAKE_ID"}` |
| AC2 | Empty string protein ID returns error before any API call | Call `process_protein("")` — should get validation error, no HTTP request made |
| AC3 | Special characters in protein ID are rejected | Call `process_protein("'; DROP TABLE")` — should get validation error |
| AC4 | Valid protein ID returns data with same schema as `summarize_protein()` | Call `process_protein("Q8I3H7")` — returned dict has `uniprot_id`, `description`, `organism`, `gene`, `length`, `confidence`, `drug_target_assessment` |
| AC5 | Missing optional fields use defaults, don't crash | Simulate response missing `drug_target_assessment` — downstream code gets `"Assessment unavailable"` via `.get()` |
| AC6 | Missing required fields return structured error dict (no partial_data) | Simulate response missing `description` — should get `{"error": "Incomplete data — missing: description", ...}` |
| AC7 | No direct `result['key']` indexing on MCP output in query_agent.py | `grep -n "\['" agents/query_agent.py` returns zero matches on any MCP-returned dict access. Internal data structures (e.g., `task["task"]`) are excluded from this check. |
| AC8 | All validation failures are logged via `logging.getLogger` | Check log output for warning messages on bad protein IDs, MCP errors, missing fields |
| AC9 | Returned error dicts are compatible with PRD-001 dual detection | Error dicts contain `"error"` key so orchestrator's soft-failure check detects them |
| AC10 | Orchestrator uses `process_protein()` instead of `summarize_protein()` directly | `grep -n "summarize_protein" agents/orchestrator.py` returns no matches (import removed, call replaced) |
| AC11 | `analyze_confidence` path in `execute_query()` also validates input and handles error dicts | Call with invalid ID + `intent="analyze_confidence"` — returns error dict, no crash |

---

## Test Cases

### Test 1: Valid Protein ID
```
Input: "Q8I3H7"
Expected: Complete protein summary with all fields, data_completeness="full"
```

### Test 2: Nonexistent Protein ID
```
Input: "ZZZZZZZZZ"
Expected: {"protein_id": "ZZZZZZZZZ", "error": "Protein not found...", "source": "query_agent"}
No KeyError, no crash
```

### Test 3: Empty String
```
Input: ""
Expected: Validation error returned immediately, no API call made
```

### Test 4: None Input
```
Input: None
Expected: Validation error: "Protein ID must be a non-empty string"
```

### Test 5: Special Characters / Injection Attempt
```
Input: "'; DROP TABLE proteins;--"
Expected: Validation error: "Invalid protein ID format"
```

### Test 6: MCP Server Returns Error Dict
```
Simulate: summarize_protein() returns {"error": "Service unavailable"}
Expected: Query Agent returns structured error dict, doesn't crash
```

### Test 7: MCP Server Returns None
```
Simulate: summarize_protein() returns None
Expected: Query Agent returns structured error: "No response from protein database"
```

### Test 8: Partial Data — Missing Optional Field
```
Simulate: Response has description and organism but no drug_target_assessment
Expected: Returns valid summary with drug_target_assessment="Assessment unavailable"
```

### Test 9: Partial Data — Missing Required Field
```
Simulate: Response has organism but no description
Expected: Returns error dict with partial_data containing the organism
```

### Test 10: Multiple Proteins — Mix of Valid and Invalid
```
Input: ["Q8I3H7", "FAKE", "P04637"]
Expected: 2 valid results + 1 error dict, no crash, all three processed
```

---

## Interaction with PRD-001 and PRD-002

```
Layer 0 (PRD-003): Query Agent validates input and response data
   → process_protein() called by orchestrator's fetch_protein AND query_agent's execute_query()
   → Returns clean result OR structured error dict
   ↓
Layer 1 (PRD-002): HTTP calls have timeouts and retry
   → Transient failures recovered silently
   ↓
Layer 2 (PRD-001): Orchestrator detects error dicts OR catches exceptions
   → Failed proteins skipped, others continue
```

PRD-003 is the **innermost defense** — it prevents garbage from entering the pipeline in the first place. PRD-001 is the **outer safety net** that catches anything PRD-003 misses. PRD-002 ensures the HTTP layer between them is reliable.

**Integration path:** `orchestrator.execute_task("fetch_protein")` → `query_agent.process_protein()` → `alphafold_mcp.summarize_protein()` → PRD-002 `resilient_get()`

---

## Out of Scope

- Changing MCP server error handling patterns (they're fine as-is)
- Caching protein lookups
- Validating that a protein ID actually exists before querying (the API is the validator)
- Changes to other agents (structure, reasoning, critic, synthesis) — they receive data from orchestrator, not query_agent directly
- Adding automated test infrastructure (AC10 is verified by grep; a proper test suite is a separate effort)

---

## Notes for Implementation Agent

- Run `grep -n "\['" agents/query_agent.py` and `grep -n '\["' agents/query_agent.py` to find ALL direct dict indexing — the specific lines referenced in this PRD are approximate
- `summarize_protein()` is defined in `mcp_servers/alphafold_mcp.py` (line 83). On error it returns `{"error": "Protein X not found in AlphaFold"}`. On success it returns a dict with keys: `uniprot_id`, `description`, `organism`, `gene`, `length`, `confidence` (nested dict), `structure_urls`, `drug_target_assessment`
- Keep the error dict format consistent: always include `"error"` and `"uniprot_id"` keys (not `"protein_id"` — match codebase convention)
- `process_protein()` must be importable from `query_agent.py` by `orchestrator.py`. Ensure import paths work.
- In `orchestrator.py`, replace the `summarize_protein` import and call — this is the critical integration step (Step 5)
- Use `logging.getLogger(__name__)` only — no `basicConfig()` (per PRD-001 v2 R7)
- After making changes, test manually with at least one valid ID (`Q8I3H7`) and one invalid ID to confirm both paths work
- Verify AC10 with `grep -n "summarize_protein" agents/orchestrator.py` — should return no matches after the change
