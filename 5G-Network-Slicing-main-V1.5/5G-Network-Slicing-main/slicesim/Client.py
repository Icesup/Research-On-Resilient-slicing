import operator
import random
from .utils import distance


class Client:
    def __init__(self, pk: int, env, x: float, y: float, mobility_pattern,
                 usage_freq: float, subscribed_slice_index: int, stat_collector,
                 slice_name: str,
                 map_limits=None,
                 base_station=None,
                 resilience_config: dict = None):
        self.pk = pk
        self.env = env
        self.x = x
        self.y = y

        self.rng = random.Random(self.pk + 1000)

        self.mobility_pattern = mobility_pattern
        self.usage_freq = usage_freq
        self.subscribed_slice_index = subscribed_slice_index
        self.slice_name = slice_name
        self.stat_collector = stat_collector
        self.base_station = base_station
        self.map_limits = map_limits

        self.res_config = resilience_config if resilience_config else {}
        self.traffic_class = "standard"
        self.priority_weight = 1.0

        enable_qos = self.res_config.get('enable_qos', False)

        if "embb" in self.slice_name.lower():
            if self.rng.random() < 0.4:
                self.traffic_class = "video_hd"
                self.priority_weight = 2.0 if enable_qos else 1.0
            else:
                self.traffic_class = "web_browsing"
                self.priority_weight = 1.0

        if "urllc" in self.slice_name.lower():
            self.priority_weight = 1.0

        self.backup_candidates = []
        self.last_usage_primary = 0
        self.usage_remaining = 0
        self.closest_base_stations = []
        self.connected = False
        self.total_consume_time = 0
        self.total_usage = 0
        self.total_request_count = 0
        self.action = env.process(self.run())

    def _is_service_available_on(self, bs):
        if bs is None or not bs.active: return False
        s = self.get_slice(bs)
        if s is None: return False
        # [修复核心] 只有 URLLC 会因为故障彻底断供。mMTC(风暴)和eMBB(降级)依旧允许接受接入控制(CAC)的审核
        if getattr(s, 'is_faulty', False) and 'urllc' in self.slice_name.lower():
            return False
        return True

    def _generate_usage(self):
        if 'embb' in self.slice_name.lower(): return self.rng.randint(2000000, 8000000)
        if 'urllc' in self.slice_name.lower(): return self.rng.randint(50000, 200000)
        if 'mmtc' in self.slice_name.lower(): return self.rng.randint(5000, 20000)
        return self.rng.randint(10000, 50000)

    def _generate_movement(self):
        return self.rng.normalvariate(0, 2), self.rng.normalvariate(0, 2)

    def run(self):
        yield self.env.timeout(self.rng.uniform(0, 1.0))
        while True:
            enable_lb = self.res_config.get('enable_active_lb', False)
            enable_ho = self.res_config.get('enable_fast_ho', False)

            if int(self.env.now) % 3 == 0 and self.connected and self.base_station:
                current_slice = self.get_slice(self.base_station)
                if current_slice and current_slice.require_backup:
                    if enable_lb or enable_ho:
                        self.update_backup_strategy()
                    if enable_lb and self.backup_candidates:
                        curr_cap = current_slice.init_capacity * current_slice.capacity_factor
                        used_cap = current_slice.connected_users * current_slice.bandwidth_guaranteed
                        if curr_cap > 0 and (used_cap / curr_cap) > 0.85:
                            if self.rng.random() < 0.2:
                                self.try_fast_handover()

            if self.base_station is not None:
                current_slice = self.get_slice(self.base_station)
                is_degraded = current_slice and getattr(current_slice, 'emergency_mode',
                                                        False) and current_slice.capacity_factor < 0.5

                if not self._is_service_available_on(self.base_station):
                    self.stat_collector.incr_handover_attempt(self.slice_name)
                    success = False
                    if enable_ho:
                        success = self.try_fast_handover()
                    if not success:
                        self.connected = False
                        yield self.env.process(self.handle_handover())
                elif is_degraded and enable_ho:
                    success = self.try_fast_handover()
                    if not success:
                        if self.usage_remaining > 0:
                            if self.connected:
                                self.start_consume()
                            else:
                                self.connect()
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

            dx, dy = self._generate_movement()
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
        for backup_bs in self.backup_candidates:
            if backup_bs.active and backup_bs.coverage.is_in_coverage(self.x, self.y):
                s_b = self.get_slice(backup_bs)
                # [修复] 统一使用 _is_service_available_on，不再一刀切屏蔽 is_faulty
                if s_b and self._is_service_available_on(backup_bs):
                    if s_b.is_available(s_b.bandwidth_guaranteed * 0.1):
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
        yield self.env.timeout(self.rng.uniform(1.0, 3.0))
        candidates = self._find_candidates()
        found = False
        for dist, bs in candidates[:5]:
            yield self.env.timeout(0.1)
            if bs.active and bs.coverage.is_in_coverage(self.x, self.y):
                s = self.get_slice(bs)
                # [修复] 允许接入降级/风暴状态但容量仍然充足的切片
                if s and self._is_service_available_on(bs) and s.is_available(s.bandwidth_guaranteed):
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
        if not self._is_service_available_on(self.base_station): return
        s_p = self.get_slice(self.base_station)
        if not s_p: return
        self.stat_collector.incr_connect_attempt(self.slice_name)

        if s_p.is_available(s_p.bandwidth_guaranteed):
            if s_p.require_backup: self.update_backup_strategy()
            s_p.connected_users += 1
            self.connected = True
        else:
            self.stat_collector.incr_block_count(self.slice_name)
            if 'mmtc' in self.slice_name.lower() and self.res_config.get('enable_fast_ho', False):
                if not self.connected:
                    if not self.backup_candidates:
                        self.update_backup_strategy()
                    self.try_fast_handover()

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
                s_p.connected_users = max(0, s_p.connected_users - 1)
            self.connected = False
            self.backup_candidates = []
        return not self.connected

    def generate_usage_and_connect(self):
        if self.usage_freq < self.rng.random() and self._is_service_available_on(self.base_station):
            self.usage_remaining = self._generate_usage()
            self.total_request_count += 1
            self.connect()

    def start_consume(self):
        if not self._is_service_available_on(self.base_station): return
        s_p = self.get_slice(self.base_station)
        if s_p and s_p.capacity:
            allocated = s_p.get_consumable_share(priority_weight=self.priority_weight)
            actual_capacity = s_p.init_capacity * s_p.capacity_factor

            if getattr(s_p, 'emergency_mode', False) and s_p.res_config.get('enable_guard_release', False):
                actual_capacity += s_p.init_capacity * 0.40

            current_used = s_p.capacity.capacity - s_p.capacity.level
            max_can_allocate = max(0.0, actual_capacity - current_used)

            base = min(allocated, self.usage_remaining, max_can_allocate)
            available = s_p.capacity.level
            actual_take = min(base, available)

            if actual_take > 0:
                s_p.capacity.get(actual_take)
                self.last_usage_primary = actual_take
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
                # [修复] 统一解除寻址硬隔离
                if s and self._is_service_available_on(bs) and s.is_available(s.bandwidth_guaranteed):
                    self.base_station = bs
                    self.connect()
                    break

    def update_backup_strategy(self):
        candidates = self._find_candidates(exclude=[self.base_station.pk])
        selected = []
        for i in range(len(candidates)):
            if len(selected) >= 2: break
            selected.append(candidates[i][1])
        self.backup_candidates = selected