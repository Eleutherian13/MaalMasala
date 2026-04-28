import os
import json
import logging
import math
from config import SCORE_WEIGHTS

logger = logging.getLogger(__name__)

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

        # Create quick lookup for structured solutions (needed for noise evaluation)
        sol_map = {s["solution_id"]: s for s in structured_data if not s.get("parse_error")}

        total_solutions = sum(c["size"] for c in cluster_data.get("clusters", [])) + cluster_data.get("n_noise", 0)
        if total_solutions == 0:
            logger.warning(f"No solutions found in clusters for {pid}. Skipping.")
            continue

        # 1. Calculate raw scores
        raw_clusters = []
        raw_scores = []
        for c in cluster_data.get("clusters", []):
            avg_q = c["avg_quality"]
            avg_n = c["avg_novelty"]
            size = c["size"]
            
            raw_score = (SCORE_WEIGHTS["quality"] * avg_q) + \
                        (SCORE_WEIGHTS["novelty"] * avg_n) + \
                        (SCORE_WEIGHTS["size_log"] * math.log(size + 1))
            
            raw_scores.append(raw_score)
            raw_clusters.append({
                "cluster_id": c["cluster_id"],
                "avg_quality": avg_q,
                "avg_novelty": avg_n,
                "size": size,
                "dominance_pct": round(size / total_solutions, 4),
                "raw_score": raw_score
            })

        # 2. Normalize and assign tiers
        min_score = min(raw_scores) if raw_scores else 0
        max_score = max(raw_scores) if raw_scores else 0
        score_range = max_score - min_score if max_score > min_score else 1

        ranked_clusters = []
        for rc in raw_clusters:
            norm_score = (rc["raw_score"] - min_score) / score_range if raw_scores else 0
            norm_score = round(norm_score, 4)
            
            if norm_score >= 0.75:
                tier = "ELITE"
            elif norm_score >= 0.50:
                tier = "STRONG"
            elif norm_score >= 0.25:
                tier = "AVERAGE"
            else:
                tier = "WEAK"
                
            ranked_clusters.append({
                "cluster_id": rc["cluster_id"],
                "tier": tier,
                "cluster_score": norm_score,
                "avg_quality": round(rc["avg_quality"], 2),
                "avg_novelty": round(rc["avg_novelty"], 2),
                "size": rc["size"],
                "dominance_pct": rc["dominance_pct"]
            })

        # Sort descending by normalized score
        ranked_clusters.sort(key=lambda x: x["cluster_score"], reverse=True)

        # 3. Process Noise Solutions for "Rare High Impact"
        rare_high_impact = []
        for noise_sid in cluster_data.get("noise_solutions", []):
            sol = sol_map.get(noise_sid)
            if sol and sol.get("novelty_score", 0) >= 8:
                rare_high_impact.append(noise_sid)

        # 4. Save Output
        output_data = {
            "problem_id": pid,
            "ranked_clusters": ranked_clusters,
            "rare_high_impact": rare_high_impact
        }

        with open(os.path.join(scores_dir, f"{pid}.json"), 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)

    logger.info("Phase 3 Completed.")
