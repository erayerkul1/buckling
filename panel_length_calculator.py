"""
Panel Length Calculator
-----------------------
Given a BDF file and a property ID, finds the panel's average X and Y lengths.

Logic:
- Collects all elements referencing the property ID (CQUAD4, CQUAD8, CTRIA3, CTRIA6)
- Extracts corner nodes (ignores mid-edge nodes)
- Detects panel plane (XZ, ZY, or XY) based on which axis has negligible variance
- Finds the 4 boundary corner nodes via convex hull
- Computes edge lengths for opposite sides and averages them
- X direction = longer average dimension
"""

import sys
import numpy as np
from itertools import combinations
from scipy.spatial import ConvexHull
from pyNastran.bdf.bdf import BDF


CORNER_NODE_COUNTS = {
    "CQUAD4": 4,
    "CQUAD8": 4,  # first 4 are corners
    "CTRIA3": 3,
    "CTRIA6": 3,  # first 3 are corners
}


def load_bdf(bdf_path: str) -> BDF:
    model = BDF(debug=False)
    model.read_bdf(bdf_path, xref=False)
    return model


def get_corner_nodes_for_property(model: BDF, property_id: int) -> dict[int, np.ndarray]:
    """
    Returns {node_id: np.array([x, y, z])} for all corner nodes
    belonging to elements that reference the given property_id.
    """
    corner_node_ids = set()

    for eid, elem in model.elements.items():
        if elem.pid != property_id:
            continue
        etype = elem.type
        if etype not in CORNER_NODE_COUNTS:
            continue
        n_corners = CORNER_NODE_COUNTS[etype]
        nids = elem.node_ids[:n_corners]
        corner_node_ids.update(nids)

    if not corner_node_ids:
        raise ValueError(f"No elements found for property ID {property_id}")

    coords = {}
    for nid in corner_node_ids:
        grid = model.nodes[nid]
        coords[nid] = np.array(grid.get_position(), dtype=float)

    return coords


def detect_plane(coords: dict[int, np.ndarray]) -> str:
    """
    Detects the panel plane by finding the axis with the smallest variance.
    Returns 'XZ', 'ZY', or 'XY'.
    """
    pts = np.array(list(coords.values()))
    variances = pts.var(axis=0)  # [var_x, var_y, var_z]
    min_axis = int(np.argmin(variances))
    plane_map = {0: "ZY", 1: "XZ", 2: "XY"}
    return plane_map[min_axis]


def project_to_plane(coords: dict[int, np.ndarray], plane: str) -> dict[int, np.ndarray]:
    """Projects 3D coords onto the 2D panel plane for convex hull computation."""
    axis_map = {"XZ": [0, 2], "ZY": [2, 1], "XY": [0, 1]}
    axes = axis_map[plane]
    return {nid: pt[axes] for nid, pt in coords.items()}


def find_panel_corners(coords: dict[int, np.ndarray], plane: str) -> list[int]:
    """
    Uses convex hull in the panel plane to find boundary corner nodes.
    Returns 4 node IDs that form the rectangular boundary.
    """
    proj = project_to_plane(coords, plane)
    nids = list(proj.keys())
    pts_2d = np.array([proj[n] for n in nids])

    if len(nids) < 4:
        raise ValueError(f"Only {len(nids)} corner nodes found, need at least 4")

    # For a rectangle, convex hull vertices are the 4 corner nodes
    if len(nids) == 4:
        return nids

    hull = ConvexHull(pts_2d)
    hull_nids = [nids[i] for i in hull.vertices]

    if len(hull_nids) < 4:
        raise ValueError("Convex hull has fewer than 4 vertices")

    # If hull has exactly 4 → perfect rectangle corners
    if len(hull_nids) == 4:
        return hull_nids

    # Hull has more than 4 vertices (e.g. slightly non-rectangular mesh boundary).
    # Pick the 4 nodes that best represent the rectangle corners:
    # maximize total perimeter of the quadrilateral formed by the 4 chosen nodes.
    best_area = -1
    best_quad = None
    for quad in combinations(hull_nids, 4):
        quad_pts = pts_2d[[nids.index(n) for n in quad]]
        # Order by angle around centroid
        centroid = quad_pts.mean(axis=0)
        angles = np.arctan2(quad_pts[:, 1] - centroid[1], quad_pts[:, 0] - centroid[0])
        order = np.argsort(angles)
        ordered = quad_pts[order]
        # Shoelace area
        n = len(ordered)
        area = 0.5 * abs(sum(
            ordered[i][0] * ordered[(i + 1) % n][1] - ordered[(i + 1) % n][0] * ordered[i][1]
            for i in range(n)
        ))
        if area > best_area:
            best_area = area
            best_quad = [quad[i] for i in order]

    return best_quad


