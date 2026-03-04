import numpy as np
import networkx as nx
from shapely.geometry import Point

def place_new_stops(G: nx.Graph, demand, k=5, weight_key="walk_cost"):
    """
    Demand: list of (lat, lon, w) in WGS84.
    Graph G: node attributes x,y are in meters (UTM) in your synthetic graph.
    This function assumes demand points were generated from the same synthetic neighborhood
    and are roughly aligned; we snap demand to nearest graph nodes using Euclidean distance
    in the graph's coordinate space.

    Returns: list of (lat, lon) stop coordinates in WGS84 *IF* your graph x/y are lon/lat.
    If your graph x/y are meters, return (y, x) in meters (for internal use) OR convert outside.
    """
    if len(G.nodes) == 0:
        return []

    nodes = list(G.nodes)

    # --- Build arrays of node coords (graph space) ---
    node_xy = np.array([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in nodes], dtype=float)

    # --- Snap demand points to nearest nodes ---
    # demand is (lat, lon, w) but graph is in meters; your synthetic demand was derived
    # from buildings in meters then converted to WGS84, so snapping in WGS84 would be wrong.
    # Instead, we snap by converting demand back to graph space if you saved a transformer.
    #
    # For now, we assume demand was generated from the same synthetic generator
    # and is close enough that nearest-node in WGS84 is acceptable ONLY if graph is WGS84.
    #
    # If your synthetic graph is in meters (recommended), then do snapping during generation
    # and store demand as node ids. (Next step below.)

    # If your graph coords look like WGS84, do a simple snap in lon/lat space:
    looks_like_wgs84 = (
        -180 <= node_xy[:, 0].min() <= 180 and -90 <= node_xy[:, 1].min() <= 90
        and -180 <= node_xy[:, 0].max() <= 180 and -90 <= node_xy[:, 1].max() <= 90
    )

    demand_arr = np.array([(lon, lat, w) for (lat, lon, w) in demand], dtype=float)

    # nearest node by Euclidean in lon/lat (ok for small test areas)
    snapped_nodes = []
    weights = []
    for lon, lat, w in demand_arr:
        d2 = (node_xy[:, 0] - lon) ** 2 + (node_xy[:, 1] - lat) ** 2
        idx = int(np.argmin(d2))
        snapped_nodes.append(nodes[idx])
        weights.append(float(w))

    # aggregate weights per snapped node
    pop_by_node = {}
    for n, w in zip(snapped_nodes, weights):
        pop_by_node[n] = pop_by_node.get(n, 0.0) + w

    demand_nodes = list(pop_by_node.keys())
    demand_weights = np.array([pop_by_node[n] for n in demand_nodes], dtype=float)

    # --- Precompute shortest paths from all candidate nodes to all demand nodes ---
    # optimization: only compute for relevant nodes if graph is huge, but here it's small.
    # We need dist(candidate, demand_node) for all pairs.
    # Repeated Dijkstra from strictly possible candidates is efficient enough.
    
    # Pre-calculate distances from all nodes to all demand nodes
    # scores[candidate][demand_node] = distance
    dist_matrix = {}
    
    # If graph is large, we might want to limit candidates, but for this grid size, all nodes are fine.
    
    print(f"Precomputing paths for {len(nodes)} candidates and {len(demand_nodes)} demand clusters...")
    
    # We can run Dijkstra from each demand node to all other nodes (reverse), 
    # but since graph is undirected, dist(a,b) == dist(b,a).
    # Since |demand_nodes| usually < |nodes|, let's run from demand nodes.
    
    for dn in demand_nodes:
        # dists from dn to all other nodes
        lengths = nx.single_source_dijkstra_path_length(G, dn, weight=weight_key)
        dist_matrix[dn] = lengths

    # --- Greedy Selection ---
    
    chosen_stops = []
    
    # distinct demand nodes coverage state
    # current_min_walk[dn] = current walking distance to nearest chosen stop
    current_min_walk = {dn: float('inf') for dn in demand_nodes}
    
    for i in range(k):
        best_candidate = None
        best_reduction = -1.0
        
        # Try every node as the next stop
        for candidate in nodes:
            reduction = 0.0
            for dn, w in zip(demand_nodes, demand_weights):
                # distance from this demand node to this candidate
                dist = dist_matrix[dn].get(candidate, float('inf'))
                
                # if this candidate is closer than what we have efficiently
                current_dist = current_min_walk[dn]
                
                if dist < current_dist:
                    # improvement term
                    improvement = (current_dist - dist) * w 
                    reduction += improvement
            
            if reduction > best_reduction:
                best_reduction = reduction
                best_candidate = candidate
        
        if best_candidate is None or best_reduction <= 0:
             print("No further improvement found.")
             break
             
        chosen_stops.append(best_candidate)
        
        # Update current best walks
        for dn in demand_nodes:
            dist = dist_matrix[dn].get(best_candidate, float('inf'))
            if dist < current_min_walk[dn]:
                current_min_walk[dn] = dist
                
    # Return stop coordinates in same CRS as graph
    stops = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in chosen_stops]
    return stops


