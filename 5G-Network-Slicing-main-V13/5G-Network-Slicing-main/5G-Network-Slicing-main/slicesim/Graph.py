from statistics import mean
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.patches import Circle
import colorsys
import numpy as np
import matplotlib
from .ResilienceMetrics import ResilienceEvaluator


# 中文字体设置
def set_chinese_font():
    fonts = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
    for font in fonts:
        try:
            plt.rcParams['font.sans-serif'] = [font]
            plt.rcParams['axes.unicode_minus'] = False
            break
        except:
            continue


set_chinese_font()


def distinct_colors(n: int):
    hues = [i / n for i in range(n)]
    colors = [colorsys.hsv_to_rgb(h, 0.7, 0.9) for h in hues]
    return ["#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)) for r, g, b in colors]


class Graph:
    def __init__(self, output_filename='comparison_report_final.png'):
        self.output_filename = output_filename
        self.fig = plt.figure(figsize=(28, 22))
        self.fig.canvas.manager.set_window_title('分切片业务语义差异化韧性评估报告')

        self.gs = gridspec.GridSpec(6, 2, width_ratios=[0.8, 1.2],
                                    height_ratios=[2, 1.2, 2, 1.2, 2, 1.2],
                                    wspace=0.15, hspace=0.5, bottom=0.05, top=0.95, left=0.05, right=0.98)
        self.sat_color_map = {}

    def get_sat_color(self, pk, total_sats):
        if not self.sat_color_map:
            colors = distinct_colors(total_sats)
            for i in range(total_sats):
                self.sat_color_map[i] = colors[i % len(colors)]
        return self.sat_color_map.get(pk, '#000000')

    def smooth_data(self, data, window_size=30):
        if not data: return []
        if len(data) < window_size: return data
        window = np.ones(int(window_size)) / float(window_size)
        return np.convolve(data, window, 'same')

    def calc_max_interruption(self, data, threshold=0.95):
        max_duration = 0
        current_duration = 0
        for val in data:
            if val < threshold:
                current_duration += 1
            else:
                max_duration = max(max_duration, current_duration)
                current_duration = 0
        return max(max_duration, current_duration)

    def _clean_name(self, raw_name):
        if '(' in raw_name:
            return raw_name.split('(')[0].strip()
        return raw_name.strip()

    def _get_conclusion(self, diff, mode='higher_good', labels=None, threshold=0.001):
        if labels is None: labels = ("优化", "恶化")
        good_lbl, bad_lbl = labels
        if abs(diff) < threshold: return "基本持平"
        if mode == 'higher_good':
            return good_lbl if diff > 0 else bad_lbl
        else:  # lower_good (数值越小越好，如阻塞率)
            # diff = Resilient - Faulty. 如果 Resilient 小，diff 为负 -> 优化
            return good_lbl if diff < 0 else bad_lbl

    def draw_final_report(self, stats_norm, stats_fault, stats_res, duration, last_scenario_objects, slice_config):
        ax_map = plt.subplot(self.gs[:, 0])
        self.draw_map_snapshot(ax_map, *last_scenario_objects)

        dict_norm, _ = stats_norm
        dict_fault, win_fault = stats_fault
        dict_res, _ = stats_res

        sample_key = list(dict_norm.keys())[0]
        full_len = len(dict_norm[sample_key]['availability'])
        l = int(full_len * 0.05)
        r = int(full_len * 0.99)
        x_axis = range(l, r)

        target_slices = ['embb', 'urllc', 'mmtc']

        for idx, sn in enumerate(target_slices):
            if sn not in dict_norm: continue

            row_chart = idx * 2
            ax_chart = plt.subplot(self.gs[row_chart, 1])

            config = slice_config.get(sn, {})
            display_name = self._clean_name(config.get('name_display', sn))

            if 'embb' in sn:
                data_key = 'throughput'
                y_label = '总吞吐量 (Mbps)'
                line_color = '#2ca02c'
            elif 'urllc' in sn:
                data_key = 'availability'
                y_label = '连接可靠性 (0-1)'
                line_color = '#1f77b4'
            elif 'mmtc' in sn:
                data_key = 'blocking'
                y_label = '接入阻塞率 (0-1)'
                line_color = '#ff7f0e'
            else:
                data_key = 'availability'
                y_label = '可用性'
                line_color = 'black'

            raw_n = dict_norm[sn][data_key][l:r]
            raw_f = dict_fault[sn][data_key][l:r]
            raw_r = dict_res[sn][data_key][l:r]
            w_size = max(5, int(len(raw_n) * 0.05))
            y_n = self.smooth_data(raw_n, w_size)
            y_f = self.smooth_data(raw_f, w_size)
            y_r = self.smooth_data(raw_r, w_size)

            ax_chart.plot(x_axis, y_n, color='gray', linestyle=':', linewidth=1.5, alpha=0.7, label='正常组 (Normal)')
            ax_chart.plot(x_axis, y_f, color='red', linestyle='--', linewidth=2, alpha=0.8, label='故障组 (Faulty)')
            ax_chart.plot(x_axis, y_r, color=line_color, linestyle='-', linewidth=2.5, label='韧性组 (Resilient)')

            ax_chart.set_title(display_name, fontsize=16, fontweight='bold', loc='center')
            ax_chart.set_ylabel(y_label, fontsize=10)
            ax_chart.grid(True, linestyle='--', alpha=0.4)
            ax_chart.set_xlim(l, r)
            ax_chart.legend(loc='lower right', fontsize='small', framealpha=0.9, ncol=3)

            row_table = idx * 2 + 1
            ax_table = plt.subplot(self.gs[row_table, 1])
            ax_table.axis('off')

            self.draw_single_slice_table(ax_table, sn, display_name,
                                         (dict_norm, dict_fault, dict_res),
                                         win_fault, l, r)

        plt.suptitle("大规模卫星网络切片：基于业务语义的差异化韧性评估报告", fontsize=20, y=0.99)

    def draw_single_slice_table(self, ax, sn, display_name, all_stats, fault_windows, l, r):
        s_n, s_f, s_r = all_stats
        d_n, d_f, d_r = s_n[sn], s_f[sn], s_r[sn]

        conn_n = d_n['availability'][l:r]
        conn_f = d_f['availability'][l:r]
        conn_r = d_r['availability'][l:r]

        aligned_windows = []
        for s, e in fault_windows:
            new_s = max(0, s - l)
            new_e = max(0, e - l)
            if new_e > 0 and new_s < (r - l):
                aligned_windows.append((new_s, new_e))

        evaluator = ResilienceEvaluator()
        res_f = evaluator.evaluate(conn_f, aligned_windows, target_series=conn_n)
        res_r = evaluator.evaluate(conn_r, aligned_windows, target_series=conn_n)

        columns = [display_name, "具体指标", "正常组", "故障组", "韧性组", "优化效果", "结论"]
        rows = []
        cell_colors = []

        def get_row_color(conclusion, positive_keywords):
            base_color = ["#ffffff"] * 7
            if any(k in conclusion for k in positive_keywords) and "基本" not in conclusion:
                base_color[5] = "#d9f0a3"
                base_color[6] = "#d9f0a3"
            return base_color

        if 'embb' in sn:
            th_n = mean(d_n['throughput'][l:r])
            th_f = mean(d_f['throughput'][l:r])
            th_r = mean(d_r['throughput'][l:r])
            diff = th_r - th_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("带宽回升", "带宽劣化"), threshold=0.05)
            rows.append(
                ["核心指标", "平均吞吐率 (Mbps)", f"{th_n:.2f}", f"{th_f:.2f}", f"{th_r:.2f}", f"{diff:+.2f}", concl])
            cell_colors.append(get_row_color(concl, ["回升", "提升"]))

            la_f = res_f['loss_area']
            la_r = res_r['loss_area']
            diff = la_r - la_f
            concl = self._get_conclusion(diff, 'lower_good', labels=("损失减小", "损失增加"), threshold=0.1)
            rows.append(["核心指标", "性能损失面积", "0.0", f"{la_f:.1f}", f"{la_r:.1f}", f"{diff:.1f}", concl])
            cell_colors.append(get_row_color(concl, ["减小", "改善"]))

            av_n = mean(conn_n)
            av_f = mean(conn_f)
            av_r = mean(conn_r)
            diff = av_r - av_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("连接改善", "连接恶化"), threshold=0.005)
            rows.append(["基础指标", "平均连接率", f"{av_n:.3f}", f"{av_f:.3f}", f"{av_r:.3f}", f"{diff:+.3f}", concl])
            cell_colors.append(get_row_color(concl, ["改善"]))

        elif 'urllc' in sn:
            int_n = self.calc_max_interruption(conn_n, 0.95)
            int_f = self.calc_max_interruption(conn_f, 0.95)
            int_r = self.calc_max_interruption(conn_r, 0.95)
            diff = int_r - int_f
            concl = self._get_conclusion(diff, 'lower_good', labels=("中断缩短", "中断延长"), threshold=0.5)
            rows.append(["核心指标", "最大中断时长 (秒)", f"{int_n}s", f"{int_f}s", f"{int_r}s", f"{diff:+}s", concl])
            cell_colors.append(get_row_color(concl, ["缩短"]))

            min_n = min(conn_n) if conn_n else 0
            min_f = min(conn_f) if conn_f else 0
            min_r = min(conn_r) if conn_r else 0
            diff = min_r - min_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("鲁棒性增强", "鲁棒性减弱"), threshold=0.01)
            rows.append(
                ["核心指标", "最低性能水平", f"{min_n:.3f}", f"{min_f:.3f}", f"{min_r:.3f}", f"{diff:+.3f}", concl])
            cell_colors.append(get_row_color(concl, ["增强"]))

            av_n = mean(conn_n)
            av_f = mean(conn_f)
            av_r = mean(conn_r)
            diff = av_r - av_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("连接稳定", "连接抖动"), threshold=0.005)
            rows.append(["基础指标", "平均连接率", f"{av_n:.3f}", f"{av_f:.3f}", f"{av_r:.3f}", f"{diff:+.3f}", concl])
            cell_colors.append(get_row_color(concl, ["稳定"]))

        elif 'mmtc' in sn:
            blk_n_seq = d_n['blocking'][l:r]
            blk_f_seq = d_f['blocking'][l:r]
            blk_r_seq = d_r['blocking'][l:r]

            suc_n = 1.0 - mean(blk_n_seq)
            suc_f = 1.0 - mean(blk_f_seq)
            suc_r = 1.0 - mean(blk_r_seq)
            diff = suc_r - suc_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("接入优化", "接入劣化"), threshold=0.005)
            rows.append(
                ["核心指标", "接入成功率", f"{suc_n:.1%}", f"{suc_f:.1%}", f"{suc_r:.1%}", f"{diff:+.1%}", concl])
            cell_colors.append(get_row_color(concl, ["优化"]))

            bk_n = mean(blk_n_seq)
            bk_f = mean(blk_f_seq)
            bk_r = mean(blk_r_seq)
            diff = bk_r - bk_f
            concl = self._get_conclusion(diff, 'lower_good', labels=("拥塞缓解", "拥塞加剧"), threshold=0.005)
            rows.append(["核心指标", "平均阻塞率", f"{bk_n:.3f}", f"{bk_f:.3f}", f"{bk_r:.3f}", f"{diff:+.3f}", concl])
            cell_colors.append(get_row_color(concl, ["缓解"]))

            dev_n = mean(d_n['connected_count'][l:r])
            dev_f = mean(d_f['connected_count'][l:r])
            dev_r = mean(d_r['connected_count'][l:r])
            diff = dev_r - dev_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("容量提升", "容量下降"), threshold=1.0)
            rows.append(
                ["基础指标", "平均连接数", f"{int(dev_n)}", f"{int(dev_f)}", f"{int(dev_r)}", f"{int(diff):+d}", concl])
            cell_colors.append(get_row_color(concl, ["提升"]))

        table = ax.table(cellText=rows, cellColours=cell_colors, colLabels=columns,
                         loc='center', cellLoc='center', bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.8)

        for (row, col), cell in table.get_celld().items():
            if row == 0:
                cell.set_text_props(weight='bold')
                cell.set_facecolor('#d0d0d0')

    def draw_map_snapshot(self, ax, base_stations, clients, map_limits):
        ax.set_title(f"韧性组网络拓扑快照 (T=结束时刻)", fontsize=14, fontweight='bold')
        ax.set_xlim(map_limits[0])
        ax.set_ylim(map_limits[1])
        ax.set_aspect('equal')
        ax.set_xlabel("X (km)")
        ax.set_ylabel("Y (km)")

        for bs in base_stations:
            if bs.x < map_limits[0][0] or bs.x > map_limits[0][1]: continue
            if bs.active:
                # [修改] 覆盖圈颜色改为深灰色，虚线，清晰可见
                circle = Circle((bs.x, bs.y), bs.coverage_radius, fill=False, linewidth=1.2, linestyle='--',
                                color='#555555', alpha=0.5)
                ax.add_artist(circle)
                # [修改] 卫星点改为黑色
                ax.plot(bs.x, bs.y, 'k.', markersize=4)
            else:
                ax.plot(bs.x, bs.y, 'rx', markersize=8, markeredgewidth=2)
                circle = Circle((bs.x, bs.y), bs.coverage_radius, fill=False, linewidth=1, linestyle='--', color='red',
                                alpha=0.2)
                ax.add_artist(circle)

        slice_colors = ['#2ca02c', '#1f77b4', '#ff7f0e']
        for c in clients:
            col = slice_colors[c.subscribed_slice_index % 3]
            if not (c.connected and c.base_station and c.base_station.active):
                ax.scatter(c.x, c.y, facecolors='none', edgecolors=col, s=15, alpha=0.6, linewidth=1)
            else:
                ax.scatter(c.x, c.y, c=col, s=15, alpha=0.8, edgecolors='none')

        from matplotlib.lines import Line2D
        custom_lines = [
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#2ca02c', label='eMBB'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#1f77b4', label='URLLC'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='#ff7f0e', label='mMTC'),
            Line2D([0], [0], marker='o', color='w', markeredgecolor='black', label='卫星'),
            Line2D([0], [0], marker='x', color='red', linestyle='None', label='故障'),
        ]
        ax.legend(handles=custom_lines, loc='upper right', fontsize='small')

    def save_fig(self):
        self.fig.savefig(self.output_filename, dpi=150)

    def show_plot(self):
        plt.show()