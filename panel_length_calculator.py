"""
Panel Length Calculator
-----------------------
Given a BDF file and a property ID:
- Finds panel X/Y average lengths (X = long side)
- Finds the bar property on each of the 4 edges (X1, X2, Y1, Y2)
"""

import sys
import numpy as np
from itertools import combinations
from scipy.spatial import ConvexHull
from pyNastran.bdf.bdf import BDF


SHELL_TYPES = {"CQUAD4": 4, "CQUAD8": 4, "CTRIA3": 3, "CTRIA6": 3}
BAR_TYPES   = {"CBAR", "CBEAM", "CROD", "CTUBE"}


def load_bdf(bdf_path: str) -> BDF:
    model = BDF(debug=False)
    model.read_bdf(bdf_path, xref=False)
    return model


# ── Node collection ─────────────────────────────────────────────────────────

def get_corner_nodes_for_property(model: BDF, property_id: int) -> dict[int, np.ndarray]:
    """Corner nodes only (first N nodes of each shell element)."""
    nids = set()
    for elem in model.elements.values():
        if elem.pid != property_id or elem.type not in SHELL_TYPES:
            continue
        nids.update(elem.node_ids[:SHELL_TYPES[elem.type]])

    if not nids:
        raise ValueError(f"No shell elements found for property ID {property_id}")

    return {n: np.array(model.nodes[n].get_position(), dtype=float) for n in nids}


def get_all_nodes_for_property(model: BDF, property_id: int) -> dict[int, np.ndarray]:
    """All nodes (corner + mid-edge) for every shell element of the property."""
    nids = set()
    for elem in model.elements.values():
        if elem.pid != property_id or elem.type not in SHELL_TYPES:
            continue
        nids.update(elem.node_ids)

    return {n: np.array(model.nodes[n].get_position(), dtype=float) for n in nids}


# ── Plane / projection ───────────────────────────────────────────────────────

def detect_plane(coords: dict[int, np.ndarray]) -> str:
    pts = np.array(list(coords.values()))
    min_axis = int(np.argmin(pts.var(axis=0)))
    return {0: "ZY", 1: "XZ", 2: "XY"}[min_axis]


def project_to_plane(coords: dict[int, np.ndarray], plane: str) -> dict[int, np.ndarray]:
    axes = {"XZ": [0, 2], "ZY": [2, 1], "XY": [0, 1]}[plane]
    return {nid: pt[axes] for nid, pt in coords.items()}


# ── Corner detection ─────────────────────────────────────────────────────────

def find_panel_corners(coords: dict[int, np.ndarray], plane: str) -> list[int]:
    proj  = project_to_plane(coords, plane)
    nids  = list(proj.keys())
    pts2d = np.array([proj[n] for n in nids])

    if len(nids) < 4:
        raise ValueError(f"Only {len(nids)} corner nodes, need at least 4")
    if len(nids) == 4:
        return nids

    hull      = ConvexHull(pts2d)
    hull_nids = [nids[i] for i in hull.vertices]

    if len(hull_nids) == 4:
        return hull_nids

    # More than 4 hull vertices → pick the quad with maximum area
    best_area, best_quad = -1, None
    for quad in combinations(hull_nids, 4):
        qpts = pts2d[[nids.index(n) for n in quad]]
        c    = qpts.mean(axis=0)
        ang  = np.arctan2(qpts[:, 1] - c[1], qpts[:, 0] - c[0])
        o    = np.argsort(ang)
        op   = qpts[o]
        n    = 4
        area = 0.5 * abs(sum(
            op[i][0] * op[(i+1) % n][1] - op[(i+1) % n][0] * op[i][1]
            for i in range(n)
        ))
        if area > best_area:
            best_area = area
            best_quad = [quad[i] for i in o]

    return best_quad


def order_corners(corner_nids: list[int], coords: dict[int, np.ndarray], plane: str) -> list[int]:
    """CCW order: [bottom-left, bottom-right, top-right, top-left]."""
    proj = project_to_plane({n: coords[n] for n in corner_nids}, plane)
    pts  = np.array([proj[n] for n in corner_nids])
    c    = pts.mean(axis=0)
    ang  = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    return [corner_nids[i] for i in np.argsort(ang)]


# ── Edge node finding ────────────────────────────────────────────────────────

def get_nodes_on_edge(
    all_coords: dict[int, np.ndarray],
    nid_a: int,
    nid_b: int,
) -> set[int]:
    """All nodes that lie on the segment A→B (including A and B)."""
    pa       = all_coords[nid_a]
    pb       = all_coords[nid_b]
    edge_vec = pb - pa
    edge_len_sq = float(np.dot(edge_vec, edge_vec))
    tol      = 1e-4

    edge_len = np.sqrt(edge_len_sq)
    # Allow up to 1% of edge length as perpendicular deviation (handles slightly
    # trapezoidal panels where mid-edge nodes are not perfectly collinear)
    dist_tol = max(0.01 * edge_len, 1e-3)

    on_edge = set()
    for nid, pt in all_coords.items():
        v = pt - pa
        t = float(np.dot(v, edge_vec)) / edge_len_sq if edge_len_sq > 0 else 0.0
        if t < -tol or t > 1.0 + tol:
            continue
        proj = pa + t * edge_vec
        if np.linalg.norm(pt - proj) < dist_tol:
            on_edge.add(nid)

    return on_edge


# ── Bar property lookup ──────────────────────────────────────────────────────

