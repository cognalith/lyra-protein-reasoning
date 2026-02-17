"""
Synthesis Agent
Compiles all agent outputs into a structured research brief.
"""

import os
import sys
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AzureOpenAI

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview",
    timeout=60.0,
    max_retries=3,
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")


SYNTHESIS_PROMPT = """You are the Synthesis Agent for Lyra, a protein research system.

Your job: Compile all agent findings into a clear, actionable research brief.

Given inputs from multiple agents, create a synthesis that:
1. Summarizes key findings in plain language
2. Highlights areas of agreement and disagreement between agents
3. Provides a final confidence-weighted recommendation
4. Lists concrete next steps for researchers

Write in clear scientific prose. This is the final output a researcher will read.

Respond with ONLY valid JSON:
{
    "executive_summary": "2-3 sentence summary for busy researchers",
    "protein_overview": {
        "name": "...",
        "organism": "...",
        "function": "...",
        "length": 0
    },
    "drug_target_assessment": {
        "verdict": "PROMISING | CAUTIOUS | NOT_RECOMMENDED",
        "confidence": 0.0,
        "one_liner": "One sentence assessment"
    },
    "key_findings": [
        {"finding": "...", "confidence": "high|medium|low", "source": "which agent"}
    ],
    "agent_consensus": {
        "areas_of_agreement": ["..."],
        "areas_of_disagreement": ["..."],
        "unresolved_questions": ["..."]
    },
    "structural_highlights": {
        "overall_quality": "...",
        "best_target_regions": [{"start": 0, "end": 0, "suitability": "..."}],
        "concerns": ["..."]
    },
    "recommended_next_steps": [
        {"step": "...", "priority": "high|medium|low", "rationale": "..."}
    ],
    "limitations": ["..."]
}
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


def synthesize_findings(
    uniprot_id: str,
    protein_summary: dict,
    structure_analysis: dict,
    reasoning_result: dict,
    critique_result: dict
) -> dict:
    """
    Synthesize all agent outputs into a final research brief.
    """
    
    # Build context from all agents
    context = f"""
PROTEIN SUMMARY (from Query Agent):
{json.dumps(protein_summary, indent=2)}

STRUCTURE ANALYSIS (from Structure Agent):
{json.dumps(structure_analysis, indent=2)}

REASONING (from Reasoning Agent):
{json.dumps(reasoning_result.get('reasoning', {}), indent=2)}

SELF-REFLECTION (from Reasoning Agent):
{json.dumps(reasoning_result.get('self_reflection', {}), indent=2)}

CRITIQUE (from Critic Agent):
{json.dumps(critique_result.get('critique', {}), indent=2)}

UNIPROT ANNOTATIONS (external validation):
{json.dumps(critique_result.get('uniprot_annotations', {}), indent=2)}

