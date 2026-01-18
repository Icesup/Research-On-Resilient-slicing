import numpy as np


class ResilienceEvaluator:
    """
    Performance-based Resilience Evaluation
    核心：Curve-to-Curve 评价 + 加权 QoR
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

        total_loss = 0
        total_ideal_area = 0
        min_perf_val = 1.0
        recovery_times = []

        for start, end in fault_windows:
            duration = end - start
            start = max(0, int(start))
            eval_end = min(len(data), int(end + duration * 3.0))

            seg_actual = data[start:eval_end]
            seg_ideal = ideal[start:eval_end]

            if len(seg_actual) < 2: continue

            # Loss Area
            loss_curve = np.maximum(0, seg_ideal - seg_actual)
            loss = np.trapz(loss_curve)
            total_loss += loss
            total_ideal_area += np.trapz(seg_ideal)

            # Robustness
            local_min = np.min(seg_actual)
            if local_min < min_perf_val:
                min_perf_val = local_min

            # Recovery Time
            min_idx = np.argmin(seg_actual)
            target_val = seg_ideal[min_idx] * 0.95

            if local_min >= target_val:
                recovery_times.append(0.0)
            else:
                recovered = False
                for i in range(min_idx, len(seg_actual)):
                    if seg_actual[i] >= seg_ideal[i] * 0.95:
                        recovery_times.append(float(i - min_idx))
                        recovered = True
                        break
                if not recovered:
                    recovery_times.append(float(len(seg_actual) - min_idx))

        # Basic QoR
        if total_ideal_area > 0:
            qor_basic = 1.0 - (total_loss / total_ideal_area)
        else:
            qor_basic = 1.0

        avg_rec = np.mean(recovery_times) if recovery_times else 0.0

        # === [新增] Weighted QoR (综合评价) ===
        # 结合了 Availability 和 Blocking 的改善
        # Alpha=0.7 (Availability权重), Beta=0.3 (Blocking权重)
        weighted_qor = qor_basic
        if blocking_series:
            avg_blocking = np.mean(blocking_series)
            # 阻塞率越低越好，所以用 (1 - blocking) 作为正向指标
            # 公式：0.7 * QoR + 0.3 * (1 - AvgBlocking)
            weighted_qor = 0.7 * qor_basic + 0.3 * (1.0 - avg_blocking)

        return {
            "loss_area": round(total_loss, 2),
            "qor_score": round(max(0, qor_basic), 4),
            "weighted_qor": round(max(0, weighted_qor), 4),
            "min_performance": round(min_perf_val, 3),
            "recovery_time": round(avg_rec, 1)
        }