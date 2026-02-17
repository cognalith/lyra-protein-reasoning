"""
Lyra Orchestrator
Coordinates all agents using Magnetic Orchestration pattern.
Takes a research question, manages the agent pipeline, returns final brief.
"""

import os
import sys
import json
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AzureOpenAI

# Import all agents
from mcp_servers.alphafold_mcp import get_protein_prediction
from query_agent import process_protein
from structure_agent import analyze_confidence_regions
from reasoning_agent import reason_about_target
from critic_agent import critique_reasoning
from synthesis_agent import generate_research_brief, synthesize_findings

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview",
    timeout=60.0,
    max_retries=3,
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

logger = logging.getLogger("lyra.orchestrator")


@dataclass
class TaskResult:
    task_id: str
    protein_id: str
    task_type: str
    status: str  # "success" | "failed" | "skipped" | "partial"
    result: Any = None
    error: Optional[str] = None
    error_source: Optional[str] = None  # "error_dict" | "exception" | None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


PLANNER_PROMPT = """You are the Lyra Orchestrator, coordinating a team of protein research agents.

Given a research question, extract:
1. The UniProt ID(s) to analyze
2. The type of analysis needed
3. Any specific focus areas

Respond with ONLY valid JSON:
{
    "uniprot_ids": ["Q8I3H7"],
    "analysis_type": "drug_target" | "structure_only" | "comparison",
    "focus_areas": ["druggability", "confidence", "function"],
    "requires_full_pipeline": true,
    "reasoning": "Brief explanation of plan"
}

If no specific protein is mentioned, try to infer from context (organism, disease, etc.)
If you cannot determine a protein ID, set uniprot_ids to empty list.
"""


def parse_json_response(content: str) -> dict:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return json.loads(content.strip())


