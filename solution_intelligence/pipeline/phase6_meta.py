import os
import json
import logging
from collections import Counter
from statistics import mean
from typing import Dict, Any, List
from tqdm import tqdm
from utils.schema import FinalEvaluation, SolutionExtraction
from pipeline.phase3_score import score_solution

logger = logging.getLogger(__name__)

def generate_markdown_report(pid: str, title: str, stats: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Deterministically generates a markdown report without LLM randomness."""
    md = f"# Intelligence Report: {title} ({pid})\n\n"
    
    # 1. Summary Statistics
    md += "## Executive Summary\n"
    md += f"- **Total Valid Solutions**: {stats['total_solutions']}\n"
    md += f"- **Clusters Identified**: {stats['n_clusters']}\n"
    md += f"- **Average Final Score**: {stats['avg_score']:.2f}/100\n"
    md += f"- **Highest Score**: {stats['max_score']:.2f}/100\n\n"
    
    # 2. Top Solutions Breakdown
    md += "## Top Performing Solutions\n\n"
    for i, sol in enumerate(meta['top_solutions'][:5], 1):
        ext = sol['extraction']
        eval_data = sol['evaluation']
        
        md += f"### {i}. Solution ID: {sol['solution_id']}\n"
        md += f"**Final Score**: {eval_data.final_score:.2f}/100 (Confidence: {eval_data.confidence:.2f})\n"
        md += f"**Approach**: {ext.approach_type.upper()}\n"
        md += f"**Summary**: {ext.summary}\n\n"
        
        md += "**Score Breakdown:**\n"
        md += f"- FIT: {eval_data.scores.problem_fit}/5 | FEA: {eval_data.scores.feasibility}/5 | OPT: {eval_data.scores.optimization}/5\n"
        md += f"- COM: {eval_data.scores.completeness}/5 | SCA: {eval_data.scores.scalability}/5 | NOV: {eval_data.scores.novelty}/5 | CLA: {eval_data.scores.clarity}/5\n\n"
        
        if eval_data.penalties.missing_core > 0 or eval_data.penalties.overclaim > 0:
            md += "**Penalties Applied:**\n"
            if eval_data.penalties.missing_core > 0:
                md += f"- Missing Core Requirements: -{eval_data.penalties.missing_core}\n"
            if eval_data.penalties.overclaim > 0:
                md += f"- Overclaimed Optimizations: -{eval_data.penalties.overclaim}\n"
            md += "\n"
            
        md += f"**Reasoning**: {eval_data.reasoning}\n\n"

    # 3. Cluster Insights
    md += "## Cluster Analysis (ELITE & STRONG)\n\n"
    for c in meta['target_clusters']:
        md += f"### Cluster {c['cluster_id']} ({c['tier']})\n"
        md += f"- **Size**: {c['size']} solutions ({c['dominance_pct'] * 100:.1f}%)\n"
        md += f"- **Average Score**: {c['avg_score']:.2f}/100\n"
        md += f"- **Max Score**: {c['max_score']:.2f}/100\n\n"

    # 4. Synthesized Recommendation
    md += "## Final Recommendation (Synthesized Optimal Solution)\n\n"
    synth = meta['synthesis']
    md += f"**Architecture**: {synth.get('architecture', 'N/A')}\n\n"
    
    md += "**Pipeline:**\n"
    for step in synth.get('pipeline', []):
        md += f"{step.get('step', 0)}. **{step.get('name', '')}**: {step.get('action', '')}\n"
        md += f"   *Validation*: {step.get('validation', '')}\n"
    md += "\n"
    
    md += "**Optimizations:**\n"
    for opt in synth.get('optimizations', []):
        md += f"- {opt.get('target', '')}: {opt.get('mechanism', '')} -> *{opt.get('impact', '')}*\n"
    md += "\n"
    
    md += f"**Justification**: {synth.get('justification', 'N/A')}\n"
    
    return md

def phase6_meta(problems_dict: dict, problem_id: str, force_rerun: bool, output_dir: str):
    structured_dir = os.path.join(output_dir, "structured")
    clusters_dir = os.path.join(output_dir, "clusters")
    scores_dir = os.path.join(output_dir, "scores")
    patterns_dir = os.path.join(output_dir, "patterns")
    synthesis_dir = os.path.join(output_dir, "synthesis")
    reports_dir = os.path.join(output_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    pids_to_process = [problem_id] if problem_id else list(problems_dict.keys())

    logger.info("Phase 6: Generating Meta Reports (Deterministic)...")

    for pid in tqdm(pids_to_process, desc="Generating Reports"):
        problem = problems_dict.get(pid)
        if not problem:
            continue

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

        # 1. Evaluate top solutions with strict schemas
        valid_solutions = []
        all_final_scores = []
        
        for s in all_structured:
            if s.get("parse_error"):
                continue
            try:
                ext = SolutionExtraction(**s)
                eval_data = score_solution(ext)
                if eval_data:
                    valid_solutions.append({
                        "solution_id": s["solution_id"],
                        "extraction": ext,
                        "evaluation": eval_data
                    })
                    all_final_scores.append(eval_data.final_score)
            except Exception:
                continue
                
        if not valid_solutions:
            logger.warning(f"No valid scored solutions to report on for {pid}. Skipping.")
            continue
            
        valid_solutions.sort(key=lambda x: x["evaluation"].final_score, reverse=True)
        top_solutions = valid_solutions[:10]

        # 2. Stats
        stats = {
            "total_solutions": len(valid_solutions),
            "n_clusters": cluster_data.get("n_clusters", 0),
            "n_noise": cluster_data.get("n_noise", 0),
            "avg_score": float(mean(all_final_scores)) if all_final_scores else 0.0,
            "max_score": float(max(all_final_scores)) if all_final_scores else 0.0
        }

        # 3. Target Clusters (ELITE / STRONG)
        ranked_clusters = scores_data.get("ranked_clusters", [])
        target_clusters = [c for c in ranked_clusters if c["tier"] in ["ELITE", "STRONG"]]

        # 4. Build Meta Object
        meta_dict = {
            "problem_id": pid,
            "stats": stats,
            "top_solutions": [
                {
                    "solution_id": s["solution_id"],
                    "extraction": s["extraction"].model_dump(),
                    "evaluation": s["evaluation"].model_dump()
                } for s in top_solutions
            ],
            "target_clusters": target_clusters,
            "synthesis": synthesis_data
        }

        # Save JSON
        json_path = os.path.join(reports_dir, f"{pid}_report.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(meta_dict, f, indent=2)

        # Prepare pure objects for markdown rendering
        meta_render = {
            "top_solutions": top_solutions, # Keeps Pydantic objects for property access
            "target_clusters": target_clusters,
            "synthesis": synthesis_data
        }

        # Save Markdown
        md_content = generate_markdown_report(pid, problem['title'], stats, meta_render)
        md_path = os.path.join(reports_dir, f"{pid}_report.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

    logger.info("Phase 6 Completed.")