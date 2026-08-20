#!/usr/bin/env python3
"""
RTL 仿真自动化工具 - 给命令行装上 Python 大脑
功能：自动编译 Verilog 文件并生成波形
"""

import subprocess
import os
import sys
from pathlib import Path
from datetime import datetime

def compile_and_run(
    top_name: str,
    testbench: str,
    dut_files: list = None,
    wave_dir: str = "./waves",
    wave_file: str = None,
    gtkwave: bool = False,
    verbose: bool = True
) -> bool:
    """
    编译并运行 Verilog 仿真

    参数:
        top_name: 顶层模块名（用于命名输出文件）
        testbench: testbench 文件路径
        dut_files: DUT 文件列表（会自动加上路径）
        wave_dir: 波形文件存放目录
        wave_file: 波形文件完整路径（如果不指定，自动生成）
        gtkwave: 是否自动打开 GTKWave
        verbose: 是否打印详细信息

    返回:
        True: 成功，False: 失败
    """

    # 1. 参数初始化
    if dut_files is None:
        dut_files = []

    # 如果 wave_file 没指定，自动生成
    if wave_file is None:
        wave_file = f"{wave_dir}/{top_name}.vcd"

    # 2. 创建波形目录
    Path(wave_dir).mkdir(parents=True, exist_ok=True)

    # 3. 确保文件存在
    if not Path(testbench).exists():
        print(f"[错误] Testbench 文件不存在: {testbench}")
        return False

    for dut in dut_files:
        if not Path(dut).exists():
            print(f"[错误] DUT 文件不存在: {dut}")
            return False

    # 4. 组装编译命令
    sim_exe = f"sim_{top_name}"
    compile_cmd = ["iverilog", "-o", sim_exe, "-Wall"]

    # 添加 DUT 文件（确保 testbench 在最后）
    compile_cmd.extend(dut_files)
    compile_cmd.append(testbench)

    if verbose:
        print("=" * 60)
        print(f"[编译] 开始编译 {top_name}")
        print(f"[命令] {' '.join(compile_cmd)}")
        print("-" * 60)

    # 5. 执行编译
    try:
        result = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            timeout=30  # 30秒超时
        )
    except subprocess.TimeoutExpired:
        print("[错误] 编译超时（30秒）")
        return False

    # 检查编译结果
    if result.returncode != 0:
        print(f"[错误] 编译失败 (返回码: {result.returncode})")
        print(f"[错误详情]\n{result.stderr}")
        return False

    if verbose:
        print("[成功] ✅ 编译通过")
        if result.stdout:
            print(f"[输出]\n{result.stdout}")

    # 6. 执行仿真
    if verbose:
        print("-" * 60)
        print(f"[仿真] 运行 {sim_exe}")

    try:
        result = subprocess.run(
            [f"./{sim_exe}"],
            capture_output=True,
            text=True,
            timeout=60
        )
    except subprocess.TimeoutExpired:
        print("[错误] 仿真超时（60秒）")
        return False

    if result.returncode != 0:
        print(f"[错误] 仿真失败 (返回码: {result.returncode})")
        print(f"[错误详情]\n{result.stderr}")
        return False

    if verbose:
        print("[成功] ✅ 仿真完成")
        if result.stdout:
            print(f"[仿真输出]\n{result.stdout}")

    # 7. 检查波形文件
    if Path(wave_file).exists():
        file_size = Path(wave_file).stat().st_size
        print("-" * 60)
        print(f"[成功] ✅ 波形已生成: {wave_file} (大小: {file_size} 字节)")
    else:
        print(f"[警告] ⚠️ 波形文件未生成: {wave_file}")
        print("[提示] 请检查 testbench 中是否包含:")
        print("         initial begin")
        print("             $dumpfile(\"xxx.vcd\");")
        print("             $dumpvars(0, xxx);")
        print("         end")
        return False

    # 8. 自动打开 GTKWave
    if gtkwave:
        try:
            subprocess.Popen(
                ["gtkwave", wave_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"[GUI] 🖥️ GTKWave 已启动: {wave_file}")
        except FileNotFoundError:
            print("[警告] 未找到 GTKWave，请确认已安装")

    print("=" * 60)
    return True


def run_batch(modules: list, gtkwave: bool = False):
    """
    批量运行多个模块

    参数:
        modules: 模块配置列表，每个元素是 dict
        gtkwave: 是否打开波形查看器
    """
    print("\n" + "🚀" * 30)
    print("开始批量仿真...")
    print("🚀" * 30 + "\n")

    results = {}
    for config in modules:
        name = config.get("name", "unknown")
        print(f"\n{'='*60}")
        print(f"📦 模块: {name}")
        print('='*60)

        success = compile_and_run(
            top_name=config.get("top_name", name),
            testbench=config.get("testbench"),
            dut_files=config.get("dut_files", []),
            gtkwave=gtkwave and config.get("show_wave", False),
            verbose=True
        )
        results[name] = success

    # 打印汇总
    print("\n" + "📊" * 30)
    print("批量仿真结果汇总")
    print("📊" * 30)
    for name, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"  {name}: {status}")

    total = len(results)
    passed = sum(results.values())
    print(f"\n总计: {passed}/{total} 通过")
    return results


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 方式1：单个模块运行
    print("【方式1】单个模块运行")
    compile_and_run(
        top_name="mux",
        testbench="tb_mux.v",
        dut_files=["mux.v"],
        gtkwave=False,
        verbose=True
    )

    # 方式2：批量运行（推荐）
    print("\n\n【方式2】批量运行所有模块")
    modules = [
        {
            "name": "多路器",
            "top_name": "mux",
            "testbench": "tb_mux.v",
            "dut_files": ["mux.v"],
            "show_wave": True  # 只对多路器打开波形
        },
        {
            "name": "D触发器",
            "top_name": "dff",
            "testbench": "tb_dff.v",
            "dut_files": ["dff.v"],
            "show_wave": False
        },
        {
            "name": "计数器",
            "top_name": "counter",
            "testbench": "tb_counter.v",
            "dut_files": ["dff.v", "counter.v"],  # 注意依赖关系
            "show_wave": False
        }
    ]

    # 批量运行（最后一个参数 True 表示自动打开波形）
    run_batch(modules, gtkwave=False)
