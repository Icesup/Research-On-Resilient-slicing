import simpy
import math


class Slice:
    def __init__(self, name: str, ratio: float,
                 connected_users: int, user_share: float, delay_tolerance: float, qos_class: int,
                 bandwidth_guaranteed: float, bandwidth_max: float, init_capacity: float,
                 usage_pattern, resilience_policy: dict = None,
                 qor_metric: str = "loss_area", name_display: str = None,
                 # [新增] 接收细粒度的韧性配置
                 resilience_config: dict = None):

        self.name = name
        self.name_display = name_display if name_display else name
        self.qor_metric = qor_metric

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

        # === 韧性配置解析 ===
        # resilience_config 用于消融实验，控制具体机制的开启/关闭
        # 默认为空字典，表示不强制干预，走 resilience_policy 的默认逻辑
        self.res_config = resilience_config if resilience_config else {}

        # === 策略参数 ===
        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
            self.protection_guard_band = resilience_policy.get('guard_band', 0.05)
            self.congestion_k = resilience_policy.get('congestion_k', 10.0)
            self.congestion_threshold = resilience_policy.get('congestion_threshold', 0.85)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False
            self.protection_guard_band = 0.05
            self.congestion_k = 10.0
            self.congestion_threshold = 0.85

        # [消融实验] 如果配置了 'high_overhead' 强制开启/关闭高开销因子 (URLLC)
        if 'enable_high_overhead' in self.res_config:
            if self.res_config['enable_high_overhead']:
                self.overhead_factor = 1.5  # 示例：强制提高开销因子
            else:
                self.overhead_factor = 1.0

    def _calculate_congestion_factor(self, current_load_ratio: float) -> float:
        # 保持原样...
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
        """
        [修改] 结合消融实验配置，决定是否应用 QoS 权重
        """
        current_total_cap = self.init_capacity * self.capacity_factor
        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)

        nominal_demand = self.connected_users * self.bandwidth_guaranteed
        load_ratio = nominal_demand / current_total_cap if current_total_cap > 0 else 999.0

        congestion_efficiency = self._calculate_congestion_factor(load_ratio)
        base_share = (current_total_cap / self.connected_users) * congestion_efficiency

        # [消融实验] 检查是否允许 QoS 权重机制
        # 如果 enable_qos 为 False，强制 weight = 1.0 (无差异服务)
        use_weight = priority_weight
        if 'enable_qos' in self.res_config and not self.res_config['enable_qos']:
            use_weight = 1.0

        final_share = base_share * use_weight
        return min(final_share, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        [修改] 结合消融实验配置，决定是否允许解封保护带
        """
        if self.capacity is None: return False

        real_total_capacity = self.init_capacity * self.capacity_factor
        virtual_used = self.connected_users * self.bandwidth_guaranteed

        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        # [消融实验] 准入控制 CAC 机制
        # 如果是 mMTC 且 forbid_cac (禁止CAC) 为真，则不进行拥塞判断(只要有物理空间就进)
        # 或者如果要测试 "Only CAC"，则此处逻辑保持。这里主要处理保护带。

        limit = real_total_capacity * self.protection_guard_band  # 默认保留保护带

        # [核心逻辑] 判断是否解封保护带
        # 条件：1. 需要备份 2. 处于紧急模式 3. [新] 消融配置允许解封
        allow_release = True
        if 'enable_guard_release' in self.res_config:
            allow_release = self.res_config['enable_guard_release']

        if self.require_backup and self.emergency_mode and allow_release:
            limit = 0.0

        if (virtual_used + demand + limit) > real_total_capacity:
            return False

        return True

    def set_emergency_mode(self, active: bool):
        self.emergency_mode = active