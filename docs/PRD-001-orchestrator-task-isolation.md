# PRD-001: Orchestrator Task Failure Isolation

**Project:** Lyra Multi-Agent Protein Reasoning System
**Priority:** Critical — Demo Killer
**Estimated Effort:** 1–2 hours
**Target File:** `agents/orchestrator.py`
**Related Files:** `agents/query_agent.py`, `agents/lyra.py`

---

## Problem Statement

The Lyra orchestrator executes tasks sequentially with no per-task error handling (`orchestrator.py`, `execute_all` method). If any single task fails — a bad protein ID, an API timeout, a malformed response — the entire pipeline aborts. In a multi-protein analysis, one problematic protein kills results for all proteins, including those that would have succeeded.

Both code reviews independently flagged this as a top-severity issue.

**Important context on failure modes:** The current MCP servers use **two different failure patterns**. Some errors raise exceptions (network timeouts, non-404 HTTP errors via `raise_for_status()`), but the most common failure — an invalid protein ID returning 404 — is handled as a **soft failure**: the function returns `{"error": "..."}` without raising (see `alphafold_mcp.py:25`, `alphafold_mcp.py:90`). The orchestrator currently stores these soft-failure dicts as if they were successful results. This PRD must handle both failure modes.

### Current Behavior

```
Orchestrator receives 3 proteins to analyze: [P04637, INVALID_ID, Q8I3H7]

→ Task 1: P04637 — ✅ Success
→ Task 2: INVALID_ID — ❌ Exception raised
→ Task 3: Q8I3H7 — ⛔ Never executes
→ Pipeline: CRASH — no output at all
```

### Desired Behavior

```
Orchestrator receives 3 proteins to analyze: [P04637, INVALID_ID, Q8I3H7]

→ Task 1: P04637 — ✅ Success → result stored
→ Task 2: INVALID_ID — ❌ Exception caught → error logged, marked as failed, continue
→ Task 3: Q8I3H7 — ✅ Success → result stored
→ Pipeline: COMPLETES — returns results for 2/3 proteins + failure report for 1
```

---

## Requirements

### R1: Detect Both Hard and Soft Failures

**Location:** `orchestrator.py`, the `execute_all` method

The error isolation must handle **two distinct failure modes**:

**Hard failures (exceptions):**
- Each individual task must be wrapped in its own `try/except` block
- Catch specific exceptions: `Exception` (not bare `except:`)
- Do NOT catch `SystemExit` or `KeyboardInterrupt`
- On failure: log the error, record it in task results, continue to next task

**Soft failures (error dicts):**
- After `execute_task()` returns, check if the result contains an `"error"` key (i.e., `isinstance(result, dict) and "error" in result`)
- If so, treat it as a failure: log the error, record it in task results with `status="failed"`, trigger skip logic for downstream tasks
- This is critical because the most common failure path — invalid protein ID returning 404 — uses this pattern (`alphafold_mcp.py:25-26`, `alphafold_mcp.py:90-91`)

### R2: Create a Task Result Dataclass

Each task execution should produce a structured result. Use a `@dataclass` to get type safety and prevent silent typos in field names:

```python
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

@dataclass
class TaskResult:
    task_id: str                        # Auto-generated, format: "{protein}_{task}_{index}"
    protein_id: str                     # The UniProt ID being analyzed
    task_type: str                      # "fetch_protein" | "analyze_structure" | "reason" | "critique" | "synthesize"
    status: str                         # "success" | "failed" | "skipped" | "partial"
    result: Any = None                  # Agent output on success (dict or str depending on agent), None on failure
    error: Optional[str] = None         # Error message on failure, None on success
    duration_seconds: float = 0.0       # How long the task took

    def to_dict(self) -> dict:
        return asdict(self)
```

**Note on `result` type:** Most agents return `dict`, but `generate_research_brief()` (the synthesize step) returns a `str`. The `result` field uses `Any` to accommodate both. Consumers should check `isinstance(result, str)` for brief text vs `isinstance(result, dict)` for structured data.

**Task ID generation:** `task_id = f"{protein}_{task_type}_{index}"` where `index` is the task's position in the task list (0-based).

### R3: Implement Skip Logic for Dependent Tasks

When a task fails, downstream tasks that depend on its output should be **skipped** (not attempted with missing data). The skip behavior depends on which stage failed:

**Full skip — `fetch_protein` failure:**
If `fetch_protein` fails for protein X → skip ALL downstream tasks (`analyze_structure`, `reason`, `critique`, `synthesize`) for protein X. No data exists to work with.

