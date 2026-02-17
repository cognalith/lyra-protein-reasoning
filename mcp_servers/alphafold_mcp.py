"""
AlphaFold MCP Server
Provides tools for querying AlphaFold protein structure database.
"""

import sys
import os
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config.http_client import resilient_get

ALPHAFOLD_BASE_URL = "https://alphafold.ebi.ac.uk/api"


def get_protein_prediction(uniprot_id: str) -> dict:
    """
    Fetch protein prediction metadata from AlphaFold.
    
    Args:
        uniprot_id: UniProt accession (e.g., 'Q8I3H7')
    
    Returns:
        Protein metadata including confidence scores and structure URLs
    """
    url = f"{ALPHAFOLD_BASE_URL}/prediction/{uniprot_id}"
    try:
        response = resilient_get(url, timeout_key="alphafold_metadata")
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return {"error": f"Protein {uniprot_id} not found in AlphaFold"}
        raise
    data = response.json()
    
    # Return first result (AlphaFold returns a list)
    if isinstance(data, list) and len(data) > 0:
        return data[0]
    return data


def get_plddt_scores(uniprot_id: str) -> dict:
    """
    Fetch per-residue confidence scores (pLDDT).
    
    Args:
        uniprot_id: UniProt accession
    
    Returns:
        Per-residue confidence scores (0-100)
    """
    # First get the metadata to find the confidence URL
    metadata = get_protein_prediction(uniprot_id)
    
    if "error" in metadata:
        return metadata
    
    plddt_url = metadata.get("plddtDocUrl")
    if not plddt_url:
        return {"error": "No pLDDT data available"}
    
    response = resilient_get(plddt_url, timeout_key="alphafold_structure")
    return response.json()


def search_proteins_by_organism(taxon_id: int, limit: int = 10) -> list:
    """
    Search for proteins by organism taxonomy ID.
    
    Args:
        taxon_id: NCBI taxonomy ID (e.g., 36329 for P. falciparum)
        limit: Max results to return
    
    Returns:
        List of protein accessions
    """
    # AlphaFold doesn't have a direct search API, so we'll use UniProt
    # This is a placeholder - real implementation would use UniProt API
    return {"note": "Use UniProt API for organism search", "taxon_id": taxon_id}


def summarize_protein(uniprot_id: str) -> dict:
    """
    Get a summary of protein suitability as a drug target.
    
    Args:
        uniprot_id: UniProt accession
    
    Returns:
        Summary with confidence assessment
    """
    metadata = get_protein_prediction(uniprot_id)
    
    if "error" in metadata:
        return metadata
    
    return {
        "uniprot_id": uniprot_id,
        "description": metadata.get("uniprotDescription", "Unknown"),
        "organism": metadata.get("organismScientificName", "Unknown"),
        "gene": metadata.get("gene", "Unknown"),
        "length": metadata.get("sequenceEnd", 0),
        "confidence": {
            "overall": metadata.get("globalMetricValue", 0),
            "very_high_fraction": metadata.get("fractionPlddtVeryHigh", 0),
            "very_low_fraction": metadata.get("fractionPlddtVeryLow", 0),
        },
        "structure_urls": {
            "pdb": metadata.get("pdbUrl"),
            "cif": metadata.get("cifUrl"),
        },
        "drug_target_assessment": _assess_drug_target(metadata)
    }


def _assess_drug_target(metadata: dict) -> str:
    """Simple heuristic for drug target potential."""
    confidence = metadata.get("globalMetricValue", 0)
    high_conf_fraction = metadata.get("fractionPlddtVeryHigh", 0)
    
    if confidence >= 80 and high_conf_fraction >= 0.5:
        return "HIGH - Reliable structure, good candidate for analysis"
    elif confidence >= 60:
        return "MEDIUM - Moderate confidence, proceed with caution"
    else:
        return "LOW - Structure unreliable, not recommended"


# Test the server
if __name__ == "__main__":
    print("Testing AlphaFold MCP Server...\n")
    
    # Test with malaria protein
    summary = summarize_protein("Q8I3H7")
    
    print(f"Protein: {summary['description']}")
    print(f"Organism: {summary['organism']}")
    print(f"Gene: {summary['gene']}")
    print(f"Length: {summary['length']} residues")
    print(f"Overall confidence: {summary['confidence']['overall']}")
    print(f"Drug target assessment: {summary['drug_target_assessment']}")