Synthesize all of the above into a final research brief for protein {uniprot_id}.
"""
    
    print("  → Calling LLM for synthesis...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYNTHESIS_PROMPT},
            {"role": "user", "content": context}
        ],
        temperature=0.3
    )
    
    raw = response.choices[0].message.content
    print(f"  → Got response ({len(raw)} chars)")
    
    try:
        synthesis = parse_json_response(raw)
    except json.JSONDecodeError:
        print("  ⚠ JSON parse failed")
        synthesis = {"raw_synthesis": raw}
    
    return {
        "uniprot_id": uniprot_id,
        "generated_at": datetime.now().isoformat(),
        "synthesis": synthesis,
        "reasoning_chain_visible": True
    }


def generate_research_brief(
    uniprot_id: str,
    protein_summary: dict,
    structure_analysis: dict,
    reasoning_result: dict,
    critique_result: dict
) -> str:
    """Generate human-readable research brief."""
    
    result = synthesize_findings(
        uniprot_id,
        protein_summary,
        structure_analysis,
        reasoning_result,
        critique_result
    )
    
    syn = result.get("synthesis", {})
    
    if "raw_synthesis" in syn:
        return f"# Research Brief: {uniprot_id}\n\n{syn['raw_synthesis']}"
    
    # Build formatted report
    report = [
        "═" * 60,
        f"  LYRA RESEARCH BRIEF: {uniprot_id}",
        f"  Generated: {result['generated_at']}",
        "═" * 60,
        "",
        "## Executive Summary",
        syn.get("executive_summary", "N/A"),
        "",
    ]
    
    # Protein overview
    overview = syn.get("protein_overview", {})
    report.extend([
        "## Protein Overview",
        f"- **Name:** {overview.get('name', 'N/A')}",
        f"- **Organism:** {overview.get('organism', 'N/A')}",
        f"- **Function:** {overview.get('function', 'N/A')}",
        f"- **Length:** {overview.get('length', 'N/A')} residues",
        "",
    ])
    
    # Drug target assessment
    assessment = syn.get("drug_target_assessment", {})
    verdict = assessment.get("verdict", "N/A")
    verdict_emoji = {"PROMISING": "🟢", "CAUTIOUS": "🟡", "NOT_RECOMMENDED": "🔴"}.get(verdict, "⚪")
    report.extend([
        "## Drug Target Assessment",
        f"{verdict_emoji} **{verdict}** (Confidence: {assessment.get('confidence', 'N/A')})",
        f"_{assessment.get('one_liner', '')}_",
        "",
    ])
    
    # Key findings
    findings = syn.get("key_findings", [])
    if findings:
        report.append("## Key Findings")
        for f in findings:
            conf_emoji = {"high": "●", "medium": "◐", "low": "○"}.get(f.get("confidence", ""), "?")
            report.append(f"- {conf_emoji} {f.get('finding', '')} _(Source: {f.get('source', 'N/A')})_")
        report.append("")
    
    # Agent consensus
    consensus = syn.get("agent_consensus", {})
    if consensus:
        report.append("## Agent Consensus")
        if consensus.get("areas_of_agreement"):
            report.append("**Agreement:**")
            for a in consensus["areas_of_agreement"]:
                report.append(f"  ✓ {a}")
        if consensus.get("areas_of_disagreement"):
            report.append("**Disagreement:**")
            for d in consensus["areas_of_disagreement"]:
                report.append(f"  ✗ {d}")
        if consensus.get("unresolved_questions"):
            report.append("**Unresolved:**")
            for q in consensus["unresolved_questions"]:
                report.append(f"  ? {q}")
        report.append("")
    
    # Structural highlights
    struct = syn.get("structural_highlights", {})
    if struct:
        report.append("## Structural Analysis")
        report.append(f"**Quality:** {struct.get('overall_quality', 'N/A')}")
        if struct.get("best_target_regions"):
            report.append("**Best Target Regions:**")
            for r in struct["best_target_regions"][:3]:
                report.append(f"  - Residues {r.get('start', '?')}-{r.get('end', '?')}: {r.get('suitability', 'N/A')}")
        if struct.get("concerns"):
            report.append("**Concerns:**")
            for c in struct["concerns"]:
                report.append(f"  ⚠ {c}")
        report.append("")
    
    # Next steps
    steps = syn.get("recommended_next_steps", [])
    if steps:
        report.append("## Recommended Next Steps")
        for i, s in enumerate(steps, 1):
            priority = s.get("priority", "medium").upper()
            report.append(f"{i}. [{priority}] {s.get('step', '')}")
            report.append(f"   _{s.get('rationale', '')}_")
        report.append("")
    
    # Limitations
    limitations = syn.get("limitations", [])
    if limitations:
        report.append("## Limitations")
        for l in limitations:
            report.append(f"- {l}")
        report.append("")
    
    report.extend([
        "═" * 60,
        "  End of Lyra Research Brief",
        "  Reasoning chain fully visible for verification",
        "═" * 60,
    ])
    
    return "\n".join(report)


# Test
if __name__ == "__main__":
    print("=" * 60)
    print("SYNTHESIS AGENT TEST")
    print("=" * 60)
    print()
    
    # Import other agents
    from mcp_servers.alphafold_mcp import summarize_protein
    from structure_agent import analyze_confidence_regions
    from reasoning_agent import reason_about_target
    from critic_agent import critique_reasoning
    
    protein_id = "Q8I3H7"
    
    print("Step 1: Getting protein summary...")
    protein_summary = summarize_protein(protein_id)
    
    print("Step 2: Analyzing structure...")
    structure_analysis = analyze_confidence_regions(protein_id)
    
    print("Step 3: Running reasoning...")
    reasoning_result = reason_about_target(protein_id)
    
    print("Step 4: Running critique...")
    critique_result = critique_reasoning(protein_id, reasoning_result)
    
    print("\nStep 5: Synthesizing final brief...")
    brief = generate_research_brief(
        protein_id,
        protein_summary,
        structure_analysis,
        reasoning_result,
        critique_result
    )
    
    print("\n" + brief)
