import os
import json
import logging
from collections import Counter
from statistics import mean
from tqdm import tqdm
from utils.llm import ask_llm

logger = logging.getLogger(__name__)

def phase6_meta(problems_dict: dict, problem_id: str, force_rerun: bool, output_dir: str):
    structured_dir = os.path.join(output_dir, "structured")
    clusters_dir = os.path.join(output_dir, "clusters")
    scores_dir = os.path.join(output_dir, "scores")
    patterns_dir = os.path.join(output_dir, "patterns")
    synthesis_dir = os.path.join(output_dir, "synthesis")
    reports_dir = os.path.join(output_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())

    logger.info("Phase 6: Generating Meta Reports...")

    for pid in tqdm(pids_to_process, desc="Generating Reports"):
        problem = problems_dict.get(pid)
        if not problem:
            continue

        # Load all required files
        req_files = {
            "summary": os.path.join(structured_dir, pid, "_summary.json"),
            "clusters": os.path.join(clusters_dir, f"{pid}.json"),
            "scores": os.path.join(scores_dir, f"{pid}.json"),
            "patterns": os.path.join(patterns_dir, f"{pid}.json"),
            "synthesis": os.path.join(synthesis_dir, f"{pid}.json")
        }

        missing = [name for name, path in req_files.items() if not os.path.exists(path)]
        if missing:
            logger.warning(f"Problem {pid} missing outputs from previous phases: {missing}. Skipping.")
            continue

        with open(req_files["summary"], 'r', encoding='utf-8') as f:
            all_structured = json.load(f)
        with open(req_files["clusters"], 'r', encoding='utf-8') as f:
            cluster_data = json.load(f)
        with open(req_files["scores"], 'r', encoding='utf-8') as f:
            scores_data = json.load(f)
        with open(req_files["patterns"], 'r', encoding='utf-8') as f:
            patterns_data = json.load(f)
        with open(req_files["synthesis"], 'r', encoding='utf-8') as f:
            synthesis_data = json.load(f)

        # Remove parsing errors
        valid_structured = [s for s in all_structured if not s.get("parse_error")]
        if not valid_structured:
            logger.warning(f"No valid structured solutions to report on for {pid}. Skipping.")
            continue

        # Computed metrics
        total_solutions = len(valid_structured)
        n_clusters = cluster_data.get("n_clusters", 0)
        n_noise = cluster_data.get("n_noise", 0)
        avg_novelty_global = mean([s.get("novelty_score", 0) for s in valid_structured])
        avg_quality_global = mean([s.get("quality_score", 0) for s in valid_structured])
        
        techs = []
        for s in valid_structured:
            techs.extend(s.get("tools_and_techniques", []))
        tech_frequency = Counter(techs)
        most_common_techs = tech_frequency.most_common(10)

        # Prepare LLM Prompt
        ranked_clusters = scores_data.get("ranked_clusters", [])
        cluster_patterns = patterns_data.get("cluster_patterns", [])
        top_3_patterns = cluster_patterns[:3]
        
        all_weaknesses = []
        for s in valid_structured:
            all_weaknesses.extend(s.get("weaknesses", []))
            
        json_ranked_clusters_with_tiers = json.dumps(ranked_clusters, indent=2)
        json_top_3_cluster_patterns = json.dumps(top_3_patterns, indent=2)
        comma_separated_weaknesses = ", ".join(all_weaknesses[:200]) # Cap to avoid context overflow

        prompt = f"""SYSTEM: You are a data analyst producing a competition intelligence report. Return ONLY valid JSON.

USER:
Problem: {problem['title']}
Total solutions analyzed: {total_solutions}
Total clusters identified: {n_clusters}

Cluster breakdown:
{json_ranked_clusters_with_tiers}

Top patterns extracted:
{json_top_3_cluster_patterns}

Common weaknesses found across solutions:
{comma_separated_weaknesses}

Produce a JSON meta-analysis report with these exact keys:
- "dominant_approaches": array of {{"approach": string, "pct_adoption": float, "effectiveness": string}}
- "top_3_mistakes": array of strings (most common errors across all solutions)
- "innovation_gaps": array of strings (unexplored angles that could have won)
- "approach_distribution": {{"elite_pct": float, "strong_pct": float, "average_pct": float, "weak_pct": float}}
- "rare_idea_summary": string (describe the outlier/rare ideas and their potential)
- "key_insight": string (the single most important takeaway from analyzing all solutions)"""

        try:
            meta_report = ask_llm(prompt, expect_json=True, force_rerun=force_rerun)
        except Exception as e:
            logger.error(f"Failed to generate meta report for {pid}: {e}")
            continue

        # Save the pure JSON meta (optional but good for debugging/C6)
        with open(os.path.join(reports_dir, f"{pid}_meta.json"), 'w', encoding='utf-8') as f:
            json.dump(meta_report, f, indent=2)

        # Compile Markdown Report
        syn = synthesis_data.get("synthesized_solution", {})
        judge = synthesis_data.get("judge_evaluation", {})

        md = f"# Intelligence Report: {problem['title']}\n\n"
        
        md += "## Summary Statistics\n"
        md += f"| Metric | Value |\n"
        md += f"|---|---|\n"
        md += f"| Total Solutions | {total_solutions} |\n"
        md += f"| Number of Clusters | {n_clusters} |\n"
        md += f"| Noise/Outliers | {n_noise} |\n"
        md += f"| Global Avg Novelty | {avg_novelty_global:.2f}/10 |\n"
        md += f"| Global Avg Quality | {avg_quality_global:.2f}/10 |\n"
        md += "\n"
        
        md += "### Top 10 Tools & Techniques\n"
        for t, c in most_common_techs:
            md += f"- **{t}**: {c} uses\n"
        md += "\n"

        md += "## Dominant Approaches\n"
        for da in meta_report.get("dominant_approaches", []):
            md += f"- **{da.get('approach', '')}** (Adoption: {da.get('pct_adoption', 0)}%)\n"
            md += f"  *Effectiveness*: {da.get('effectiveness', '')}\n"
        md += "\n"

        md += "## Key Patterns Found\n"
        md += f"**Key Insight**: {meta_report.get('key_insight', '')}\n\n"
        md += f"**Approach Distribution**:\n"
        dist = meta_report.get("approach_distribution", {})
        md += f"- Elite: {dist.get('elite_pct', 0)}%\n"
        md += f"- Strong: {dist.get('strong_pct', 0)}%\n"
        md += f"- Average: {dist.get('average_pct', 0)}%\n"
        md += f"- Weak: {dist.get('weak_pct', 0)}%\n\n"

        md += "## Common Mistakes\n"
        for m in meta_report.get("top_3_mistakes", []):
            md += f"- {m}\n"
        md += "\n"

        md += "## Innovation Gaps\n"
        for g in meta_report.get("innovation_gaps", []):
            md += f"- {g}\n"
        md += "\n"

        md += "## Rare High-Impact Ideas\n"
        md += f"{meta_report.get('rare_idea_summary', '')}\n\n"

        md += "## 🏆 Synthesized Optimal Solution\n"
        md += f"### Executive Summary\n{syn.get('executive_summary', '')}\n\n"
        md += f"### Core Strategy\n{syn.get('core_strategy', '')}\n\n"
        md += "### Implementation Steps\n"
        for step in syn.get("implementation_steps", []):
            md += f"{step.get('step', '')}. **{step.get('action', '')}**: {step.get('rationale', '')}\n"
        md += "\n"
        
        md += "### Key Innovations\n"
        for ki in syn.get("key_innovations", []):
            md += f"- {ki}\n"
        md += "\n"
        
        md += "## Judge Simulation Score\n"
        md += f"- **Overall Score**: {judge.get('overall_score', '')}/100\n"
        md += f"- **Innovation**: {judge.get('innovation_score', '')}/10\n"
        md += f"- **Feasibility**: {judge.get('feasibility_score', '')}/10\n"
        md += f"- **Clarity**: {judge.get('clarity_score', '')}/10\n"
        md += f"- **Would Win?**: {'Yes' if judge.get('would_win') else 'No'}\n\n"
        md += f"**Reasoning**: {judge.get('reasoning', '')}\n\n"
        
        md += "### Judge Strengths\n"
        for s in judge.get("strengths", []):
            md += f"- {s}\n"
        md += "\n"
        
        md += "### Judge Weaknesses & Improvements\n"
        for w in judge.get("weaknesses", []):
            md += f"- Weakness: {w}\n"
        for i in judge.get("improvement_suggestions", []):
            md += f"- Suggested Fix: {i}\n"
        md += "\n"

        md += "---\n"
        md += "## Methodology Note\n"
        md += "Pipeline: Structuring → Embedding → Clustering (HDBSCAN) → Scoring → Pattern Extraction → Synthesis\n"
        md += "Model: Mistral 7B via Ollama\n"

        report_path = os.path.join(reports_dir, f"{pid}_report.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(md)

        # 5. Build Machine-Readable Summary payload
        machine_summary = {
            "problem_id": pid,
            "pipeline_summary_stats": {
                "total_solutions": total_solutions,
                "n_clusters": n_clusters,
                "n_noise": n_noise,
                "avg_novelty_global": avg_novelty_global,
                "avg_quality_global": avg_quality_global
            },
            "meta_analysis": meta_report,
            "clusters": ranked_clusters,
            "synthesized_solution": syn,
            "judge_evaluation": judge
        }

        with open(os.path.join(reports_dir, f"{pid}_summary.json"), 'w', encoding='utf-8') as f:
            json.dump(machine_summary, f, indent=2)

    logger.info("Phase 6 Completed.")