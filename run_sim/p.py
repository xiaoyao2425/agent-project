#!/usr/bin/env python3
"""
RTL 仿真自动化工具 - 给命令行装上 Python 大脑
作者：你的名字
日期：2026-08-13
功能：自动编译 Verilog 文件并生成波形
"""

import subprocess
import os
from pathlib import Path
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def compile_and_run(
    top_name: str,
    testbench: str,
    dut_files: list = None,
    wave_dir: str = "./waves",
    wave_file: str = None,
    gtkwave_executable: str = "gtkwave.exe",  # 新增参数
    sim_exe_path: str = "./sim_{}.exe",       # 新增参数
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
        gtkwave_executable: GTKWave 执行文件名
        sim_exe_path: 仿真执行文件的模板字符串
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
        logging.error(f"[错误] Testbench 文件不存在: {testbench}")
        return False
    
    for dut in dut_files:
        if not Path(dut).exists():
            logging.error(f"[错误] DUT 文件不存在: {dut}")
            return False
    
    # 4. 组装编译命令
    compile_cmd = ["iverilog", "-o", sim_exe_path.format(top_name), "-Wall"]
    
    # 添加 DUT 文件（确保 testbench 在最后）
    compile_cmd.extend(dut_files)
    compile_cmd.append(testbench)
    
    if verbose:
        logging.info("=" * 60)
        logging.info(f"[编译] 开始编译 {top_name}")
        logging.info(f"[命令] {' '.join(compile_cmd)}")
        logging.info("-" * 60)
    
    # 5. 执行编译
    try:
        result = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            timeout=30  # 30秒超时
        )
    except subprocess.TimeoutExpired as e:
        logging.error("[错误] 编译超时（30秒）: %s", e)
        return False
    
    # 检查编译结果
    if result.returncode != 0:
        logging.error(f"[错误] 编译失败 (返回码: {result.returncode})")
        logging.error(f"[错误详情]\n{result.stderr}")
        return False
    
    if verbose:
        logging.info("[成功] ✅ 编译通过")
        if result.stdout:
            logging.info(f"[输出]\n{result.stdout}")
    
    # 6. 执行仿真
    if verbose:
        logging.info("-" * 60)
        logging.info(f"[仿真] 运行 {sim_exe_path.format(top_name)}")
    
    try:
        result = subprocess.run(
            [f"./{sim_exe_path.format(top_name)}"],
            capture_output=True,
            text=True,
            timeout=60
        )
    except subprocess.TimeoutExpired as e:
        logging.error("[错误] 仿真超时（60秒）: %s", e)
        return False
    
    if result.returncode != 0:
        logging.error(f"[错误] 仿真失败 (返回码: {result.returncode})")
        logging.error(f"[错误详情]\n{result.stderr}")
        return False
    
    if verbose:
        logging.info("[成功] ✅ 仿真完成")
        if result.stdout:
            logging.info(f"[仿真输出]\n{result.stdout}")
    
    # 7. 检查波形文件
    if Path(wave_file).exists():
        file_size = Path(wave_file).stat().st_size
        logging.info("-" * 60)
        logging.info(f"[成功] ✅ 波形已生成: {wave_file} (大小: {file_size} 字节)")
    else:
        logging.warning(f"[警告] ⚠️ 波形文件未生成: {wave_file}")
        logging.warning("[提示] 请检查 testbench 中是否包含:")
        logging.warning("         initial begin")
        logging.warning("             $dumpfile(\"xxx.vcd\");")
        logging.warning("             $dumpvars(0, xxx);")
        logging.warning("         end")
        return False
    
    # 8. 自动打开 GTKWave
    if gtkwave_executable and Path(gtkwave_executable).exists():
        try:
            subprocess.Popen(
                [gtkwave_executable, wave_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logging.info(f"[GUI] 🖥️ GTKWave 已启动: {wave_file}")
        except FileNotFoundError as e:
            logging.warning("[警告] 未找到 GTKWave，请确认已安装: %s", e)
    
    return True


def run_batch(modules: list, gtkwave_executable: str = "gtkwave.exe"):
    """
    批量运行多个模块
    
    参数:
        modules: 模块配置列表，每个元素是 dict
        gtkwave_executable: GTKWave 的可执行文件路径
    """
    print("\n" + "🚀" * 30)
    logging.info("开始批量仿真...")
    print("🚀" * 30 + "\n")
    
    results = {}
    for config in modules:
        name = config.get("name", "unknown")
        logging.info(f"\n{'='*60}")
        logging.info(f"📦 模块: {name}")
        logging.info(f"{'='*60}")
        
        top_name = config.get("top_name", f"{name}_sim")  # 新增或修改顶层模块名
        testbench = config["testbench"]
        dut_files = config.get("dut_files", [])
        wave_dir = config.get("wave_dir", "./waves")
        sim_exe_path = config.get("sim_exe_path", "./sim_{}.exe")
        
        results[top_name] = compile_and_run(
            top_name=top_name,
            testbench=testbench,
            dut_files=dut_files,
            wave_dir=wave_dir,
            gtkwave_executable=gtkwave_executable,  # 使用传入的 GTKWave 可执行文件
            sim_exe_path=sim_exe_path,
            verbose=True
        )
    
    return results


if __name__ == "__main__":
    import os
    
    # 示例模块配置
    modules = [
        {
            "name": "mux",
            "top_name": "mux_sim",  # 顶层模块名
            "testbench": "tb_mux.sv",
            "dut_files": ["mux.sv"],
            "wave_dir": "./waves",
            "sim_exe_path": "./sim_{}.exe"
        }
    ]
    
    # 设置 GTKWave 可执行文件路径（确保该路径正确）
    gtkwave_executable = r"C:\path\to\gtkwave.exe"  # 根据实际情况修改
    results = run_batch(modules, gtkwave_executable)
