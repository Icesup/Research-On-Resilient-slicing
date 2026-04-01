import numpy as np


class ResilienceEvaluator:
    """
    Performance-based Resilience Evaluation
    [修正版]: 严格分离 '故障损失(Loss)' 与 '性能增益(Gain)'。
    解决了之前版本中性能提升掩盖故障影响的问题。
    """

    def __init__(self, ideal_performance=1.0):
        self.ideal = ideal_performance
        # 可配置的权重参数
        self.w_qor = 0.7
        self.w_blocking = 0.3

    def evaluate(self, data_series, fault_windows, target_series=None, blocking_series=None):
        data = np.array(data_series)

        # 1. Baseline 构建
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
                "gain_area": 0.0,
                "qor_score": 1.0,
                "min_performance": round(np.mean(data), 3) if len(data) > 0 else 0,
                "recovery_time": 0.0,
                "weighted_qor": 1.0
            }

        # [核心修复] 分离 Loss 和 Gain
        diff = ideal - data

        # Loss: 只有当 Ideal > Data 时才算 Loss (diff > 0)
        # 使用 np.maximum(diff, 0) 过滤出正值
        loss_curve = np.maximum(diff, 0)
        total_loss_area = np.trapz(loss_curve)

        # Gain: 只有当 Data > Ideal 时才算 Gain (diff < 0)
        # Data - Ideal > 0
        gain_curve = np.maximum(data - ideal, 0)
        total_gain_area = np.trapz(gain_curve)

        # 计算理想总面积用于归一化
        total_ideal_area = np.trapz(ideal)
        if total_ideal_area == 0: total_ideal_area = 1.0

        # QoR Basic (仅反映损失，不再允许 > 1.0)
        # 这样能真实反映故障期间的打击
        qor_basic = max(0.0, 1.0 - (total_loss_area / total_ideal_area))

        # Min Performance (鲁棒性)
        min_perf = np.min(data)

        # Recovery Time (保持逻辑，但建议仅针对故障窗口)
        recovery_times = []
        for start_idx, end_idx in fault_windows:
            if start_idx >= len(data): continue
            end_idx = min(end_idx, len(data))

            seg_actual = data[start_idx:end_idx]
            seg_ideal = ideal[start_idx:end_idx]

            # 如果这一段平均值高于理想值，认为瞬间恢复或无影响
            if np.mean(seg_actual) >= np.mean(seg_ideal):
                recovery_times.append(0.0)
                continue

            min_idx = np.argmin(seg_actual)
            # 恢复阈值：达到理想值的 95%
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
        if blocking_series and len(blocking_series) > 0:
            avg_blocking = np.mean(blocking_series)
            weighted_qor = self.w_qor * qor_basic + self.w_blocking * (1.0 - avg_blocking)

        return {
            "loss_area": float(total_loss_area),  # 纯粹的损失
            "gain_area": float(total_gain_area),  # 纯粹的增益 (建议在图表/表格中单独列出)
            "qor_score": float(qor_basic),  # <= 1.0
            "min_performance": float(min_perf),
            "recovery_time": float(avg_rec),
            "weighted_qor": float(weighted_qor)
        }