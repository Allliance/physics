#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from collections import defaultdict, deque, Counter
import math

# ---- Hyper-parameters for PCSC (performance-calibrated structural complexity) ----
Q_LOCAL = 0.10   # per-step local error rate used to estimate success propagation
LAMBDA  = 0.40   # mix between structure entropy and (1 - EAS): PCSC = λ*C_struct + (1-λ)*(1-EAS)

def _toposort(nodes, parents_map, children):
    indeg = {u: len(parents_map.get(u, [])) for u in nodes}
    q = deque([u for u in nodes if indeg[u] == 0])
    topo = []
    while q:
        u = q.popleft()
        topo.append(u)
        for v in children.get(u, []):
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return topo

def _compute_EAS(nodes, parents_map, children, node_weights=None, q_local=Q_LOCAL):
    """
    Expected Attainable Score (EAS) under a simple step-failure model:
      P(root) = 1 - q
      P(u)    = (prod_{p in parents(u)} P(p)) * (1 - q)
    EAS = sum_u w(u) * P(u) / sum_u w(u)
    """
    topo = _toposort(nodes, parents_map, children)
    P = {}
    for u in topo:
        ps = parents_map.get(u, [])
        if not ps:  # root
            P[u] = (1.0 - q_local)
        else:
            prod_par = 1.0
            for p in ps:
                prod_par *= P[p]
            P[u] = prod_par * (1.0 - q_local)

    if node_weights is None:
        node_weights = {u: 1.0 for u in nodes}

    total_w = sum(node_weights.get(u, 1.0) for u in nodes) or 1.0
    eas = sum(node_weights.get(u, 1.0) * P[u] for u in nodes) / total_w
    return eas, P

