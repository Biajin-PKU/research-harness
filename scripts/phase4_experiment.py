"""
Phase 4 Validation Experiment Script
Runs paper_summarize, claim_extract, gap_detect, and section_draft
"""
import os
import sys
sys.path.insert(0, '/workspace/research-hub/packages/research_harness')
sys.path.insert(0, '/workspace/research-hub/packages/paperindex')

from research_harness.storage.db import Database
from research_harness.execution.harness import ResearchHarnessBackend
from research_harness.primitives.registry import list_primitives
import json
from datetime import datetime

DB_PATH = "/workspace/research-hub/.research-harness/pool.db"
TOPIC_ID = 1  # cross-budget-rebalancing

# Papers with PDFs and annotations
ANNOTATED_PAPERS = [1, 4, 5, 6, 7, 14, 15, 16, 20]

def run_experiment():
    db = Database(DB_PATH)
    backend = ResearchHarnessBackend(db=db)
    
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "topic_id": TOPIC_ID,
        "available_primitives": list_primitives(),
        "experiments": []
    }
    
    print("=" * 60)
    print("Phase 4 Validation Experiment")
    print("=" * 60)
    
    # Experiment 1: paper_summarize on first 3 papers
    print("\n[1/4] Running paper_summarize...")
    for paper_id in ANNOTATED_PAPERS[:3]:
        result = backend.execute("paper_summarize", paper_id=paper_id, focus="methodology")
        exp_result = {
            "primitive": "paper_summarize",
            "paper_id": paper_id,
            "success": result.success,
            "model_used": result.model_used,
            "cost_usd": result.cost_usd,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
        }
        if result.success and result.output:
            exp_result["summary_length"] = len(result.output.summary) if result.output.summary else 0
            exp_result["confidence"] = result.output.confidence
            print(f"  Paper {paper_id}: success, confidence={result.output.confidence:.2f}")
        else:
            exp_result["error"] = result.error
            print(f"  Paper {paper_id}: failed - {result.error}")
        results["experiments"].append(exp_result)
    
    # Experiment 2: claim_extract on 5 papers
    print("\n[2/4] Running claim_extract...")
    result = backend.execute("claim_extract", paper_ids=ANNOTATED_PAPERS[:5], topic_id=TOPIC_ID, focus="cross-channel budget allocation")
    exp_result = {
        "primitive": "claim_extract",
        "paper_ids": ANNOTATED_PAPERS[:5],
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
    }
    if result.success and result.output:
        exp_result["claims_count"] = len(result.output.claims)
        exp_result["papers_processed"] = result.output.papers_processed
        print(f"  Success: extracted {len(result.output.claims)} claims from {result.output.papers_processed} papers")
        for i, claim in enumerate(result.output.claims[:3], 1):
            print(f"    Claim {i}: {claim.content[:80]}...")
    else:
        exp_result["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp_result)
    
    # Experiment 3: gap_detect
    print("\n[3/4] Running gap_detect...")
    result = backend.execute("gap_detect", topic_id=TOPIC_ID, focus="cross-channel advertising optimization")
    exp_result = {
        "primitive": "gap_detect",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
    }
    if result.success and result.output:
        exp_result["gaps_count"] = len(result.output.gaps)
        exp_result["papers_analyzed"] = result.output.papers_analyzed
        print(f"  Success: found {len(result.output.gaps)} gaps from {result.output.papers_analyzed} papers")
        for i, gap in enumerate(result.output.gaps[:3], 1):
            print(f"    Gap {i}: {gap.description[:80]}...")
    else:
        exp_result["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp_result)
    
    # Experiment 4: section_draft (intro)
    print("\n[4/4] Running section_draft (intro)...")
    result = backend.execute(
        "section_draft", 
        section="introduction", 
        topic_id=TOPIC_ID,
        outline="1. Background on cross-channel advertising\n2. Budget allocation challenges\n3. Research gaps\n4. Our contributions",
        max_words=500
    )
    exp_result = {
        "primitive": "section_draft",
        "section": "introduction",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
    }
    if result.success and result.output:
        exp_result["word_count"] = result.output.draft.word_count
        print(f"  Success: drafted {result.output.draft.word_count} words")
        print(f"  Preview: {result.output.draft.content[:150]}...")
    else:
        exp_result["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp_result)
    
    # Summary
    print("\n" + "=" * 60)
    print("Experiment Summary")
    print("=" * 60)
    total_cost = sum(e.get("cost_usd", 0) for e in results["experiments"])
    success_count = sum(1 for e in results["experiments"] if e.get("success"))
    print(f"Total experiments: {len(results['experiments'])}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(results['experiments']) - success_count}")
    print(f"Total cost: ${total_cost:.4f}")
    
    # Save results
    output_path = "/workspace/research-hub/docs/experiments/phase4_results.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")
    
    return results

if __name__ == "__main__":
    run_experiment()
