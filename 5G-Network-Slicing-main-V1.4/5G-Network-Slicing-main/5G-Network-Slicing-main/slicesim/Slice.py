import simpy


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

        # === V13 风格初始化 ===
        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False

    def get_consumable_share(self) -> float:
        """
        [V13 原版逻辑] 简单的线性均分
        """
        # 计算当前物理总容量
        current_total_cap = self.init_capacity * self.capacity_factor

        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)
        else:
            # 直接均分，不搞复杂的拥塞惩罚
            return min(current_total_cap / self.connected_users, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        [V13 原版逻辑] 准入控制
        这是 mMTC 能够正常"削峰"（产生阻塞）的关键逻辑
        """
        if self.capacity is None: return False

        # 1. 物理容量
        real_total_capacity = self.init_capacity * self.capacity_factor

        # 2. 名义已用
        virtual_used = self.connected_users * self.bandwidth_guaranteed

        # 3. 新需求
        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        # 4. [V13 核心] 韧性余量 (Resilience Headroom)
        # 故障组(False)必须保留 5% 余量 -> 导致更容易阻塞(削峰)
        # 韧性组(True)可以吃到 0 -> 允许更多接入
        limit = 0 if self.require_backup else (real_total_capacity * 0.05)

        # 5. 准入判定
        if (virtual_used + demand + limit) > real_total_capacity:
            return False

        return True