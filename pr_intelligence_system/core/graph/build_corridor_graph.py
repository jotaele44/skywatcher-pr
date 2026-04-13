import networkx as nx
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def build_corridor_graph(df: pd.DataFrame, max_distance_deg: float = 0.1) -> nx.Graph:
    """Build an undirected spatial corridor graph from a point DataFrame.

    Nodes are DataFrame row indices; edges connect any two points whose
    Euclidean degree-distance is ≤ max_distance_deg.  Edge weight = distance.

    For performance, limit df to a representative sample before calling.
    """
    G = nx.Graph()

    if len(df) == 0:
        logger.warning("Empty DataFrame – returning empty corridor graph")
        return G

    # Add nodes with spatial attributes
    for idx, row in df.iterrows():
        G.add_node(
            idx,
            lat=float(row['lat']),
            lon=float(row['lon']),
            cell_id=str(row.get('cell_id', idx)),
        )

    # Add proximity edges (O(n²), keep df small)
    coords = df[['lat', 'lon']].values
    n = len(coords)
    indices = df.index.tolist()

    for i in range(n):
        for j in range(i + 1, n):
            dlat = coords[i][0] - coords[j][0]
            dlon = coords[i][1] - coords[j][1]
            dist = np.sqrt(dlat ** 2 + dlon ** 2)
            if dist <= max_distance_deg:
                G.add_edge(indices[i], indices[j], weight=float(dist))

    logger.info(
        f"Corridor graph: {G.number_of_nodes()} nodes, "
        f"{G.number_of_edges()} edges "
        f"(max_dist={max_distance_deg}°)"
    )
    return G


def get_graph_metrics(G: nx.Graph) -> dict:
    """Return basic topology metrics for a graph."""
    return {
        'num_nodes':                  G.number_of_nodes(),
        'num_edges':                  G.number_of_edges(),
        'num_connected_components':   nx.number_connected_components(G),
        'density':                    nx.density(G) if G.number_of_nodes() > 1 else 0.0,
    }
