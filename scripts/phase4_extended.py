"""
Phase 4 Extended Validation Experiments
"""
import os
import sys
sys.path.insert(0, '/workspace/research-hub/packages/research_harness')
sys.path.insert(0, '/workspace/research-hub/packages/paperindex')

from research_harness.storage.db import Database
from research_harness.execution.harness import ResearchHarnessBackend
import json
from datetime import datetime

DB_PATH = "/workspace/research-hub/.research-harness/pool.db"
TOPIC_ID = 1
ANNOTATED_PAPERS = [1, 4, 5, 6, 7, 14, 15, 16, 20]

def run_extended_experiments():
    db = Database(DB_PATH)
    backend = ResearchHarnessBackend(db=db)
    
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "experiments": []
    }
    
    print("=" * 60)
    print("Phase 4 Extended Experiments")
    print("=" * 60)
    
    # Test 1: claim_extract on all 8 annotated papers
    print("\n[1] Running claim_extract on all 8 papers...")
    result = backend.execute(
        "claim_extract", 
        paper_ids=ANNOTATED_PAPERS, 
        topic_id=TOPIC_ID, 
        focus="cross-channel budget allocation and optimization"
    )
    exp = {
        "test": "claim_extract_all",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "papers_processed": result.output.papers_processed if result.success else 0,
        "claims_count": len(result.output.claims) if result.success else 0,
        "claims": []
    }
    if result.success and result.output:
        for claim in result.output.claims:
            exp["claims"].append({
                "content": claim.content[:200],
                "evidence_type": claim.evidence_type,
                "confidence": claim.confidence,
                "paper_ids": claim.paper_ids
            })
        print(f"  Success: {len(result.output.claims)} claims from {result.output.papers_processed} papers")
    else:
        exp["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp)
    
    # Test 2: gap_detect with different focus
    print("\n[2] Running gap_detect (methodology focus)...")
    result = backend.execute(
        "gap_detect", 
        topic_id=TOPIC_ID, 
        focus="methodology and evaluation metrics"
    )
    exp = {
        "test": "gap_detect_methodology",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "gaps_count": len(result.output.gaps) if result.success else 0,
        "gaps": []
    }
    if result.success and result.output:
        for gap in result.output.gaps[:5]:  # Top 5 gaps
            exp["gaps"].append({
                "description": gap.description[:200],
                "gap_type": gap.gap_type,
                "severity": gap.severity
            })
        print(f"  Success: {len(result.output.gaps)} gaps found")
    else:
        exp["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp)
    
    # Test 3: section_draft for related_work
    print("\n[3] Running section_draft (related_work)...")
    result = backend.execute(
        "section_draft", 
        section="related_work", 
        topic_id=TOPIC_ID,
        outline="1. Traditional budget allocation methods\n2. Reinforcement learning approaches\n3. Cross-channel optimization\n4. Research gaps",
        max_words=800
    )
    exp = {
        "test": "section_draft_related_work",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "word_count": result.output.draft.word_count if result.success else 0,
        "content_preview": result.output.draft.content[:300] if result.success else ""
    }
    if result.success:
        print(f"  Success: {result.output.draft.word_count} words")
    else:
        exp["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp)
    
    # Test 4: consistency_check
    print("\n[4] Running consistency_check...")
    result = backend.execute(
        "consistency_check", 
        topic_id=TOPIC_ID,
        sections=["introduction", "related_work", "methodology"]
    )
    exp = {
        "test": "consistency_check",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "issues_count": len(result.output.issues) if result.success else 0,
        "issues": []
    }
    if result.success and result.output:
        for issue in result.output.issues[:3]:
            exp["issues"].append({
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "description": issue.description[:150]
            })
        print(f"  Success: {len(result.output.issues)} issues found")
    else:
        exp["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp)
    
    # Test 5: baseline_identify (the one that failed before)
    print("\n[5] Running baseline_identify...")
    result = backend.execute(
        "baseline_identify", 
        topic_id=TOPIC_ID,
        focus="cross-channel budget allocation"
    )
    exp = {
        "test": "baseline_identify",
        "success": result.success,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
    }
    if result.success and result.output:
        exp["baselines_count"] = len(result.output.baselines)
        exp["baselines"] = []
        for baseline in result.output.baselines[:3]:
            exp["baselines"].append({
                "name": baseline.name,
                "metrics": baseline.metrics,
                "notes": baseline.notes[:100] if baseline.notes else ""
            })
        print(f"  Success: {len(result.output.baselines)} baselines identified")
    else:
        exp["error"] = result.error
        print(f"  Failed: {result.error}")
    results["experiments"].append(exp)
    
    # Summary
    print("\n" + "=" * 60)
    print("Extended Experiment Summary")
    print("=" * 60)
    total_cost = sum(e.get("cost_usd", 0) for e in results["experiments"])
    success_count = sum(1 for e in results["experiments"] if e.get("success"))
    print(f"Total experiments: {len(results['experiments'])}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(results['experiments']) - success_count}")
    print(f"Total cost: ${total_cost:.4f}")
    
    # Save results
    output_path = "/workspace/research-hub/docs/experiments/phase4_extended.json"
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")
    
    return results

if __name__ == "__main__":
    run_extended_experiments()
