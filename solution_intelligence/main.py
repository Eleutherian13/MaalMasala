import argparse
import sys
import logging
from config import *
from utils.schema import validate_inputs
from pipeline.phase1_structure import phase1_structure
from pipeline.phase2_embed_cluster import phase2_embed_cluster
from pipeline.phase3_score import phase3_score
from pipeline.phase4_patterns import phase4_patterns
from pipeline.phase5_synthesis import phase5_synthesis
from pipeline.phase6_meta import phase6_meta
from utils.gates import preflight_check, validate_phase1_output

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Solution Intelligence Analysis Pipeline")
    parser.add_argument("--problems", default=DATA_DIR + "problems.json", help="Input problems JSON")
    parser.add_argument("--solutions", default=DATA_DIR + "solutions.json", help="Input solutions JSON")
    parser.add_argument("--phase", default="all", choices=["all", "structure", "embed", "score", "patterns", "synthesis", "meta"], help="Pipeline phase to run")
    parser.add_argument("--problem-id", help="Optional: Run only for one problem ID")
    parser.add_argument("--force-rerun", action="store_true", help="Ignore LLM cache")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output directory")

    args = parser.parse_args()

    # Apply configuration overrides based on CLI args (e.g. output dir)
    
    phases_to_run = []
    if args.phase == "all":
        phases_to_run = ["structure", "embed", "score", "patterns", "synthesis", "meta"]
    else:
        phases_to_run = [args.phase]

    try:
        logger.info(f"Running Preflight checks...")
        preflight_check(args.problems, args.solutions, args.output_dir)
        logger.info(f"Validating inputs: {args.problems}, {args.solutions}")
        problems_dict, solutions_by_problem = validate_inputs(args.problems, args.solutions)
    except ValueError as e:
        logger.error(f"Input validation failed: {str(e)}")
        sys.exit(1)

    if "structure" in phases_to_run:
        logger.info("Running Phase 1: Structuring")
        phase1_structure(problems_dict, solutions_by_problem, args.problem_id, args.force_rerun, args.output_dir)
        
    if "embed" in phases_to_run:
        logger.info("Running Phase 2: Embedding & Clustering")
        phase2_embed_cluster(args.problem_id, args.output_dir)

    if "score" in phases_to_run:
        logger.info("Running Phase 3: Cluster Scoring")
        phase3_score(args.problem_id, args.output_dir)

    if "patterns" in phases_to_run:
        logger.info("Running Phase 4: Pattern Extraction")
        phase4_patterns(problems_dict, args.problem_id, args.force_rerun, args.output_dir)

    if "synthesis" in phases_to_run:
        logger.info("Running Phase 5: Synthesis")
        phase5_synthesis(problems_dict, args.problem_id, args.force_rerun, args.output_dir)

    if "meta" in phases_to_run:
        logger.info("Running Phase 6: Meta Reports")
        phase6_meta(problems_dict, args.problem_id, args.force_rerun, args.output_dir)

    logger.info("Pipeline execution complete.")

if __name__ == "__main__":
    main()
