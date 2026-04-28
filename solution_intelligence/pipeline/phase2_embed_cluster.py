import os
import json
import logging
import numpy as np
import hdbscan
import faiss
from sentence_transformers import SentenceTransformer
from sklearn.metrics import pairwise_distances_argmin_min
from config import EMBEDDING_MODEL, HDBSCAN_MIN_CLUSTER_SIZE, HDBSCAN_MIN_SAMPLES

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
        novelty_scores = []
        quality_scores = []
        
        for s in valid_sols:
            t = f"{s['core_idea']} {s['approach']} {' '.join(s['tools_and_techniques'])}"
            texts.append(t)
            solution_ids.append(s['solution_id'])
            novelty_scores.append(s.get('novelty_score', 0))
            quality_scores.append(s.get('quality_score', 0))

        embeddings = model.encode(texts, batch_size=32, show_progress_bar=True)
        
        # Save embeddings
        np.save(os.path.join(embed_dir, f"{pid}.npy"), embeddings)

        # Build FAISS index
        embedding_dim = embeddings.shape[1]
        index = faiss.IndexFlatL2(embedding_dim)
        index.add(embeddings)
        faiss.write_index(index, os.path.join(embed_dir, f"{pid}.faiss"))
        
        logger.info(f"Problem {pid}: Clustering with HDBSCAN...")
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
            min_samples=HDBSCAN_MIN_SAMPLES,
            metric='euclidean',
            cluster_selection_method='eom'
        )
        labels = clusterer.fit_predict(embeddings)

        unique_labels = set(labels)
        noise_solutions = [solution_ids[i] for i, lbl in enumerate(labels) if lbl == -1]
        num_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
        
        cluster_list = []
        for cluster_id in unique_labels:
            if cluster_id == -1:
                continue
                
            indices = np.where(labels == cluster_id)[0]
            cluster_sids = [solution_ids[i] for i in indices]
            cluster_novelty = [novelty_scores[i] for i in indices]
            cluster_quality = [quality_scores[i] for i in indices]
            
            # Find centroid solution ID
            cluster_embeddings = embeddings[indices]
            centroid = np.mean(cluster_embeddings, axis=0).reshape(1, -1)
            closest_idx, _ = pairwise_distances_argmin_min(centroid, cluster_embeddings)
            centroid_sid = cluster_sids[closest_idx[0]]
            
            cluster_data = {
                "cluster_id": int(cluster_id),
                "solution_ids": cluster_sids,
                "size": len(indices),
                "avg_novelty": float(np.mean(cluster_novelty)),
                "avg_quality": float(np.mean(cluster_quality)),
                "centroid_solution_id": centroid_sid
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
