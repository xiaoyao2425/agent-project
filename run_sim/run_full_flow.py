#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_full_flow —— 仿真一条龙（W1 成果）
=====================================
把“查文件 → 编译 → 仿真 → 验波形”串成一条流水线，
输出不再是杂乱的控制台打印，而是评测组能直接读取的结构化 JSON：

    {
      "status": "success" | "fail",
      "data":   {"output": 仿真标准输出, "metrics": {"latency_ms": 耗时}},
      "error":  null 或 11 字段标准错误（error_translator.py 生成）：
                {
                  "error_id":     "001",
                  "error_type":   "syntax | simulation | assertion | timeout | uvm_fatal | compile",
                  "severity":     "error | warn | fatal",
                  "code":         "RTL-SYNTAX-0001",
                  "file":         "fifo.sv",
                  "line":         123,
                  "module_name":  "top.dut.u_fifo" | null,
                  "message":      "英文原始报错关键行",
                  "column":       45 | null,
                  "code_snippet": "出错行源码" | null,
                  "suggestion":   "给 RTL 组看的中文建议"
                },
      "meta":   {"timestamp": 时间戳, "version": "2.0", "top_name": ...}
    }

用法：
    # 作为函数被其他脚本调用
    from run_full_flow import run_full_flow
    result = run_full_flow("tb/tb_mux.v", ["design/mux.v"], top_name="mux")

    # 命令行直接跑（JSON 打印到屏幕，可用 --out 存档）
    python run_full_flow.py tb/tb_mux.v design/mux.v --top mux
    python run_full_flow.py tests/tb_bad_syntax.v tests/bad_syntax.v \
        --top bad_syntax --out tests/evidence/case2_syntax.json
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 中文 Windows 上 iverilog/vvp 的输出编码不稳定：
# 可能是 UTF-8，也可能是 GBK（含中文路径时），因此拿原始字节自己探测
def _decode(raw: bytes) -> str:
    """先按 UTF-8 严格解码，失败再退回 GBK，保证中文路径不乱码。"""
    if raw is None:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

# 同目录的 W3 翻译官
sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_translator import (  # noqa: E402
    classify_error,
    make_file_error,
    make_tool_error,
    make_timeout_error,
    make_unknown_error,
    make_wave_error,
)

VERSION = "2.0"
_DUMPFILE_RE = re.compile(r'\$dumpfile\s*\(\s*"([^"]+)"\s*\)')


def _fail(error: dict, top_name: str, started: float, testbench: str):
    """组装失败结果。"""
    return {
        "status": "fail",
        "data": None,
        "error": error,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "top_name": top_name,
            "testbench": str(testbench),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    }


