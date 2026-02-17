"""
Reasoning Agent
Performs multi-step scientific reasoning about protein drug targets.
Includes self-reflection to identify gaps in reasoning.
"""

import os
import sys
import json
import logging

# Fix import paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_servers.alphafold_mcp import summarize_protein
from structure_agent import analyze_confidence_regions

from openai import AzureOpenAI

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview",
    timeout=60.0,
    max_retries=3,
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

logger = logging.getLogger(__name__)


REASONING_PROMPT = """You are the Reasoning Agent for Lyra, a protein research system.

Your job: Perform multi-step scientific reasoning about whether a protein is a viable drug target.

Given protein data, reason through these steps:
1. Function Analysis: What does this protein do? Why might it matter for disease?
2. Structure Quality: Is the predicted structure reliable enough for drug design?
3. Target Regions: Which regions could bind a drug molecule?
4. Druggability Assessment: Could a small molecule or biologic realistically target this protein?
5. Risk Factors: What could go wrong? Off-target effects? Resistance?

Provide your reasoning chain explicitly. Show your thinking at each step.

You MUST respond with ONLY valid JSON, no markdown, no code blocks. Use this exact format:
{"reasoning_steps": [{"step": "Function Analysis", "reasoning": "your reasoning here", "conclusion": "your conclusion"}], "overall_assessment": "HIGH", "confidence_in_assessment": 0.8, "key_strengths": ["strength 1"], "key_risks": ["risk 1"], "recommended_next_steps": ["step 1"]}
"""


def get_reflection_prompt(reasoning_text: str) -> str:
    return f"""Review this drug target reasoning and identify gaps.

Previous reasoning:
{reasoning_text}

You MUST respond with ONLY valid JSON, no markdown, no code blocks:
{{"assumptions_identified": ["assumption 1"], "missing_evidence": ["evidence 1"], "alternative_interpretations": ["interpretation 1"], "revised_confidence": 0.7, "reasoning_gaps": ["gap 1"]}}
"""


def parse_json_response(content: str) -> dict:
    """Try to parse JSON, handling markdown code blocks."""
    # Remove markdown code blocks if present
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    return json.loads(content)


def reason_about_target(uniprot_id: str) -> dict:
    """Perform multi-step reasoning about a protein drug target."""
    
    # Gather evidence
    protein_summary = summarize_protein(uniprot_id)
    structure_analysis = analyze_confidence_regions(uniprot_id)
    
    if "error" in protein_summary:
        return {"error": protein_summary["error"]}
    
    context = f"""
PROTEIN DATA:
- UniProt ID: {uniprot_id}
- Description: {protein_summary.get('description', 'Unknown')}
- Organism: {protein_summary.get('organism', 'Unknown')}
- Gene: {protein_summary.get('gene', 'Unknown')}
- Length: {protein_summary.get('length', 'Unknown')} residues

STRUCTURE ANALYSIS:
- Overall confidence: {structure_analysis.get('overall_confidence', 'N/A')}/100
- Interpretation: {structure_analysis.get('interpretation', 'N/A')}

POTENTIAL TARGET REGIONS:
{_format_target_regions(structure_analysis.get('drug_target_regions', []))}

INITIAL ASSESSMENT: {protein_summary.get('drug_target_assessment', 'Unknown')}
"""
    
    # Step 1: Initial reasoning
    logger.info("Calling LLM for reasoning...")
    reasoning_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": REASONING_PROMPT},
            {"role": "user", "content": f"Analyze this protein as a potential drug target:\n{context}"}
        ],
        temperature=0.3
    )
    
    raw_reasoning = reasoning_response.choices[0].message.content
    logger.info("Got response (%d chars)", len(raw_reasoning))

    try:
        reasoning = parse_json_response(raw_reasoning)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s", e)
        logger.debug("Raw response preview: %s...", raw_reasoning[:200])
        reasoning = {"raw_reasoning": raw_reasoning}
    
    # Step 2: Self-reflection
    logger.info("Calling LLM for self-reflection...")
    reflection_prompt = get_reflection_prompt(json.dumps(reasoning, indent=2))
    reflection_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": reflection_prompt},
            {"role": "user", "content": "Reflect on the above reasoning."}
        ],
        temperature=0.3
    )
    
    raw_reflection = reflection_response.choices[0].message.content
    logger.info("Got response (%d chars)", len(raw_reflection))

    try:
        reflection = parse_json_response(raw_reflection)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s", e)
        reflection = {"raw_reflection": raw_reflection}
    
    return {
        "uniprot_id": uniprot_id,
        "protein_summary": protein_summary,
        "structure_analysis": {
            "overall_confidence": structure_analysis.get("overall_confidence"),
            "drug_target_regions": structure_analysis.get("drug_target_regions", [])
        },
        "reasoning": reasoning,
        "self_reflection": reflection,
        "reasoning_chain_visible": True
    }


def _format_target_regions(regions: list) -> str:
    if not regions:
        return "No high-confidence target regions identified."
    lines = []
    for r in regions[:5]:
        lines.append(f"- Residues {r['start']}-{r['end']} ({r['length']} aa): {r['suitability']} suitability")
    return "\n".join(lines)


def generate_reasoning_report(uniprot_id: str) -> str:
    """Generate human-readable reasoning report."""
    
    result = reason_about_target(uniprot_id)
    
    if "error" in result:
        return f"Error: {result['error']}"
    
    reasoning = result.get("reasoning", {})
    reflection = result.get("self_reflection", {})
    
    # Handle raw reasoning if JSON parse failed
    if "raw_reasoning" in reasoning:
        return f"# Drug Target Reasoning: {uniprot_id}\n\n{reasoning['raw_reasoning']}"
    
    report = [
        f"# Drug Target Reasoning: {uniprot_id}",
        f"**{result['protein_summary'].get('description', 'Unknown protein')}**",
        f"Organism: {result['protein_summary'].get('organism', 'Unknown')}",
        "",
        "## Reasoning Chain",
    ]
    
    for step in reasoning.get("reasoning_steps", []):
        report.append(f"### {step.get('step', 'Step')}")
        report.append(step.get('reasoning', ''))
        report.append(f"**Conclusion:** {step.get('conclusion', 'N/A')}")
        report.append("")
    
    report.extend([
        f"## Overall Assessment: {reasoning.get('overall_assessment', 'N/A')}",
        f"Confidence: {reasoning.get('confidence_in_assessment', 'N/A')}",
        "",
        "### Strengths",
    ])
    for s in reasoning.get("key_strengths", []):
        report.append(f"- {s}")
    
    report.append("\n### Risks")
    for r in reasoning.get("key_risks", []):
        report.append(f"- {r}")
    
    report.append("\n## Self-Reflection")
    
    if "raw_reflection" in reflection:
        report.append(reflection["raw_reflection"])
    else:
        report.append("### Assumptions Made")
        for a in reflection.get("assumptions_identified", []):
            report.append(f"- {a}")
        
        report.append("\n### Missing Evidence")
        for m in reflection.get("missing_evidence", []):
            report.append(f"- {m}")
        
        report.append(f"\n**Revised confidence after reflection:** {reflection.get('revised_confidence', 'N/A')}")
    
    return "\n".join(report)


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    report = generate_reasoning_report("Q8I3H7")
    logger.info(report)
