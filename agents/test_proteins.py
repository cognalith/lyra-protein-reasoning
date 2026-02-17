"""
Test Lyra with multiple proteins to find edge cases.
"""

import sys
sys.path.append('.')

from lyra import run_safe

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
    print("═" * 60)
    print("  LYRA MULTI-PROTEIN TEST SUITE")
    print("═" * 60)
    
    results = []
    
    for i, test in enumerate(TEST_CASES, 1):
        print(f"\n{'─' * 60}")
        print(f"Test {i}: {test['name']}")
        print(f"Question: {test['question']}")
        print(f"{'─' * 60}")
        
        result = run_safe(test["question"], verbose=False)
        
        status = "✓ PASS" if result["success"] else "⚠ HANDLED"
        print(f"\nStatus: {status}")
        print(f"Duration: {result['duration_seconds']:.1f}s")
        
        # Show brief preview of result
        preview = result["result"][:200] + "..." if len(result["result"]) > 200 else result["result"]
        print(f"Preview: {preview}")
        
        results.append({
            "test": test["name"],
            "success": result["success"],
            "duration": result["duration_seconds"],
            "error": result.get("error")
        })
    
    # Summary
    print(f"\n{'═' * 60}")
    print("  TEST SUMMARY")
    print(f"{'═' * 60}")
    
    passed = sum(1 for r in results if r["success"])
    handled = sum(1 for r in results if not r["success"] and not r.get("error"))
    failed = sum(1 for r in results if r.get("error"))
    
    print(f"  ✓ Passed: {passed}/{len(results)}")
    print(f"  ⚠ Gracefully handled: {handled}/{len(results)}")
    print(f"  ✗ Errors: {failed}/{len(results)}")
    
    return results


if __name__ == "__main__":
    run_tests()
