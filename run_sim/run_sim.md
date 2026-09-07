# RTL 仿真自动化工具 (run_sim.py)
## 基础元信息
<<<<<<< HEAD
开发语言： Python
=======
开发语言： Python 
>>>>>>> a24656fd7fec120ba93a23306a54b964adc553e1

## 1. 模块概述
一句话定位：run_sim.py 是一个用于自动编译 Verilog 文件并生成波形的 Python 脚本；
上游依赖：
Icarus Verilog（iverilog/vvp 命令）
GTKWave（可选，用于波形查看）
Python 3.6+（subprocess、os、pathlib 标准库）
下游调用方：
RTL 开发工程师（手动运行脚本）
CI/CD 流水线（集成到回归测试）
其他 Python 脚本（通过 from run_sim import compile_and_run 调用）

## 2. 启动/编译/仿真流程
在WSL Ubuntu环境运行run_sim.py文件，需要下载iverilog，Gtkwave,同时Verilog 源文件在同一目录

## 3. 测试方案
测试文件路径；
执行测试命令python3 run_sim.py（注意修改文件中Verilog 源文件名称）；
通过标准：
编译无错误（iverilog 返回码为 0）
仿真无错误（vvp 返回码为 0）
波形文件（.vcd）成功生成且大小 > 0；
已覆盖场景：
单模块编译仿真
多模块批量编译仿真
自动创建波形目录
编译/仿真超时保护（编译 30s，仿真 60s）
可选自动打开 GTKWave
未覆盖边界场景：
多顶层模块同时编译
依赖文件缺失时的错误恢复
波形文件已存在时的覆盖策略
大文件仿真性能测试

## 4. 已知缺陷、临时方案、风险点
1.未修复问题
dut_files 顺序依赖：用户需手动保证依赖顺序，未做自动拓扑排序
文件路径硬编码：未提供命令行参数接口，仅能通过 Python 函数调用
2. 临时 Hack
仿真可执行文件 sim_<top_name> 直接生成在当前目录，未清理，可能堆积
超时时间（编译 30s/仿真 60s）为硬编码，不适合大型设计
3. 性能与风险
不支持并行编译，批量仿真串行执行
未对波形文件大小做限制，大设计可能导致磁盘爆满
依赖系统 PATH 中的 iverilog/vvp，环境缺失时错误信息不够友好
subprocess.run() 的 timeout 会直接终止进程，可能导致部分仿真结果丢失
4. 集成注意
确保 WSL 环境已安装：sudo apt install iverilog gtkwave
CI/CD 中需要确保 iverilog 在 PATH 中
testbench 中必须包含 $dumpfile 和 $dumpvars，否则波形文件不会生成

## 5. 目录关键文件说明
run_sim.py	    主脚本，包含编译仿真核心逻辑
./waves/*.vcd	生成的 VCD 波形文件存放目录

### 🟢 可选板块 B：Python 算法 / 脚本模块追加
## 7. 输入输出规范
<<<<<<< HEAD
参数	    类型	必填   说明
top_name	str	   ✅	顶层模块名，用于命名输出文件
testbench	str	   ✅	testbench 文件路径（如 tb_mux.v）
dut_files	list   ❌	DUT 文件列表（如 ["mux.v", "adder.v"]）
wave_dir	str	   ❌	波形存放目录，默认 ./waves
wave_file	str	   ❌	波形完整路径，默认自动生成
gtkwave	    bool   ❌	是否自动打开 GTKWave，默认 False
verbose	    bool   ❌	是否打印详细信息，默认 True
=======
参数	类型	必填	说明
top_name	str	✅	顶层模块名，用于命名输出文件
testbench	str	✅	testbench 文件路径（如 tb_mux.v）
dut_files	list	❌	DUT 文件列表（如 ["mux.v", "adder.v"]）
wave_dir	str	❌	波形存放目录，默认 ./waves
wave_file	str	❌	波形完整路径，默认自动生成
gtkwave	bool	❌	是否自动打开 GTKWave，默认 False
verbose	bool	❌	是否打印详细信息，默认 True
>>>>>>> a24656fd7fec120ba93a23306a54b964adc553e1
数据格式要求：
文件路径支持相对路径和绝对路径
文件必须为 .v 或 .sv 格式（Verilog/SystemVerilog）
输出：
返回值：bool（True 成功，False 失败）
生成文件：
波形文件：<wave_dir>/<top_name>.vcd
仿真可执行文件：./sim_<top_name>（临时文件）
控制台输出：编译/仿真过程的详细日志

## 8. 关键算法说明
核心逻辑简述：
参数初始化：处理默认值（dut_files=[]，自动生成波形路径）
目录创建：Path(wave_dir).mkdir(parents=True, exist_ok=True)
件存在性检查：遍历 testbench 和 dut_files，任一不存在则提前返回 False
编译命令组装：["iverilog", "-o", sim_exe, "-Wall"] + dut_files + [testbench]
注意将 testbench 放在最后，满足 Icarus Verilog 的编译顺序要求
子进程执行：使用 subprocess.run() 并设置 timeout 防止卡死
波形文件验证：检查 .vcd 是否存在且大小 > 0
GTKWave 启动：通过 subprocess.Popen() 异步启动，不阻塞主流程
算法约束条件：
dut_files 顺序必须符合依赖关系（如 DFF 需在 Counter 之前）
testbench 中必须包含波形导出代码（$dumpfile/$dumpvars）
编译/仿真超时后直接终止，不会清理临时文件
<<<<<<< HEAD
批量仿真为串行执行，不支持并行
=======
批量仿真为串行执行，不支持并行
>>>>>>> a24656fd7fec120ba93a23306a54b964adc553e1
