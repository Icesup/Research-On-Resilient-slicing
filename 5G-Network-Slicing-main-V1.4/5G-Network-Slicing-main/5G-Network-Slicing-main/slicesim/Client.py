import operator
import random
from .utils import distance


class Client:
    def __init__(self, pk: int, env, x: float, y: float, mobility_pattern,
                 usage_freq: float, subscribed_slice_index: int, stat_collector,
                 slice_name: str,
                 map_limits=None,  # [新增] 接收边界参数
                 base_station=None):
        self.pk = pk
        self.env = env
        self.x = x
        self.y = y
        self.mobility_pattern = mobility_pattern
        self.usage_freq = usage_freq
        self.subscribed_slice_index = subscribed_slice_index
        self.slice_name = slice_name
        self.stat_collector = stat_collector
        self.base_station = base_station
        self.map_limits = map_limits  # [新增]

        self.backup_candidates = []
        self.last_usage_primary = 0
        self.usage_remaining = 0
        self.closest_base_stations = []
        self.connected = False
        self.total_consume_time = 0
        self.total_usage = 0
        self.total_request_count = 0
        self.action = env.process(self.run())

    def run(self):
        yield self.env.timeout(random.uniform(0, 1.0))
        while True:
            # 策略更新：仅对需要备份的切片（如 URLLC）维护候选列表
            if int(self.env.now) % 2 == 0 and self.connected and self.base_station:
                current_slice = self.get_slice(self.base_station)
                if current_slice and current_slice.require_backup:
                    self.update_backup_strategy()
                    if self.backup_candidates and random.random() < 0.05:
                        self.try_fast_handover()

            # 状态检查
            if self.base_station is not None:
                if not self.base_station.active:
                    self.stat_collector.incr_handover_attempt(self.slice_name)
                    if not self.try_fast_handover():
                        self.connected = False
                        yield self.env.process(self.handle_handover())
                elif self.usage_remaining > 0:
                    if self.connected:
                        self.start_consume()
                    else:
                        self.connect()
                else:
                    if self.connected:
                        self.disconnect()
                    else:
                        self.generate_usage_and_connect()

            yield self.env.timeout(0.25)
            if self.connected:
                self.release_consume()
                if self.usage_remaining <= 0: self.disconnect()
            yield self.env.timeout(0.25)

            # === [核心修改] 移动与环面穿越 (Toroidal Wrap-around) ===
            # 这是标准的仿真移动模型：从右边出去，从左边进来。
            # 保证用户永远在地图内，且密度均匀，不会堆积。
            dx, dy = self.mobility_pattern.generate_movement()
            self.x += dx
            self.y += dy

            if self.map_limits:
                x_min, x_max = self.map_limits[0]
                y_min, y_max = self.map_limits[1]
                width = x_max - x_min
                height = y_max - y_min

                if self.x < x_min: self.x += width
                if self.x > x_max: self.x -= width
                if self.y < y_min: self.y += height
                if self.y > y_max: self.y -= height

            if self.base_station is not None:
                out = not self.base_station.coverage.is_in_coverage(self.x, self.y)
                if out: yield self.env.process(self.handle_handover())
            else:
                self.search_and_connect()
            yield self.env.timeout(0.25)

    def try_fast_handover(self):
        for backup_bs in self.backup_candidates:
            if backup_bs.active and backup_bs.coverage.is_in_coverage(self.x, self.y):
                s_b = self.get_slice(backup_bs)
                if s_b and s_b.is_available(s_b.bandwidth_guaranteed):
                    self.release_consume()
                    old_bs = self.base_station
                    self.base_station = backup_bs
                    self.backup_candidates = []

                    if old_bs != self.base_station:
                        self.stat_collector.incr_handover_count(self.slice_name)
                    self.stat_collector.incr_handover_success(self.slice_name)
                    self.connected = True

                    if self.usage_remaining > 0: self.start_consume()
                    return True
        return False

    def handle_handover(self):
        self.disconnect()
        self.stat_collector.incr_handover_attempt(self.slice_name)
        delay = random.uniform(1.0, 3.0)
        yield self.env.timeout(delay)
        candidates = self._find_candidates()
        found = False
        for dist, bs in candidates[:5]:
            yield self.env.timeout(0.1)
            if bs.active and bs.coverage.is_in_coverage(self.x, self.y):
                s = self.get_slice(bs)
                if s and s.is_available(s.bandwidth_guaranteed):
                    self.base_station = bs
                    found = True
                    break
        if found:
            self.stat_collector.incr_handover_success(self.slice_name)
            self.stat_collector.incr_handover_count(self.slice_name)
            if self.usage_remaining > 0: self.connect()
        else:
            self.base_station = None

    def connect(self):
        if self.connected or self.base_station is None: return
        if not self.base_station.active: return
        s_p = self.get_slice(self.base_station)
        if not s_p: return

        self.stat_collector.incr_connect_attempt(self.slice_name)

        if s_p.is_available(s_p.bandwidth_guaranteed):
            if s_p.require_backup: self.update_backup_strategy()
            s_p.connected_users += 1
            self.connected = True
        else:
            self.stat_collector.incr_block_count(self.slice_name)

    def get_slice(self, bs=None):
        target_bs = bs if bs is not None else self.base_station
        if target_bs is None: return None
        if self.subscribed_slice_index < len(target_bs.slices):
            return target_bs.slices[self.subscribed_slice_index]
        return None

    def disconnect(self):
        if self.connected:
            s_p = self.get_slice(self.base_station)
            if s_p and self.base_station.active:
                s_p.connected_users -= 1
            self.connected = False
            self.backup_candidates = []
        return not self.connected

    def generate_usage_and_connect(self):
        if self.usage_freq < random.random() and self.get_slice(self.base_station) is not None:
            self.usage_remaining = self.get_slice(self.base_station).usage_pattern.generate()
            self.total_request_count += 1
            self.connect()

    def start_consume(self):
        if not self.base_station or not self.base_station.active: return
        s_p = self.get_slice(self.base_station)
        if s_p and s_p.capacity:
            base = min(s_p.get_consumable_share(), self.usage_remaining)
            if s_p.capacity.level >= base:
                s_p.capacity.get(base)
                self.last_usage_primary = base
            else:
                self.last_usage_primary = 0

    def release_consume(self):
        s_p = self.get_slice(self.base_station)
        if s_p and self.base_station.active and self.last_usage_primary > 0:
            s_p.capacity.put(self.last_usage_primary)
            self.total_consume_time += 1
            self.total_usage += self.last_usage_primary
            self.usage_remaining -= self.last_usage_primary
        self.last_usage_primary = 0

    def _find_candidates(self, exclude=None):
        candidates = []
        for d, b in self.closest_base_stations:
            if exclude and b.pk in exclude: continue
            candidates.append((d, b))
        candidates.sort(key=operator.itemgetter(0))
        return candidates

    def search_and_connect(self):
        candidates = self._find_candidates()
        for dist, bs in candidates[:3]:
            if bs.active and bs.coverage.is_in_coverage(self.x, self.y):
                s = self.get_slice(bs)
                if s and s.is_available(s.bandwidth_guaranteed):
                    self.base_station = bs
                    self.connect()
                    break

    def update_backup_strategy(self):
        # [优化] 放宽备份选择策略，只要是覆盖范围内的其他卫星都行
        candidates = self._find_candidates(exclude=[self.base_station.pk])
        selected = []
        for i in range(len(candidates)):
            if len(selected) >= 2: break
            selected.append(candidates[i][1])
        self.backup_candidates = selected