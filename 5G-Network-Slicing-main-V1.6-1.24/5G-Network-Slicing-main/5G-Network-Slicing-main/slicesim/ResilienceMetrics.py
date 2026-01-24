import numpy as np


class ResilienceEvaluator:
    """
    [V16.5 完美版]
    1. 严格损益分离：Loss 归 Loss, Gain 归 Gain。
    2. 接口全兼容：确保包含 Graph.py 调用的所有 Key。
    """

    def __init__(self, ideal_performance=1.0):
        self.ideal = ideal_performance

    def evaluate(self, data_series, fault_windows, target_series=None, blocking_series=None):
        data = np.array(data_series)
        if target_series is None:
            ideal = np.ones(len(data))
        else:
            ideal = np.array(target_series)[:len(data)]

        # --- 核心：损益分离逻辑 ---
        diff = ideal - data
        loss_diff = np.maximum(0, diff)  # 真正的损失
        gain_diff = np.maximum(0, -diff)  # 额外的红利

        total_loss_area = np.trapz(loss_diff)
        total_gain_area = np.trapz(gain_diff)
        total_ideal_area = np.trapz(ideal) if np.trapz(ideal) != 0 else 1.0

        # --- 科学定义 QoR (上限1.0) ---
        qor_score = max(0.0, 1.0 - (total_loss_area / total_ideal_area))
        # 接入成功率 (Availability)
        avail = (1.0 - np.mean(blocking_series)) if blocking_series is not None else 1.0

        # --- 返回字典：修复 Graph.py 的 KeyError ---
        return {
            "loss_area": float(total_loss_area),  # 修复关键！
            "gain_area": float(total_gain_area),  # 新增供 Graph 调用
            "qor_score": float(qor_score),
            "min_performance": float(np.min(data)) if len(data) > 0 else 0,
            "recovery_time": self._calc_recovery(data, ideal, fault_windows),
            "weighted_qor": float(np.sqrt(qor_score * avail))  # 改用几何平均，更严谨
        }

    def _calc_recovery(self, data, ideal, windows):
        times = []
        for s, e in windows:
            if s >= len(data): continue
            seg = data[s:min(e, len(data))]
            if len(seg) == 0: continue
            thresh = ideal[s] * 0.95
            m_idx = np.argmin(seg)
            rec = False
            for i in range(m_idx, len(seg)):
                if seg[i] >= thresh:
                    times.append(float(i - m_idx));
                    rec = True;
                    break
            if not rec: times.append(float(len(seg) - m_idx))
        return float(np.mean(times)) if times else 0.0