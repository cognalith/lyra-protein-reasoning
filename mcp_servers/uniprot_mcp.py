"""
UniProt MCP Server
Provides tools for searching and fetching protein data from UniProt.
"""

import requests
from typing import Optional, List

UNIPROT_API = "https://rest.uniprot.org/uniprotkb"


def search_proteins(
    query: str,
    organism: Optional[str] = None,
    limit: int = 10
) -> List[dict]:
    """
    Search UniProt for proteins matching query.
    
    Args:
        query: Search terms (gene name, function, disease, etc.)
        organism: Optional organism filter (e.g., "Plasmodium falciparum")
        limit: Max results to return
    
    Returns:
        List of protein summaries
    """
    
    # Build query string
    search_query = query
    if organism:
        search_query += f" AND (organism_name:{organism})"
    
    url = f"{UNIPROT_API}/search"
    params = {
        "query": search_query,
        "format": "json",
        "size": limit,
        "fields": "accession,id,protein_name,gene_names,organism_name,length,cc_function"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for entry in data.get("results", []):
            results.append({
                "uniprot_id": entry.get("primaryAccession", ""),
                "entry_name": entry.get("uniProtkbId", ""),
                "protein_name": _extract_protein_name(entry),
                "gene_names": _extract_gene_names(entry),
                "organism": entry.get("organism", {}).get("scientificName", "Unknown"),
                "length": entry.get("sequence", {}).get("length", 0),
                "function": _extract_function_comment(entry),
            })
        
        return results
        
    except requests.RequestException as e:
        return [{"error": f"UniProt search failed: {str(e)}"}]


def get_protein_details(uniprot_id: str) -> dict:
    """
    Fetch detailed protein information from UniProt.
    
    Args:
        uniprot_id: UniProt accession (e.g., 'Q8I3H7')
    
    Returns:
        Detailed protein data
    """
    
    url = f"{UNIPROT_API}/{uniprot_id}.json"
    
    try:
        response = requests.get(url, timeout=15)
        
        if response.status_code == 404:
            return {"error": f"Protein {uniprot_id} not found in UniProt"}
        
        response.raise_for_status()
        data = response.json()
        
        return {
            "uniprot_id": data.get("primaryAccession", ""),
            "entry_name": data.get("uniProtkbId", ""),
            "protein_name": _extract_protein_name(data),
            "gene_names": _extract_gene_names(data),
            "organism": data.get("organism", {}).get("scientificName", "Unknown"),
            "taxonomy_id": data.get("organism", {}).get("taxonId", 0),
            "length": data.get("sequence", {}).get("length", 0),
            "sequence": data.get("sequence", {}).get("value", ""),
            "function": _extract_function_comment(data),
            "subcellular_location": _extract_subcellular_location(data),
            "go_terms": _extract_go_terms(data),
            "domains": _extract_domains(data),
            "disease_associations": _extract_diseases(data),
            "cross_references": _extract_cross_refs(data),
        }
        
    except requests.RequestException as e:
        return {"error": f"UniProt fetch failed: {str(e)}"}


def search_by_organism(organism: str, keyword: Optional[str] = None, limit: int = 10) -> List[dict]:
    """
    Search for proteins from a specific organism.
    
    Args:
        organism: Organism name (e.g., "Plasmodium falciparum")
        keyword: Optional keyword filter (e.g., "membrane", "kinase")
        limit: Max results
    """
    query = f"organism_name:{organism}"
    if keyword:
        query += f" AND ({keyword})"
    
    return search_proteins(query, limit=limit)


def search_by_disease(disease: str, limit: int = 10) -> List[dict]:
    """
    Search for proteins associated with a disease.
    
    Args:
        disease: Disease name (e.g., "malaria", "cancer")
        limit: Max results
    """
    return search_proteins(f"cc_disease:{disease}", limit=limit)


def search_drug_targets(organism: str, limit: int = 10) -> List[dict]:
    """
    Search for potential drug targets in an organism.
    Looks for membrane proteins, enzymes, and receptors.
    
    Args:
        organism: Organism name
        limit: Max results
    """
    # Search for common drug target types
    queries = [
        f"organism_name:{organism} AND (keyword:receptor)",
        f"organism_name:{organism} AND (keyword:kinase)", 
        f"organism_name:{organism} AND (ec:*)",  # Enzymes
    ]
    
    all_results = []
    for q in queries:
        results = search_proteins(q, limit=limit//3 + 1)
        all_results.extend([r for r in results if "error" not in r])
    
    # Deduplicate by uniprot_id
    seen = set()
    unique = []
    for r in all_results:
        uid = r.get("uniprot_id")
        if uid and uid not in seen:
            seen.add(uid)
            unique.append(r)
    
    return unique[:limit]


# Helper functions

def _extract_protein_name(entry: dict) -> str:
    """Extract protein name from UniProt entry."""
    desc = entry.get("proteinDescription", {})
    rec_name = desc.get("recommendedName", {})
    full_name = rec_name.get("fullName", {})
    return full_name.get("value", "Unknown protein")


def _extract_gene_names(entry: dict) -> List[str]:
    """Extract gene names from UniProt entry."""
    genes = entry.get("genes", [])
    names = []
    for gene in genes:
        if gene.get("geneName"):
            names.append(gene["geneName"].get("value", ""))
    return names


def _extract_function_comment(entry: dict) -> str:
    """Extract function annotation."""
    comments = entry.get("comments", [])
    for c in comments:
        if c.get("commentType") == "FUNCTION":
            texts = c.get("texts", [])
            if texts:
                return texts[0].get("value", "")
    return "No function annotation available"


def _extract_subcellular_location(entry: dict) -> List[str]:
    """Extract subcellular locations."""
    comments = entry.get("comments", [])
    locations = []
    for c in comments:
        if c.get("commentType") == "SUBCELLULAR LOCATION":
            for loc in c.get("subcellularLocations", []):
                loc_val = loc.get("location", {}).get("value")
                if loc_val:
                    locations.append(loc_val)
    return locations if locations else ["Unknown"]


def _extract_go_terms(entry: dict) -> List[dict]:
    """Extract GO terms."""
    go_terms = []
    for ref in entry.get("uniProtKBCrossReferences", []):
        if ref.get("database") == "GO":
            term_id = ref.get("id", "")
            props = ref.get("properties", [])
            term_name = ""
            category = ""
            for p in props:
                if p.get("key") == "GoTerm":
                    full = p.get("value", "")
                    if ":" in full:
                        category, term_name = full.split(":", 1)
            go_terms.append({
                "id": term_id,
                "term": term_name.strip(),
                "category": category.strip()
            })
    return go_terms[:15]


def _extract_domains(entry: dict) -> List[dict]:
    """Extract domain annotations."""
    domains = []
    for f in entry.get("features", []):
        if f.get("type") in ["Domain", "Region", "Motif"]:
            domains.append({
                "type": f.get("type"),
                "description": f.get("description", ""),
                "start": f.get("location", {}).get("start", {}).get("value"),
                "end": f.get("location", {}).get("end", {}).get("value"),
            })
    return domains[:10]


def _extract_diseases(entry: dict) -> List[str]:
    """Extract disease associations."""
    diseases = []
    for c in entry.get("comments", []):
        if c.get("commentType") == "DISEASE":
            disease = c.get("disease", {})
            name = disease.get("diseaseId", "")
            if name:
                diseases.append(name)
    return diseases


def _extract_cross_refs(entry: dict) -> dict:
    """Extract key cross-references."""
    refs = {"PDB": [], "AlphaFoldDB": [], "Pfam": []}
    for ref in entry.get("uniProtKBCrossReferences", []):
        db = ref.get("database")
        if db in refs:
            refs[db].append(ref.get("id", ""))
    return refs


# Test
if __name__ == "__main__":
    print("=" * 60)
    print("UNIPROT MCP SERVER TEST")
    print("=" * 60)
    
    # Test 1: Search by organism
    print("\n📡 Test 1: Search for Plasmodium falciparum proteins")
    results = search_by_organism("Plasmodium falciparum", keyword="membrane", limit=5)
    for r in results[:3]:
        if "error" not in r:
            print(f"  - {r['uniprot_id']}: {r['protein_name'][:50]}...")
    
    # Test 2: Get protein details
    print("\n📡 Test 2: Get details for Q8I3H7")
    details = get_protein_details("Q8I3H7")
    if "error" not in details:
        print(f"  Name: {details['protein_name']}")
        print(f"  Organism: {details['organism']}")
        print(f"  Function: {details['function'][:100]}...")
        print(f"  GO terms: {len(details['go_terms'])}")
        print(f"  Domains: {len(details['domains'])}")
    
    # Test 3: Search drug targets
    print("\n📡 Test 3: Search potential drug targets")
    targets = search_drug_targets("Plasmodium falciparum", limit=5)
    for t in targets[:3]:
        if "error" not in t:
            print(f"  - {t['uniprot_id']}: {t['protein_name'][:50]}...")
    
    print("\n✓ UniProt MCP Server ready")
