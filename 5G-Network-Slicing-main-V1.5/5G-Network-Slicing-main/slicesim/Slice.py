import simpy
import math
import random


class Slice:
    def __init__(self, name: str, ratio: float,
                 connected_users: int, user_share: float, delay_tolerance: float, qos_class: int,
                 bandwidth_guaranteed: float, bandwidth_max: float, init_capacity: float,
                 usage_pattern, resilience_policy: dict = None,
                 qor_metric: str = "loss_area", name_display: str = None,
                 resilience_config: dict = None):

        self.name = name
        self.name_display = name_display if name_display else name
        self.qor_metric = qor_metric
        self.base_station = None

        self.connected_users = connected_users
        self.user_share = user_share
        self.delay_tolerance = delay_tolerance
        self.qos_class = qos_class
        self.ratio = ratio
        self.bandwidth_guaranteed = bandwidth_guaranteed
        self.bandwidth_max = bandwidth_max
        self.init_capacity = init_capacity
        self.usage_pattern = usage_pattern
        self.capacity = None

        self.capacity_factor = 1.0
        self.emergency_mode = False
        self.is_faulty = False
        self.res_config = resilience_config if resilience_config else {}

        # 切片独立沙盒
        seed_val = sum(ord(c) for c in name) + 2000
        self.rng = random.Random(seed_val)

        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
            self.protection_guard_band = resilience_policy.get('guard_band', 0.15)
            self.congestion_k = resilience_policy.get('congestion_k', 10.0)
            self.congestion_threshold = resilience_policy.get('congestion_threshold', 0.85)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False
            self.protection_guard_band = 0.15
            self.congestion_k = 10.0
            self.congestion_threshold = 0.85

        self.is_overprovisioned = self.res_config.get('enable_high_overhead', False)

    def _calculate_congestion_factor(self, current_load_ratio: float) -> float:
        if self.res_config.get('enable_qos', False) or self.res_config.get('enable_guard_release', False):
            if current_load_ratio > 2.0: return 0.5
            return 1.0

        if current_load_ratio > 1.5: return 0.1
        try:
            val = 1.0 / (1.0 + math.exp(self.congestion_k * (current_load_ratio - self.congestion_threshold)))
        except OverflowError:
            val = 0.0
        if current_load_ratio <= self.congestion_threshold:
            return 1.0
        else:
            penalty = math.pow((current_load_ratio - self.congestion_threshold) * 2, 2)
            return max(0.1, 1.0 - penalty)

    def get_consumable_share(self, priority_weight: float = 1.0) -> float:
        current_total_cap = self.init_capacity * self.capacity_factor

        if self.emergency_mode and self.res_config.get('enable_guard_release', False):
            current_total_cap += self.init_capacity * 0.40

        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)

        # 严格隔离：仅 mMTC 且开启 CAC 时才压缩统计带宽
        virtual_used_bw = self.bandwidth_guaranteed
        if 'mmtc' in self.name.lower() and self.is_faulty and self.res_config.get('enable_cac', False):
            virtual_used_bw *= 0.15

        nominal_demand = self.connected_users * virtual_used_bw
        load_ratio = nominal_demand / current_total_cap if current_total_cap > 0 else 999.0

        congestion_efficiency = self._calculate_congestion_factor(load_ratio)
        base_share = (current_total_cap / self.connected_users) * congestion_efficiency

        use_weight = priority_weight
        if self.res_config.get('enable_qos', False) and 'embb' in self.name.lower():
            use_weight = priority_weight * 5.0

        final_share = base_share * use_weight
        return min(final_share, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        if self.capacity is None: return False

        if 'mmtc' in self.name.lower():
            if self.is_faulty:
                if not self.res_config.get('enable_cac', False):
                    if self.rng.random() < 0.80:
                        return False
                else:
                    requested_amount = (requested_amount if requested_amount > 0 else self.bandwidth_guaranteed) * 0.15

        if 'urllc' in self.name.lower() and self.is_faulty:
            return False

        real_total_capacity = self.init_capacity * self.capacity_factor

        if getattr(self, 'emergency_mode', False) and self.res_config.get('enable_guard_release', False):
            real_total_capacity += self.init_capacity * 0.40

        if self.is_overprovisioned:
            real_total_capacity *= 1.3

        # 严格隔离：确保基站判定总容量时，已连接的 mMTC 用户的账面占用也是被压缩过的
        virtual_used_bw = self.bandwidth_guaranteed
        if 'mmtc' in self.name.lower() and self.is_faulty and self.res_config.get('enable_cac', False):
            virtual_used_bw *= 0.15

        virtual_used = self.connected_users * virtual_used_bw
        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        limit = real_total_capacity * self.protection_guard_band

        if self.emergency_mode and self.res_config.get('enable_guard_release', False):
            limit = 0.0
        if 'urllc' in self.name.lower() and self.res_config.get('enable_qos', False):
            limit = 0.0

        if (virtual_used + demand + limit) > real_total_capacity:
            return False

        return True

    def set_emergency_mode(self, active: bool):
        self.emergency_mode = active