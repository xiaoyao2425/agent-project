#!/usr/bin/env python3
"""
仿真脚本 - 从config.yaml读取配置
W1任务：解耦工具路径
"""

import yaml
import subprocess
import sys
from pathlib import Path

# 脚本所在目录（无论从哪个工作目录启动都以此为基准）
SCRIPT_DIR = Path(__file__).resolve().parent

def load_config():
    """
    加载配置文件
    关键：用 __file__ 定位脚本所在目录，确保无论从哪里执行都能找到config.yaml
    """
    # 获取脚本所在目录
    config_path = SCRIPT_DIR / "config.yaml"
    
    # 检查文件是否存在
    if not config_path.exists():
        raise FileNotFoundError(
            f"❌ 配置文件不存在: {config_path}\n"
            f"   请确保 config.yaml 在 {script_dir} 目录下"
        )

    # 读取并解析YAML
    try:
        with open(config_path, "r", encoding='utf-8') as f:
            config = yaml.safe_load(f)
        print(f"✅ 成功加载配置: {config_path}")
        return config
    except yaml.YAMLError as e:
        raise RuntimeError(f"❌ YAML格式错误: {e}")

def run_iverilog(sources, output_file="simv", config=None, cwd=None):
    """
    编译Verilog源文件
    sources: 源文件路径列表（绝对路径），如 ["cpu.v", "memory.v", "tb_top.v"]
    output_file: 输出的可执行文件路径
    cwd: 编译工作目录（testbench 中的相对路径以此为基准）
    """
    iverilog_path = config["tools"]["iverilog"]
    command = [iverilog_path, "-o", str(output_file)] + [str(s) for s in sources]
    print(f"🔨 编译: {' '.join(command)}")

    try:
        subprocess.run(command, check=True, cwd=cwd)
        print("✅ 编译成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 编译失败: {e}")
        return False

def run_vvp(simv_file="simv", timeout=None, config=None, cwd=None):
    """
    运行仿真，带超时保护
    timeout: 超时秒数，从config读取
    cwd: 仿真工作目录（$dumpfile 的相对路径以此为基准）
    """
    vvp_path = config["tools"]["vvp"]
    command = [vvp_path, str(simv_file)]
    print(f"⚡ 仿真: {' '.join(command)} (超时={timeout}秒)")

    try:
        subprocess.run(command, check=True, timeout=timeout, cwd=cwd)
        print("✅ 仿真正常结束")
        return True
    except subprocess.TimeoutExpired:
        print(f"❌ 仿真超时（{timeout}秒），已强制终止（可能是死循环！）")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ 仿真失败: {e}")
        return False

def open_waveform(waveform_file, config=None):
    """打开波形文件"""
    gtkwave_path = config["tools"]["gtkwave"]
    command = [gtkwave_path, waveform_file]
    print(f"📊 打开波形: {' '.join(command)}")
    
    try:
        subprocess.Popen(command)  # 用Popen让GTKWave在后台运行
        print("✅ 波形查看器已启动")
        return True
    except Exception as e:
        print(f"❌ 打开波形失败: {e}")
        return False

def main():
    """主函数：演示W1功能 - 读取配置并执行仿真"""
    print("=" * 50)
    print("🚀 仿真工具链 - W1任务演示")
    print("=" * 50)
    
    # 1. 加载配置
    try:
        config = load_config()
    except Exception as e:
        print(e)
        sys.exit(1)
    
    # 2. 显示配置信息
    print(f"\n📋 当前配置:")
    print(f"   iverilog: {config['tools']['iverilog']}")
    print(f"   vvp: {config['tools']['vvp']}")
    print(f"   gtkwave: {config['tools']['gtkwave']}")
    print(f"   timeout: {config['simulation']['timeout']}秒")
    print(f"   波形文件: {config['simulation']['waveform_file']}")

    # 3. 获取仿真参数
    timeout = config["simulation"]["timeout"]
    waveform_file = config["simulation"]["waveform_file"]

    # 源文件目录：相对 config.yaml 解析为绝对路径，避免依赖启动时的工作目录
    source_dir = (SCRIPT_DIR / config["simulation"].get("source_dir", ".")).resolve()
    print(f"   源文件目录: {source_dir}")
    if not source_dir.is_dir():
        print(f"❌ 源文件目录不存在: {source_dir}")
        sys.exit(1)

    # 4. 执行编译（testbench 必须包含在内，否则 iverilog 报 No top level modules）
    # 注意：这里需要根据你的实际文件名修改
    sources = ["mux.v", "tb_mux.v"]  # ← 改成你的实际文件名（最后一个为 testbench）
    src_paths = [source_dir / name for name in sources]
    missing = [p for p in src_paths if not p.exists()]
    if missing:
        print("❌ 以下源文件不存在:")
        for p in missing:
            print(f"   - {p}")
        sys.exit(1)

    simv_path = source_dir / "simv"
    if not run_iverilog(src_paths, output_file=simv_path, config=config, cwd=source_dir):
        sys.exit(1)

    # 5. 执行仿真（cwd=源文件目录，保证 testbench 里 $dumpfile 的相对路径正确）
    if not run_vvp(simv_path, timeout=timeout, config=config, cwd=source_dir):
        sys.exit(1)

    # 6. 检查波形文件
    waveform_path = source_dir / waveform_file
    if waveform_path.exists():
        print(f"✅ 波形文件已生成: {waveform_path}")
        # 可选：自动打开波形
        # open_waveform(waveform_path, config=config)
    else:
        print(f"⚠️  波形文件未生成: {waveform_path}")
    
    print("\n" + "=" * 50)
    print("✅ 任务完成！")
    print("=" * 50)

if __name__ == "__main__":
    main()