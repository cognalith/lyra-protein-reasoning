"""
Query Agent
Translates natural language protein questions into AlphaFold API calls.
"""

import os
import sys
import json
from openai import AzureOpenAI

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_servers.alphafold_mcp import get_protein_prediction, summarize_protein, get_plddt_scores


# Azure OpenAI client
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview"
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")


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
            data = get_plddt_scores(uid)
            results["proteins"].append({"uniprot_id": uid, "plddt_scores": data})
        else:
            data = summarize_protein(uid)
            results["proteins"].append(data)
    
    # Generate summary based on intent
    if intent == "compare" and len(results["proteins"]) > 1:
        results["summary"] = _generate_comparison(results["proteins"])
    elif intent == "summarize" and results["proteins"]:
        p = results["proteins"][0]
        results["summary"] = f"{p['description']} from {p['organism']}. Drug target potential: {p['drug_target_assessment']}"
    
    return results


def _generate_comparison(proteins: list) -> str:
    """Generate a comparison summary."""
    lines = ["Comparison:"]
    for p in proteins:
        conf = p.get("confidence", {}).get("overall", "N/A")
        assessment = p.get("drug_target_assessment", "Unknown")
        lines.append(f"- {p['uniprot_id']}: confidence={conf}, {assessment}")
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
