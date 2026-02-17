"""Centralized HTTP configuration for all Lyra API calls."""

# Timeout defaults (connect_seconds, read_seconds)
TIMEOUTS = {
    "alphafold_metadata": (10, 20),
    "alphafold_structure": (10, 45),
    "uniprot_search": (10, 20),
    "uniprot_annotation": (10, 15),
    "azure_openai": (10, 60),
    "default": (10, 30),
}

# Retry configuration
RETRY = {
    "max_attempts": 3,
    "retry_on_status": [429, 500, 502, 503, 504],
    "backoff_base": 1.0,       # seconds
    "backoff_multiplier": 2.0,  # exponential: 1s, 2s, 4s
    "backoff_max": 10.0,        # cap at 10 seconds
}
