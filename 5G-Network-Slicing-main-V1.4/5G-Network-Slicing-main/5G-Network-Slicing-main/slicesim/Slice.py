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

        # === 融合逻辑：正确初始化所有属性 ===
        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
            # 韧性组：开启智能CAC，且没有强制的5%保留限制
            self.enable_cac = True
        else:
            self.overhead_factor = 1.0
            self.require_backup = False
            # 故障组：无智能CAC
            self.enable_cac = False

    def _calculate_efficiency(self, current_capacity):
        """
        [物理核心] 计算拥塞效率因子 (Load-based Efficiency)
        这是为了解决 eMBB 故障组吞吐量虚高的问题。
        """
        if self.connected_users == 0 or current_capacity <= 0:
            return 1.0

        # 计算总需求
        total_demand = self.connected_users * self.bandwidth_guaranteed
        load_ratio = total_demand / current_capacity

        if load_ratio <= 1.0:
            return 1.0
        else:
            # 拥塞崩溃模型 (Congestion Collapse)
            # 即使只有一点点过载，效率也会开始下降
            return 1.0 / (load_ratio ** 1.5)

    def get_consumable_share(self) -> float:
        """
        计算用户实际体验到的带宽 (考虑了拥塞损耗)
        """
        # 1. 物理容量 (受雨衰影响)
        phys_capacity = self.init_capacity * self.capacity_factor

        # 2. 拥塞效率 (受人数影响)
        # 故障组人多 -> 效率低；韧性组人少 -> 效率高
        efficiency = self._calculate_efficiency(phys_capacity)

        # 3. 有效容量 (Goodput)
        effective_capacity = phys_capacity * efficiency

        if self.connected_users <= 0:
            return min(effective_capacity, self.bandwidth_max)
        else:
            return min(effective_capacity / self.connected_users, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        [融合逻辑] 连接准入控制 (CAC)
        结合了旧代码的 Headroom 逻辑和新代码的物理容量判断
        """
        if self.capacity is None: return False

        # 1. 实际物理容量
        real_total_capacity = self.init_capacity * self.capacity_factor

        # 2. 名义已用带宽
        current_load = self.connected_users * self.bandwidth_guaranteed
        new_demand = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed

        # 3. 韧性余量 (Resilience Headroom) - 這是您喜歡的舊邏輯
        # 韧性组(require_backup=True)可以吃满 100%
        # 普通/故障组保留 5% 余量，防止波动
        limit = 0 if self.require_backup else (real_total_capacity * 0.05)

        # 4. 判定逻辑
        if self.enable_cac:
            # === 韧性组 (Smart CAC) ===
            # 严格控制：为了保住 Efficiency=1.0，一旦预测过载立即拒绝
            # 这里必须包含 new_demand
            if (current_load + new_demand) > real_total_capacity:
                return False
        else:
            # === 故障组 (Loose Limit) ===
            # 虽然没有智能 CAC，但物理极限 + 5% 保留位依然存在
            # 这允许它稍微过载一点点，但最终会撞墙
            if (current_load + new_demand + limit) > real_total_capacity:
                return False

        return True