import math
import logging
from typing import List, Tuple

from sklearn.neighbors import KDTree as kdt


def distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """
    Calculate Euclidean distance between two points.
    """
    return math.sqrt(sum((i - j) ** 2 for i, j in zip(a, b)))


# Initial connections using k-d tree
def kdtree(clients, base_stations):
    """
    Assign clients to base stations using a k-d tree for initial connections.
    """
    c_coor = [(c.x, c.y) for c in clients]
    bs_coor = [p.coverage.center for p in base_stations]

    tree = KDTree(bs_coor, leaf_size=2)
    res = tree.query(c_coor)

    for c, d, p in zip(clients, res[0], res[1]):
        if d[0] <= base_stations[p[0]].coverage.radius:
            c.base_station = base_stations[p[0]]


class KDTree:
    last_run_time = 0
    limit = None

    # Initial connections using k-d tree
    @staticmethod
    def run(clients, base_stations, run_at: int, assign: bool = True):
        """
        Run the KDTree assignment for clients and base stations.
        """
        logging.debug(f'KDTREE CALL [{run_at}] - limit: {KDTree.limit}')
        if run_at == KDTree.last_run_time:
            return
        KDTree.last_run_time = run_at

        c_coor = [(c.x, c.y) for c in clients]
        bs_coor = [p.coverage.center for p in base_stations]

        k = min(KDTree.limit, len(base_stations)) if KDTree.limit else len(base_stations)
        tree = kdt(bs_coor, leaf_size=2)
        res = tree.query(c_coor, k=k)

        for c, d, p in zip(clients, res[0], res[1]):
            if assign and d[0] <= base_stations[p[0]].coverage.radius:
                c.base_station = base_stations[p[0]]
            c.closest_base_stations = [(a, base_stations[b]) for a, b in zip(d, p)]


def format_bps(size: float, pos=None, return_float: bool = False) -> str:
    """
    Format a size in bits per second to a human-readable string.
    """
    power, n = 1000, 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size >= power:
        size /= power
        n += 1
    if return_float:
        return f'{size:.3f} {power_labels[n]}bps'
    return f'{size:.0f} {power_labels[n]}bps'


# --- 新增内容: 卫星 TLE 读取器 ---
from skyfield.api import load, wgs84


def load_satellites_from_tle(tle_file_path):
    """读取 TLE 文件并返回卫星对象列表"""
    ts = load.timescale()
    satellites = load.tle_file(tle_file_path)
    print(f"成功加载 {len(satellites)} 颗卫星")
    return satellites, ts


def get_satellite_position(sat, t):
    """计算特定时间卫星的 (x, y) 坐标 (投影到地面)"""
    geocentric = sat.at(t)
    subpoint = wgs84.subpoint(geocentric)
    # 这里为了简化适配 5G 模型，我们将经纬度映射为 x, y
    # 实际项目中可能需要更复杂的坐标转换
    return subpoint.latitude.degrees, subpoint.longitude.degrees