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

        # 环境干扰因子 (1.0=正常)
        self.capacity_factor = 1.0

        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False

    def get_consumable_share(self) -> float:
        # 计算可用份额时考虑容量因子
        current_total_cap = self.init_capacity * self.capacity_factor
        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)
        else:
            return min(current_total_cap / self.connected_users, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        [核心修改] 连接准入控制 (CAC)
        解决并发连接时不阻塞的问题：必须基于'已连接用户数'来预判负载。
        """
        if self.capacity is None: return False

        # 1. 计算实际物理容量上限 (受故障/雨衰影响)
        real_total_capacity = self.capacity.capacity * self.capacity_factor

        # 2. 计算"名义已用带宽" (Nominal Usage)
        # 即使很多用户暂未传输数据，只要连上了，就必须预留 guaranteed 带宽
        # 这对于 mMTC 这种海量小包业务尤为关键
        virtual_used = self.connected_users * self.bandwidth_guaranteed

        # 3. 计算新请求的预留需求
        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        # 4. 韧性预留阈值 (Resilience Headroom)
        # 普通切片必须保留 5% 的余量，关键切片可以吃到 0
        limit = 0 if self.require_backup else (real_total_capacity * 0.05)

        # 5. 准入判断
        # 如果 (名义已用 + 新需求) 超过了 实际物理容量，则拒绝
        if (virtual_used + demand + limit) > real_total_capacity:
            return False

        return True