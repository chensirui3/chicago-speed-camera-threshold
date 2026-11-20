"""Small geometry helpers: project lat/lon to meters and cluster nearby points."""
import numpy as np
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

# NAD83 / UTM zone 16N: planar coordinates in meters, accurate across Chicago.
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:26916", always_xy=True)


def to_meters(lon, lat) -> np.ndarray:
    x, y = _TO_UTM.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.column_stack([x, y])


def single_linkage(xy: np.ndarray, link_m: float) -> np.ndarray:
    """Label points so that any two points chained within link_m share a label."""
    pairs = cKDTree(xy).query_pairs(link_m, output_type="ndarray")
    n = len(xy)
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    return connected_components(graph, directed=False)[1]
