import math
import os
import random
import sys
import logging
import copy
import simpy
import yaml
import numpy as np
from .Graph import Graph
from .BaseStation import BaseStation
from .Client import Client
from .Coverage import Coverage
from .Distributor import Distributor
from .Slice import Slice
from .Stats import Stats
from .utils import KDTree

logging.basicConfig(level=logging.WARNING, format='%(message)s')


def get_dist(d: str):
    return {
        'randint': random.randint,
        'normal': random.normalvariate,
        'uniform': random.uniform,
    }.get(d, random.random)


def parse_tle_file_strict(filename):
    satellites_data = []
    if not os.path.exists(filename):
        print(f"[Error] TLE file not found: {filename}")
        return []
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('SAT-'):
            if i + 2 < len(lines):
                l2 = lines[i + 2].strip()
                try:
                    satellites_data.append({
                        'inc': float(l2[8:16]), 'raan': float(l2[17:25]),
                        'ma': float(l2[43:51]), 'mm': float(l2[52:63])
                    })
                except:
                    pass
            i += 3
        else:
            i += 1
    print(f"[System] Loaded {len(satellites_data)} satellites only once.")
    return satellites_data


def update_process(env, base_stations, clients, map_limits):
    while True:
        for bs in base_stations:
            bs.update_position(env.now, map_limits)
        KDTree.run(clients, base_stations, env.now)
        yield env.timeout(1)


# 【核心隔离机制】根据 target_faults 数组，精准注入单个切片的故障
def fault_manager(env, base_stations, clients, sim_time, stats, fault_seed=1001, target_faults=None):
    rng_fault = random.Random(fault_seed)
    if target_faults is None:
        target_faults = ['embb', 'urllc', 'mmtc']

    if 'embb' in target_faults:
        env.process(fault_embb_degradation(env, base_stations, stats, rng_fault, sim_time))
    if 'urllc' in target_faults:
        env.process(fault_urllc_outage(env, base_stations, clients, stats, rng_fault, sim_time))
    if 'mmtc' in target_faults:
        env.process(fault_mmtc_storm(env, base_stations, clients, stats, rng_fault, sim_time))
    yield env.timeout(0)


def fault_embb_degradation(env, base_stations, stats, rng, sim_time):
    yield env.timeout(20)
    while True:
        interval = 150
        yield env.timeout(interval)
        if env.now > sim_time - 30: break
        stats.record_fault_start('embb', env.now)

        sorted_bs = sorted(base_stations, key=lambda b: b.pk)
        victims = rng.sample(sorted_bs, k=int(len(sorted_bs) * 0.6))

        for bs in victims:
            for sl in bs.slices:
                if 'embb' in sl.name:
                    sl.capacity_factor = 0.1
                    sl.set_emergency_mode(True)

        yield env.timeout(45)
        for bs in victims:
            for sl in bs.slices:
                if 'embb' in sl.name:
                    sl.capacity_factor = 1.0
                    sl.set_emergency_mode(False)
        stats.record_fault_end('embb', env.now)


def fault_urllc_outage(env, base_stations, clients, stats, rng, sim_time):
    yield env.timeout(50)
    while True:
        interval = 150
        yield env.timeout(interval)
        if env.now > sim_time - 10: break
        stats.record_fault_start('urllc', env.now)

        center_x, center_y = 1000, 1000
        valid_bs = [b for b in base_stations if b.x != -9999]
        sorted_bs = sorted(valid_bs, key=lambda b: (b.x - center_x) ** 2 + (b.y - center_y) ** 2)
        victims = sorted_bs[0:30:2]

        for bs in victims:
            for sl in bs.slices:
                if 'urllc' in sl.name:
                    sl.is_faulty = True

        yield env.timeout(15)

        for bs in victims:
            for sl in bs.slices:
                if 'urllc' in sl.name:
                    sl.is_faulty = False

        for c in clients:
            if 'urllc' in getattr(c, 'slice_name', '') and not c.connected:
                c.search_and_connect()

        stats.record_fault_end('urllc', env.now)


def fault_mmtc_storm(env, base_stations, clients, stats, rng, sim_time):
    yield env.timeout(60)
    while True:
        interval = 150
        yield env.timeout(interval)
        if env.now > sim_time - 10: break
        stats.record_fault_start('mmtc', env.now)

        center_x, center_y = 1000, 1000
        valid_bs = [b for b in base_stations if b.x != -9999]
        sorted_bs = sorted(valid_bs, key=lambda b: (b.x - center_x) ** 2 + (b.y - center_y) ** 2)
        victims = sorted_bs[1:30:2]

        for bs in victims:
            for sl in bs.slices:
                if 'mmtc' in sl.name:
                    sl.is_faulty = True
                    sl.capacity_factor = 0.3

        storm_users = [c for c in clients if 'mmtc' in getattr(c, 'slice_name', '') and c.base_station in victims]
        attackers = rng.sample(storm_users, k=int(len(storm_users) * 0.95))

        for c in attackers:
            if c.connected: c.disconnect()
            c.usage_remaining = 30000
            c.connect()

        yield env.timeout(20)

        for bs in victims:
            for sl in bs.slices:
                if 'mmtc' in sl.name:
                    sl.is_faulty = False
                    sl.capacity_factor = 1.0

        stats.record_fault_end('mmtc', env.now)


