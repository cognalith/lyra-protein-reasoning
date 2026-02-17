"""
Lyra - Main Entry Point
Clean interface with robust error handling for demos.
"""

import os
import sys
import logging
import traceback
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import LyraOrchestrator, analyze


def check_environment() -> tuple[bool, str]:
    """Verify all required environment variables are set."""
    
    required = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY", 
        "AZURE_OPENAI_DEPLOYMENT"
    ]
    
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        return False, f"Missing environment variables: {', '.join(missing)}"
    
    return True, "Environment OK"


def check_apis() -> tuple[bool, str]:
    """Verify external APIs are reachable."""
    
    import requests
    
    # Check AlphaFold
    try:
        r = requests.get("https://alphafold.ebi.ac.uk/api/prediction/Q8I3H7", timeout=10)
        if r.status_code != 200:
            return False, f"AlphaFold API returned {r.status_code}"
    except Exception as e:
        return False, f"AlphaFold API unreachable: {e}"
    
    # Check UniProt
    try:
        r = requests.get("https://rest.uniprot.org/uniprotkb/Q8I3H7.json", timeout=10)
        if r.status_code != 200:
            return False, f"UniProt API returned {r.status_code}"
    except Exception as e:
        return False, f"UniProt API unreachable: {e}"
    
    return True, "APIs OK"


def run_safe(question: str, verbose: bool = True) -> dict:
    """
    Run Lyra with full error handling.
    
    Returns:
        {
            "success": bool,
            "result": str (the research brief or error message),
            "duration_seconds": float,
            "error": str or None
        }
    """
    
    start = datetime.now()
    
    # Check environment
    env_ok, env_msg = check_environment()
    if not env_ok:
        return {
            "success": False,
            "result": f"❌ Configuration Error: {env_msg}",
            "duration_seconds": 0,
            "error": env_msg
        }
    
    try:
        # Run the analysis
        result = analyze(question, verbose=verbose)
        duration = (datetime.now() - start).total_seconds()
        
        return {
            "success": True,
            "result": result,
            "duration_seconds": duration,
            "error": None
        }
        
    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        error_detail = traceback.format_exc()
        
        # Friendly error messages
        error_msg = str(e)
        if "api_key" in error_msg.lower() or "401" in error_msg:
            friendly = "Authentication failed. Check your AZURE_OPENAI_API_KEY."
        elif "timeout" in error_msg.lower():
            friendly = "Request timed out. The API may be slow or unreachable."
        elif "rate limit" in error_msg.lower() or "429" in error_msg:
            friendly = "Rate limit exceeded. Wait a moment and try again."
        elif "404" in error_msg:
            friendly = "Protein not found. Check the UniProt ID."
        else:
            friendly = f"An error occurred: {error_msg}"
        
        return {
            "success": False,
            "result": f"❌ {friendly}",
            "duration_seconds": duration,
            "error": error_detail
        }


def health_check() -> dict:
    """
    Run a complete health check of the system.
    """
    
    logger.info("Running Lyra health check...")

    checks = {}

    # Environment
    env_ok, env_msg = check_environment()
    checks["environment"] = {"ok": env_ok, "message": env_msg}
    logger.info("  %s Environment: %s", "OK" if env_ok else "FAIL", env_msg)

    # APIs
    api_ok, api_msg = check_apis()
    checks["apis"] = {"ok": api_ok, "message": api_msg}
    logger.info("  %s External APIs: %s", "OK" if api_ok else "FAIL", api_msg)
    
    # Azure OpenAI
    if env_ok:
        try:
            from openai import AzureOpenAI
            client = AzureOpenAI(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                timeout=60.0,
                max_retries=3,
            )
            response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[{"role": "user", "content": "Say 'OK'"}],
                max_tokens=5
            )
            checks["azure_openai"] = {"ok": True, "message": "Connected"}
            logger.info("  OK Azure OpenAI: Connected")
        except Exception as e:
            checks["azure_openai"] = {"ok": False, "message": str(e)}
            logger.error("  FAIL Azure OpenAI: %s", e)

    # Overall
    all_ok = all(c["ok"] for c in checks.values())
    logger.info("All systems operational" if all_ok else "Some checks failed")
    
    return {"healthy": all_ok, "checks": checks}


def interactive():
    """Run Lyra in interactive mode."""
    
    logger.info("═" * 60)
    logger.info("  LYRA - Protein Reasoning System")
    logger.info("  Type 'quit' to exit, 'health' to check system status")
    logger.info("═" * 60)

    while True:
        question = input("\nYour question: ").strip()

        if not question:
            continue

        if question.lower() in ["quit", "exit", "q"]:
            logger.info("Goodbye!")
            break

        if question.lower() == "health":
            health_check()
            continue

        result = run_safe(question)

        if result["success"]:
            logger.info(result["result"])
            logger.info("Completed in %.1f seconds", result['duration_seconds'])
        else:
            logger.error(result["result"])
            if result.get("error") and os.getenv("DEBUG"):
                logger.debug("Debug info:\n%s", result['error'])


# Test
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Command line mode
        question = " ".join(sys.argv[1:])
        result = run_safe(question)
        logger.info(result["result"])
    else:
        # Interactive mode
        interactive()
