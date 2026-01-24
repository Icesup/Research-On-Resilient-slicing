import simpy
import math


class Slice:
    """
    [V16.3 修复版]
    1. 修复 usage_pattern 缺失导致的 AttributeError。
    2. 维持符合 Bianchi 802.11 模型的非线性效率衰减。
    3. 完善业务细分接口。
    """

    def __init__(self, name: str, ratio: float,
                 connected_users: int, user_share: float, delay_tolerance: float, qos_class: int,
                 bandwidth_guaranteed: float, bandwidth_max: float, init_capacity: float,
                 usage_pattern, resilience_policy: dict = None,
                 qor_metric: str = "loss_area", name_display: str = None):

        # 基础属性初始化
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

        # 【关键修复】：必须显式赋值 usage_pattern 供 Client.py 调用
        self.usage_pattern = usage_pattern

        self.capacity = None
        self.capacity_factor = 1.0

        # 业务细分定义 (针对 eMBB 的精细化管理)
        self.sub_types = {
            'premium': {'weight': 0.7, 'min_guarantee_ratio': 1.2},
            'basic': {'weight': 0.3, 'min_guarantee_ratio': 0.5}
        }

        # 韧性策略与开销 (符合工程实验中的资源消耗代价)
        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.05)
            self.require_backup = resilience_policy.get('require_backup', False)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False

    def get_consumable_share(self) -> float:
        """
        基于 Bianchi 802.11 冲突模型趋势的非线性资源分配
        支撑文献：Bianchi (2000) Performance Analysis
        """
        current_total_cap = self.init_capacity * self.capacity_factor

        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)

        # 模拟拥塞：负载因子 = 当前连接数 / 50(设计基准)
        load_factor = self.connected_users / 50.0

        # 非线性效率函数：模拟信道争用导致的吞吐量坍塌
        # 支撑文献：Shenker (1995) Utility Functions
        efficiency = 1.0 / (1.0 + 0.2 * pow(load_factor, 2))

        # 计算单用户所得带宽（计入韧性开销）
        effective_share = (current_total_cap / self.connected_users) * efficiency / self.overhead_factor

        return min(effective_share, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        准入控制：通过预留安全余量模拟“手机刷不出网”的拥塞感
        """
        if self.capacity is None: return False

        real_total_capacity = self.init_capacity * self.capacity_factor
        virtual_used = self.connected_users * self.bandwidth_guaranteed

        # 物理层安全余量：预留 8% 防止系统崩溃
        safe_margin = 0.08 * real_total_capacity

        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        # 判定：如果剩余空间不足以支撑最低 SLA + 安全余量，则拒绝接入
        if (virtual_used + demand + safe_margin) > real_total_capacity:
            return False

        return True

    def __str__(self) -> str:
        return f'Slice({self.name})'