# 透传 target_faults 控制器
def run_scenario(config_data, run_label, sat_data_cache, resilience_config=None, enable_faults=False, base_seed=42,
                 fault_seed=None, target_faults=None):
    print(f"  -> Running: {run_label}")
    random.seed(base_seed)
    np.random.seed(base_seed)

    env = simpy.Environment()
    SETTINGS = config_data['settings']
    SLICES_INFO = copy.deepcopy(config_data['slices'])

    if resilience_config is None:
        resilience_config = {}

    slice_names = list(SLICES_INFO.keys())
    slice_weights = [s['client_weight'] for s in SLICES_INFO.values()]
    cum_weights = []
    curr = 0
    for w in slice_weights:
        curr += w
        cum_weights.append(curr)

    mobility_patterns = []
    mb_weights = []
    w_sum = 0
    for name, mb in config_data['mobility_patterns'].items():
        w_sum += mb['client_weight']
        mb_weights.append(w_sum)
        mobility_patterns.append(Distributor(name, get_dist(mb['distribution']), *mb['params']))

    usage_patterns = {}
    for name, s in SLICES_INFO.items():
        usage_patterns[name] = Distributor(name, get_dist(s['usage_pattern']['distribution']),
                                           *s['usage_pattern']['params'])

    base_stations = []
    map_x = SETTINGS['statistics_params']['x']
    map_y = SETTINGS['statistics_params']['y']
    map_limits = ((map_x['min'], map_x['max']), (map_y['min'], map_y['max']))
    template = config_data['base_stations'][0]

    sat_params = sat_data_cache

    for i, sat_data in enumerate(sat_params):
        slices = []
        cap = template['capacity_bandwidth']
        for name, s_info in SLICES_INFO.items():
            ratio = template['ratios'].get(name, 0)
            s_cap = cap * ratio
            res_policy = s_info.get('resilience_policy', None)
            slice_type_key = next((k for k in resilience_config.keys() if k in name), None)
            curr_res_conf = resilience_config.get(slice_type_key, {})

            s = Slice(name, ratio, 0, s_info['client_weight'],
                      s_info['delay_tolerance'], s_info['qos_class'],
                      s_info['bandwidth_guaranteed'], s_info['bandwidth_max'],
                      s_cap, usage_patterns[name], resilience_policy=res_policy,
                      qor_metric=s_info.get('qor_metric', 'availability'),
                      name_display=s_info.get('name_display', name),
                      resilience_config=curr_res_conf)
            s.capacity = simpy.Container(env, init=s_cap, capacity=s_cap)
            slices.append(s)
        cov = template.get('coverage', 280)
        bs = BaseStation(i, cov, cap, slices, tle_data=sat_data)
        base_stations.append(bs)

    stats = Stats(env, base_stations, clients=None, area=map_limits)
    stats.init_slice_stats(slice_names)

    clients = []
    ufp = config_data['clients']['usage_frequency']
    uf_dist = Distributor('uf', get_dist(ufp['distribution']), *ufp['params'], divide_scale=ufp['divide_scale'])

    for i in range(SETTINGS['num_clients']):
        cx = get_dist(config_data['clients']['location']['x']['distribution'])(
            *config_data['clients']['location']['x']['params'])
        cy = get_dist(config_data['clients']['location']['y']['distribution'])(
            *config_data['clients']['location']['y']['params'])

        r = random.random()
        mb_idx = 0
        while mb_weights[mb_idx] < r * mb_weights[-1]: mb_idx += 1
        r = random.random()
        sl_idx = 0
        while cum_weights[sl_idx] < r * cum_weights[-1]: sl_idx += 1
        sl_name = slice_names[sl_idx]

        slice_type_key = next((k for k in resilience_config.keys() if k in sl_name), None)
        curr_res_conf = resilience_config.get(slice_type_key, {})

        c = Client(i, env, cx, cy, mobility_patterns[mb_idx], uf_dist.generate_scaled(),
                   sl_idx, stats, sl_name,
                   map_limits=map_limits,
                   resilience_config=curr_res_conf)
        clients.append(c)

    KDTree.limit = SETTINGS['limit_closest_base_stations']
    stats.clients = clients

    env.process(stats.collect())
    env.process(update_process(env, base_stations, clients, map_limits))

    sim_time = int(SETTINGS['simulation_time'])
    if enable_faults:
        env.process(fault_manager(env, base_stations, clients, sim_time, stats, fault_seed, target_faults))

    env.run(until=sim_time)
    return stats.get_stats(), (base_stations, clients, map_limits)


