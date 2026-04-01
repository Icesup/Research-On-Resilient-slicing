import numpy as np


class Stats:
    def __init__(self, env, base_stations, clients, area: tuple):
        self.env = env
        self.base_stations = base_stations
        self.clients = clients
        self.area = area

        self.fault_windows = {'embb': [], 'urllc': [], 'mmtc': []}
        self.curr_fault_start = {}

        self.slice_stats = {}
        self.slice_names = []

    def init_slice_stats(self, slice_names):
        self.slice_names = slice_names
        for sn in slice_names:
            self.slice_stats[sn] = {
                'availability': [],
                'blocking': [],
                'handover': [],
                'throughput': [],
                'connected_count': [],

                'cnt_connect_att': 0,
                'cnt_block': 0,
                'cnt_handover': 0,
                'cnt_handover_att': 0,
                'cnt_handover_succ': 0,

                'last_blocking': 0.0,
                'last_handover': 0.0
            }

    def collect(self):
        yield self.env.timeout(0.25)
        while True:
            for sn in self.slice_names:
                stats = self.slice_stats[sn]

                if stats['cnt_connect_att'] > 0:
                    blk = stats['cnt_block'] / stats['cnt_connect_att']
                    stats['last_blocking'] = blk
                else:
                    blk = stats.get('last_blocking', 0.0)
                stats['blocking'].append(blk)

                c_count = self.get_client_count_by_slice_total(sn)
                if c_count > 0:
                    ho = stats['cnt_handover'] / c_count
                    stats['last_handover'] = ho
                else:
                    ho = stats.get('last_handover', 0.0)
                stats['handover'].append(ho)

                avail, conn_count = self.get_slice_availability_and_count(sn)
                stats['availability'].append(avail)
                stats['connected_count'].append(conn_count)

                thru = self.get_slice_throughput(sn)
                stats['throughput'].append(thru)

                stats['cnt_connect_att'] = 0
                stats['cnt_block'] = 0
                stats['cnt_handover'] = 0
                stats['cnt_handover_att'] = 0
                stats['cnt_handover_succ'] = 0

            yield self.env.timeout(1)

    def get_client_count_by_slice_total(self, slice_name):
        c = 0
        for client in self.clients:
            if getattr(client, 'slice_name', '') == slice_name:
                c += 1
        return c

    def get_slice_availability_and_count(self, slice_name):
        connected = 0
        total = 0
        for client in self.clients:
            if getattr(client, 'slice_name', '') == slice_name:
                total += 1
                s = client.get_slice()
                if client.connected and client.base_station and client.base_station.active and s:
                    # [核心修复] 统计模块不能抹除在故障基站中苟活的 mMTC 和 eMBB 用户
                    # 只有由于基站物理下线导致完全不可用的 URLLC 业务才被排除
                    if 'urllc' in slice_name.lower() and getattr(s, 'is_faulty', False):
                        continue
                    connected += 1
        ratio = connected / total if total > 0 else 0
        return ratio, connected

    def get_slice_throughput(self, slice_name):
        total_bw = 0
        for bs in self.base_stations:
            if not bs.active: continue
            for sl in bs.slices:
                if sl.name == slice_name and sl.capacity:
                    # [修复同上] 保证系统能正确记录风暴期间基站挤压式的吞吐量占用
                    if 'urllc' in slice_name.lower() and getattr(sl, 'is_faulty', False):
                        continue
                    used = sl.capacity.capacity - sl.capacity.level
                    total_bw += used
        return total_bw / 1000000.0

    def incr_connect_attempt(self, slice_name):
        if slice_name in self.slice_stats: self.slice_stats[slice_name]['cnt_connect_att'] += 1

    def incr_block_count(self, slice_name):
        if slice_name in self.slice_stats: self.slice_stats[slice_name]['cnt_block'] += 1

    def incr_handover_count(self, slice_name):
        if slice_name in self.slice_stats: self.slice_stats[slice_name]['cnt_handover'] += 1

    def incr_handover_attempt(self, slice_name):
        if slice_name in self.slice_stats: self.slice_stats[slice_name]['cnt_handover_att'] += 1

    def incr_handover_success(self, slice_name):
        if slice_name in self.slice_stats: self.slice_stats[slice_name]['cnt_handover_succ'] += 1

    def record_fault_start(self, slice_name, t):
        self.curr_fault_start[slice_name] = int(t)

    def record_fault_end(self, slice_name, t):
        if slice_name in self.curr_fault_start:
            self.fault_windows[slice_name].append((self.curr_fault_start[slice_name], int(t)))
            del self.curr_fault_start[slice_name]

    def get_stats(self):
        return self.slice_stats, self.fault_windows