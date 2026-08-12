#!/usr/bin/env python3
import subprocess
import sys

# 1. 定义要编译的文件列表
source_files = ["mux.v", "tb_mux.v"]

# 2. 定义输出可执行文件的名称
output_file = "tb_mux"

# 3. 构建编译命令 (相当于你手动敲的: iverilog -o tb_mux mux.v tb_mux.v)
compile_cmd = ["iverilog", "-o", output_file] + source_files

print(f"[INFO] 正在编译: {' '.join(compile_cmd)}")

# 4. 执行编译命令
#    capture_output=True 表示捕获编译器的输出信息
#    text=True 表示以文本(字符串)形式返回，而不是字节
result_compile = subprocess.run(compile_cmd, capture_output=True, text=True)

# 5. 检查编译是否出错
if result_compile.returncode != 0:
    print("[ERROR] 编译失败！错误信息如下：")
    print(result_compile.stderr)  # 打印错误信息
    sys.exit(1)  # 退出脚本，不再往下执行
else:
    print("[SUCCESS] 编译成功！")

# 6. 构建仿真运行命令 (相当于你手动敲的: vvp tb_mux)
sim_cmd = ["vvp", output_file]

print(f"[INFO] 正在运行仿真: {' '.join(sim_cmd)}")

# 7. 执行仿真命令
#    不需要捕获输出，直接显示在终端上（类似你看到 "$finish called at 80" 那行）
result_sim = subprocess.run(sim_cmd)

# 8. 检查仿真是否正常结束
if result_sim.returncode != 0:
    print("[ERROR] 仿真运行异常！")
    sys.exit(1)
else:
    print("[SUCCESS] 仿真完成！波形文件已生成: tb_mux.vcd")

# 9. 询问是否打开波形
print("[INFO] 是否打开 GTKWave 查看波形？(y/n)")
choice = input().strip().lower()
if choice in ['y', 'yes']:
    # 使用 try-except 块处理可能的异常，确保脚本更加健壮
    try:
        subprocess.run(["gtkwave", "tb_mux.vcd"])
    except FileNotFoundError:
        print("[ERROR] GTKWave 不可用，请手动打开波形文件: tb_mux.vcd")
else:
    print("[INFO] 跳过打开波形。")