def find_bar_property_for_edge(
    model: BDF,
    edge_nodes: set[int],
) -> tuple[int | None, int]:
    """
    Returns (best_property_id, shared_node_count).
    Best = property whose bar elements share the most nodes with edge_nodes.
    """
    prop_nodes: dict[int, set[int]] = {}

    for elem in model.elements.values():
        if elem.type not in BAR_TYPES:
            continue
        pid = elem.pid
        if pid not in prop_nodes:
            prop_nodes[pid] = set()
        prop_nodes[pid].update(elem.node_ids)

    best_pid, best_count = None, 0
    for pid, bar_nids in prop_nodes.items():
        shared = len(edge_nodes & bar_nids)
        if shared > best_count:
            best_count = shared
            best_pid   = pid

    return best_pid, best_count


def get_bar_property_dims(model: BDF, bar_pid: int | None) -> tuple:
    """
    Returns (dim1, dim2) for the bar property.
    PBARL/PBEAML → cross-section DIM1, DIM2
    PBAR/PBEAM   → area (A), moment of inertia I1
    """
    if bar_pid is None or bar_pid not in model.properties:
        return None, None

    prop  = model.properties[bar_pid]
    ptype = prop.type

    if ptype in ("PBARL", "PBEAML"):
        dims = prop.dim if hasattr(prop, "dim") else []
        d1 = round(float(dims[0]), 6) if len(dims) > 0 else None
        d2 = round(float(dims[1]), 6) if len(dims) > 1 else None
        return d1, d2

    if ptype == "PBAR":
        return round(float(prop.A), 6), round(float(prop.i1), 6)

    if ptype == "PBEAM":
        a_list  = prop.A  if hasattr(prop, "A")  else [None]
        i1_list = prop.i1 if hasattr(prop, "i1") else [None]
        a  = round(float(a_list[0]),  6) if a_list[0]  is not None else None
        i1 = round(float(i1_list[0]), 6) if i1_list[0] is not None else None
        return a, i1

    if ptype == "PROD":
        return round(float(prop.A), 6), None

    return None, None


# ── Distance helper ──────────────────────────────────────────────────────────

def euclidean(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


# ── Main computation ─────────────────────────────────────────────────────────

def compute_panel_lengths(bdf_path: str, property_id: int) -> dict:
    """
    Returns:
    {
        property_id, plane,
        corner_nodes, edge_lengths,
        x_length, y_length, x_direction,
        bars: {
            "x1": {pid, dim1, dim2, shared_nodes},
            "x2": {pid, dim1, dim2, shared_nodes},
            "y1": {pid, dim1, dim2, shared_nodes},
            "y2": {pid, dim1, dim2, shared_nodes},
        }
    }
    """
    model = load_bdf(bdf_path)

    corner_coords = get_corner_nodes_for_property(model, property_id)
    all_coords    = get_all_nodes_for_property(model, property_id)

    plane      = detect_plane(corner_coords)
    corner_nids = find_panel_corners(corner_coords, plane)
    ordered    = order_corners(corner_nids, corner_coords, plane)

    # Ordered CCW: [bl, br, tr, tl]
    bl_id, br_id, tr_id, tl_id = ordered
    bl, br, tr, tl = [corner_coords[n] for n in ordered]

    bottom = euclidean(bl, br)
    right  = euclidean(br, tr)
    top    = euclidean(tr, tl)
    left   = euclidean(tl, bl)

    horiz_avg = (bottom + top) / 2
    vert_avg  = (left + right) / 2

    if horiz_avg >= vert_avg:
        x_length, y_length, x_direction = horiz_avg, vert_avg, "horizontal"
        x_edges = [("x1", bl_id, br_id), ("x2", tl_id, tr_id)]
        y_edges = [("y1", tl_id, bl_id), ("y2", br_id, tr_id)]
    else:
        x_length, y_length, x_direction = vert_avg, horiz_avg, "vertical"
        x_edges = [("x1", tl_id, bl_id), ("x2", br_id, tr_id)]
        y_edges = [("y1", bl_id, br_id), ("y2", tl_id, tr_id)]

    bars = {}
    for label, nid_a, nid_b in x_edges + y_edges:
        edge_nodes = get_nodes_on_edge(all_coords, nid_a, nid_b)
        pid, shared = find_bar_property_for_edge(model, edge_nodes)
        d1, d2 = get_bar_property_dims(model, pid)
        bars[label] = {
            "pid":          pid,
            "dim1":         d1,
            "dim2":         d2,
            "shared_nodes": shared,
        }

    return {
        "property_id": property_id,
        "plane":        plane,
        "corner_nodes": ordered,
        "edge_lengths": {
            "bottom": round(bottom, 4),
            "right":  round(right,  4),
            "top":    round(top,    4),
            "left":   round(left,   4),
        },
        "x_length":    round(x_length, 4),
        "y_length":    round(y_length, 4),
        "x_direction": x_direction,
        "bars":        bars,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python panel_length_calculator.py <bdf_file> <property_id>")
        sys.exit(1)

    res = compute_panel_lengths(sys.argv[1], int(sys.argv[2]))

    print(f"\n{'='*56}")
    print(f"Property ID : {res['property_id']}   Plane: {res['plane']}")
    print(f"Corner Nodes: {res['corner_nodes']}")
    print(f"{'='*56}")
    for side, length in res["edge_lengths"].items():
        print(f"  {side:<8}: {length:.4f} mm")
    print(f"{'─'*56}")
    print(f"  X Length (long,  avg): {res['x_length']:.4f} mm  [{res['x_direction']}]")
    print(f"  Y Length (short, avg): {res['y_length']:.4f} mm")
    print(f"{'='*56}")
    print("  Bar Properties:")
    for label, b in res["bars"].items():
        print(f"  {label}: PID={b['pid']}  DIM1={b['dim1']}  DIM2={b['dim2']}"
              f"  (shared nodes: {b['shared_nodes']})")
    print(f"{'='*56}\n")


if __name__ == "__main__":
    main()
