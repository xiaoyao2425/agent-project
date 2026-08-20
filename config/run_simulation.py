#!/usr/bin/env python3
"""
仿真脚本 - 从config.yaml读取配置
W1任务：解耦工具路径
"""

import yaml
import subprocess
import sys
from pathlib import Path

def load_config():
    """
    加载配置文件
    关键：用 __file__ 定位脚本所在目录，确保无论从哪里执行都能找到config.yaml
    """
    # 获取脚本所在目录
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"
    
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

def run_iverilog(sources, output_file="simv", config=None):
    """
    编译Verilog源文件
    sources: 源文件列表，如 ["cpu.v", "memory.v", "tb_top.v"]
    output_file: 输出的可执行文件名
    """
    iverilog_path = config["tools"]["iverilog"]
    command = [iverilog_path, "-o", output_file] + sources
    print(f"🔨 编译: {' '.join(command)}")
    
    try:
        subprocess.run(command, check=True)
        print("✅ 编译成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 编译失败: {e}")
        return False

def run_vvp(simv_file="simv", timeout=None, config=None):
    """
    运行仿真，带超时保护
    timeout: 超时秒数，从config读取
    """
    vvp_path = config["tools"]["vvp"]
    command = [vvp_path, simv_file]
    print(f"⚡ 仿真: {' '.join(command)} (超时={timeout}秒)")
    
    try:
        subprocess.run(command, check=True, timeout=timeout)
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
    
    # 4. 执行编译（示例：编译你的Verilog文件）
    # 注意：这里需要根据你的实际文件名修改
    sources = ["mux.v", "counter.v", "dff.v"]  # ← 改成你的实际文件名
    if not run_iverilog(sources, output_file="simv", config=config):
        sys.exit(1)
    
    # 5. 执行仿真
    if not run_vvp("simv", timeout=timeout, config=config):
        sys.exit(1)
    
    # 6. 检查波形文件
    waveform_path = Path(waveform_file)
    if waveform_path.exists():
        print(f"✅ 波形文件已生成: {waveform_path}")
        # 可选：自动打开波形
        # open_waveform(waveform_file, config=config)
    else:
        print(f"⚠️  波形文件未生成: {waveform_path}")
    
    print("\n" + "=" * 50)
    print("✅ 任务完成！")
    print("=" * 50)

if __name__ == "__main__":
    main()