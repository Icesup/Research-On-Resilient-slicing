from statistics import mean
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.patches import Circle
import colorsys
import numpy as np
import matplotlib
import csv
from .ResilienceMetrics import ResilienceEvaluator
import matplotlib.colors as mc


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
        # === 核心修改：大幅增加高度以容纳底部消融实验图 ===
        self.fig = plt.figure(figsize=(28, 28))
        self.fig.canvas.manager.set_window_title('分切片业务语义差异化韧性评估报告')

        # === 核心修改：布局调整为 7 行 ===
        # [Map, Table1, Chart1, Table2, Chart2, Table3, Chart3, AblationBars]
        # height_ratios 最后一行给 2.5，保证柱状图足够大
        self.gs = gridspec.GridSpec(7, 2, width_ratios=[0.8, 1.2],
                                    height_ratios=[2, 1.2, 2, 1.2, 2, 1.2, 2.5],
                                    wspace=0.15, hspace=0.5, bottom=0.03, top=0.96, left=0.05, right=0.98)
        self.sat_color_map = {}

    def get_sat_color(self, pk, total_sats):
        if not self.sat_color_map:
            colors = distinct_colors(total_sats)
            for i in range(total_sats):
                self.sat_color_map[i] = colors[i % len(colors)]
        return self.sat_color_map.get(pk, '#000000')

    def smooth_data(self, data, window_size=1):
        if not data: return []
        if window_size <= 1: return data
        if len(data) < window_size: return data

        window = np.ones(int(window_size)) / float(window_size)
        return np.convolve(data, window, 'same')

    def calc_max_interruption(self, data, baseline_data, threshold_ratio=0.95):
        max_duration = 0
        current_duration = 0
        length = min(len(data), len(baseline_data))
        for i in range(length):
            baseline_val = max(baseline_data[i], 0.01)
            if data[i] < (baseline_val * threshold_ratio):
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
        else:
            return bad_lbl if diff > 0 else good_lbl

    def draw_final_report(self, stats_norm, stats_fault, stats_res, duration, last_scenario_objects, slice_config):
        # 绘制地图 (占用前两行左侧)
        ax_map = plt.subplot(self.gs[0:2, 0])
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
            row_table = idx * 2 + 1

            config = slice_config.get(sn, {})
            display_name = self._clean_name(config.get('name_display', sn))

            # 数据准备
            if 'embb' in sn:
                data_key = 'throughput'
                y_label = '总吞吐量 (Mbps)'
                line_color = '#2ca02c'
                w_size = 20
            elif 'urllc' in sn:
                data_key = 'availability'
                y_label = '瞬时可用性 (0-1)'
                line_color = '#1f77b4'
                w_size = 1
            elif 'mmtc' in sn:
                data_key = 'blocking'
                y_label = '接入阻塞率 (0-1)'
                line_color = '#ff7f0e'
                w_size = 10
            else:
                data_key = 'availability'
                y_label = '可用性'
                line_color = 'black'
                w_size = 1

            raw_n = dict_norm[sn][data_key][l:r]
            raw_f = dict_fault[sn][data_key][l:r]
            raw_r = dict_res[sn][data_key][l:r]

            y_n = self.smooth_data(raw_n, w_size)
            y_f = self.smooth_data(raw_f, w_size)
            y_r = self.smooth_data(raw_r, w_size)

            # === eMBB 特殊处理：双子图 ===
            if 'embb' in sn:
                gs_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=self.gs[row_chart, 1],
                                                            width_ratios=[1, 1], wspace=0.2)
                ax_chart = plt.subplot(gs_inner[0])
                ax_delta = plt.subplot(gs_inner[1])

                ax_chart.plot(x_axis, y_n, color='gray', linestyle=':', linewidth=1.5, alpha=0.7, label='正常组')
                ax_chart.plot(x_axis, y_f, color='red', linestyle='--', linewidth=2, alpha=0.8, label='故障组')
                ax_chart.plot(x_axis, y_r, color=line_color, linestyle='-', linewidth=2.5, label='韧性组')

                ax_chart.set_title(f"{display_name}: 总吞吐量趋势", fontsize=14, fontweight='bold')
                ax_chart.set_ylabel(y_label, fontsize=10)
                ax_chart.grid(True, linestyle='--', alpha=0.4)
                ax_chart.legend(loc='lower left', fontsize='small')

                delta_series = np.array(y_r) - np.array(y_n)
                ax_delta.axhline(0, color='black', linewidth=1, linestyle='-')
                ax_delta.plot(x_axis, delta_series, color='#555555', linewidth=1.0, alpha=0.5)
                ax_delta.fill_between(x_axis, delta_series, 0, where=(delta_series >= 0),
                                      color='#2ca02c', alpha=0.3, label='性能增益')
                ax_delta.fill_between(x_axis, delta_series, 0, where=(delta_series < 0),
                                      color='#d62728', alpha=0.4, label='性能损失')

                ax_delta.set_title(f"{display_name}: 韧性增益透视 (Res - Norm)", fontsize=14, fontweight='bold')
                ax_delta.set_ylabel("吞吐量差异 (Mbps)", fontsize=10)
                ax_delta.grid(True, linestyle='--', alpha=0.4)
                ax_delta.legend(loc='upper right', fontsize='small')

                ax_chart.set_xlim(l, r)
                ax_delta.set_xlim(l, r)

            else:
                ax_chart = plt.subplot(self.gs[row_chart, 1])
                ax_chart.plot(x_axis, y_n, color='gray', linestyle=':', linewidth=1.5, alpha=0.7, label='Normal')
                ax_chart.plot(x_axis, y_f, color='red', linestyle='--', linewidth=2, alpha=0.8, label='Faulty')
                ax_chart.plot(x_axis, y_r, color=line_color, linestyle='-', linewidth=2.5, label='Resilient')

                ax_chart.set_title(display_name, fontsize=16, fontweight='bold', loc='center')
                ax_chart.set_ylabel(y_label, fontsize=10)
                ax_chart.grid(True, linestyle='--', alpha=0.4)
                ax_chart.set_xlim(l, r)
                ax_chart.set_ylim(-0.05, 1.1)
                ax_chart.legend(loc='lower right', fontsize='small', framealpha=0.9, ncol=3)

            # === 下方表格 ===
            ax_table = plt.subplot(self.gs[row_table, 1])
            ax_table.axis('off')

            self.draw_single_slice_table(ax_table, sn, display_name,
                                         (dict_norm, dict_fault, dict_res),
                                         win_fault, l, r)

        plt.suptitle("大规模卫星网络切片：基于业务语义的差异化韧性评估报告", fontsize=20, y=0.99)

    def draw_single_slice_table(self, ax, sn, display_name, all_stats, fault_windows, l, r):
        s_n, s_f, s_r = all_stats
        d_n, d_f, d_r = s_n[sn], s_f[sn], s_r[sn]

        if 'embb' in sn:
            target_n = d_n['throughput'][l:r]
            target_f = d_f['throughput'][l:r]
            target_r = d_r['throughput'][l:r]
        else:
            target_n = d_n['availability'][l:r]
            target_f = d_f['availability'][l:r]
            target_r = d_r['availability'][l:r]

        conn_n = d_n['availability'][l:r]
        conn_f = d_f['availability'][l:r]
        conn_r = d_r['availability'][l:r]

        full_window = [(0, len(target_n))]
        evaluator = ResilienceEvaluator()
        res_f = evaluator.evaluate(target_f, full_window, target_series=target_n)
        res_r = evaluator.evaluate(target_r, full_window, target_series=target_n)

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

            ga_f = res_f.get('gain_area', 0.0)
            ga_r = res_r.get('gain_area', 0.0)
            diff_g = ga_r - ga_f
            concl_g = self._get_conclusion(diff_g, 'higher_good', labels=("显著增益", "无增益"), threshold=0.1)
            rows.append(["核心指标", "性能增益面积", "0.0", f"{ga_f:.1f}", f"{ga_r:.1f}", f"{diff_g:+.1f}", concl_g])
            gain_color = ["#ffffff"] * 7
            if diff_g > 1.0:
                gain_color[5] = "#e6f7ff";
                gain_color[6] = "#e6f7ff"
            cell_colors.append(gain_color)

            la_f = res_f['loss_area']
            la_r = res_r['loss_area']
            diff_loss = la_f - la_r
            concl = self._get_conclusion(diff_loss, 'higher_good', labels=("损失消除", "损失增加"), threshold=0.1)
            rows.append(["核心指标", "性能损失面积", "0.0", f"{la_f:.1f}", f"{la_r:.1f}", f"{diff_loss:+.1f}", concl])
            cell_colors.append(get_row_color(concl, ["消除", "减小"]))

            av_n = mean(conn_n)
            av_f = mean(conn_f)
            av_r = mean(conn_r)
            diff = av_r - av_f
            concl = self._get_conclusion(diff, 'higher_good', labels=("连接改善", "连接恶化"), threshold=0.005)
            rows.append(["基础指标", "平均连接率", f"{av_n:.3f}", f"{av_f:.3f}", f"{av_r:.3f}", f"{diff:+.3f}", concl])
            cell_colors.append(get_row_color(concl, ["改善"]))

        elif 'urllc' in sn:
            int_n = self.calc_max_interruption(conn_n, conn_n)
            int_f = self.calc_max_interruption(conn_f, conn_n)
            int_r = self.calc_max_interruption(conn_r, conn_n)
            diff = int_f - int_r
            concl = self._get_conclusion(diff, 'higher_good', labels=("中断缩短", "中断延长"), threshold=0.5)
            rows.append(
                ["核心指标", "最大中断时长 (秒)", f"{int_n}s", f"{int_f}s", f"{int_r}s", f"{diff:+.1f}s", concl])
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
            diff = bk_f - bk_r
            concl = self._get_conclusion(diff, 'higher_good', labels=("拥塞缓解", "拥塞加剧"), threshold=0.005)
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
                circle = Circle((bs.x, bs.y), bs.coverage_radius, fill=False, linewidth=1.2, linestyle='--',
                                color='#555555', alpha=0.5)
                ax.add_artist(circle)
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

    def save_data_to_csv(self, stats_norm, stats_fault, stats_res, slice_config):
        print("\n[System] Exporting data to CSV...")

        dict_norm, _ = stats_norm
        dict_fault, win_fault = stats_fault
        dict_res, _ = stats_res

        sample_key = list(dict_norm.keys())[0]
        full_len = len(dict_norm[sample_key]['availability'])
        l = int(full_len * 0.05)
        r = int(full_len * 0.99)

        # 1. 导出汇总指标
        summary_file = 'simulation_summary.csv'
        with open(summary_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['Slice', 'Metric', 'Normal_Val', 'Faulty_Val', 'Resilient_Val', 'Diff(Opt)'])

            target_slices = ['embb', 'urllc', 'mmtc']
            evaluator = ResilienceEvaluator()

            for sn in target_slices:
                if sn not in dict_norm: continue

                d_n, d_f, d_r = dict_norm[sn], dict_fault[sn], dict_res[sn]

                if 'embb' in sn:
                    key = 'throughput'
                    target_n = d_n[key][l:r]
                    target_f = d_f[key][l:r]
                    target_r = d_r[key][l:r]

                    th_n, th_f, th_r = mean(target_n), mean(target_f), mean(target_r)
                    writer.writerow([sn, 'Mean Throughput (Mbps)', f"{th_n:.2f}", f"{th_f:.2f}", f"{th_r:.2f}",
                                     f"{th_r - th_f:+.2f}"])

                    full_window = [(0, len(target_n))]
                    res_f = evaluator.evaluate(target_f, full_window, target_series=target_n)
                    res_r = evaluator.evaluate(target_r, full_window, target_series=target_n)

                    la_f, la_r = res_f['loss_area'], res_r['loss_area']
                    ga_f, ga_r = res_f.get('gain_area', 0.0), res_r.get('gain_area', 0.0)

                    writer.writerow([sn, 'Loss Area', '0.00', f"{la_f:.2f}", f"{la_r:.2f}", f"{la_f - la_r:+.2f}"])
                    writer.writerow([sn, 'Gain Area', '0.00', f"{ga_f:.2f}", f"{ga_r:.2f}", f"{ga_r - ga_f:+.2f}"])

                elif 'urllc' in sn:
                    key = 'availability'
                    conn_n, conn_f, conn_r = d_n[key][l:r], d_f[key][l:r], d_r[key][l:r]
                    int_n = self.calc_max_interruption(conn_n, conn_n)
                    int_f = self.calc_max_interruption(conn_f, conn_n)
                    int_r = self.calc_max_interruption(conn_r, conn_n)
                    writer.writerow(
                        [sn, 'Max Interruption (s)', f"{int_n}", f"{int_f}", f"{int_r}", f"{int_f - int_r:+.1f}"])

                elif 'mmtc' in sn:
                    key = 'connected_count'
                    if key in d_n and d_n[key]:
                        cnt_n = d_n[key][l:r]
                        cnt_f = d_f[key][l:r]
                        cnt_r = d_r[key][l:r]
                        mc_n, mc_f, mc_r = mean(cnt_n), mean(cnt_f), mean(cnt_r)
                        writer.writerow([sn, 'Mean Connected Count', f"{mc_n:.2f}", f"{mc_f:.2f}", f"{mc_r:.2f}",
                                         f"{mc_r - mc_f:+.2f}"])

        print(f"  -> Saved summary to: {summary_file}")

        # 时序数据导出
        raw_file = 'simulation_timeseries.csv'
        with open(raw_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            headers = ['Time_Sec']
            cols_map = []
            metrics = ['availability', 'throughput', 'blocking', 'connected_count']
            for sn in target_slices:
                if sn not in dict_norm: continue
                for m in metrics:
                    headers.append(f"{sn}_Norm_{m}")
                    headers.append(f"{sn}_Fault_{m}")
                    headers.append(f"{sn}_Res_{m}")
                    cols_map.append((sn, m))
            writer.writerow(headers)
            for t in range(full_len):
                row = [t]
                for sn, m in cols_map:
                    try:
                        row.append(dict_norm[sn][m][t])
                        row.append(dict_fault[sn][m][t])
                        row.append(dict_res[sn][m][t])
                    except IndexError:
                        row.extend(['', '', ''])
                writer.writerow(row)
        print(f"  -> Saved time series to: {raw_file}")

    # === [核心逻辑] 绘制消融实验柱状图（集成在主图底部） ===
    def draw_ablation_bar_chart(self, ablation_results):
        # 使用最后一行 (index 6)，并将其分为3列
        gs_bottom = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=self.gs[6, :], wspace=0.3)

        # 1. eMBB: Max Total Throughput (or Mean) -> User said "Total Throughput Max"
        ax_embb = plt.subplot(gs_bottom[0])
        # 使用 Max 值作为 metric
        self._plot_single_ablation(ax_embb, ablation_results['embb'], 'embb',
                                   metric_func=lambda d: np.max(self.smooth_data(d['throughput'], 20)),
                                   y_label='峰值总吞吐量 (Mbps)', title='eMBB: 韧性机制消融分析',
                                   base_color='#2ca02c')

        # 2. URLLC: Max Interruption Time
        ax_urllc = plt.subplot(gs_bottom[1])
        # 获取 Normal 基准数据用于计算中断
        # 需要做容错处理，防止 Normal 组没跑的情况
        norm_key = next((k for k in ablation_results['urllc'].keys() if 'Normal' in k), None)
        norm_data = []
        if norm_key:
            norm_data = ablation_results['urllc'][norm_key]['urllc']['availability']

        def calc_urllc_metric(d):
            # 获取当前组的数据
            curr = d['availability']
            if not norm_data: return 0
            # 使用 Graph 类里的方法计算最大中断
            return self.calc_max_interruption(curr, norm_data)

        self._plot_single_ablation(ax_urllc, ablation_results['urllc'], 'urllc',
                                   metric_func=calc_urllc_metric,
                                   y_label='最大中断时长 (s)', title='URLLC: 中断恢复能力分析',
                                   base_color='#1f77b4', minimize=True)  # Minimize=True意味着越低越好

        # 3. mMTC: Mean Connected Count
        ax_mmtc = plt.subplot(gs_bottom[2])
        self._plot_single_ablation(ax_mmtc, ablation_results['mmtc'], 'mmtc',
                                   metric_func=lambda d: mean(d['connected_count']) if d['connected_count'] else 0,
                                   y_label='平均在线连接数', title='mMTC: 拥塞接入能力分析',
                                   base_color='#ff7f0e')

    def _plot_single_ablation(self, ax, data_map, sn, metric_func, y_label, title, base_color, minimize=False):
        labels = []
        values = []
        colors = []

        # 排序：保证顺序 1.Normal, 2.Faulty ...
        sorted_keys = sorted(data_map.keys())

        # 动态配色：SCI风格
        for k in sorted_keys:
            res = data_map[k]
            # 提取具体的 metric
            slice_data = res.get(sn, {})
            if not slice_data:
                val = 0
            else:
                val = metric_func(slice_data)

            clean_label = k.split('.')[-1]  # Remove "1."
            labels.append(clean_label)
            values.append(val)

            # === 配色逻辑：高水平文献风格 ===
            if 'Normal' in k:
                colors.append('#D3D3D3')  # Light Gray for Baseline
            elif 'Faulty' in k:
                colors.append('#EE0000')  # Red for Fault/Warning
            elif 'All' in k:
                colors.append(base_color)  # Deep Main Color for Final Solution
            else:
                # 中间消融组，使用主色的浅色版本，或者不同的纹理
                # 简单变浅逻辑: 混合白色
                try:
                    c_rgb = mc.to_rgb(base_color)
                    # 0.5 混合白色 -> 变浅
                    c_light = tuple([(x + 0.6) / 1.6 for x in c_rgb])
                    colors.append(c_light)
                except:
                    colors.append(base_color)

        x_pos = np.arange(len(labels))
        # 绘制柱状图
        bars = ax.bar(x_pos, values, align='center', alpha=0.9, color=colors, capsize=10, edgecolor='black',
                      linewidth=0.8)

        # 在柱子上标数值
        for bar in bars:
            height = bar.get_height()
            offset = height * 0.02
            # 防止文字重叠
            va = 'bottom'
            if height < 0: va = 'top'; offset = -offset

            ax.text(bar.get_x() + bar.get_width() / 2., height + offset,
                    f'{height:.1f}', ha='center', va=va, fontsize=10, fontweight='bold')

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=10, fontweight='medium')
        ax.set_ylabel(y_label, fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
        ax.grid(axis='y', linestyle='--', alpha=0.4)