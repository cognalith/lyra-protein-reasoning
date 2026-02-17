"""
Lyra Orchestrator
Coordinates all agents using Magnetic Orchestration pattern.
Takes a research question, manages the agent pipeline, returns final brief.
"""

import os
import sys
import json
from datetime import datetime
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AzureOpenAI

# Import all agents
from mcp_servers.alphafold_mcp import summarize_protein, get_protein_prediction
from structure_agent import analyze_confidence_regions
from reasoning_agent import reason_about_target
from critic_agent import critique_reasoning
from synthesis_agent import generate_research_brief, synthesize_findings

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview"
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")


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
        except:
            plan = {"uniprot_ids": [], "error": "Failed to parse plan"}
        
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
    
    def execute_task(self, task: dict) -> dict:
        """Execute a single task and return results."""
        
        task_type = task["task"]
        protein = task["protein"]
        
        if task_type == "fetch_protein":
            self.log(f"\n📡 QUERY AGENT: Fetching {protein}...")
            result = summarize_protein(protein)
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
        """Phase 3: Execute all tasks in order."""
        
        self.log("\n" + "="*60)
        self.log("  LYRA EXECUTION PHASE")
        self.log("="*60)
        
        for i, task in enumerate(self.task_list):
            task["status"] = "running"
            result = self.execute_task(task)
            task["status"] = "complete"
            task["result"] = result
            self.completed_tasks.append(task)
            
            # Magnetic pattern: check if we need to adjust plan
            self._maybe_adjust_plan(task, result)
    
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
        
        # Phase 4: Return final brief(s)
        self.log("\n" + "═"*60)
        self.log("  EXECUTION COMPLETE")
        self.log("═"*60)
        
        # Gather all briefs
        briefs = []
        for uid in plan.get("uniprot_ids", []):
            brief = self.results.get(f"{uid}_brief", "No brief generated")
            briefs.append(brief)
        
        return "\n\n".join(briefs)


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
