import os
import json
import logging
from collections import defaultdict
from typing import Dict, List, Set
from tqdm import tqdm

from utils.schema import SolutionExtraction
from pipeline.phase3_score import score_solution

logger = logging.getLogger(__name__)

def phase4_patterns(problems_dict: dict, problem_id: str, force_rerun: bool, output_dir: str):
    scores_dir = os.path.join(output_dir, "scores")
    structured_dir = os.path.join(output_dir, "structured")
    patterns_dir = os.path.join(output_dir, "patterns")
    os.makedirs(patterns_dir, exist_ok=True)

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())

    logger.info("Phase 4: Extracting Winning Patterns & Contradictions (Deterministic)...")

    for pid in tqdm(pids_to_process, desc="Processing Patterns"):
        problem = problems_dict.get(pid)
        if not problem:
            continue
            
        cluster_file = os.path.join(output_dir, "clusters", f"{pid}.json")
        summary_file = os.path.join(structured_dir, pid, "_summary.json")

        if not os.path.exists(cluster_file) or not os.path.exists(summary_file):
            logger.warning(f"Missing required Phase 2/structured outputs for {pid}. Skipping Phase 4.")
            continue

        with open(cluster_file, 'r', encoding='utf-8') as f:
            cluster_data = json.load(f)

        with open(summary_file, 'r', encoding='utf-8') as f:
            structured_data = json.load(f)

        # 1. Aggregate features & Scores
        feature_scores: Dict[str, Dict[str, float]] = {
            "tech_stack": defaultdict(float),
            "key_steps": defaultdict(float),
            "approach_type": defaultdict(float)
        }
        
        feature_counts: Dict[str, Dict[str, int]] = {
            "tech_stack": defaultdict(int),
            "key_steps": defaultdict(int),
            "approach_type": defaultdict(int)
        }
        
        # Track which clusters features appear in
        feature_clusters: Dict[str, Dict[str, Set[int]]] = {
            "tech_stack": defaultdict(set),
            "key_steps": defaultdict(set),
            "approach_type": defaultdict(set)
        }
        
        cluster_tiers = {}
        for c in cluster_data.get("clusters", []):
            cluster_tiers[c["cluster_id"]] = c.get("tier", "BASELINE")

        sol_map = {}
        for s in structured_data:
            if s.get("parse_error"):
                continue
            
            try:
                extraction = SolutionExtraction(**s)
                eval_obj = score_solution(extraction)
                if eval_obj:
                    sol_map[s["solution_id"]] = {
                        "extraction": extraction,
                        "score": eval_obj.final_score
                    }
            except Exception:
                continue

        if not sol_map:
            logger.warning(f"No valid scored solutions for {pid}.")
            continue

        # Reverse map solution to its cluster_id
        sol_to_cluster = {}
        for c in cluster_data.get("clusters", []):
            cid = c["cluster_id"]
            for sid in c["solution_ids"]:
                sol_to_cluster[sid] = cid

        for sid, data in sol_map.items():
            ext = data["extraction"]
            score = data["score"]
            cid = sol_to_cluster.get(sid, -1) # -1 is noise
            
            # Helper to tally
            def tally(category: str, items: List[str]):
                for item in items:
                    item_clean = item.strip().lower()
                    if not item_clean:
                        continue
                    feature_scores[category][item_clean] += score
                    feature_counts[category][item_clean] += 1
                    if cid != -1:
                        feature_clusters[category][item_clean].add(cid)

            tally("tech_stack", ext.tech_stack)
            tally("key_steps", ext.key_steps)
            if ext.approach_type:
                tally("approach_type", [ext.approach_type])

        # 2. Compute winning, anti, tradeoffs
        winning_patterns = []
        anti_patterns = []
        tradeoffs = []
        
        # Criteria parameters
        min_occurrences = 2

        for category, items in feature_scores.items():
            for item, total_score in items.items():
                count = feature_counts[category][item]
                if count < min_occurrences:
                    continue
                    
                avg_weighted_score = total_score / count
                clusters_present = feature_clusters[category][item]
                
                # Check tiers of clusters this feature is in
                tiers_present = {cluster_tiers.get(c, "BASELINE") for c in clusters_present}
                
                feature_record = {
                    "feature": item,
                    "category": category,
                    "count": count,
                    "avg_weighted_score": round(avg_weighted_score, 2),
                    "clusters": list(clusters_present)
                }

                if avg_weighted_score > 75.0 and ("ELITE" in tiers_present or "STRONG" in tiers_present):
                    winning_patterns.append(feature_record)
                elif avg_weighted_score < 50.0 and "ELITE" not in tiers_present:
                    anti_patterns.append(feature_record)
                    
                # Tradeoffs: Appears in both high and low performing clusters
                if "ELITE" in tiers_present and len(tiers_present) > 1 and "BASELINE" in tiers_present:
                    tradeoffs.append(feature_record)

        # Sort descending by score
        winning_patterns.sort(key=lambda x: x["avg_weighted_score"], reverse=True)
        anti_patterns.sort(key=lambda x: x["avg_weighted_score"])
        tradeoffs.sort(key=lambda x: x["avg_weighted_score"], reverse=True)

        # 4. Output
        output_data = {
            "problem_id": pid,
            "winning_patterns": winning_patterns,
            "anti_patterns": anti_patterns,
            "tradeoffs": tradeoffs
        }

        with open(os.path.join(patterns_dir, f"{pid}.json"), 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)

    logger.info("Phase 4 Completed.")
