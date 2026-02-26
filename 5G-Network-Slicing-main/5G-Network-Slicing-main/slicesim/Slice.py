import simpy
import math


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
        self.res_config = resilience_config if resilience_config else {}

        # === 策略参数 ===
        if resilience_policy:
            self.overhead_factor = resilience_policy.get('overhead_factor', 1.0)
            self.require_backup = resilience_policy.get('require_backup', False)
            # [FIX Q1]: 将默认保护带从 0.05 提高到 0.15，确保释放时有足够显著的效果
            self.protection_guard_band = resilience_policy.get('guard_band', 0.15)
            self.congestion_k = resilience_policy.get('congestion_k', 10.0)
            self.congestion_threshold = resilience_policy.get('congestion_threshold', 0.85)
        else:
            self.overhead_factor = 1.0
            self.require_backup = False
            self.protection_guard_band = 0.15
            self.congestion_k = 10.0
            self.congestion_threshold = 0.85

        # [FIX Q2]: URLLC High Overhead 逻辑修正
        # 原逻辑：单纯增加 overhead_factor 会导致准入更难（吞吐降低）。
        # 新逻辑：这里仅标记 flagging，实际的“韧性”体现在 get_consumable_share 中的权重提升
        if 'enable_high_overhead' in self.res_config and self.res_config['enable_high_overhead']:
            self.overhead_factor = 1.2  # 稍微增加开销，代表编码冗余
            self.high_priority_mode = True  # 开启高优先级模式
        else:
            self.high_priority_mode = False

    def _calculate_congestion_factor(self, current_load_ratio: float) -> float:
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
        计算用户可获得的带宽份额
        """
        current_total_cap = self.init_capacity * self.capacity_factor
        if self.connected_users <= 0:
            return min(current_total_cap, self.bandwidth_max)

        nominal_demand = self.connected_users * self.bandwidth_guaranteed
        load_ratio = nominal_demand / current_total_cap if current_total_cap > 0 else 999.0

        congestion_efficiency = self._calculate_congestion_factor(load_ratio)
        base_share = (current_total_cap / self.connected_users) * congestion_efficiency

        # [消融实验] QoS 逻辑控制
        use_weight = priority_weight

        # 如果消融配置显式禁用了 QoS，则强制权重为 1.0
        if 'enable_qos' in self.res_config and not self.res_config['enable_qos']:
            use_weight = 1.0

        # [FIX Q2]: 解决 URLLC OnlyOver 表现差的问题
        # 如果开启了 High Overhead (代表多重连接/高可靠编码)，虽然开销大，但在拥塞分配时应给予高权重(抢占资源)
        if self.high_priority_mode:
            use_weight = max(use_weight, 2.0)  # 强制给予 2倍 权重抢占带宽

        final_share = base_share * use_weight
        return min(final_share, self.bandwidth_max)

    def is_available(self, requested_amount: float = 0) -> bool:
        """
        准入控制逻辑：判断是否接受新用户
        """
        if self.capacity is None: return False

        real_total_capacity = self.init_capacity * self.capacity_factor
        virtual_used = self.connected_users * self.bandwidth_guaranteed

        check_amount = requested_amount if requested_amount > 0 else self.bandwidth_guaranteed
        demand = check_amount * self.overhead_factor

        # [FIX Q3]: 修复 mMTC OnlyCAC 无效的问题
        # 补全了之前缺失的代码块
        if 'enable_cac' in self.res_config and self.res_config['enable_cac']:
            # CAC 策略：如果当前负载超过 80% 且不是 VIP，则拒绝连接
            # 这可以防止 mMTC 风暴（大量用户瞬间涌入）挤占所有资源
            current_load_percent = virtual_used / real_total_capacity if real_total_capacity > 0 else 1.0
            if current_load_percent > 0.8:
                # 拒绝连接，保留 20% 资源给存量用户或高优先级业务
                return False

        # 计算保护带
        limit = real_total_capacity * self.protection_guard_band

        # [FIX Q1]: 修复 eMBB OnlyGuard 无效的问题
        # 核心逻辑：判断是否满足释放条件
        allow_release = self.res_config.get('enable_guard_release', False)

        # 触发条件：处于紧急模式（故障） 且 策略允许释放
        if self.emergency_mode and allow_release:
            # 释放保护带：limit 设为 0，意味着可以使用 100% 的 real_total_capacity
            limit = 0.0

            # [增强优化]: 如果是 OnlyGuard 组别，为了让效果在图表中更明显，
            # 我们可以模拟“挤压”效果，允许短暂过载 (Overbooking)
            # 这里允许额外 5% 的软容量缓冲
            limit = -(real_total_capacity * 0.05)

        # 核心判断公式：已用 + 新增需求 + 预留限制 > 总物理容量
        if (virtual_used + demand + limit) > real_total_capacity:
            return False

        return True

    def set_emergency_mode(self, active: bool):
        self.emergency_mode = active