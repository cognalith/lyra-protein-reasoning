"""
Critic Agent
Challenges reasoning, cross-references data, identifies contradictions.
"""

import os
import sys
import json
import logging
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AzureOpenAI
from config.http_client import resilient_get

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    timeout=60.0,
    max_retries=3,
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

logger = logging.getLogger(__name__)


def get_uniprot_annotations(uniprot_id: str) -> dict:
    """Fetch protein annotations from UniProt for cross-referencing."""
    
    url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
    
    try:
        response = resilient_get(url, timeout_key="uniprot_annotation")
        data = response.json()
        
        # Extract relevant fields
        return {
            "uniprot_id": uniprot_id,
            "protein_name": data.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", "Unknown"),
            "organism": data.get("organism", {}).get("scientificName", "Unknown"),
            "function": _extract_function(data),
            "subcellular_location": _extract_location(data),
            "go_terms": _extract_go_terms(data),
            "features": _extract_features(data),
            "disease_associations": _extract_disease(data),
        }
    except Exception as e:
        return {"error": str(e)}


def _extract_function(data: dict) -> str:
    comments = data.get("comments", [])
    for c in comments:
        if c.get("commentType") == "FUNCTION":
            texts = c.get("texts", [])
            if texts:
                return texts[0].get("value", "")
    return "No function annotation available"


def _extract_location(data: dict) -> list:
    comments = data.get("comments", [])
    locations = []
    for c in comments:
        if c.get("commentType") == "SUBCELLULAR LOCATION":
            for loc in c.get("subcellularLocations", []):
                loc_val = loc.get("location", {}).get("value")
                if loc_val:
                    locations.append(loc_val)
    return locations if locations else ["Unknown"]


def _extract_go_terms(data: dict) -> list:
    go_terms = []
    for ref in data.get("uniProtKBCrossReferences", []):
        if ref.get("database") == "GO":
            term_id = ref.get("id", "")
            props = ref.get("properties", [])
            term_name = next((p.get("value") for p in props if p.get("key") == "GoTerm"), "")
            if term_name:
                go_terms.append(f"{term_id}: {term_name}")
    return go_terms[:10]  # Limit to 10


def _extract_features(data: dict) -> list:
    features = []
    for f in data.get("features", [])[:10]:  # Limit
        feat_type = f.get("type", "")
        desc = f.get("description", "")
        start = f.get("location", {}).get("start", {}).get("value", "?")
        end = f.get("location", {}).get("end", {}).get("value", "?")
        if feat_type in ["Domain", "Binding site", "Active site", "Region"]:
            features.append(f"{feat_type} ({start}-{end}): {desc}")
    return features


def _extract_disease(data: dict) -> list:
    diseases = []
    for c in data.get("comments", []):
        if c.get("commentType") == "DISEASE":
            disease = c.get("disease", {})
            name = disease.get("diseaseId", "")
            if name:
                diseases.append(name)
    return diseases


CRITIC_PROMPT = """You are the Critic Agent for Lyra, a protein research system.

Your job: Challenge the Reasoning Agent's conclusions by:
1. Identifying unsupported claims
2. Finding contradictions between reasoning and evidence
3. Highlighting overconfident conclusions
4. Checking if UniProt annotations support or contradict the assessment

Be rigorous but fair. Your goal is to strengthen the analysis, not tear it down.

Respond with ONLY valid JSON:
{
    "challenges": [
        {"claim": "the claim being challenged", "issue": "why it's problematic", "severity": "high|medium|low"}
    ],
    "contradictions": [
        {"reasoning_says": "...", "evidence_says": "...", "resolution": "..."}
    ],
    "unsupported_claims": ["claim 1", "claim 2"],
    "confidence_assessment": {
        "original_confidence": 0.0,
        "recommended_confidence": 0.0,
        "justification": "..."
    },
    "verdict": "SUPPORTED | PARTIALLY_SUPPORTED | WEAK | UNSUPPORTED",
    "key_concerns": ["concern 1", "concern 2"]
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


def critique_reasoning(uniprot_id: str, reasoning_result: dict) -> dict:
    """
    Critique the reasoning agent's output using external evidence.
    """
    
    # Get external evidence from UniProt
    logger.info("Fetching UniProt annotations...")
    uniprot_data = get_uniprot_annotations(uniprot_id)
    
    if "error" in uniprot_data:
        logger.warning("UniProt fetch failed: %s", uniprot_data['error'])
        uniprot_context = "UniProt data unavailable for cross-reference."
    else:
        uniprot_context = f"""
