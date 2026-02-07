import operator
import random
from .utils import distance


class Client:
    def __init__(self, pk: int, env, x: float, y: float, mobility_pattern,
                 usage_freq: float, subscribed_slice_index: int, stat_collector,
                 slice_name: str,
                 map_limits=None,
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
        self.map_limits = map_limits

        # === [新增] 业务类型区分 ===
        # 如果是 eMBB 切片，随机分配 Video (重载) 或 Web (轻载)
        # 这通过 priority_weight 影响资源分配
        self.traffic_class = "standard"
        self.priority_weight = 1.0

        if "embb" in self.slice_name.lower():
            if random.random() < 0.4:  # 40% 概率是高清视频用户
                self.traffic_class = "video_hd"
                self.priority_weight = 2.0  # 抢占能力强
            else:
                self.traffic_class = "web_browsing"
                self.priority_weight = 0.8  # 抢占能力弱

        # 其他属性保持不变...
        self.backup_candidates = []
        self.last_usage_primary = 0
        self.usage_remaining = 0
        self.closest_base_stations = []
        self.connected = False
        self.total_consume_time = 0
        self.total_usage = 0
        self.total_request_count = 0
        self.action = env.process(self.run())

    # ... run, try_fast_handover, handle_handover, connect 方法保持不变 ...
    # (为了节省篇幅，此处省略未修改的样板代码，请保留原文件中的这些方法)
    def run(self):
        # 保持原样...
        yield self.env.timeout(random.uniform(0, 1.0))
        while True:
            # ... (逻辑同原文件)
            if int(self.env.now) % 2 == 0 and self.connected and self.base_station:
                current_slice = self.get_slice(self.base_station)
                if current_slice and current_slice.require_backup:
                    self.update_backup_strategy()
                    if self.backup_candidates and random.random() < 0.05:
                        self.try_fast_handover()

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

            if not self.connected:
                self.search_and_connect()

            yield self.env.timeout(0.25)
            if self.connected:
                self.release_consume()
                if self.usage_remaining <= 0: self.disconnect()
            yield self.env.timeout(0.25)

            dx, dy = self.mobility_pattern.generate_movement()
            self.x += dx
            self.y += dy

            if self.map_limits:
                x_min, x_max = self.map_limits[0]
                y_min, y_max = self.map_limits[1]
                w, h = x_max - x_min, y_max - y_min
                if self.x < x_min: self.x += w
                if self.x > x_max: self.x -= w
                if self.y < y_min: self.y += h
                if self.y > y_max: self.y -= h

            if self.base_station is not None:
                if not self.base_station.coverage.is_in_coverage(self.x, self.y):
                    yield self.env.process(self.handle_handover())

    def try_fast_handover(self):
        # 保持原样...
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
        # 保持原样...
        self.disconnect()
        self.stat_collector.incr_handover_attempt(self.slice_name)
        yield self.env.timeout(random.uniform(1.0, 3.0))
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
        # 保持原样...
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
        # 保持原样...
        target_bs = bs if bs is not None else self.base_station
        if target_bs is None: return None
        if self.subscribed_slice_index < len(target_bs.slices):
            return target_bs.slices[self.subscribed_slice_index]
        return None

    def disconnect(self):
        # 保持原样...
        if self.connected:
            s_p = self.get_slice(self.base_station)
            if s_p and self.base_station.active:
                s_p.connected_users -= 1
            self.connected = False
            self.backup_candidates = []
        return not self.connected

    def generate_usage_and_connect(self):
        # 保持原样...
        if self.usage_freq < random.random() and self.get_slice(self.base_station) is not None:
            self.usage_remaining = self.get_slice(self.base_station).usage_pattern.generate()
            self.total_request_count += 1
            self.connect()

    def start_consume(self):
        if not self.base_station or not self.base_station.active: return
        s_p = self.get_slice(self.base_station)
        if s_p and s_p.capacity:
            # === [修改] 传递 priority_weight 给 Slice ===
            # 让 Slice 根据权重和拥塞情况决定分配量
            allocated = s_p.get_consumable_share(priority_weight=self.priority_weight)
            base = min(allocated, self.usage_remaining)

            if s_p.capacity.level >= base:
                s_p.capacity.get(base)
                self.last_usage_primary = base
            else:
                self.last_usage_primary = 0

    def release_consume(self):
        # 保持原样...
        s_p = self.get_slice(self.base_station)
        if s_p and self.base_station.active and self.last_usage_primary > 0:
            s_p.capacity.put(self.last_usage_primary)
            self.total_consume_time += 1
            self.total_usage += self.last_usage_primary
            self.usage_remaining -= self.last_usage_primary
        self.last_usage_primary = 0

    def _find_candidates(self, exclude=None):
        # 保持原样...
        candidates = []
        for d, b in self.closest_base_stations:
            if exclude and b.pk in exclude: continue
            candidates.append((d, b))
        candidates.sort(key=operator.itemgetter(0))
        return candidates

    def search_and_connect(self):
        # 保持原样...
        candidates = self._find_candidates()
        for dist, bs in candidates[:3]:
            if bs.active and bs.coverage.is_in_coverage(self.x, self.y):
                s = self.get_slice(bs)
                if s and s.is_available(s.bandwidth_guaranteed):
                    self.base_station = bs
                    self.connect()
                    break

    def update_backup_strategy(self):
        # 保持原样...
        candidates = self._find_candidates(exclude=[self.base_station.pk])
        selected = []
        for i in range(len(candidates)):
            if len(selected) >= 2: break
            selected.append(candidates[i][1])
        self.backup_candidates = selected