def compute_dag_metrics(whole_item):
    """
    Compute DAG metrics from a grading_standard list, including:
      - depth (longest path length in edges)
      - num_nodes / num_edges / roots / sinks
      - longest_path_nodes
      - per-layer stats (layer_nodes, layer_out_edges, layer_avg_branching)
      - entropy-like complexity: sum_l log(1 + layer_avg_branching[l])
      - EAS (expected attainable score) and PCSC (performance-calibrated structural complexity)

    Assumes each entry in whole_item["grading_standard"] has:
      - "index": node id
      - "dependency": list of parent indices (in-edges)
      - "is_final_answer": optional flag
    """
    grading_standard = whole_item.get("grading_standard", [])
    pid = whole_item.get("id")

    idx_set = set()
    deps_map = {}
    children = defaultdict(list)  # u -> list of v (edges u->v)
    is_final = {}

    # Build graph
    for it in grading_standard:
        try:
            u = it["index"]
            idx_set.add(u)
            deps = it.get("dependency", []) or []
            deps_map[u] = deps[:]
            is_final[u] = bool(it.get("is_final_answer", False))
            for p in deps:
                children[p].append(u)
                idx_set.add(p)
        except Exception:
            # malformed record; skip this node
            pass

    nodes = sorted(idx_set)
    if not nodes:
        return {
            "id": pid,
            "depth": -0.001,
            "num_nodes": 0,
            "num_edges": 0,
            "num_roots": 0,
            "roots": [],
            "num_sinks": 0,
            "sinks": [],
            "longest_path_nodes": [],
            "layers": {},
            "layer_out_edges": {},
            "layer_avg_branching": {},
            "entropy_complexity": 0.0,
            "EAS": 0.0,
            "PCSC": 0.0,
        }

    # indegree
    indeg = {u: 0 for u in nodes}
    for u in nodes:
        for v in children[u]:
            indeg[v] += 1

    # Kahn topo
    q = deque([u for u in nodes if indeg[u] == 0])
    topo = []
    while q:
        u = q.popleft()
        topo.append(u)
        for v in children[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    # Longest path in DAG (distance in edges from any root)
    dp = {u: 0 for u in nodes}        # layer index
    parent = {u: None for u in nodes}
    for u in topo:
        for v in children[u]:
            if dp[u] + 1 > dp[v]:
                dp[v] = dp[u] + 1
                parent[v] = u

    try:
        end = max(nodes, key=lambda u: dp[u])
        path = []
        cur = end
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()

        depth = dp[end]  # number of edges along the longest path

        # Roots / Sinks
        roots = [u for u in nodes if len(deps_map.get(u, [])) == 0]
        sinks = [u for u in nodes if len(children.get(u, [])) == 0]

        # Per-layer nodes
        layers = defaultdict(list)  # layer -> nodes list
        for u in nodes:
            layers[dp[u]].append(u)

        # Per-layer outgoing edges and average branching
        layer_out_edges = {}
        layer_avg_branching = {}
        for l, ns in layers.items():
            total_out = sum(len(children.get(u, [])) for u in ns)
            layer_out_edges[l] = total_out
            layer_avg_branching[l] = (total_out / max(1, len(ns)))

        # Entropy-like complexity = sum_l log(1 + layer_avg_branching[l])
        entropy_complexity = 0.0
        for l in sorted(layers.keys()):
            entropy_complexity += math.log1p(layer_avg_branching[l])

        # ---- Performance component (EAS) ----
        node_weights = {u: 1.0 for u in nodes}  # if rubric has per-step points, plug them here
        eas, Pmap = _compute_EAS(nodes, deps_map, children, node_weights=node_weights, q_local=Q_LOCAL)

        # ---- PCSC: performance-calibrated structural complexity ----
        pcsc = LAMBDA * float(entropy_complexity) + (1.0 - LAMBDA) * (1.0 - float(eas))

        info = {
            "id": pid,
            "depth": depth,
            "num_nodes": len(nodes),
            "num_edges": sum(len(deps_map.get(u, [])) for u in nodes),
            "num_roots": len(roots),
            "roots": roots,
            "num_sinks": len(sinks),
            "sinks": sinks,
            "longest_path_nodes": path,
            "layers": {int(k): v for k, v in layers.items()},
            "layer_out_edges": {int(k): int(v) for k, v in layer_out_edges.items()},
            "layer_avg_branching": {int(k): float(v) for k, v in layer_avg_branching.items()},
            "entropy_complexity": float(entropy_complexity),
            "EAS": float(eas),
            "PCSC": float(pcsc),
        }
    except Exception:
        info = {
            "id": pid,
            "depth": -0.001,
            "num_nodes": len(nodes),
            "num_edges": sum(len(deps_map.get(u, [])) for u in nodes),
            "num_roots": len([u for u in nodes if len(deps_map.get(u, [])) == 0]),
            "roots": [u for u in nodes if len(deps_map.get(u, [])) == 0],
            "num_sinks": len([u for u in nodes if len(children.get(u, [])) == 0]),
            "sinks": [u for u in nodes if len(children.get(u, [])) == 0],
            "longest_path_nodes": [],
            "layers": {},
            "layer_out_edges": {},
            "layer_avg_branching": {},
            "entropy_complexity": 0.0,
            "EAS": 0.0,
            "PCSC": 0.0,
        }

    return info


if __name__ == "__main__":
    for i in range(7):
        print(i + 1)
        input_file = f"/home/users/wanjiazh/AI4S_Bench/main_exp/0{i+1}_dag.json"
        out_file = f"/home/users/wanjiazh/AI4S_Bench/main_exp/0{i+1}_dag_depth.json"
        stats_file = f"/home/users/wanjiazh/AI4S_Bench/main_exp/0{i+1}_dag_depth_stats.txt"

        with open(input_file, "r") as f:
            data = json.load(f)

        results = []
        for item in data:
            info = compute_dag_metrics(item)
            results.append(info)

        with open(out_file, "w") as f:
            json.dump(results, f, indent=2)

        # Stats
        depth_counts = Counter([r["depth"] for r in results])
        avg_depth   = sum(r["depth"] for r in results) / max(1, len(results))
        avg_entropy = sum(r.get("entropy_complexity", 0.0) for r in results) / max(1, len(results))
        avg_eas     = sum(r.get("EAS", 0.0) for r in results) / max(1, len(results))
        avg_pcsc    = sum(r.get("PCSC", 0.0) for r in results) / max(1, len(results))

        with open(stats_file, "w") as f:
            for depth in sorted(depth_counts):
                f.write(f"Depth={depth}: {depth_counts[depth]} problems\n")
            f.write(f"Average depth: {avg_depth:.4f}\n")
            f.write(f"Average entropy_complexity: {avg_entropy:.6f}\n")
            f.write(f"Average EAS: {avg_eas:.6f}\n")
            f.write(f"Average PCSC: {avg_pcsc:.6f}\n")
            f.write(f"Saved depth+metrics info for {len(results)} problems to {out_file}\n")

        print(f"Average depth: {avg_depth:.2f}")
        print(f"Average entropy_complexity: {avg_entropy:.6f}")
        print(f"Average EAS: {avg_eas:.6f}")
        print(f"Average PCSC: {avg_pcsc:.6f}")
        print(f"Saved to: {out_file}")