def run_full_flow(testbench: str, dut_files=None, top_name: str = None,
                  compile_timeout: int = 30, sim_timeout: int = 60):
    """
    一条龙跑完整仿真流程。

    参数:
        testbench:      testbench 文件（.v）
        dut_files:      DUT 设计文件列表（testbench 始终排在编译列表最后）
        top_name:       顶层名，用于命名 sim 可执行文件；缺省取 testbench 文件名
        compile_timeout: 编译超时秒数
        sim_timeout:     仿真超时秒数
    返回:
        结构化 dict（见模块开头的格式说明）
    """
    started = time.perf_counter()
    dut_files = dut_files or []
    tb_path = Path(testbench).resolve()
    dut_paths = [Path(f).resolve() for f in dut_files]
    top_name = top_name or tb_path.stem.replace("tb_", "")

    # 所有子进程以 run_sim 根目录（脚本所在目录）为工作目录：
    # testbench 里的 $dumpfile("waves/xx.vcd") 与编译产物 output/ 都锚定在这里，
    # 无论 testbench 放在 tb/ 还是 tests/，波形都统一落到 run_sim/waves/
    workdir = Path(__file__).resolve().parent
    sim_exe = workdir / "output" / f"sim_{top_name}"
    (workdir / "output").mkdir(parents=True, exist_ok=True)

    # ---------------- 0. 文件存在性检查 ----------------
    if not tb_path.exists():
        return _fail(make_file_error(str(tb_path)), top_name, started, testbench)
    for f in dut_paths:
        if not f.exists():
            return _fail(make_file_error(str(f)), top_name, started, testbench)

    (workdir / "waves").mkdir(parents=True, exist_ok=True)

    # ---------------- 1. 编译 ----------------
    compile_cmd = ["iverilog", "-o", str(sim_exe), "-Wall"]
    compile_cmd.extend(str(f) for f in dut_paths)
    compile_cmd.append(str(tb_path))

    try:
        cp = subprocess.run(
            compile_cmd, capture_output=True,
            timeout=compile_timeout, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        return _fail(make_timeout_error("compile", compile_timeout),
                     top_name, started, testbench)
    except FileNotFoundError:
        return _fail(make_tool_error("iverilog"),
                     top_name, started, testbench)

    if cp.returncode != 0:
        stderr = _decode(cp.stderr)
        err = classify_error(stderr, stage="compile") \
            or make_unknown_error(stderr, "compile")
        return _fail(err, top_name, started, testbench)

    # ---------------- 2. 仿真 ----------------
    try:
        sp = subprocess.run(
            ["vvp", str(sim_exe)], capture_output=True,
            timeout=sim_timeout, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        return _fail(make_timeout_error("sim", sim_timeout),
                     top_name, started, testbench)
    except FileNotFoundError:
        return _fail(make_tool_error("vvp"),
                     top_name, started, testbench)

    if sp.returncode != 0:
        stderr = _decode(sp.stderr)
        err = classify_error(stderr, stage="sim") \
            or make_unknown_error(stderr, "sim")
        return _fail(err, top_name, started, testbench)

    # ---------------- 3. 验证波形 ----------------
    wave_name = None
    try:
        m = _DUMPFILE_RE.search(tb_path.read_text(encoding="utf-8",
                                                  errors="ignore"))
        if m:
            wave_name = m.group(1)
    except OSError:
        pass

    if wave_name:
        wave_path = (workdir / wave_name).resolve()
    else:
        # testbench 没写 $dumpfile 时，退而检查 waves 目录里有没有 vcd
        waves = sorted((workdir / "waves").glob("*.vcd"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        wave_path = waves[0] if waves else None

    if wave_path is None or not wave_path.exists() or wave_path.stat().st_size == 0:
        return _fail(make_wave_error(), top_name, started, testbench)

    # ---------------- 4. 成功 ----------------
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": "success",
        "data": {
            "output": _decode(sp.stdout).strip(),
            "metrics": {
                "latency_ms": latency_ms,
                "wave_file": str(wave_path),
                "wave_size_bytes": wave_path.stat().st_size,
            },
        },
        "error": None,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "top_name": top_name,
            "testbench": str(tb_path),
            "latency_ms": latency_ms,
        },
    }


# ---------------------------- 命令行入口 ----------------------------

def main():
    ap = argparse.ArgumentParser(
        description="仿真一条龙：编译→仿真→验波形，输出结构化 JSON")
    ap.add_argument("testbench", help="testbench .v 文件")
    ap.add_argument("dut", nargs="*", help="DUT .v 文件（0 个或多个）")
    ap.add_argument("--top", default=None, help="顶层名（默认取 testbench 文件名）")
    ap.add_argument("--compile-timeout", type=int, default=30)
    ap.add_argument("--sim-timeout", type=int, default=60)
    ap.add_argument("--out", default=None, help="把 JSON 结果同时写入该文件")
    args = ap.parse_args()

    result = run_full_flow(
        args.testbench, args.dut, top_name=args.top,
        compile_timeout=args.compile_timeout, sim_timeout=args.sim_timeout)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\n[已存档] {out_path}", file=sys.stderr)

    # 成功退出码 0，失败 1，方便 CI 判定
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