def main():
    if len(sys.argv) != 2:
        print('Usage: python -m slicesim example-input.yml')
        exit(1)

    CONF = os.path.join(os.path.dirname(__file__), sys.argv[1])
    with open(CONF, 'r', encoding='utf-8') as f:
        data = yaml.load(f, Loader=yaml.FullLoader)

    sim_time = int(data['settings']['simulation_time'])
    print(f"\n🚀 Simulation Start (Duration: {sim_time}s)")

    TLE_FILE = os.path.join(os.path.dirname(__file__), 'LAYER0_tle.txt')
    SAT_DATA_CACHE = parse_tle_file_strict(TLE_FILE)
    if not SAT_DATA_CACHE:
        print("Error: No satellite data.")
        return

    BASE_SEED = 42
    FAULT_SEED = 1001

    print("\n[Phase 1] Standard Scenarios (全局测试 - 用于生成最终对比图表)...")
    stats_norm, _ = run_scenario(data, "Normal", SAT_DATA_CACHE, resilience_config={}, enable_faults=False,
                                 base_seed=BASE_SEED)
    stats_fault, _ = run_scenario(data, "Faulty", SAT_DATA_CACHE, resilience_config={}, enable_faults=True,
                                  base_seed=BASE_SEED, fault_seed=FAULT_SEED, target_faults=None)

    full_resilience_config = {
        'embb': {'enable_guard_release': True, 'enable_active_lb': True, 'enable_fast_ho': True, 'enable_qos': True},
        'urllc': {'enable_fast_ho': True, 'enable_qos': True, 'enable_high_overhead': True},
        'mmtc': {'enable_fast_ho': True, 'enable_cac': True}
    }
    stats_res, objs = run_scenario(data, "Resilient-All", SAT_DATA_CACHE, resilience_config=full_resilience_config,
                                   enable_faults=True, base_seed=BASE_SEED, fault_seed=FAULT_SEED, target_faults=None)

    print("\n[Phase 2] Ablation Study & Chart Generation (单业务硬隔离重跑)...")
    ablation_results = {'embb': {}, 'urllc': {}, 'mmtc': {}}

    # 字典中仅仅保留自己业务的策略配置，彻底切断污染
    ablation_embb = {
        '1.Normal': (False, {}),
        '2.Faulty': (True, {}),
        '3.OnlyGuard': (True, {'embb': {'enable_guard_release': True}}),
        '4.OnlyLB': (True, {'embb': {'enable_active_lb': True}}),
        '5.OnlyHO': (True, {'embb': {'enable_fast_ho': True}}),
        '6.OnlyQoS': (True, {'embb': {'enable_qos': True}}),
        '7.All': (True, {'embb': full_resilience_config['embb']})
    }

    ablation_urllc = {
        '1.Normal': (False, {}),
        '2.Faulty': (True, {}),
        '3.OnlyHO': (True, {'urllc': {'enable_fast_ho': True}}),
        '4.OnlyQoS': (True, {'urllc': {'enable_qos': True}}),
        '5.OnlyOver': (True, {'urllc': {'enable_high_overhead': True}}),
        '6.All': (True, {'urllc': full_resilience_config['urllc']})
    }

    ablation_mmtc = {
        '1.Normal': (False, {}),
        '2.Faulty': (True, {}),
        '3.OnlyHO': (True, {'mmtc': {'enable_fast_ho': True}}),
        '4.OnlyCAC': (True, {'mmtc': {'enable_cac': True}}),
        '5.All': (True, {'mmtc': full_resilience_config['mmtc']})
    }

    def run_ablation_batch(category, config_map, result_dict):
        target_slice = category.lower()
        for label, (has_fault, sl_cfg) in config_map.items():
            if label == '1.Normal':
                # Normal 因为完全无故障且无策略，任何环境下表现都一致，复用以节省几秒
                result_dict[label] = stats_norm[0]
            else:
                # [关键隔离] 当开启故障时，仅向底层传递当前切片的名字！其他业务全部处于无干扰的安静状态
                t_faults = [target_slice] if has_fault else []
                s_stat, _ = run_scenario(data, f"Ablation-{category}-{label}", SAT_DATA_CACHE, sl_cfg, has_fault,
                                         BASE_SEED,
                                         FAULT_SEED, target_faults=t_faults)
                result_dict[label] = s_stat[0]

    run_ablation_batch('eMBB', ablation_embb, ablation_results['embb'])
    run_ablation_batch('URLLC', ablation_urllc, ablation_results['urllc'])
    run_ablation_batch('mMTC', ablation_mmtc, ablation_results['mmtc'])

    print("\n[Output] Generating Report...")
    if data['settings']['plotting_params']['plotting']:
        graph = Graph(output_filename='comparison_report_final.png')
        graph.draw_final_report(stats_norm, stats_fault, stats_res, sim_time, objs, data['slices'])
        graph.save_data_to_csv(stats_norm, stats_fault, stats_res, data['slices'])
        print("[Output] Adding Ablation Bar Charts...")
        graph.draw_ablation_bar_chart(ablation_results)
        graph.save_fig()
        print("[System] Plotting complete. Window popping up...")
        graph.show_plot()


if __name__ == "__main__":
    main()