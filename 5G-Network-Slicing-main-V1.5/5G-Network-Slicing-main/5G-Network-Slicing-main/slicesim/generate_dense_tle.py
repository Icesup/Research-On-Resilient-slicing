# 文件名: slicesim/generate_dense_tle.py
import math


def generate_walker_star_tle(filename, num_planes=20, sats_per_plane=20, inclination=53.0):
    """
    生成一个高密度的 Walker Star 星座 TLE 文件
    符合 Slicesim 的读取格式
    """
    with open(filename, 'w', encoding='utf-8') as f:
        # 写入头部信息
        f.write(f"shell_name:LAYER0 num_orbits:{num_planes} num_sats_per_orbit:{sats_per_plane}\n")

        sat_id = 0

        # Walker 星座参数
        # 360度 / 轨道面数
        raan_spacing = 360.0 / num_planes
        # 360度 / 每面卫星数
        mean_anomaly_spacing = 360.0 / sats_per_plane
        # 相位因子 F (0 <= F < P)，这里设为 1，即相邻轨道有一个小的相位错开
        phase_offset_step = 360.0 / (num_planes * sats_per_plane)

        # 设定每天绕行圈数 (Mean Motion)
        # 550km 高度大约是 15.19 revs/day
        mean_motion = 15.19

        for p in range(num_planes):
            raan = (p * raan_spacing) % 360

            for s in range(sats_per_plane):
                # Walker Delta 相位计算
                # MA = (s * spacing) + (p * phase_offset)
                ma = (s * mean_anomaly_spacing + p * phase_offset_step) % 360

                # 构造 TLE 格式
                # SAT-xxxxx
                # 1 ...
                # 2 ID Inc RAAN Ecc ArgP MA MM ...

                f.write(f"SAT-{sat_id:05d}\n")
                # Line 1 (伪造校验和等次要信息，仿真器通常不读这些)
                f.write(f"1 {sat_id:05d}U 00000A   23001.00000000  .00000000  00000-0  00000-0 0  9991\n")

                # Line 2 (包含关键轨道参数)
                # 格式控制：2 {ID} {Inc:8.4f} {RAAN:8.4f} {Ecc} {ArgP} {MA:8.4f} {MM:11.8f}
                # 注意：Inc, RAAN, MA 必须严格对齐列宽

                line2 = (
                    f"2 {sat_id:05d} "
                    f"{inclination:8.4f} "  # Inc
                    f"{raan:8.4f} "  # RAAN
                    f"0001000 "  # Ecc (接近圆轨道)
                    f"000.0000 "  # ArgP
                    f"{ma:8.4f} "  # Mean Anomaly
                    f"{mean_motion:11.8f}"  # Mean Motion
                    f"00001"  # Rev number
                )
                f.write(line2 + "\n")

                sat_id += 1

    print(f"✅ 已生成高密度 TLE 文件: {filename} (共 {sat_id} 颗卫星)")


if __name__ == "__main__":
    generate_walker_star_tle("LAYER0_tle.txt")