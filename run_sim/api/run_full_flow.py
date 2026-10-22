#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_full_flow —— 仿真一条龙
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

# 同目录的翻译官
sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_translator import (  # noqa: E402
    classify_error,
    make_file_error,
    make_tool_error,
    make_timeout_error,
    make_unknown_error,
    make_wave_error,
    _make,
)

VERSION = "2.1"
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
                  compile_timeout: int = 30, sim_timeout: int = 60,
                  assert_pass: bool = False):
    """
    一条龙跑完整仿真流程。

    参数:
        testbench:      testbench 文件（.v）
        dut_files:      DUT 设计文件列表（testbench 始终排在编译列表最后）
        top_name:       顶层名，用于命名 sim 可执行文件；缺省取 testbench 文件名
        compile_timeout: 编译超时秒数
        sim_timeout:     仿真超时秒数
        assert_pass:    是否做功能自检判定（v2.1 新增）。tb 的功能断言失败时
                        vvp 退出码仍为 0，只看退出码会把功能失败误判成 success；
                        True 时按闭环约定检查 stdout：有 PASS 且无 FAIL/Error，
                        或正常结束且无 FAIL/Error → 通过；否则 status=fail、
                        error_type=assertion（RTL-ASSERT-0001），供闭环触发回喂。
                        闭环调用建议恒为 True；默认 False 保持旧行为。
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
    # 锚定 run_sim 根目录（api/ 的上一级），波形/编译产物统一落 run_sim 下
    workdir = Path(__file__).resolve().parent.parent
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

    # ---------------- 4. 功能自检（assert_pass=True 时启用） ----------------
    # tb 功能断言失败时 vvp 退出码仍是 0，必须查 stdout 文本才能发现；
    # 判定规则与闭环方（run_loop.py）保持一致
    sim_out = _decode(sp.stdout)
    pass_text = None
    if assert_pass:
        has_pass = "PASS" in sim_out
        has_fail = ("FAIL" in sim_out) or ("Error" in sim_out)
        finished = ("Simulation finished" in sim_out or "$finish" in sim_out
                    or sim_out.strip() != "")
        pass_text = (has_pass and not has_fail) or (finished and not has_fail)
        if not pass_text:
            tail = "\n".join(sim_out.strip().splitlines()[-5:]) or "(无输出)"
            err = _make(
                "assertion", f"tb functional self-check failed: {tail}",
                "功能自检失败：仿真正常跑完，但 tb 输出里没有 PASS 或出现了 "
                "FAIL/Error（判定规则：有 PASS 且无 FAIL/Error，或正常结束且无 "
                "FAIL）；请检查 tb 断言条件与 valid/ready 握手时序")
            return _fail(err, top_name, started, testbench)

    # ---------------- 5. 成功 ----------------
    latency_ms = int((time.perf_counter() - started) * 1000)
    metrics = {
        "latency_ms": latency_ms,
        "wave_file": str(wave_path),
        "wave_size_bytes": wave_path.stat().st_size,
    }
    if pass_text is not None:
        metrics["pass_text_check"] = pass_text
    return {
        "status": "success",
        "data": {
            "output": sim_out.strip(),
            "metrics": metrics,
        },
        "error": None,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "top_name": top_name,
            "testbench": str(tb_path),
            "assert_pass": assert_pass,
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
    ap.add_argument("--assert-pass", action="store_true",
                    help="启用功能自检：tb 输出无 PASS 或含 FAIL/Error 时判 fail"
                         "（assertion），闭环调用建议加上")
    ap.add_argument("--out", default=None, help="把 JSON 结果同时写入该文件")
    args = ap.parse_args()

    result = run_full_flow(
        args.testbench, args.dut, top_name=args.top,
        compile_timeout=args.compile_timeout, sim_timeout=args.sim_timeout,
        assert_pass=args.assert_pass)

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
