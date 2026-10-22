# RTL 仿真自动化工具 (run_sim.py)
## 基础元信息
开发语言： Python

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
（Windows 环境下同样可用：已安装在 D:\iverilog\bin，并通过 vvp 执行仿真产物）

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
（注：结构化 JSON 输出已由 run_full_flow.py 提供，报错自动翻译由 error_translator.py 提供）
2. 临时 Hack
仿真可执行文件 sim_<top_name> 统一生成在 output/ 目录，会覆盖堆积，可定期清理
超时时间（编译 30s/仿真 60s）为硬编码，不适合大型设计
3. 性能与风险
不支持并行编译，批量仿真串行执行
未对波形文件大小做限制，大设计可能导致磁盘爆满
依赖系统 PATH 中的 iverilog/vvp，环境缺失时给出中文提示
subprocess.run() 的 timeout 会直接终止进程，可能导致部分仿真结果丢失
4. 集成注意
确保 WSL 环境已安装：sudo apt install iverilog gtkwave
CI/CD 中需要确保 iverilog 在 PATH 中
testbench 中必须包含 $dumpfile 和 $dumpvars，否则波形文件不会生成

## 5. 目录关键文件说明（v2 分层：api/ 代码，docs/ 文档）
api/run_sim.py	    主脚本，包含编译仿真核心逻辑（返回 bool）
api/run_full_flow.py	一条龙封装，输出结构化 JSON（v2.1：新增 assert_pass 功能自检，tb 打 FAIL 而 vvp 退出码为 0 的场景判 fail+assertion，供闭环回喂）
api/error_translator.py	英文报错→中文人话的分类翻译器（W3）
api/auto_fix.py	自动修复 v1.1（任务三合并版）：源文件只读写 fixed/ 副本 + 结构化 JSON。规则 4 条：缺分号（原有）+ SV→2001 转换 / reg→wire / wire→reg（吸收田玉伟 rtl2 版），对外接口保持本目录标准
api/lint.py	Verilog 静态检查（Lint）黑盒，输出结构化 JSON（见第 9 节；探测链含 MSYS2 已知路径，自动配 VERILATOR_ROOT）
docs/run_sim.md	调用规范+替换代码+边界条款+碰头会待确认清单（v2：RUN_SIM_DIR 已改为 run_sim\api）
tests/	测试样例，内部分三层：
  - 根（fixtures，输入）：故意制造错误的坏文件样例，bad_*.v / tb_bad_*.v（W2 回归用）+ lint_semantic.v（语义级 Lint 样例）+ tb_fail_demo.v（assert_pass 断言失败样例）
  - tests/demos/（演示样例，自 json/demos 并入）：auto_fix/闭环演示用的坏文件（syntax_demo_a/b、timeout_demo*），fixed/ 为其修复副本
  - tests/fixed/（输出）：auto_fix 的修复副本，运行可再生，可随时清空
  - tests/evidence/（存档）：case1~6 实测 JSON 证据，11 字段标准格式，路径引用请勿挪动样例
