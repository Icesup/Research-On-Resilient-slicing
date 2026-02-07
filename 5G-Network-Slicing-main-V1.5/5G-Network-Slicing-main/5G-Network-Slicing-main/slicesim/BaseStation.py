import math


class BaseStation:
    def __init__(self, pk: int, coverage_radius, capacity_bandwidth: float, slices=None, tle_data=None):
        self.pk = pk
        self.coverage_radius = coverage_radius
        self.capacity_bandwidth = capacity_bandwidth
        self.slices = slices
        self.active = True  # 故障开关

        # === 真实轨道动力学参数 ===
        if not tle_data:
            raise ValueError("必须提供 TLE 数据以保证科研真实性")

        # 解析 TLE
        self.inc = math.radians(tle_data['inc'])
        self.raan = math.radians(tle_data['raan'])
        self.ma_0 = math.radians(tle_data['ma'])
        self.n = tle_data['mm'] * 2 * math.pi / 86400.0  # rad/s
        self.arg_p = 0

        # 物理常数 (Earth + 550km Orbit)
        self.R_earth = 6371.0
        self.h = 550.0
        self.r = self.R_earth + self.h

        # 初始化位置
        self.x = -9999
        self.y = -9999

        from .Coverage import Coverage
        self.coverage = Coverage((self.x, self.y), self.coverage_radius)

    def update_position(self, t_seconds, map_limits):
        """
        基于物理公式计算卫星位置 (Physics-based Propagation)
        这比简单的 x+=v*t 更具说服力
        """
        if not self.active:
            # 即使故障，卫星还在轨道上飞，只是不可用
            # 但为了可视化区分，这里我们继续计算位置
            pass

        # 1. 平近点角传播 M(t) = M0 + n*t
        M_t = self.ma_0 + self.n * t_seconds
        u = M_t  # 圆轨道假设

        # 2. 轨道平面坐标 -> ECI 坐标
        x_p = self.r * math.cos(u)
        y_p = self.r * math.sin(u)

        X = x_p * math.cos(self.raan) - y_p * math.cos(self.inc) * math.sin(self.raan)
        Y = x_p * math.sin(self.raan) + y_p * math.cos(self.inc) * math.cos(self.raan)
        Z = y_p * math.sin(self.inc)

        # 3. ECI -> ECEF (考虑地球自转)
        omega_e = 7.2921159e-5
        theta = omega_e * t_seconds

        x_ecef = X * math.cos(theta) + Y * math.sin(theta)
        y_ecef = -X * math.sin(theta) + Y * math.cos(theta)
        z_ecef = Z

        # 4. ECEF -> 经纬度
        lat = math.degrees(math.asin(z_ecef / self.r))
        lon = math.degrees(math.atan2(y_ecef, x_ecef))

        # 5. 投影到 2000x2000 的视窗 (Map Projection)
        # 我们选取地球上的一块区域作为仿真区
        # 假设区域：经度 -20~20, 纬度 20~60 (覆盖中纬度，卫星多)
        lat_min, lat_max = 20, 60
        lon_min, lon_max = -20, 20

        map_w = map_limits[0][1] - map_limits[0][0]
        map_h = map_limits[1][1] - map_limits[1][0]

        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            # 归一化映射
            norm_x = (lon - lon_min) / (lon_max - lon_min)
            norm_y = (lat - lat_min) / (lat_max - lat_min)

            self.x = map_limits[0][0] + norm_x * map_w
            self.y = map_limits[1][0] + norm_y * map_h
        else:
            # 飞出视窗
            self.x = -9999
            self.y = -9999

        self.coverage.center = (self.x, self.y)

    def __str__(self) -> str:
        return f'BS_{self.pk}'