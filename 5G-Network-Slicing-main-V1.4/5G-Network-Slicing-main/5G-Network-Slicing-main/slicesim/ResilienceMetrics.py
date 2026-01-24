import numpy as np


class ResilienceEvaluator:
    """
    Performance-based Resilience Evaluation
    核心：Curve-to-Curve 评价 + 加权 QoR
    [修改版]：支持负数损失（即性能增益），真实反映负载均衡带来的额外红利。
    """

    def __init__(self, ideal_performance=1.0):
        self.ideal = ideal_performance

    def evaluate(self, data_series, fault_windows, target_series=None, blocking_series=None):
        data = np.array(data_series)

        # 1. Baseline
        if target_series is None:
            ideal = np.ones(len(data))
        elif np.isscalar(target_series):
            ideal = np.ones(len(data)) * float(target_series)
        else:
            ideal = np.array(target_series)
            min_len = min(len(data), len(ideal))
            data = data[:min_len]
            ideal = ideal[:min_len]

        if not fault_windows or len(data) < 2:
            return {
                "loss_area": 0.0,
                "qor_score": 1.0,
                "min_performance": round(np.mean(data), 3) if len(data) > 0 else 0,
                "recovery_time": 0.0,
                "weighted_qor": 1.0
            }

        # [核心修改] 使用全时段数据进行评估，而不仅仅是故障窗口
        # 这样才能捕捉到非故障期间负载均衡带来的增益
        # 如果你只关心故障期间，可以保留之前的 mask 逻辑。
        # 但对于 eMBB 这种全程增益的，建议看全程。

        # 这里为了保持跟 Graph 的兼容，我们计算 target - actual 的净值
        # 正数 = 损失 (Loss)
        # 负数 = 增益 (Gain)

        diff = ideal - data

        # 使用梯形积分计算“净面积”
        total_net_loss = np.trapz(diff)

        total_ideal_area = np.trapz(ideal)
        if total_ideal_area == 0: total_ideal_area = 1.0

        # Basic QoR (允许大于 1.0)
        qor_basic = 1.0 - (total_net_loss / total_ideal_area)

        # Robustness (Min Performance)
        min_perf = np.min(data)

        # Recovery Time (保持原逻辑，只看跌落的部分)
        recovery_times = []
        for start_idx, end_idx in fault_windows:
            if start_idx >= len(data): continue
            end_idx = min(end_idx, len(data))

            # 在故障窗口内寻找跌落点
            seg_actual = data[start_idx:end_idx]
            seg_ideal = ideal[start_idx:end_idx]

            # 如果这一段整体都比 ideal 好，恢复时间为 0
            if np.mean(seg_actual) >= np.mean(seg_ideal):
                recovery_times.append(0.0)
                continue

            # 否则计算恢复时间
            min_idx = np.argmin(seg_actual)
            target_val = seg_ideal[min_idx] * 0.95

            recovered = False
            for i in range(min_idx, len(seg_actual)):
                if seg_actual[i] >= target_val:
                    recovery_times.append(float(i - min_idx))
                    recovered = True
                    break
            if not recovered:
                recovery_times.append(float(len(seg_actual) - min_idx))

        avg_rec = np.mean(recovery_times) if recovery_times else 0.0

        # Weighted QoR
        weighted_qor = qor_basic
        if blocking_series:
            avg_blocking = np.mean(blocking_series)
            # 如果 blocking 很高，会拉低分数
            weighted_qor = 0.7 * qor_basic + 0.3 * (1.0 - avg_blocking)

        return {
            "loss_area": float(total_net_loss),  # 可能是负数
            "qor_score": float(qor_basic),  # 可能是 > 1.0
            "min_performance": float(min_perf),
            "recovery_time": float(avg_rec),
            "weighted_qor": float(weighted_qor)
        }