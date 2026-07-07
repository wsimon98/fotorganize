"""Face clustering + auto-assignment to known people. numpy only (no sklearn).

Rules (see docs/ai_pipeline.md):
- User assignments are ground truth: faces with confirmed_by_user=1 are NEVER moved.
- New/unassigned faces close to a NAMED person's confirmed faces are auto-linked to that
  person (this is "remember my choices and apply to similar faces"). Auto links have
  confirmed_by_user=0 so the user can still correct them.
- Remaining unassigned faces are grouped into clusters for review.

Embeddings are L2-normalized, so cosine similarity == dot product.
"""
from __future__ import annotations

import logging

import numpy as np

from ..database import get_db, utcnow

log = logging.getLogger(__name__)

# tuned for ArcFace/buffalo_l normed embeddings; overridable via config later
ASSIGN_THRESHOLD = 0.42   # auto-link an unassigned face to a known person
CLUSTER_THRESHOLD = 0.40  # group two unassigned faces into the same cluster


def _load_embeddings(rows):
    embs, ids = [], []
    for r in rows:
        if r["embedding_vector"]:
            embs.append(np.frombuffer(r["embedding_vector"], dtype="float32"))
            ids.append(r["id"])
    if not embs:
        return np.zeros((0, 512), dtype="float32"), []
    return np.vstack(embs), ids


def cluster_all(assign_threshold: float = ASSIGN_THRESHOLD,
                cluster_threshold: float = CLUSTER_THRESHOLD) -> dict:
    db = get_db()
    now = utcnow()
    stats = {"auto_assigned": 0, "clusters_created": 0, "unassigned_clustered": 0}

    # 0) tear down previous auto clusters (never touch named/reviewed ones). Null the
    #    faces' cluster_id BEFORE deleting the cluster rows or the FK constraint fails.
    db.execute("UPDATE faces SET cluster_id=NULL WHERE cluster_id IN "
               "(SELECT id FROM face_clusters WHERE status='needs_review')")
    db.execute("DELETE FROM face_clusters WHERE status='needs_review'")

    # 1) auto-assign unassigned faces to known people using confirmed faces as anchors
    people = db.execute("SELECT id, display_name FROM people").fetchall()
    person_anchors = {}
    for p in people:
        rows = db.execute(
            "SELECT id, embedding_vector FROM faces WHERE person_id=? AND status='active'"
            " AND confirmed_by_user=1", (p["id"],)).fetchall()
        mat, _ = _load_embeddings(rows)
        if len(mat):
            person_anchors[p["id"]] = mat

    unassigned = db.execute(
        "SELECT id, embedding_vector FROM faces WHERE person_id IS NULL AND status='active'"
        " AND confirmed_by_user=0").fetchall()
    u_mat, u_ids = _load_embeddings(unassigned)

    still_unassigned = list(range(len(u_ids)))
    if person_anchors and len(u_mat):
        best_pid = [None] * len(u_ids)
        best_sim = [0.0] * len(u_ids)
        for pid, anchors in person_anchors.items():
            sims = u_mat @ anchors.T          # (U, A)
            maxsim = sims.max(axis=1)
            for i in range(len(u_ids)):
                if maxsim[i] > best_sim[i]:
                    best_sim[i] = maxsim[i]
                    best_pid[i] = pid
        remaining = []
        for i in still_unassigned:
            if best_pid[i] is not None and best_sim[i] >= assign_threshold:
                db.execute(
                    "UPDATE faces SET person_id=?, cluster_id=NULL WHERE id=?",
                    (best_pid[i], u_ids[i]))
                _link_person_image(db, u_ids[i], best_pid[i], best_sim[i], "face_match", now)
                stats["auto_assigned"] += 1
            else:
                remaining.append(i)
        still_unassigned = remaining

    # 2) re-cluster the faces that are still unassigned
    idxs = still_unassigned
    if idxs:
        sub = u_mat[idxs]
        n = len(idxs)
        assigned = [-1] * n
        clusters: list[list[int]] = []
        for i in range(n):
            if assigned[i] != -1:
                continue
            cid = len(clusters)
            clusters.append([i])
            assigned[i] = cid
            sims = sub @ sub[i]
            for j in range(i + 1, n):
                if assigned[j] == -1 and sims[j] >= cluster_threshold:
                    assigned[j] = cid
                    clusters[cid].append(j)
        for members in clusters:
            cur = db.execute(
                "INSERT INTO face_clusters (auto_label, status, confidence, created_at,"
                " updated_at) VALUES (?, 'needs_review', ?, ?, ?)",
                (None, float(len(members)), now, now))
            cluster_id = cur.lastrowid
            stats["clusters_created"] += 1
            for m in members:
                db.execute("UPDATE faces SET cluster_id=? WHERE id=?",
                           (cluster_id, u_ids[idxs[m]]))
                stats["unassigned_clustered"] += 1

    db.commit()
    log.info("cluster_all: %s", stats)
    return stats


def _link_person_image(db, face_id, person_id, conf, source, now):
    row = db.execute("SELECT file_id FROM faces WHERE id=?", (face_id,)).fetchone()
    if not row:
        return
    db.execute(
        "INSERT OR IGNORE INTO image_people (file_id, person_id, confidence, source,"
        " confirmed_by_user, created_at) VALUES (?,?,?,?,0,?)",
        (row["file_id"], person_id, conf, source, now))
