"""
Test Lyra with multiple proteins to find edge cases.
"""

import sys
import logging
sys.path.append('.')

from lyra import run_safe

logger = logging.getLogger(__name__)

# Test cases: variety of proteins
TEST_CASES = [
    {
        "name": "Malaria target (known good)",
        "question": "Is Q8I3H7 a viable drug target?",
        "protein": "Q8I3H7"
    },
    {
        "name": "Human protein (different organism)",
        "question": "Analyze P53 tumor suppressor protein P04637",
        "protein": "P04637"
    },
    {
        "name": "Invalid protein ID",
        "question": "Analyze protein INVALID123",
        "protein": "INVALID123"
    },
    {
        "name": "Bacterial protein",
        "question": "Is E. coli protein P0A7B3 a drug target?",
        "protein": "P0A7B3"
    },
    {
        "name": "No protein specified",
        "question": "What makes a good drug target?",
        "protein": None
    },
]

def run_tests():
    logger.info("═" * 60)
    logger.info("  LYRA MULTI-PROTEIN TEST SUITE")
    logger.info("═" * 60)

    results = []

    for i, test in enumerate(TEST_CASES, 1):
        logger.info("─" * 60)
        logger.info("Test %d: %s", i, test['name'])
        logger.info("Question: %s", test['question'])
        logger.info("─" * 60)

        result = run_safe(test["question"], verbose=False)

        status = "PASS" if result["success"] else "HANDLED"
        logger.info("Status: %s", status)
        logger.info("Duration: %.1fs", result['duration_seconds'])

        # Show brief preview of result
        preview = result["result"][:200] + "..." if len(result["result"]) > 200 else result["result"]
        logger.info("Preview: %s", preview)

        results.append({
            "test": test["name"],
            "success": result["success"],
            "duration": result["duration_seconds"],
            "error": result.get("error")
        })

    # Summary
    logger.info("═" * 60)
    logger.info("  TEST SUMMARY")
    logger.info("═" * 60)

    passed = sum(1 for r in results if r["success"])
    handled = sum(1 for r in results if not r["success"] and not r.get("error"))
    failed = sum(1 for r in results if r.get("error"))

    logger.info("  Passed: %d/%d", passed, len(results))
    logger.info("  Gracefully handled: %d/%d", handled, len(results))
    logger.info("  Errors: %d/%d", failed, len(results))

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_tests()
