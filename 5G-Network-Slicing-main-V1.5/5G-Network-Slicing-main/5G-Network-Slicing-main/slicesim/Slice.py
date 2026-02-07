import simpy
import math


class Slice:
    def __init__(self, name: str, ratio: float,
                 connected_users: int, user_share: float, delay_tolerance: float, qos_class: int,
                 bandwidth_guaranteed: float, bandwidth_max: float, init_capacity: float,
                 usage_pattern, resilience_policy: dict = None,
                 qor_metric: str = "loss_area", name_display: str = None):

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

        # === [新增] 紧急模式状态标志 ===
        # 默认为 False (平时状态)，此时必须遵守保护带限制
        self.emergency_mode = False

        # === [修改] 工程化配置代替硬编码 ===
        # 默认预留 5% 保护带，可通过 resilience_policy 配置
        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
            self.protection_guard_band = resilience_policy.get('guard_band', 0.05)
            # 拥塞控制参数: k (陡峭度), threshold (临界负载率)
            self.congestion_k = resilience_policy.get('congestion_k', 10.0)
            self.congestion_threshold = resilience_policy.get('congestion_threshold', 0.85)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False
            self.protection_guard_band = 0.05
            self.congestion_k = 10.0
            self.congestion_threshold = 0.85

    def _calculate_congestion_factor(self, current_load_ratio: float) -> float:
        """
        [新增] 使用 Sigmoid 函数模拟网络性能在由轻载向重载过渡时的非线性坍塌。
        相比简单的线性均分，这能更真实地反映 eMBB 在高并发下的体验恶化。
        """
        # 防止数学溢出
        if current_load_ratio > 1.5: return 0.1

        # Sigmoid 变体: f(x) = 1 / (1 + e^(k * (x - x0)))
        # 当负载 x 超过 x0 (threshold) 时，因子急剧下降
        try:
            val = 1.0 / (1.0 + math.exp(self.congestion_k * (current_load_ratio - self.congestion_threshold)))
        except OverflowError:
            val = 0.0

        # 归一化：保证低负载时因子接近 1.0
        if current_load_ratio <= self.congestion_threshold:
            return 1.0
        else:
            # 超过阈值后的线性+指数混合惩罚
            penalty = math.pow((current_load_ratio - self.congestion_threshold) * 2, 2)
            return max(0.1, 1.0 - penalty)

    def get_consumable_share(self, priority_weight: float = 1.0) -> float:
        """
        [修改] 引入拥塞控制和业务优先级
        :param priority_weight: 业务权重 (e.g. Video=1.5, Web=0.5)
        """
        current_total_cap = self.init_capacity * self.capacity_factor

        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)

        # 1. 计算当前负载率 (基于名义保障带宽)
        nominal_demand = self.connected_users * self.bandwidth_guaranteed
        load_ratio = nominal_demand / current_total_cap if current_total_cap > 0 else 999.0

        # 2. 计算拥塞效率因子 (Simulate Collapse)
        congestion_efficiency = self._calculate_congestion_factor(load_ratio)

        # 3. 基于优先级的分配
        # 假设所有用户平均权重为 1.0，则总权重约为 connected_users
        # 这里的逻辑是：资源紧张时，高优先级抢占更多
        base_share = (current_total_cap / self.connected_users) * congestion_efficiency

        # 4. 应用权重并截断
        final_share = base_share * priority_weight

        # 5. 最终限制 (不能超过物理极限或最大设定)
        return min(final_share, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        [修改] 准入控制：平时保留保护带，仅在紧急模式下解封
        """
        if self.capacity is None: return False

        real_total_capacity = self.init_capacity * self.capacity_factor
        virtual_used = self.connected_users * self.bandwidth_guaranteed

        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        # === [核心修改] 动态解封逻辑 ===
        # 只有当：1.切片具备韧性能力(require_backup)  AND  2.处于紧急模式(emergency_mode)
        # 才允许突破保护带 (limit = 0)
        # 否则，必须预留 protection_guard_band (默认5%)
        if self.require_backup and self.emergency_mode:
            limit = 0.0
        else:
            limit = real_total_capacity * self.protection_guard_band

        if (virtual_used + demand + limit) > real_total_capacity:
            return False

        return True

    # [新增] 设置紧急模式开关
    def set_emergency_mode(self, active: bool):
        self.emergency_mode = active