output/	运行时编译产物（sim_*），可再生垃圾，可随时清空
./waves/*.vcd	生成的 VCD 波形文件存放目录
design/	        DUT 设计文件（mux.v / dff.v / counter.v）
tb/	            testbench 文件（tb_mux.v / tb_dff.v / tb_counter.v）

### 🟢 可选板块 B：Python 算法 / 脚本模块追加
## 7. 输入输出规范
参数	    类型	必填   说明
top_name	str	   ✅	顶层模块名，用于命名输出文件
testbench	str	   ✅	testbench 文件路径（如 tb_mux.v）
dut_files	list   ❌	DUT 文件列表（如 ["mux.v", "adder.v"]）
wave_dir	str	   ❌	波形存放目录，默认 ./waves
wave_file	str	   ❌	波形完整路径，默认自动生成
gtkwave	    bool   ❌	是否自动打开 GTKWave，默认 False
verbose	    bool   ❌	是否打印详细信息，默认 True

数据格式要求：
文件路径支持相对路径和绝对路径（相对路径以脚本所在目录为基准）
文件必须为 .v 或 .sv 格式（Verilog/SystemVerilog）
输出：
返回值：bool（True 成功，False 失败）
生成文件：
波形文件：<wave_dir>/<top_name>.vcd
仿真可执行文件：sim_<top_name>（临时文件，位于 output/ 目录）
控制台输出：编译/仿真过程的详细日志

## 8. 关键算法说明
核心逻辑简述：
参数初始化：处理默认值（dut_files=[]，自动生成波形路径），路径锚定到脚本目录
目录创建：Path(wave_dir).mkdir(parents=True, exist_ok=True)
文件存在性检查：遍历 testbench 和 dut_files，任一不存在则提前返回 False
编译命令组装：["iverilog", "-o", sim_exe, "-Wall"] + dut_files + [testbench]
注意将 testbench 放在最后，满足 Icarus Verilog 的编译顺序要求
子进程执行：使用 subprocess.run() 并设置 timeout 防止卡死
仿真执行：["vvp", sim_exe]（iverilog 产物为 vvp 脚本，不能直接当 exe 运行）
波形文件验证：检查 .vcd 是否存在且大小 > 0
GTKWave 启动：通过 subprocess.Popen() 异步启动，不阻塞主流程
算法约束条件：
dut_files 顺序必须符合依赖关系（如 DFF 需在 Counter 之前）
testbench 中必须包含波形导出代码（$dumpfile/$dumpvars）
编译/仿真超时后直接终止，不会清理临时文件
批量仿真为串行执行，不支持并行

## 9. Lint 模块接口说明（lint.py，供闭环对接）
一句话定位：输入 Verilog 源文件，输出标准结构化 JSON 的黑盒；本轮只做 Verilog（.vhd 明确返回 unsupported，架构留口子）。

检查引擎（自动选择，无需配置；探测顺序见下）：
- ① Windows PATH 里的 verilator（原生模式）→ ② WSL 里的 verilator → ③ 都没有则降级 iverilog -Wall（仅语法级），并在 data.note 里说明降级状态
- Windows 原生安装 verilator：MSYS2 终端执行 pacman -S mingw-w64-ucrt-x86_64-verilator，再把 <MSYS2目录>\ucrt64\bin 加入 Windows PATH；WSL 方式为 sudo apt install verilator
- 装好 verilator 后不改代码，下次调用自动升级为语义级检查（位宽不匹配、未驱动信号、悬空端口、锁存器推断等）

调用方式：
- 命令行：python api/lint.py <source.v> [依赖.v ...] [--top 顶层名] [--out 存档.json]（在 run_sim 目录下执行）
- 函数调用：from lint import lint; result = lint("design/counter.v", extra_files=["design/dff.v"], top=None)

status 取值与闭环处理建议：
- "pass"        无问题 → 直接进仿真（run_full_flow）
- "warn"        只有警告 → 不阻塞，可继续仿真，警告留给 RTL 组看
- "fail"        有错误 → 阻塞，建议调 auto_fix 尝试自动修复
- "unsupported" .vhd 等不支持类型 → 不处理，人工流转
退出码：pass/warn=0，fail=1，unsupported=2

lint_errors 元素字段（每条问题）：
- line / column   出错位置（解析不到为 null）
- rule            规则名：verilator 官方警告名（WIDTH、UNDRIVEN、LATCH…，可用 -Wno-<rule> 屏蔽误报）或 syntax / misc
- severity        error / warn / fatal
- file            文件基名
- message         英文原始报错关键行
- code_snippet    出错行源码（读不到为 null）
- suggestion      给 RTL 组看的中文建议

完整返回结构（与 run_full_flow / auto_fix 同构）：
{"status": "...", "data": {"source_file", "linter", "note", "lint_errors": [...], "metrics": {"latency_ms", "errors", "warnings"}}, "error": null 或 11 字段标准错误, "meta": {"timestamp", "version", "source_file", "latency_ms"}}

边界约定（与闭环维护方的分工）：lint 报错本身 = 工具链问题，由插件维护人（胡肖瑶）修；闭环程序调用 lint 之后的流程 Bug = 闭环维护方修。
