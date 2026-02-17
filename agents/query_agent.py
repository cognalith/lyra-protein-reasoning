"""
Query Agent
Translates natural language protein questions into AlphaFold API calls.
"""

import os
import sys
import re
import json
import logging
from openai import AzureOpenAI

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_servers.alphafold_mcp import get_protein_prediction, summarize_protein, get_plddt_scores


# Azure OpenAI client
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview",
    timeout=60.0,
    max_retries=3,
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

logger = logging.getLogger(__name__)

UNIPROT_ID_PATTERN = re.compile(r'^[A-Za-z0-9]{1,15}$')
REQUIRED_PROTEIN_FIELDS = ["description", "organism"]


def validate_protein_id(protein_id):
    """Basic format check. Catches obvious garbage before wasting an API call."""
    if not protein_id or not isinstance(protein_id, str):
        return False, "Protein ID must be a non-empty string"
    protein_id = protein_id.strip()
    if not UNIPROT_ID_PATTERN.match(protein_id):
        return False, f"Invalid protein ID format: '{protein_id}'"
    return True, None


def process_protein(protein_id):
    """Query and validate a single protein. Returns structured result or error dict."""
    valid, error_msg = validate_protein_id(protein_id)
    if not valid:
        logger.warning("Rejected invalid protein ID: %s — %s", protein_id, error_msg)
        return {"uniprot_id": protein_id, "error": error_msg, "source": "query_agent"}

    result = summarize_protein(protein_id)

    if result is None:
        logger.warning("No response from MCP server for %s", protein_id)
        return {"uniprot_id": protein_id, "error": "No response from protein database", "source": "query_agent"}

    if not isinstance(result, dict):
        logger.warning("Unexpected response type for %s: %s", protein_id, type(result).__name__)
        return {"uniprot_id": protein_id, "error": f"Unexpected response type: {type(result).__name__}", "source": "query_agent"}

    if "error" in result:
        logger.warning("MCP server error for %s: %s", protein_id, result.get("error", "unknown"))
        return {"uniprot_id": protein_id, "error": result["error"], "source": "query_agent"}

    missing = [f for f in REQUIRED_PROTEIN_FIELDS if f not in result]
    if missing:
        logger.warning("Missing required fields for %s: %s", protein_id, missing)
        return {"uniprot_id": protein_id, "error": f"Incomplete data — missing: {', '.join(missing)}", "source": "query_agent"}

    return result


SYSTEM_PROMPT = """You are the Query Agent for Lyra, a protein research system.

Your job: Extract protein identifiers and intent from natural language questions.

Given a research question, respond with JSON containing:
{
    "uniprot_ids": ["Q8I3H7", ...],  // List of UniProt IDs mentioned or implied
    "intent": "summarize" | "analyze_confidence" | "compare" | "search",
    "organism": "species name if mentioned",
    "keywords": ["drug target", "binding site", ...]  // Key research terms
}

Examples:
- "Tell me about Q8I3H7" → {"uniprot_ids": ["Q8I3H7"], "intent": "summarize", "organism": null, "keywords": []}
- "Is Q8I3H7 a good drug target?" → {"uniprot_ids": ["Q8I3H7"], "intent": "summarize", "organism": null, "keywords": ["drug target"]}
- "Compare confidence of Q8I3H7 and P12345" → {"uniprot_ids": ["Q8I3H7", "P12345"], "intent": "compare", "organism": null, "keywords": ["confidence"]}

If no specific protein is mentioned but an organism is, set intent to "search".
Always respond with valid JSON only, no other text.
"""


def parse_query(question: str) -> dict:
    """Use LLM to extract structured query from natural language."""
    
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question}
        ],
        temperature=0
    )
    
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return {"error": "Failed to parse query", "raw": response.choices[0].message.content}


def execute_query(parsed: dict) -> dict:
    """Execute the parsed query against AlphaFold."""
    
    intent = parsed.get("intent", "summarize")
    uniprot_ids = parsed.get("uniprot_ids", [])
    
    results = {
        "intent": intent,
        "proteins": [],
        "summary": ""
    }
    
    if not uniprot_ids:
        results["summary"] = "No protein IDs found in query. Try asking about a specific UniProt ID like Q8I3H7."
        return results
    
    # Fetch data for each protein
    for uid in uniprot_ids:
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
        else:
            data = process_protein(uid)
            results["proteins"].append(data)

    # Generate summary based on intent
    if intent == "compare" and len(results["proteins"]) > 1:
        results["summary"] = _generate_comparison(results["proteins"])
    elif intent == "summarize" and results["proteins"]:
        p = results["proteins"][0]
        if isinstance(p, dict) and "error" not in p:
            results["summary"] = (
                f"{p.get('description', 'Unknown protein')} from {p.get('organism', 'Unknown organism')}. "
                f"Drug target potential: {p.get('drug_target_assessment', 'Assessment unavailable')}"
            )
        else:
            results["summary"] = f"Failed to fetch protein: {p.get('error', 'Unknown error') if isinstance(p, dict) else 'Unknown error'}"
    
    return results


def _generate_comparison(proteins: list) -> str:
    """Generate a comparison summary."""
    lines = ["Comparison:"]
    for p in proteins:
        conf = p.get("confidence", {}).get("overall", "N/A")
        assessment = p.get("drug_target_assessment", "Unknown")
        lines.append(f"- {p.get('uniprot_id', 'Unknown')}: confidence={conf}, {assessment}")
    return "\n".join(lines)


def run(question: str) -> dict:
    """Main entry point: question in, structured results out."""
    parsed = parse_query(question)
    
    if "error" in parsed:
        return parsed
    
    return execute_query(parsed)


# Test
if __name__ == "__main__":
    print("=" * 60)
    print("QUERY AGENT TEST")
    print("=" * 60)
    
    test_questions = [
        "Tell me about protein Q8I3H7",
        "Is Q8I3H7 a good drug target for malaria?",
        "What's the structure confidence for Q8I3H7?",
    ]
    
    for q in test_questions:
        print(f"\n📝 Question: {q}")
        print("-" * 40)
        result = run(q)
        print(f"Intent: {result.get('intent')}")
        print(f"Summary: {result.get('summary')}")
        if result.get('proteins'):
            p = result['proteins'][0]
            print(f"Confidence: {p.get('confidence', {}).get('overall', 'N/A')}")

# Quick test of confidence display
def _test_confidence():
    result = run("What's the structure confidence for Q8I3H7?")
    if result.get('proteins'):
        p = result['proteins'][0]
        if 'plddt_scores' in p:
            scores = p['plddt_scores']
            print(f"Got {len(scores)} residue confidence scores")
            print(f"Sample (first 5): {scores[:5]}")