**Partial skip — mid-pipeline failure:**
If `analyze_structure`, `reason`, or `critique` fails for protein X → skip remaining analysis tasks for that protein, but still attempt `synthesize` with whatever partial data was collected. The synthesis agent already handles missing inputs via `self.results.get(...)` returning `{}`. Mark the synthesis result status as `"partial"` instead of `"success"`.

**Cross-protein isolation:**
Other proteins' pipelines are completely unaffected by any failure.

**Dependency chain per protein:**
```
fetch_protein → analyze_structure → reason → critique → synthesize
     ↓ (fail)                                            ↑
  skip ALL downstream                                    |
                                                         |
         analyze_structure → reason → critique           |
              ↓ (fail)                                   |
           skip reason + critique, still attempt ────────┘
           synthesize with partial data (status: "partial")
```

**Important:** The orchestrator builds its task list in `build_task_list()` using well-defined task dicts with `"task"` and `"protein"` keys. The skip logic keys on the `"protein"` field of each task dict. This field is always present and always a valid UniProt ID (set directly from the plan's `uniprot_ids` list). No extraction or inference is needed.

### R4: Aggregate Results with Failure Reporting

The orchestrator's final output should include:

```python
final_output = {
    "completed_analyses": [...],    # Full protein briefs (status: "success")
    "partial_analyses": [...],      # Briefs with incomplete data (status: "partial")
    "failed_analyses": [            # Proteins that had errors
        {
            "protein_id": "INVALID_ID",
            "failed_at_stage": "fetch_protein",      # First (root cause) failure
            "error": "Protein INVALID_ID not found in AlphaFold",
            "tasks_skipped": ["analyze_structure", "reason", "critique", "synthesize"],
            "additional_failures": []                 # Later failures for same protein (if any)
        }
    ],
    "summary": {
        "total_requested": 3,
        "successful": 2,
        "partial": 0,
        "failed": 1
    }
}
```

The `build_failure_report` function must be defined (see Implementation Guidance, Step 3).

### R5: Replace Bare Except Clauses

**Location:** `orchestrator.py`, `plan()` method (the `try/except` around `parse_json_response`)

- Replace all `except:` with `except Exception as e:`
- Ensure `KeyboardInterrupt` and `SystemExit` propagate normally
- Log the exception type and message

### R6: Add Timing to Task Execution

Wrap each task with timing so you can see performance in logs:

```python
import time
start = time.time()
# ... execute task ...
duration = time.time() - start
```

This data feeds into the task result model (R2) and is useful for demo narration.

### R7: Configure Logging

Add structured logging to replace ad-hoc `print()` calls **within the new error-handling code only**. Existing `self.log()` calls are out of scope for this PRD.

At the top of `orchestrator.py`, add only the logger instance — do **not** call `logging.basicConfig()` here. `basicConfig` is a global operation that mutates the root logger and can interfere with test harnesses, library consumers, and any other module that configures logging. Logging configuration belongs in the application entry point (`lyra.py`), not in a library-style module.

```python
import logging

logger = logging.getLogger("lyra.orchestrator")
```

In `agents/lyra.py` (the entry point), add logging configuration if not already present:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
```

Use `logger.error(...)` for caught exceptions, `logger.warning(...)` for skipped tasks, and `logger.info(...)` for task completion with timing. The existing `self.log()` method (which uses `print()`) remains unchanged — migrating all output to `logging` is out of scope. If no `basicConfig` has been called (e.g., in tests), the logger will use Python's default `lastResort` handler (stderr, WARNING+), which is safe.

---

## Implementation Guidance

### Step 1: Define the Task Result Dataclass

Add at the top of `orchestrator.py`, after imports:

```python
from dataclasses import dataclass, asdict
from typing import Any, Optional

@dataclass
class TaskResult:
    task_id: str
    protein_id: str
    task_type: str
    status: str  # "success" | "failed" | "skipped" | "partial"
    result: Any = None                  # dict or str depending on agent
    error: Optional[str] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
```

### Step 2: Refactor the Task Execution Loop

The current `execute_all` method should become:

```python
def execute_all(self):
    """Phase 3: Execute all tasks in order with per-task error isolation."""

    self.log("\n" + "="*60)
    self.log("  LYRA EXECUTION PHASE")
    self.log("="*60)

    self.task_results = []
    failed_proteins = set()       # Proteins where fetch_protein failed (skip all)
    degraded_proteins = set()     # Proteins where a mid-pipeline task failed (skip to synthesis)

    for i, task in enumerate(self.task_list):
        protein = task["protein"]
        task_type = task["task"]
        task_id = f"{protein}_{task_type}_{i}"

        # Skip logic: full skip if fetch failed
        if protein in failed_proteins:
            self.task_results.append(TaskResult(
                task_id=task_id,
                protein_id=protein,
                task_type=task_type,
                status="skipped",
                error=f"Skipped due to fetch_protein failure for {protein}"
            ))
            logger.warning(f"Skipping {task_type} for {protein} (fetch failed)")
            continue

        # Skip logic: partial skip if mid-pipeline failed (but allow synthesize)
        if protein in degraded_proteins and task_type != "synthesize":
            self.task_results.append(TaskResult(
                task_id=task_id,
                protein_id=protein,
                task_type=task_type,
                status="skipped",
                error=f"Skipped due to earlier failure for {protein}"
            ))
            logger.warning(f"Skipping {task_type} for {protein} (degraded)")
            continue

        try:
            start = time.time()
            task["status"] = "running"
            result = self.execute_task(task)
            duration = time.time() - start

            # Soft-failure check: MCP servers return {"error": "..."} on 404s
            # instead of raising. Detect this and treat as a failure.
            if isinstance(result, dict) and "error" in result:
                error_msg = result["error"]
                if task_type == "fetch_protein":
                    failed_proteins.add(protein)
                else:
                    degraded_proteins.add(protein)

                self.task_results.append(TaskResult(
                    task_id=task_id,
                    protein_id=protein,
                    task_type=task_type,
                    status="failed",
                    error=error_msg,
                    duration_seconds=round(duration, 2)
                ))
                logger.error(f"Soft failure in {task_type} for {protein}: {error_msg}")
                continue

            status = "partial" if protein in degraded_proteins else "success"
            task["status"] = "complete"
            task["result"] = result
            self.completed_tasks.append(task)

            self.task_results.append(TaskResult(
                task_id=task_id,
                protein_id=protein,
                task_type=task_type,
                status=status,
                result=result,
                duration_seconds=round(duration, 2)
            ))
            logger.info(f"Completed {task_type} for {protein} in {duration:.2f}s")

            # Magnetic pattern: check if we need to adjust plan
            self._maybe_adjust_plan(task, result)

        except Exception as e:
            duration = time.time() - start

            if task_type == "fetch_protein":
                failed_proteins.add(protein)
            else:
                degraded_proteins.add(protein)

            self.task_results.append(TaskResult(
                task_id=task_id,
                protein_id=protein,
                task_type=task_type,
                status="failed",
                error=f"{type(e).__name__}: {str(e)}",
                duration_seconds=round(duration, 2)
            ))
            logger.error(f"Failed {task_type} for {protein}: {type(e).__name__}: {e}")
```

### Step 3: Define the Failure Report Builder

Add this helper method to `LyraOrchestrator` or as a module-level function:

```python
def build_failure_report(self, task_results: list[TaskResult]) -> list[dict]:
    """Build a failure report from task results.

    Records the FIRST failure per protein as the root cause (failed_at_stage).
    Subsequent failures for the same protein are appended to additional_failures,
    preserving the initial cause rather than overwriting it.
    """
    failures = {}
    for r in task_results:
        if r.status == "failed":
            if r.protein_id not in failures:
                # First failure for this protein — this is the root cause
                failures[r.protein_id] = {
                    "protein_id": r.protein_id,
                    "failed_at_stage": r.task_type,
                    "error": r.error,
                    "tasks_skipped": [],
                    "additional_failures": []
                }
            else:
                # Subsequent failure for same protein (e.g., degraded path)
                failures[r.protein_id]["additional_failures"].append({
                    "stage": r.task_type,
                    "error": r.error
                })
        elif r.status == "skipped" and r.protein_id in failures:
            failures[r.protein_id]["tasks_skipped"].append(r.task_type)
    return list(failures.values())
```

### Step 4: Update Final Output Assembly

Replace the current brief-gathering section in `run()`.

**Important:** The task list does NOT always include a `synthesize` task. When `requires_full_pipeline` is `false`, the pipeline ends at `analyze_structure`. The output assembly must detect the terminal task for each protein dynamically, not assume `synthesize` is always present.

```python
# Phase 4: Assemble results with failure reporting
self.log("\n" + "═"*60)
self.log("  EXECUTION COMPLETE")
self.log("═"*60)

unique_proteins = plan.get("uniprot_ids", [])
failure_report = self.build_failure_report(self.task_results)
failed_protein_ids = {f["protein_id"] for f in failure_report}

completed = []
partial = []
for uid in unique_proteins:
    if uid in failed_protein_ids:
        continue

    # Find the terminal (last successful/partial) task result for this protein.
    # This is "synthesize" for full-pipeline runs, or "analyze_structure"
    # for structure-only runs (requires_full_pipeline=false).
    protein_results = [r for r in self.task_results
                       if r.protein_id == uid and r.status in ("success", "partial")]
    if not protein_results:
        continue

    terminal = protein_results[-1]  # Last successful task is the terminal one
    if terminal.status == "success":
        completed.append(terminal.result)
    elif terminal.status == "partial":
        partial.append(terminal.result)

final_output = {
    "completed_analyses": completed,
    "partial_analyses": partial,
    "failed_analyses": failure_report,
    "summary": {
        "total_requested": len(unique_proteins),
        "successful": len(completed),
        "partial": len(partial),
        "failed": len(failure_report)
    }
}

# Return human-readable briefs (backwards-compatible) plus structured data
self.final_output = final_output  # Store structured output for programmatic access

# Build display output: briefs are strings, structure results are dicts
briefs = []
for result in completed + partial:
    if isinstance(result, str):
        briefs.append(result)
    elif isinstance(result, dict):
        # Structure-only runs return dicts; format a minimal summary
        uid = result.get("uniprot_id", "unknown")
        conf = result.get("overall_confidence", "N/A")
        briefs.append(f"Structure analysis for {uid}: overall confidence {conf}")

if not briefs and failure_report:
    briefs = [f"❌ Analysis failed for {f['protein_id']} at {f['failed_at_stage']}: {f['error']}"
              for f in failure_report]
return "\n\n".join(briefs) if briefs else "No analyses completed."
```

### Step 5: Fix Bare Except in `plan()` Method

```python
# BEFORE (bad)
except:
    plan = {"uniprot_ids": [], "error": "Failed to parse plan"}

# AFTER (good)
except Exception as e:
    logger.error(f"Task planning failed: {type(e).__name__}: {e}")
    plan = {"uniprot_ids": [], "error": f"Failed to parse plan: {type(e).__name__}: {e}"}
```

---

## Handling Cross-Protein Tasks

The current orchestrator does not generate cross-protein tasks (e.g., `compare_proteins`). All tasks are scoped to a single protein via the `"protein"` key. If cross-protein tasks are added in the future, the following rule applies:

- A cross-protein task should be skipped if **any** of its referenced proteins are in `failed_proteins`.
- This is **out of scope** for this PRD but noted here to inform future design.

---

## Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| AC1 | A single invalid protein ID does not crash the pipeline | Run with `["P04637", "XXXXX", "Q8I3H7"]` — should get 2 results + 1 failure report |
| AC2 | Successful proteins produce identical output to current behavior | Compare output for `P04637` before and after — should match |
| AC3 | Failed tasks include error type, message, and which stage failed | Check `failed_analyses` in output — each entry has `failed_at_stage`, `error`, `tasks_skipped` |
| AC4 | Downstream tasks for failed proteins are skipped, not attempted | Add a `logger.debug` at the top of `execute_task` and verify it is NOT called for skipped tasks. Alternatively, confirm skipped `TaskResult` entries exist with no `duration_seconds > 0` |
| AC5 | No bare `except:` clauses remain in `orchestrator.py` | `grep -n "except:" orchestrator.py` returns no matches. (Bare `except:` has a colon immediately after; `except Exception as e:` is matched by `grep -n "except "` instead, which is the correct form.) Verify with: `grep -nP "except\s*:" orchestrator.py` should return zero lines. |
| AC6 | `KeyboardInterrupt` still terminates the program immediately | Ctrl+C during execution — should exit, not be swallowed |
| AC7 | Task timing is recorded for each task | Check `duration_seconds` field in task results — non-zero for executed tasks, 0.0 for skipped |
| AC8 | Final summary reports correct counts | `total_requested`, `successful`, `partial`, `failed` numbers are accurate |
| AC9 | `TaskResult` is a dataclass, not a plain dict | `isinstance(result, TaskResult)` returns `True` |
| AC10 | Mid-pipeline failures produce partial synthesis | Simulate `analyze_structure` failure — synthesis should still run with partial data and status `"partial"` |
| AC11 | Soft failures (error dicts) are detected, not stored as successes | Run with an invalid protein ID that returns 404 (e.g., `"XXXXX"`) — the `fetch_protein` result `{"error": "..."}` must produce a `TaskResult` with `status="failed"`, not `status="success"` |
| AC12 | Structure-only runs (`requires_full_pipeline=false`) report completed analyses | Run a structure-only plan for a valid protein — `summary.successful` must be 1, not 0 |

---

## Test Cases

### Test 1: Single Valid Protein
```
Input: ["Q8I3H7"]
Expected: 1 completed analysis, 0 partial, 0 failures
```

### Test 2: Mixed Valid and Invalid
```
Input: ["P04637", "TOTALLY_FAKE_ID", "Q8I3H7"]
Expected: 2 completed, 0 partial, 1 failed (TOTALLY_FAKE_ID fails at fetch_protein stage)
         failed_analyses includes tasks_skipped: ["analyze_structure", "reason", "critique", "synthesize"]
```

### Test 3: All Invalid
```
Input: ["FAKE1", "FAKE2"]
Expected: 0 completed, 0 partial, 2 failed, pipeline still returns cleanly (no crash)
         Return value is a human-readable error message, not empty string
```

### Test 4: API Timeout Simulation
```
Setup: Use unittest.mock.patch on requests.get to raise requests.exceptions.Timeout
       for AlphaFold calls to one specific protein ID
Simulate: AlphaFold API takes 60+ seconds for one protein
Expected: That protein fails with timeout error, others complete normally
Note: Requires mocking — add to test suite as:
    @patch("mcp_servers.alphafold_mcp.requests.get", side_effect=requests.exceptions.Timeout)
```

### Test 5: Keyboard Interrupt
```
Action: Ctrl+C during multi-protein run
Expected: Program exits immediately, not caught by error handling
Note: Manual verification — cannot be automated in standard pytest
```

### Test 6: Mid-Pipeline Failure (Partial Synthesis)
```
Setup: Use unittest.mock.patch to make analyze_confidence_regions raise an exception
       for one protein while others succeed
Input: ["P04637", "Q8I3H7"] where Q8I3H7 structure analysis is mocked to fail
Expected: P04637 fully completes (status: "success")
         Q8I3H7 has reason + critique skipped, synthesis runs with partial data (status: "partial")
         summary: {successful: 1, partial: 1, failed: 0}
```

### Test 7: Soft Failure Detection (404 Error Dict)
```
Input: ["XXXXX"] (invalid protein ID that AlphaFold returns 404 for)
Expected: fetch_protein returns {"error": "Protein XXXXX not found in AlphaFold"}
         This is detected as a failure, NOT stored as a success
         TaskResult has status="failed", error contains the message
         Downstream tasks are skipped
         This is the most common real-world failure path — the test MUST use the
         actual AlphaFold MCP (or a mock returning {"error": "..."}) rather than
         raising an exception
```

### Test 8: Structure-Only Pipeline (requires_full_pipeline=false)
```
Setup: Mock the planner to return {"uniprot_ids": ["Q8I3H7"], "requires_full_pipeline": false}
Input: Valid protein with structure-only plan
Expected: Only fetch_protein and analyze_structure tasks are created
         No synthesize task exists
         summary: {successful: 1, partial: 0, failed: 0}
         Return value is a formatted structure summary, not "No analyses completed."
```

---

## Out of Scope

- Retry logic for failed tasks (that's PRD-002)
- Async/parallel task execution
- Caching of API responses
- Changes to agent logic (query, structure, reasoning, critic, synthesis agents are unchanged)
- Migrating existing `self.log()` / `print()` calls to `logging` module
- Input validation on UniProt IDs (separate concern)
- Cross-protein comparison tasks

---

## Notes for Implementation Agent

- **Critical:** The MCP servers (`alphafold_mcp.py`, `uniprot_mcp.py`) return `{"error": "..."}` dicts on 404 and similar failures — they do NOT raise exceptions. The soft-failure check (`isinstance(result, dict) and "error" in result`) after `execute_task()` is essential; without it, the skip logic will never trigger for the most common failure case (invalid protein IDs)
- The task dict structure uses `"task"` for the task type and `"protein"` for the UniProt ID — these are set in `build_task_list()` and are always present
- The actual line numbers may differ from what's referenced here — use the described method names to locate the correct code
- Preserve all existing functionality for the success path — this is purely additive error handling
- Do not change the agent interfaces — the orchestrator is the only file that should change significantly
- Run existing tests (`test_agent.py`, `test_proteins.py`) after changes to confirm no regressions
- Add `import time` and `import logging` at the top of the file if not already present
- The `self.final_output` attribute is new — it provides programmatic access to the structured results for testing and downstream consumers
