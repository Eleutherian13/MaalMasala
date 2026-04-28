import os
import json
import logging
from tqdm import tqdm
from utils.llm import ask_llm

logger = logging.getLogger(__name__)

def phase4_patterns(problems_dict: dict, problem_id: str, force_rerun: bool, output_dir: str):
    scores_dir = os.path.join(output_dir, "scores")
    structured_dir = os.path.join(output_dir, "structured")
    patterns_dir = os.path.join(output_dir, "patterns")
    os.makedirs(patterns_dir, exist_ok=True)

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())

    logger.info("Phase 4: Extracting Winning Patterns & Contradictions...")

    for pid in tqdm(pids_to_process, desc="Processing Patterns"):
        problem = problems_dict.get(pid)
        if not problem:
            continue
            
        scores_file = os.path.join(scores_dir, f"{pid}.json")
        summary_file = os.path.join(structured_dir, pid, "_summary.json")

        if not os.path.exists(scores_file) or not os.path.exists(summary_file):
            logger.warning(f"Missing required Phase 1/3 outputs for {pid}. Skipping Phase 4.")
            continue

        with open(scores_file, 'r', encoding='utf-8') as f:
            scores_data = json.load(f)

        with open(summary_file, 'r', encoding='utf-8') as f:
            structured_data = json.load(f)

        sol_map = {s["solution_id"]: s for s in structured_data if not s.get("parse_error")}

        cluster_patterns = []

        # 1. Extract Patterns per ELITE / STRONG cluster
        ranked_clusters = scores_data.get("ranked_clusters", [])
        target_clusters = [c for c in ranked_clusters if c["tier"] in ["ELITE", "STRONG"]]

        if not target_clusters:
            logger.info(f"Problem {pid}: No ELITE or STRONG clusters found.")
        
        for cluster in target_clusters:
            cid = cluster["cluster_id"]
            
            # We need to find the solution_ids for this cluster. 
            # They are in the phase 2 clusters output, or we can read them from phase2 directly...
            # Wait, phase 3 output doesn't contain solution_ids in the ranked_clusters by default (based on previous schema).
            # Let's read from phase 2 clusters output.
            cluster_file = os.path.join(output_dir, "clusters", f"{pid}.json")
            if not os.path.exists(cluster_file):
                logger.error(f"Missing phase 2 cluster file for {pid}. Skipping pattern extraction for cluster {cid}.")
                continue
                
            with open(cluster_file, 'r', encoding='utf-8') as cf:
                cluster_data_orig = json.load(cf)
                
            c_orig = next((c for c in cluster_data_orig.get("clusters", []) if c["cluster_id"] == cid), None)
            if not c_orig:
                continue
                
            c_solutions = []
            for sid in c_orig["solution_ids"]:
                if sid in sol_map:
                    c_solutions.append(sol_map[sid])

            if not c_solutions:
                continue

            n = len(c_solutions)
            batch_json = json.dumps(c_solutions, indent=2)

            prompt = f"""SYSTEM:
You are a competition strategy analyst. You receive a cluster of similar solutions to the same problem. Your job is to extract the shared winning patterns. Return ONLY valid JSON. No preamble, no markdown.

USER:
Problem: {problem['title']}
Problem Description: {problem['description']}

The following {n} solutions were grouped together as sharing similar approaches.
Cluster tier: {cluster['tier']} | Avg quality: {cluster['avg_quality']}/10 | Avg novelty: {cluster['avg_novelty']}/10

Solutions in this cluster:
{batch_json}

Return a JSON object with these exact keys:
- "cluster_id": integer
- "shared_strategy": string (2-3 sentences: the core shared approach)
- "why_it_works": string (2-3 sentences: mechanism of effectiveness)
- "key_techniques": array of strings (the techniques that appear across multiple solutions)
- "distinguishing_factors": string (what separates the better solutions in this cluster)
- "limitations": string (shared weaknesses or blind spots in this cluster)
- "contradiction_with": array of strings (names/ids of clusters this approach conflicts with, if any)"""

            try:
                pattern = ask_llm(prompt, expect_json=True, force_rerun=force_rerun)
                # Ensure cluster_id is present and correct
                if isinstance(pattern, dict):
                    pattern["cluster_id"] = cid
                    cluster_patterns.append(pattern)
            except Exception as e:
                logger.error(f"Failed to extract pattern for cluster {cid} in problem {pid}: {e}")

        # 2. Contradiction Detection
        contradictions = []
        if len(cluster_patterns) > 1:
            n_patterns = len(cluster_patterns)
            patterns_json = json.dumps(cluster_patterns, indent=2)
            
            contradiction_prompt = f"""SYSTEM: You are a competition analyst. Return ONLY valid JSON array. No preamble, no markdown.

USER:
Given these {n_patterns} extracted cluster strategies for problem "{problem['title']}":
{patterns_json}

Identify pairs of strategies that fundamentally contradict each other.
Return a JSON array of objects, each with:
- "cluster_a": integer
- "cluster_b": integer  
- "contradiction": string (why these approaches conflict)
- "resolution": string (how to reconcile or choose between them)"""

            try:
                contradictions = ask_llm(contradiction_prompt, expect_json=True, force_rerun=force_rerun)
                if not isinstance(contradictions, list):
                    logger.warning(f"Contradictions LLM returned {type(contradictions).__name__}, expected list. Wrapping.")
                    if isinstance(contradictions, dict):
                        contradictions = [contradictions]
                    else:
                        contradictions = []
            except Exception as e:
                logger.error(f"Failed to extract contradictions for problem {pid}: {e}")

        # 3. Save Output
        output_data = {
            "problem_id": pid,
            "cluster_patterns": cluster_patterns,
            "contradictions": contradictions
        }

        with open(os.path.join(patterns_dir, f"{pid}.json"), 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)

    logger.info("Phase 4 Completed.")