def order_corners(corner_nids: list[int], coords: dict[int, np.ndarray], plane: str) -> list[int]:
    """
    Orders 4 corner node IDs counter-clockwise starting from bottom-left
    in the panel plane: [bottom-left, bottom-right, top-right, top-left]
    """
    proj = project_to_plane({n: coords[n] for n in corner_nids}, plane)
    pts = np.array([proj[n] for n in corner_nids])
    centroid = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centroid[1], pts[:, 0] - centroid[0])
    order = np.argsort(angles)
    # Start from bottom-left (most negative angle = rightward-downward)
    return [corner_nids[i] for i in order]


def euclidean(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


def compute_panel_lengths(
    bdf_path: str, property_id: int
) -> dict:
    """
    Main function. Returns panel length info dict:
    {
        "property_id": int,
        "plane": str,
        "corner_nodes": [nid0, nid1, nid2, nid3],  # CCW ordered
        "edge_lengths": {"bottom": float, "right": float, "top": float, "left": float},
        "x_length": float,   # average of longer pair
        "y_length": float,   # average of shorter pair
        "x_direction": str,  # "horizontal" or "vertical" in panel plane
    }
    """
    model = load_bdf(bdf_path)
    coords = get_corner_nodes_for_property(model, property_id)
    plane = detect_plane(coords)
    corner_nids = find_panel_corners(coords, plane)
    ordered = order_corners(corner_nids, coords, plane)

    # Ordered: [bl, br, tr, tl]
    bl, br, tr, tl = [coords[n] for n in ordered]

    bottom = euclidean(bl, br)
    right  = euclidean(br, tr)
    top    = euclidean(tr, tl)
    left   = euclidean(tl, bl)

    horizontal_avg = (bottom + top) / 2
    vertical_avg   = (left + right) / 2

    if horizontal_avg >= vertical_avg:
        x_length = horizontal_avg
        y_length = vertical_avg
        x_direction = "horizontal"
    else:
        x_length = vertical_avg
        y_length = horizontal_avg
        x_direction = "vertical"

    return {
        "property_id": property_id,
        "plane": plane,
        "corner_nodes": ordered,
        "edge_lengths": {
            "bottom": round(bottom, 4),
            "right":  round(right, 4),
            "top":    round(top, 4),
            "left":   round(left, 4),
        },
        "x_length": round(x_length, 4),
        "y_length": round(y_length, 4),
        "x_direction": x_direction,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python panel_length_calculator.py <bdf_file> <property_id>")
        sys.exit(1)

    bdf_path = sys.argv[1]
    property_id = int(sys.argv[2])

    result = compute_panel_lengths(bdf_path, property_id)

    print(f"\n{'='*50}")
    print(f"Property ID : {result['property_id']}")
    print(f"Panel Plane : {result['plane']}")
    print(f"Corner Nodes: {result['corner_nodes']}")
    print(f"{'='*50}")
    print(f"Edge Lengths:")
    for side, length in result["edge_lengths"].items():
        print(f"  {side:<8}: {length:.4f} mm")
    print(f"{'='*50}")
    print(f"X Length (avg, long side)  : {result['x_length']:.4f} mm  [{result['x_direction']}]")
    print(f"Y Length (avg, short side) : {result['y_length']:.4f} mm")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