UNIPROT ANNOTATIONS:
- Protein name: {uniprot_data.get('protein_name')}
- Function: {uniprot_data.get('function')}
- Subcellular location: {', '.join(uniprot_data.get('subcellular_location', []))}
- GO terms: {'; '.join(uniprot_data.get('go_terms', [])[:5])}
- Known features: {'; '.join(uniprot_data.get('features', [])[:5])}
- Disease associations: {', '.join(uniprot_data.get('disease_associations', [])) or 'None listed'}
"""
    
    # Build critique context
    reasoning = reasoning_result.get("reasoning", {})
    context = f"""
REASONING AGENT'S ANALYSIS:
{json.dumps(reasoning, indent=2)}

EXTERNAL EVIDENCE:
{uniprot_context}

Critique the reasoning above. Are the conclusions supported by evidence?
"""
    
    # Get critique
    logger.info("Calling LLM for critique...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": CRITIC_PROMPT},
            {"role": "user", "content": context}
        ],
        temperature=0.3
    )
    
    raw = response.choices[0].message.content
    logger.info("Got response (%d chars)", len(raw))

    try:
        critique = parse_json_response(raw)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for critique response")
        critique = {"raw_critique": raw}
    
    return {
        "uniprot_id": uniprot_id,
        "uniprot_annotations": uniprot_data,
        "critique": critique
    }


def generate_critique_report(uniprot_id: str, reasoning_result: dict) -> str:
    """Generate human-readable critique report."""
    
    result = critique_reasoning(uniprot_id, reasoning_result)
    critique = result.get("critique", {})
    
    if "raw_critique" in critique:
        return f"# Critique: {uniprot_id}\n\n{critique['raw_critique']}"
    
    report = [
        f"# Critic Review: {uniprot_id}",
        f"**Verdict: {critique.get('verdict', 'N/A')}**",
        "",
    ]
    
    # Challenges
    if critique.get("challenges"):
        report.append("## Challenges")
        for c in critique["challenges"]:
            report.append(f"- **{c.get('severity', '?').upper()}**: {c.get('claim', '')}")
            report.append(f"  - Issue: {c.get('issue', '')}")
        report.append("")
    
    # Contradictions
    if critique.get("contradictions"):
        report.append("## Contradictions Found")
        for c in critique["contradictions"]:
            report.append(f"- Reasoning says: {c.get('reasoning_says', '')}")
            report.append(f"  - Evidence says: {c.get('evidence_says', '')}")
            report.append(f"  - Resolution: {c.get('resolution', '')}")
        report.append("")
    
    # Confidence assessment
    conf = critique.get("confidence_assessment", {})
    if conf:
        report.append("## Confidence Assessment")
        report.append(f"- Original: {conf.get('original_confidence', 'N/A')}")
        report.append(f"- Recommended: {conf.get('recommended_confidence', 'N/A')}")
        report.append(f"- Justification: {conf.get('justification', 'N/A')}")
        report.append("")
    
    # Key concerns
    if critique.get("key_concerns"):
        report.append("## Key Concerns")
        for c in critique["key_concerns"]:
            report.append(f"- {c}")
    
    return "\n".join(report)


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # First, run the reasoning agent to get something to critique
    from reasoning_agent import reason_about_target

    logger.info("Step 1: Running Reasoning Agent...")
    reasoning_result = reason_about_target("Q8I3H7")

    logger.info("Step 2: Running Critic Agent...")
    report = generate_critique_report("Q8I3H7", reasoning_result)
    logger.info(report)
