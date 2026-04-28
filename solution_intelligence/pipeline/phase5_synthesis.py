import os
import json
import logging
from tqdm import tqdm
from utils.llm import ask_llm

logger = logging.getLogger(__name__)

def phase5_synthesis(problems_dict: dict, problem_id: str, force_rerun: bool, output_dir: str):
    scores_dir = os.path.join(output_dir, "scores")
    patterns_dir = os.path.join(output_dir, "patterns")
    structured_dir = os.path.join(output_dir, "structured")
    synthesis_dir = os.path.join(output_dir, "synthesis")
    os.makedirs(synthesis_dir, exist_ok=True)

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())

    logger.info("Phase 5: Synthesizing Optimal Solutions...")

    for pid in tqdm(pids_to_process, desc="Processing Synthesis"):
        problem = problems_dict.get(pid)
        if not problem:
            continue
            
        scores_file = os.path.join(scores_dir, f"{pid}.json")
        patterns_file = os.path.join(patterns_dir, f"{pid}.json")

        if not os.path.exists(scores_file) or not os.path.exists(patterns_file):
            logger.warning(f"Missing required Phase 3/4 outputs for {pid}. Skipping Synthesis.")
            continue

        with open(scores_file, 'r', encoding='utf-8') as f:
            scores_data = json.load(f)

        with open(patterns_file, 'r', encoding='utf-8') as f:
            patterns_data = json.load(f)
            
        ranked_clusters = scores_data.get("ranked_clusters", [])
        rare_high_impact_ids = scores_data.get("rare_high_impact", [])
        cluster_patterns = patterns_data.get("cluster_patterns", [])
        contradictions = patterns_data.get("contradictions", [])
        
        # Calculate total solutions involved in this problem
        total_solutions = sum(c.get("size", 0) for c in ranked_clusters) + len(rare_high_impact_ids) # Approximation, or get from clusters file. Actually dominance_pct can also help, but we'll use sum of ranked clusters sizes. Better yet, we can load the summary file.
        
        summary_file = os.path.join(structured_dir, pid, "_summary.json")
        if os.path.exists(summary_file):
            with open(summary_file, 'r', encoding='utf-8') as f:
                total_solutions = len(json.load(f))

        # 1. Select Clusters to Include
        elite_cids = [c["cluster_id"] for c in ranked_clusters if c["tier"] == "ELITE"]
        strong_cids = [c["cluster_id"] for c in ranked_clusters if c["tier"] == "STRONG"]
        
        # Logic: Top 3 ELITE, Top 2 STRONG. If fewer than 2 ELITE, backfill with STRONG
        if len(elite_cids) < 2:
            num_strong = max(2, 5 - len(elite_cids))
            selected_cids = elite_cids + strong_cids[:num_strong]
        else:
            selected_cids = elite_cids[:3] + strong_cids[:2]
        
        # Get their patterns
        selected_patterns = [p for p in cluster_patterns if p.get("cluster_id") in selected_cids]
        
        # 2. Get Rare Ideas
        rare_ideas = []
        for sid in rare_high_impact_ids:
            sol_file = os.path.join(structured_dir, pid, f"{sid}.json")
            if os.path.exists(sol_file):
                with open(sol_file, 'r', encoding='utf-8') as f:
                    rare_ideas.append(json.load(f))

        if not selected_patterns and not rare_ideas:
            logger.warning(f"No elite/strong clusters or rare ideas for {pid}. Cannot synthesize.")
            continue

        # Convert to JSON strings for prompt
        json_elite_cluster_patterns = json.dumps(selected_patterns, indent=2)
        json_rare_ideas_structured = json.dumps(rare_ideas, indent=2)
        json_contradictions = json.dumps(contradictions, indent=2)

        problem_title = problem['title']
        problem_description = problem['description']

        synthesis_prompt = f"""SYSTEM:
You are a world-class solution architect synthesizing the best elements from competition submissions. You must produce an optimal, actionable solution. Return ONLY valid JSON.

USER:
Problem: {problem_title}
Full Problem Description: {problem_description}

You have analyzed {total_solutions} solutions submitted by different teams.
Below are the highest-performing strategy clusters and rare innovative ideas.

TOP ELITE CLUSTERS (proven effective, high adoption):
{json_elite_cluster_patterns}

RARE HIGH-IMPACT IDEAS (low adoption but high novelty):
{json_rare_ideas_structured}

CONTRADICTION MAP (approaches that conflict):
{json_contradictions}

Your task: Create the OPTIMAL solution by:
1. Taking the strongest shared strategies from elite clusters
2. Injecting high-novelty improvements from rare ideas
3. Explicitly resolving contradictions (choose the superior approach and justify)
4. Removing redundant or weak approaches
5. Optimizing for clarity, feasibility, and effectiveness

Return a JSON object with these exact keys:
- "problem_id": string
- "executive_summary": string (3-4 sentences)
- "core_strategy": string (the central approach, 4-6 sentences)
- "implementation_steps": array of objects [{{ "step": integer, "action": string, "rationale": string }}]
- "key_innovations": array of strings (what makes this better than the average submission)
- "tools_and_techniques": array of strings
- "tradeoffs_acknowledged": array of strings
- "judge_score_prediction": {{
    "innovation": integer 1-10,
    "feasibility": integer 1-10,
    "clarity": integer 1-10,
    "rationale": string
  }}"""

        # Call Synthesis LLM
        synthesized_solution = {}
        try:
            synthesized_solution = ask_llm(synthesis_prompt, expect_json=True, force_rerun=force_rerun)
            if isinstance(synthesized_solution, dict):
                synthesized_solution["problem_id"] = pid
        except Exception as e:
            logger.error(f"Failed synthesis LLM call for {pid}: {e}")
            continue

        # Judge Evaluation Prompt
        judge_prompt = f"""SYSTEM: You are a strict competition judge. Return ONLY valid JSON.

USER:
Evaluate this synthesized solution for problem "{problem_title}" as a competition judge would.

Solution:
{json.dumps(synthesized_solution, indent=2)}

Return a JSON object with:
- "overall_score": integer 1-100
- "innovation_score": integer 1-10
- "feasibility_score": integer 1-10
- "clarity_score": integer 1-10
- "strengths": array of strings
- "weaknesses": array of strings
- "improvement_suggestions": array of strings
- "would_win": boolean
- "reasoning": string"""

        judge_evaluation = {}
        try:
            judge_evaluation = ask_llm(judge_prompt, expect_json=True, force_rerun=force_rerun)
        except Exception as e:
            logger.error(f"Failed judge evaluation LLM call for {pid}: {e}")
            
        # 3. Save Output
        output_data = {
            "problem_id": pid,
            "synthesized_solution": synthesized_solution,
            "judge_evaluation": judge_evaluation
        }

        with open(os.path.join(synthesis_dir, f"{pid}.json"), 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)

    logger.info("Phase 5 Completed.")