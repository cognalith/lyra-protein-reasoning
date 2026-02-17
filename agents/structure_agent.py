"""
Structure Agent
Analyzes protein structure confidence and identifies key regions.
"""

import os
import sys
import json
import logging
from openai import AzureOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_servers.alphafold_mcp import get_protein_prediction, get_plddt_scores


client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    timeout=60.0,
    max_retries=3,
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

logger = logging.getLogger(__name__)


def analyze_confidence_regions(uniprot_id: str) -> dict:
    """
    Analyze pLDDT scores to identify high/low confidence regions.
    
    pLDDT scoring:
    - >90: Very high confidence (blue)
    - 70-90: Confident (cyan)
    - 50-70: Low confidence (yellow)
    - <50: Very low confidence (orange) - likely disordered
    """
    
    metadata = get_protein_prediction(uniprot_id)
    if "error" in metadata:
        return metadata
    
    # Get per-residue scores
    plddt_data = get_plddt_scores(uniprot_id)
    if "error" in plddt_data:
        # Fall back to summary stats from metadata
        return {
            "uniprot_id": uniprot_id,
            "analysis_type": "summary_only",
            "overall_confidence": metadata.get("globalMetricValue"),
            "fractions": {
                "very_high": metadata.get("fractionPlddtVeryHigh"),
                "confident": metadata.get("fractionPlddtConfident"),
                "low": metadata.get("fractionPlddtLow"),
                "very_low": metadata.get("fractionPlddtVeryLow"),
            },
            "interpretation": _interpret_fractions(metadata)
        }
    
    # Full per-residue analysis
    scores = plddt_data if isinstance(plddt_data, list) else plddt_data.get("confidenceScore", [])
    
    regions = _identify_regions(scores)
    
    return {
        "uniprot_id": uniprot_id,
        "analysis_type": "per_residue",
        "total_residues": len(scores),
        "overall_confidence": metadata.get("globalMetricValue"),
        "regions": regions,
        "drug_target_regions": _find_drug_target_regions(regions),
        "interpretation": _interpret_regions(regions)
    }


def _identify_regions(scores: list) -> dict:
    """Identify contiguous regions by confidence level."""
    
    very_high = []  # >90
    confident = []  # 70-90
    low = []        # 50-70
    very_low = []   # <50
    
    for i, score in enumerate(scores):
        if score > 90:
            very_high.append(i + 1)  # 1-indexed for biology convention
        elif score > 70:
            confident.append(i + 1)
        elif score > 50:
            low.append(i + 1)
        else:
            very_low.append(i + 1)
    
    return {
        "very_high": {"count": len(very_high), "ranges": _to_ranges(very_high)},
        "confident": {"count": len(confident), "ranges": _to_ranges(confident)},
        "low": {"count": len(low), "ranges": _to_ranges(low)},
        "very_low": {"count": len(very_low), "ranges": _to_ranges(very_low)},
    }


def _to_ranges(positions: list) -> list:
    """Convert [1,2,3,5,6,10] to [(1,3), (5,6), (10,10)]."""
    if not positions:
        return []
    
    ranges = []
    start = positions[0]
    end = positions[0]
    
    for pos in positions[1:]:
        if pos == end + 1:
            end = pos
        else:
            ranges.append((start, end))
            start = pos
            end = pos
    
    ranges.append((start, end))
    return ranges


def _find_drug_target_regions(regions: dict) -> list:
    """Identify regions suitable for drug targeting (high confidence, contiguous)."""
    
    target_regions = []
    
    # Look for substantial high-confidence regions
    for start, end in regions["very_high"]["ranges"]:
        length = end - start + 1
        if length >= 20:  # At least 20 residues
            target_regions.append({
                "start": start,
                "end": end,
                "length": length,
                "confidence": "very_high",
                "suitability": "excellent"
            })
    
    for start, end in regions["confident"]["ranges"]:
        length = end - start + 1
        if length >= 30:  # Need longer stretch if only confident
            target_regions.append({
                "start": start,
                "end": end,
                "length": length,
                "confidence": "confident",
                "suitability": "good"
            })
    
    return sorted(target_regions, key=lambda x: x["length"], reverse=True)


def _interpret_fractions(metadata: dict) -> str:
    """Generate interpretation from fraction data."""
    very_high = metadata.get("fractionPlddtVeryHigh", 0)
    very_low = metadata.get("fractionPlddtVeryLow", 0)
    
    if very_high > 0.6:
        quality = "excellent"
    elif very_high > 0.4:
        quality = "good"
    elif very_high > 0.2:
        quality = "moderate"
    else:
        quality = "poor"
    
    return f"Structure quality: {quality}. {very_high*100:.0f}% very high confidence, {very_low*100:.0f}% disordered regions."


def _interpret_regions(regions: dict) -> str:
    """Generate interpretation from region analysis."""
    vh = regions["very_high"]["count"]
    vl = regions["very_low"]["count"]
    total = vh + regions["confident"]["count"] + regions["low"]["count"] + vl
    
    vh_pct = (vh / total * 100) if total > 0 else 0
    vl_pct = (vl / total * 100) if total > 0 else 0
    
    return f"{vh_pct:.0f}% very high confidence residues, {vl_pct:.0f}% likely disordered."


def generate_structure_report(uniprot_id: str) -> str:
    """Generate a human-readable structure analysis report."""
    
    analysis = analyze_confidence_regions(uniprot_id)
    
    if "error" in analysis:
        return f"Error analyzing {uniprot_id}: {analysis['error']}"
    
    report = [
        f"## Structure Analysis: {uniprot_id}",
        f"Overall confidence: {analysis['overall_confidence']:.1f}/100",
        f"",
        f"### Confidence Distribution",
        analysis["interpretation"],
    ]
    
    if analysis.get("drug_target_regions"):
        report.append("")
        report.append("### Potential Drug Target Regions")
        for r in analysis["drug_target_regions"][:3]:  # Top 3
            report.append(f"- Residues {r['start']}-{r['end']} ({r['length']} aa): {r['suitability']}")
    
    return "\n".join(report)


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    report = generate_structure_report("Q8I3H7")
    logger.info(report)
