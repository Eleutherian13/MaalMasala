import os
import json
import logging
import hashlib
import re
import math
from typing import Optional
from config import SCORE_WEIGHTS
from utils.llm import ask_llm
from utils.schema import SolutionExtraction, SolutionScores, Penalty, FinalEvaluation
from pydantic import ValidationError

logger = logging.getLogger(__name__)

def get_llm_scores(extraction: SolutionExtraction) -> Optional[SolutionScores]:
    """Helper function to fetch bounded 1-5 scores from LLM with strict rules."""
    cache_key = hashlib.sha256(("score_" + extraction.model_dump_json()).encode('utf-8')).hexdigest()
    cache_dir = "cache/scores"
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{cache_key}.json")
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return SolutionScores(**json.load(f))
        except Exception:
            pass

    prompt = f"""SYSTEM:
You are a strict scoring engine. You ONLY output a valid JSON object. No explanation, no extra text.
Evaluate the extracted solution features and assign integer scores (1-5) for each criterion.
1 = Poor/Non-existent, 5 = Excellent/Highly evident.

Criteria Definitions:
- problem_fit: alignment with problem requirements
- feasibility: implementation realism
- optimization: efficiency improvements
- completeness: pipeline coverage
- scalability: large-scale viability
- novelty: uniqueness
- clarity: structure and readability

Output JSON strictly matching this schema:
{{
  "problem_fit": int (1-5),
  "feasibility": int (1-5),
  "optimization": int (1-5),
  "completeness": int (1-5),
  "scalability": int (1-5),
  "novelty": int (1-5),
  "clarity": int (1-5)
}}

USER:
Solution Features:
{extraction.model_dump_json(indent=2)}
"""

    for _ in range(3):
        try:
            response = ask_llm(prompt, expect_json=True, force_rerun=True)
            cleaned = re.sub(r'```json\s*|\s*```', '', response)
            cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
            parsed = json.loads(cleaned)
            scores = SolutionScores(**parsed)
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(scores.model_dump_json())
            return scores
        except Exception:
            continue
            
    return None

def score_solution(extraction: SolutionExtraction) -> Optional[FinalEvaluation]:
    """Converts SolutionExtraction to a strict FinalEvaluation architecture."""
    scores = get_llm_scores(extraction)
    if not scores:
        return None
        
    # 3. Deterministic Computation
    base_score = (
        0.25 * scores.problem_fit +
        0.20 * scores.feasibility +
        0.20 * scores.optimization +
        0.15 * scores.completeness +
        0.10 * scores.scalability +
        0.05 * scores.novelty +
        0.05 * scores.clarity
    ) * 20
    
    # 4. Penalty Logic
    missing_core = 20 if (scores.feasibility <= 2 or scores.completeness <= 2) else 0
    overclaim = 10 if (len(extraction.optimization_claims) > 0 and scores.optimization <= 2) else 0
    penalties = Penalty(missing_core=missing_core, overclaim=overclaim)
    
    # 5. Final Score
    final_score = max(0.0, min(100.0, base_score - missing_core - overclaim))
    
    # 6. Confidence
    confidence = max(0.3, 1.0 - 0.1 * len(extraction.missing_components))
    
    # 7. Reasoning (Deterministic construction)
    reasoning_parts = [f"Base score computed at {base_score:.1f}/100."]
    if missing_core > 0:
        reasoning_parts.append("Missing core principles penalty applied (-20).")
    if overclaim > 0:
        reasoning_parts.append("Overclaim penalty applied (-10).")
    if missing_core == 0 and overclaim == 0:
        reasoning_parts.append("No penalties applied.")
    reasoning_parts.append(f"Confidence reduced to {confidence:.2f} due to {len(extraction.missing_components)} missing components.")
    
    reasoning = " ".join(reasoning_parts)[:300]
    
    return FinalEvaluation(
        scores=scores,
        penalties=penalties,
        final_score=final_score,
        confidence=confidence,
        reasoning=reasoning
    )

def phase3_score(problem_id: str, output_dir: str):
    cluster_dir = os.path.join(output_dir, "clusters")
    structured_dir = os.path.join(output_dir, "structured")
    scores_dir = os.path.join(output_dir, "scores")
    os.makedirs(scores_dir, exist_ok=True)

    # Process specific problem_id or all available clusters
    pids = [problem_id] if problem_id else [f.replace('.json', '') for f in os.listdir(cluster_dir) if f.endswith('.json')]

    if not pids:
        logger.warning("No clusters found for Phase 3.")
        return

    logger.info("Phase 3: Starting Cluster Scoring and Synthesis Prep...")

    for pid in pids:
        cluster_file = os.path.join(cluster_dir, f"{pid}.json")
        summary_file = os.path.join(structured_dir, pid, "_summary.json")

        if not os.path.exists(cluster_file) or not os.path.exists(summary_file):
            logger.warning(f"Missing required Phase 1/2 outputs for {pid}. Skipping.")
            continue

        with open(cluster_file, 'r', encoding='utf-8') as f:
            cluster_data = json.load(f)

        with open(summary_file, 'r', encoding='utf-8') as f:
            structured_data = json.load(f)

        sol_map = {s["solution_id"]: s for s in structured_data if not s.get("parse_error")}

        total_solutions = sum(c["size"] for c in cluster_data.get("clusters", [])) + cluster_data.get("n_noise", 0)
        if total_solutions == 0:
            logger.warning(f"No solutions found in clusters for {pid}. Skipping.")
            continue

        # Clusters already have their scores and tiers from Phase 2
        ranked_clusters = []
        for c in cluster_data.get("clusters", []):
            avg_score = c.get("avg_score", 0)
            
            ranked_clusters.append({
                "cluster_id": c["cluster_id"],
                "tier": c.get("tier", "BASELINE"),
                "cluster_score": avg_score / 100.0, # Normalizing to 0-1 for backward compat
                "avg_score": avg_score,
                "max_score": c.get("max_score", 0),
                "variance": c.get("variance", 0),
                "size": c["size"],
                "dominance_pct": round(c["size"] / total_solutions, 4)
            })

        # Sort descending by normalized score
        ranked_clusters.sort(key=lambda x: x["cluster_score"], reverse=True)

        # 3. Process Noise Solutions for "Rare High Impact"
        rare_high_impact = []
        for noise_sid in cluster_data.get("noise_solutions", []):
            sol = sol_map.get(noise_sid)
            if sol:
                try:
                    s_extraction = SolutionExtraction(**sol)
                    s_evaluation = score_solution(s_extraction)
                    if s_evaluation and s_evaluation.final_score > 75:
                        rare_high_impact.append(noise_sid)
                except Exception:
                    pass

        # 4. Save Output
        output_data = {
            "problem_id": pid,
            "ranked_clusters": ranked_clusters,
            "rare_high_impact": rare_high_impact
        }

        with open(os.path.join(scores_dir, f"{pid}.json"), 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)

    logger.info("Phase 3 Completed.")
