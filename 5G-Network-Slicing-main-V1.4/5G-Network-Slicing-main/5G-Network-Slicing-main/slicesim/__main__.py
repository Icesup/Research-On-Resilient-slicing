import math
import os
import random
import sys
import logging
import copy
import simpy
import yaml

from .BaseStation import BaseStation
from .Client import Client
from .Coverage import Coverage
from .Distributor import Distributor
from .Graph import Graph
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
    print(f"[System] Loaded {len(satellites_data)} satellites.")
    return satellites_data


def update_process(env, base_stations, clients, map_limits):
    while True:
        for bs in base_stations:
            bs.update_position(env.now, map_limits)
        KDTree.run(clients, base_stations, env.now)
        yield env.timeout(1)


# === 故障注入逻辑 ===

def fault_manager(env, base_stations, clients, sim_time, stats, fault_seed=None):
    rng = random.Random(fault_seed) if fault_seed is not None else random

    # 启动三个针对性的故障
    env.process(fault_embb_degradation(env, base_stations, stats, rng, sim_time))
    env.process(fault_urllc_outage(env, base_stations, stats, rng, sim_time))
    env.process(fault_mmtc_storm(env, clients, stats, rng, sim_time))

    yield env.timeout(0)


def fault_embb_degradation(env, base_stations, stats, rng, sim_time):
    # eMBB: 模拟大范围雨衰
    yield env.timeout(20)
    while True:
        interval = rng.randint(60, 90)
        yield env.timeout(interval)
        if env.now > sim_time - 30: break

        stats.record_fault_start(env.now)

        victims = rng.sample(base_stations, k=int(len(base_stations) * 0.3))
        for bs in victims:
            for sl in bs.slices:
                if 'embb' in sl.name:
                    sl.capacity_factor = 0.4

        yield env.timeout(30)

        for bs in victims:
            for sl in bs.slices:
                if 'embb' in sl.name:
                    sl.capacity_factor = 1.0

        stats.record_fault_end(env.now)


def fault_urllc_outage(env, base_stations, stats, rng, sim_time):
    """
    URLLC: 最坏情况分析 (Worst-Case Analysis)
    模拟区域性灾难导致的负载集中节点失效 (Regional Disaster / Critical Node Failure)
    """
    yield env.timeout(50)
    max_faults = 3
    fault_count = 0

    while fault_count < max_faults:
        # 长间隔，保证系统恢复
        interval = rng.randint(80, 120)
        yield env.timeout(interval)

        if env.now > sim_time - 10: break

        # [学术化逻辑] 攻击"高负载区域"的卫星
        # 物理意义：模拟人口密集区的基站遭遇级联失效或干扰
        active_bs = sorted([bs for bs in base_stations if bs.active],
                           key=lambda b: sum(s.connected_users for s in b.slices),
                           reverse=True)
        if not active_bs: continue

        candidates = active_bs[:30]
        victim_count = min(len(candidates), 15)
        victims = rng.sample(candidates, k=victim_count)

        print(f"[Fault-URLLC] T={env.now:.1f}: Regional Failure Simulation on {len(victims)} Nodes.")
        for bs in victims:
            bs.active = False

        # 持续 8 秒
        yield env.timeout(8)

        for bs in victims:
            bs.active = True

        print(f"[Recovery-URLLC] T={env.now:.1f}: Nodes Recovered.")
        fault_count += 1


def fault_mmtc_storm(env, clients, stats, rng, sim_time):
    # mMTC: 接入风暴
    yield env.timeout(60)
    while True:
        interval = rng.randint(80, 110)
        yield env.timeout(interval)
        if env.now > sim_time - 10: break

        print(f"[Fault-mMTC] T={env.now:.1f}: Access Storm!")
        mmtc_users = [c for c in clients if 'mmtc' in getattr(c, 'slice_name', '')]

        # 90% 并发
        attackers = rng.sample(mmtc_users, k=int(len(mmtc_users) * 0.9))

        for c in attackers:
            if c.connected: c.disconnect()
            c.usage_remaining = 10000
            c.connect()

        yield env.timeout(10)


# === Main ===

def run_scenario(config_data, enable_resilience=True, enable_faults=False, base_seed=42, fault_seed=None):
    random.seed(base_seed)
    env = simpy.Environment()
    SETTINGS = config_data['settings']
    SLICES_INFO = copy.deepcopy(config_data['slices'])

    if not enable_resilience:
        for s_name in SLICES_INFO:
            SLICES_INFO[s_name]['resilience_policy'] = None

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

    TLE_FILE = os.path.join(os.path.dirname(__file__), 'LAYER0_tle.txt')
    sat_params = parse_tle_file_strict(TLE_FILE)

    for i, sat_data in enumerate(sat_params):
        slices = []
        cap = template['capacity_bandwidth']
        for name, s_info in SLICES_INFO.items():
            ratio = template['ratios'].get(name, 0)
            s_cap = cap * ratio
            res_policy = s_info.get('resilience_policy', None)
            s = Slice(name, ratio, 0, s_info['client_weight'],
                      s_info['delay_tolerance'], s_info['qos_class'],
                      s_info['bandwidth_guaranteed'], s_info['bandwidth_max'],
                      s_cap, usage_patterns[name], resilience_policy=res_policy,
                      qor_metric=s_info.get('qor_metric', 'availability'),
                      name_display=s_info.get('name_display', name))
            s.capacity = simpy.Container(env, init=s_cap, capacity=s_cap)
            slices.append(s)
        cov = template.get('coverage', 280)
        bs = BaseStation(i, cov, cap, slices, tle_data=sat_data)
        base_stations.append(bs)

    stats = Stats(env, base_stations, None, map_limits)
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

        c = Client(i, env, cx, cy, mobility_patterns[mb_idx], uf_dist.generate_scaled(),
                   sl_idx, stats, sl_name, map_limits=map_limits)
        clients.append(c)

    KDTree.limit = SETTINGS['limit_closest_base_stations']
    stats.clients = clients

    env.process(stats.collect())
    env.process(update_process(env, base_stations, clients, map_limits))

    sim_time = int(SETTINGS['simulation_time'])

    if enable_faults:
        env.process(fault_manager(env, base_stations, clients, sim_time, stats, fault_seed))

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

    BASE_SEED = 42
    FAULT_SEED = 1001

    print("\n[1/3] Normal Scenario...")
    stats_norm, _ = run_scenario(data, False, False, base_seed=BASE_SEED)

    print("[2/3] Faulty Scenario (Precision Injection)...")
    stats_fault, _ = run_scenario(data, False, True, base_seed=BASE_SEED, fault_seed=FAULT_SEED)

    print("[3/3] Resilient Scenario (Precision Injection)...")
    stats_res, objs = run_scenario(data, True, True, base_seed=BASE_SEED, fault_seed=FAULT_SEED)

    print("\n[Output] Generating Report...")
    if data['settings']['plotting_params']['plotting']:
        graph = Graph(output_filename='comparison_report_final.png')
        graph.draw_final_report(stats_norm, stats_fault, stats_res, sim_time, objs, data['slices'])
        graph.save_fig()
        graph.show_plot()


if __name__ == "__main__":
    main()