class LyraOrchestrator:
    """
    Magnetic Orchestration pattern implementation.
    Dynamically manages task list and coordinates specialist agents.
    """
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.task_list = []
        self.completed_tasks = []
        self.results = {}
        
    def log(self, message: str):
        if self.verbose:
            print(message)
    
    def plan(self, question: str) -> dict:
        """Phase 1: Plan the analysis based on the question."""
        
        self.log("\n🎯 ORCHESTRATOR: Planning analysis...")
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": question}
            ],
            temperature=0
        )
        
        try:
            plan = parse_json_response(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Task planning failed: {type(e).__name__}: {e}")
            plan = {"uniprot_ids": [], "error": f"Failed to parse plan: {type(e).__name__}: {e}"}
        
        self.log(f"   Plan: {plan.get('reasoning', 'N/A')}")
        self.log(f"   Proteins: {plan.get('uniprot_ids', [])}")
        
        return plan
    
    def build_task_list(self, plan: dict):
        """Phase 2: Build dynamic task list based on plan."""
        
        self.task_list = []
        
        for uid in plan.get("uniprot_ids", []):
            # Core tasks for each protein
            self.task_list.append({"task": "fetch_protein", "protein": uid, "status": "pending"})
            self.task_list.append({"task": "analyze_structure", "protein": uid, "status": "pending"})
            
            if plan.get("requires_full_pipeline", True):
                self.task_list.append({"task": "reason", "protein": uid, "status": "pending"})
                self.task_list.append({"task": "critique", "protein": uid, "status": "pending"})
                self.task_list.append({"task": "synthesize", "protein": uid, "status": "pending"})
        
        self.log(f"\n📋 ORCHESTRATOR: Built task list ({len(self.task_list)} tasks)")
    
    def build_failure_report(self, task_results: list) -> list:
        """Build a failure report from task results.

        Records the FIRST failure per protein as the root cause (failed_at_stage).
        Subsequent failures for the same protein are appended to additional_failures,
        preserving the initial cause rather than overwriting it.
        """
        failures = {}
        for r in task_results:
            if r.status == "failed":
                if r.protein_id not in failures:
                    failures[r.protein_id] = {
                        "protein_id": r.protein_id,
                        "failed_at_stage": r.task_type,
                        "error": r.error,
                        "tasks_skipped": [],
                        "additional_failures": []
                    }
                else:
                    failures[r.protein_id]["additional_failures"].append({
                        "stage": r.task_type,
                        "error": r.error
                    })
            elif r.status == "skipped" and r.protein_id in failures:
                failures[r.protein_id]["tasks_skipped"].append(r.task_type)
        return list(failures.values())

    def execute_task(self, task: dict) -> dict:
        """Execute a single task and return results."""
        
        task_type = task["task"]
        protein = task["protein"]
        
        if task_type == "fetch_protein":
            self.log(f"\n📡 QUERY AGENT: Fetching {protein}...")
            result = process_protein(protein)
            self.results[f"{protein}_summary"] = result
            return result
            
        elif task_type == "analyze_structure":
            self.log(f"\n🔬 STRUCTURE AGENT: Analyzing {protein}...")
            result = analyze_confidence_regions(protein)
            self.results[f"{protein}_structure"] = result
            return result
            
        elif task_type == "reason":
            self.log(f"\n🧠 REASONING AGENT: Reasoning about {protein}...")
            result = reason_about_target(protein)
            self.results[f"{protein}_reasoning"] = result
            return result
            
        elif task_type == "critique":
            self.log(f"\n⚖️ CRITIC AGENT: Critiquing {protein} analysis...")
            reasoning = self.results.get(f"{protein}_reasoning", {})
            result = critique_reasoning(protein, reasoning)
            self.results[f"{protein}_critique"] = result
            return result
            
        elif task_type == "synthesize":
            self.log(f"\n📝 SYNTHESIS AGENT: Generating brief for {protein}...")
            brief = generate_research_brief(
                protein,
                self.results.get(f"{protein}_summary", {}),
                self.results.get(f"{protein}_structure", {}),
                self.results.get(f"{protein}_reasoning", {}),
                self.results.get(f"{protein}_critique", {})
            )
            self.results[f"{protein}_brief"] = brief
            return brief
        
        return {"error": f"Unknown task type: {task_type}"}
    
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
                        error_source="error_dict",
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
                    error_source="exception",
                    duration_seconds=round(duration, 2)
                ))
                logger.error(f"Failed {task_type} for {protein}: {type(e).__name__}: {e}")
    
    def _maybe_adjust_plan(self, task: dict, result: dict):
        """
        Magnetic Orchestration: Dynamically adjust task list based on results.
        """
        
        # Example: If structure confidence is too low, skip reasoning
        if task["task"] == "analyze_structure":
            confidence = result.get("overall_confidence", 100)
            if confidence < 50:
                self.log(f"\n⚠️ ORCHESTRATOR: Low confidence ({confidence}), adding validation task")
                # Could add additional tasks here
    
    def run(self, question: str) -> str:
        """
        Main entry point: Question in, research brief out.
        """
        
        self.log("\n" + "═"*60)
        self.log("  LYRA PROTEIN REASONING SYSTEM")
        self.log("═"*60)
        self.log(f"\n❓ Question: {question}")
        
        # Phase 1: Plan
        plan = self.plan(question)
        
        if not plan.get("uniprot_ids"):
            return "❌ Could not identify any proteins to analyze. Please include a UniProt ID (e.g., Q8I3H7) in your question."
        
        # Phase 2: Build task list
        self.build_task_list(plan)
        
        # Phase 3: Execute
        self.execute_all()

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

            terminal = protein_results[-1]
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

        # Store structured output for programmatic access
        self.final_output = final_output

        # Build display output: briefs are strings, structure results are dicts
        briefs = []
        for result in completed + partial:
            if isinstance(result, str):
                briefs.append(result)
            elif isinstance(result, dict):
                uid = result.get("uniprot_id", "unknown")
                conf = result.get("overall_confidence", "N/A")
                briefs.append(f"Structure analysis for {uid}: overall confidence {conf}")

        if not briefs and failure_report:
            briefs = [f"❌ Analysis failed for {f['protein_id']} at {f['failed_at_stage']}: {f['error']}"
                      for f in failure_report]
        return "\n\n".join(briefs) if briefs else "No analyses completed."


def analyze(question: str, verbose: bool = True) -> str:
    """
    Convenience function: Run Lyra on a research question.
    
    Example:
        result = analyze("Is Q8I3H7 a viable drug target for malaria?")
        print(result)
    """
    orchestrator = LyraOrchestrator(verbose=verbose)
    return orchestrator.run(question)


# Test
if __name__ == "__main__":
    print("═" * 60)
    print("  LYRA ORCHESTRATOR TEST")
    print("═" * 60)
    
    # Test question
    question = "Is protein Q8I3H7 a viable drug target for malaria treatment?"
    
    result = analyze(question)
    print(result)
