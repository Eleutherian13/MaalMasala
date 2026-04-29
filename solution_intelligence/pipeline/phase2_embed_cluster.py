import os
import json
import logging
import numpy as np
from sklearn.cluster import HDBSCAN as hdbscan
import faiss
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_distances, pairwise_distances_argmin_min
from config import EMBEDDING_MODEL, HDBSCAN_MIN_CLUSTER_SIZE, HDBSCAN_MIN_SAMPLES
from pipeline.phase3_score import score_solution
from utils.schema import SolutionExtraction
from utils.gates import determine_cluster_tier

logger = logging.getLogger(__name__)

def phase2_embed_cluster(problem_id: str, output_dir: str):
    embed_dir = os.path.join(output_dir, "embeddings")
    cluster_dir = os.path.join(output_dir, "clusters")
    os.makedirs(embed_dir, exist_ok=True)
    os.makedirs(cluster_dir, exist_ok=True)

    structured_dir = os.path.join(output_dir, "structured")
    
    # Process problem_id or all _summary.json files
    pids = [problem_id] if problem_id else [d for d in os.listdir(structured_dir) if os.path.isdir(os.path.join(structured_dir, d))]

    if not pids:
        logger.warning("No structured problems found for Phase 2.")
        return

    logger.info(f"Phase 2: Loading embedding model {EMBEDDING_MODEL}...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    for pid in pids:
        summary_path = os.path.join(structured_dir, pid, "_summary.json")
        if not os.path.exists(summary_path):
            logger.warning(f"Summary not found for problem {pid}. Skipping.")
            continue

        with open(summary_path, 'r', encoding='utf-8') as f:
            solutions = json.load(f)

        # Filter out parsing errors
        valid_sols = [s for s in solutions if not s.get("parse_error")]
        if not valid_sols:
            logger.info(f"No valid structured solutions to embed for {pid}.")
            continue

        logger.info(f"Problem {pid}: Embedding {len(valid_sols)} solutions...")
        
        texts = []
        solution_ids = []
        final_scores = []
        
        for s in valid_sols:
            if 'solution_id' not in s:
                continue
            try:
                extraction = SolutionExtraction(**s)
                evaluation = score_solution(extraction)
                if not evaluation:
                    logger.warning(f"Failed to score {s['solution_id']}.")
                    continue
                score = evaluation.final_score
            except Exception as e:
                logger.warning(f"Extraction parse error for {s['solution_id']}: {e}")
                continue

            t = f"{s['summary']} {s['approach_type']} {' '.join(s['tech_stack'])}"
            texts.append(t)
            solution_ids.append(s['solution_id'])
            final_scores.append(score)

        if not texts:
            continue

        embeddings = model.encode(texts, batch_size=32, show_progress_bar=True)
        final_scores = np.array(final_scores)
        
        # Save embeddings
        np.save(os.path.join(embed_dir, f"{pid}.npy"), embeddings)

        # Build FAISS index
        embedding_dim = embeddings.shape[1]
        index = faiss.IndexFlatL2(embedding_dim)
        index.add(embeddings)
        faiss.write_index(index, os.path.join(embed_dir, f"{pid}.faiss"))
        
        # 2. Modify clustering distance metric
        alpha = 0.8
        cos_dist = cosine_distances(embeddings)
        norm_scores = final_scores / 100.0
        score_dist = np.abs(norm_scores[:, None] - norm_scores[None, :])
        custom_dist = alpha * cos_dist + (1 - alpha) * score_dist
        
        # Handle cases with very few solutions gracefully before clustering
        if len(embeddings) < max(HDBSCAN_MIN_CLUSTER_SIZE, 2):
            logger.warning(f"Problem {pid}: Not enough solutions to cluster. Found {len(embeddings)} solutions. Assigning all to a single fallback cluster.")
            labels = np.zeros(len(embeddings)) # Label all as cluster 0
        else:
            logger.info(f"Problem {pid}: Clustering with HDBSCAN...")
            clusterer = hdbscan(
                min_cluster_size=min(HDBSCAN_MIN_CLUSTER_SIZE, len(embeddings)),
                min_samples=min(HDBSCAN_MIN_SAMPLES, len(embeddings)),
                metric='precomputed',
                cluster_selection_method='eom'
            )
            # HDBSCAN expects float64 for precomputed
            labels = clusterer.fit_predict(custom_dist.astype(np.float64))

        unique_labels = set(labels)
        noise_solutions = [solution_ids[i] for i, lbl in enumerate(labels) if lbl == -1]
        num_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
        
        cluster_list = []
        for cluster_id in unique_labels:
            if cluster_id == -1:
                continue
                
            indices = np.where(labels == cluster_id)[0]
            cluster_sids = [solution_ids[i] for i in indices]
            cluster_scores = final_scores[indices]
            
            # Find representative solution (centroid in embedding space)
            cluster_embeddings = embeddings[indices]
            centroid = np.mean(cluster_embeddings, axis=0).reshape(1, -1)
            closest_idx, _ = pairwise_distances_argmin_min(centroid, cluster_embeddings)
            centroid_sid = cluster_sids[closest_idx[0]]
            
            # 3. Compute cluster stats
            avg_score = float(np.mean(cluster_scores))
            max_score = float(np.max(cluster_scores))
            variance = float(np.var(cluster_scores))
            size = len(indices)
            
            tier = determine_cluster_tier(avg_score, variance, size, HDBSCAN_MIN_CLUSTER_SIZE)
            
            cluster_data = {
                "cluster_id": int(cluster_id),
                "solution_ids": cluster_sids,
                "size": size,
                "avg_score": avg_score,
                "max_score": max_score,
                "variance": variance,
                "representative_solution": centroid_sid,
                "tier": tier
            }
            cluster_list.append(cluster_data)
            
        cluster_output = {
            "problem_id": pid,
            "n_clusters": num_clusters,
            "n_noise": len(noise_solutions),
            "clusters": cluster_list,
            "noise_solutions": noise_solutions
        }
        
        # Save cluster assignments
        with open(os.path.join(cluster_dir, f"{pid}.json"), 'w', encoding='utf-8') as f:
            json.dump(cluster_output, f, indent=2)

    logger.info("Phase 2 Completed.")
