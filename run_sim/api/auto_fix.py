#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_fix —— Verilog 简单错误自动修复
=========================================================
把"编译报错 → 规则匹配 → 生成修复副本 → 重新编译验证"串成闭环。

修复规则（v1.1 起为任务三合并版：吸收田玉伟 rtl2/tools/auto_fix.py 的三条规则，
架构沿用本文件的注册表+副本机制，对外 JSON 接口不变）：
    ① missing_semicolon  syntax 类：缺分号（报错行向上回溯找未闭合语句）
    ② sv_to_2001         syntax 类：SystemVerilog 构造转 Verilog-2001
                          （always_ff→always、always_comb→always @(*)、logic→reg；
                          iverilog 对这些只报笼统 syntax error，所以直接扫源码）
    ③ reg_to_wire        compile 类：reg 被连续赋值驱动（报错文本抓信号名，改声明）
    ④ wire_to_reg        compile 类：wire 在 always 块里被过程赋值（改声明）
    ②③④ 来自田玉伟版；策略优先级：syntax 先做 SV 转换（补分号规则容易
    把 always_comb begin 这类行误补分号），转换后仍报错再试补分号。

安全原则（硬性约束）：
    1. 源文件只读，任何情况下都不改动原文件；
    2. 修复结果一律写到 <源目录>/fixed/<名字>.fixed.v；
    3. 只有重新编译（iverilog）返回码为 0，才算修复成功——
       规则猜错了会被重编译当场打回，绝不假装修好。
    （对比：田玉伟原版直接改写源文件且不回滚，合并时已改为本文件的副本机制）

输出与 run_full_flow.py 同构的结构化 JSON：
    {
      "status": "success" | "already_ok" | "unsupported" | "fail",
      "data": {
        "source_file": "xxx.v",
        "fixed_file":  "fixed/xxx.fixed.v" | null,
        "fixer":       "missing_semicolon | sv_to_2001 | reg_to_wire | wire_to_reg" | null,
        "attempts":    [{"round": 1, "line": 26, "action": "append_semicolon"}],
        "verify":      "iverilog recompile returncode 0",
        "metrics":     {"latency_ms": 耗时, "rounds": 轮数}
      },
      "error":  null 或 11 字段标准错误（由 error_translator 生成）,
      "meta":   {"timestamp": ..., "version": "1.0", "source_file": ...}
    }

用法：
    # 命令行（在 run_sim 目录下执行）
    python api/auto_fix.py tests/demos/syntax_demo_a.v
    python api/auto_fix.py tests/demos/syntax_demo_a.v --out tests/demos/fixed

    # 作为函数调用
    from auto_fix import auto_fix
    result = auto_fix("tests/demos/syntax_demo_a.v")
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# 复用同目录的报错翻译官（拿到 error_type / file / line）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_translator import classify_error, make_tool_error, make_unknown_error  # noqa: E402

VERSION = "1.1"         # v1.1：任务三合并版（吸收田玉伟 3 条规则，接口不变）
MAX_ROUNDS = 3          # 单个文件最多修复轮数（防止规则来回乱改）
COMPILE_TIMEOUT = 30

# 需要跳过/绝不补分号的结构行
# 经验：控制语句要容忍不同空白风格，if ( 和 if( 都得认
_SKIP_ENDS = (",", ":", "(", ")", "+", "-", "*", "&", "|", "=")
_STRUCT_RE = re.compile(
    r"^\s*(?:"
    r"module\b|endmodule\b|endfunction\b|endtask\b|endcase\b|"
    r"begin\b|end\b|else\b|default\b|"
    r"(?:if|for|while|case|casex|casez)\s*\(.*\)\s*"      # 块头（无语句体）
    r")$")
_DECL_RE = re.compile(r"^\s*(?:`|//|/\*|\*)")             # 宏/注释行
# 行内注释（简单处理：Verilog 里 // 极少出现在字符串中）
_LINE_COMMENT_RE = re.compile(r"//")


# ----------------------------------------------------------------------
# 修复策略（v1.1 合并版）
# 统一签名 fn(lines, err_line, message, touched) ->
#     (新lines列表, action描述, line号或None) 或 None（本策略不适用/没命中）
# 策略按报错类型组队，组内按优先级依次尝试，第一条命中即应用。
# ----------------------------------------------------------------------

def fix_missing_semicolon(lines, err_line, touched):
    """规则①：缺分号（保留 v1.0 原逻辑，供 _apply_semicolon 调用）。
    iverilog 往往在读到下一个关键字时才报 syntax error（如007：26行漏分号，
    28行 endmodule 处才报错），所以从报错行向上回溯，找最近一条
    "语句性且未闭合"的行补分号。
    """
    for idx in range(err_line - 2, -1, -1):          # err_line 为 1-based，从其上一行开始
        line_no = idx + 1
        if line_no in touched:
            continue
        raw = lines[idx]
        s = raw.strip()
        if not s or _DECL_RE.match(s):
            continue                                 # 空行 / 注释 / 宏
        if s.endswith(";"):
            continue                                 # 已闭合
        if s.endswith(_SKIP_ENDS):
            continue                                 # 端口列表、续行表达式等
        if _STRUCT_RE.match(raw):
            continue                                 # begin/end/if(...) 等结构行
        # 命中候选：在语句末尾插分号（若有行内注释，插在注释前面）
        m = _LINE_COMMENT_RE.search(raw)
        if m:
            new_line = raw[:m.start()].rstrip() + ";" + raw[m.start():]
        else:
            new_line = raw.rstrip() + ";"
        return line_no, new_line
    return None


def _to_lines(text):
    return text.splitlines(keepends=True)


def _apply_semicolon(lines, err_line, message, touched):
    found = fix_missing_semicolon(lines, err_line, touched)
    if found is None:
        return None
    line_no, new_line = found
    nl = "\r\n" if lines[line_no - 1].endswith("\r\n") else "\n"
    out = list(lines)
    out[line_no - 1] = new_line + nl
    return out, "append_semicolon", line_no


def _apply_sv_to_2001(lines, err_line, message, touched):
    """规则②（田玉伟）：SystemVerilog 构造 → Verilog-2001。"""
    text = "".join(lines)
    new, n_ff = re.subn(r"\balways_ff\b", "always", text)
    new, n_comb = re.subn(r"\balways_comb\b", "always @(*)", new)
    new, n_logic = re.subn(r"\blogic\b", "reg", new)
    total = n_ff + n_comb + n_logic
    if not total:
        return None
    action = "sv_to_2001(always_ff×%d, always_comb×%d, logic×%d)" % (
        n_ff, n_comb, n_logic)
    return _to_lines(new), action, None


def _apply_reg_to_wire(lines, err_line, message, touched):
    """规则③（田玉伟）：reg 被连续赋值（assign）驱动 → 声明改 wire。
    iverilog 报错形如 "reg `q'; cannot be driven by continuous assignments"。
    """
    m = (re.search(r"reg\s+`?(\w+)'?;?\s*cannot be driven", message)
         or re.search(r"`?(\w+)'?[,;]?\s+cannot be driven", message))
    if not m:
        return None
    sig = m.group(1)
    new, n = re.subn(
        r"\breg\b(\s*(?:\[[^\]]*\])?\s*" + re.escape(sig) + r"\b)",
        r"wire\1", "".join(lines), count=1)
    if not n:
        return None
    return _to_lines(new), "reg_to_wire(%s)" % sig, None


def _apply_wire_to_reg(lines, err_line, message, touched):
    """规则④（田玉伟）：wire 在 always 块里被过程赋值 → 声明改 reg。
    iverilog 报错形如 "'q' is not a valid l-value in this assignment"。
    """
    m = re.search(r"`?(\w+)'?\s+is not a valid l-value", message)
    if not m:
        return None
    sig = m.group(1)
    new, n = re.subn(
        r"\bwire\b(\s*(?:\[[^\]]*\])?\s*" + re.escape(sig) + r"\b)",
        r"reg\1", "".join(lines), count=1)
    if not n:
        return None
    return _to_lines(new), "wire_to_reg(%s)" % sig, None


def _strategies_for(err):
    """按 11 字段错误的 outer error_type 返回本轮策略组（优先级从高到低）。"""
    if err["error_type"] == "syntax":
        # syntax：先 SV 转换（补分号规则会把 always_comb begin 误补分号），
        # 转换完没得转了自动落到补分号
        return [("sv_to_2001", _apply_sv_to_2001),
                ("missing_semicolon", _apply_semicolon)]
    # compile（含 invalid_lvalue）：驱动方式错位类，从报错文本抓信号名
    return [("reg_to_wire", _apply_reg_to_wire),
            ("wire_to_reg", _apply_wire_to_reg)]


def _ok(result, started, source_file, extra=None):
    """组装成功类结果（success / already_ok / unsupported）。"""
    latency = int((time.perf_counter() - started) * 1000)
    data = {
        "source_file": str(source_file),
        "fixed_file": None,
        "fixer": None,
        "attempts": [],
        "verify": None,
        "metrics": {"latency_ms": latency, "rounds": 0},
    }
    if extra:
        data.update(extra)
        data["metrics"]["rounds"] = len(data["attempts"])
    return {
        "status": result,
        "data": data,
        "error": None,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "source_file": str(source_file),
            "latency_ms": latency,
        },
    }


def _fail(error, started, source_file, attempts=None, fixer=None):
    """组装失败结果（fixer 尝试后重编译仍不通过）。"""
    latency = int((time.perf_counter() - started) * 1000)
    return {
        "status": "fail",
        "data": {
            "source_file": str(source_file),
            "fixed_file": None,
            "fixer": fixer,
            "attempts": attempts or [],
            "verify": "iverilog recompile still fails",
            "metrics": {"latency_ms": latency, "rounds": len(attempts or [])},
        },
        "error": error,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "source_file": str(source_file),
            "latency_ms": latency,
        },
    }


def _compile(path: Path):
    """编译单个源文件到临时产物，返回 (returncode, stderr文本)。"""
    with tempfile.TemporaryDirectory() as td:
        sim_exe = str(Path(td) / "sim_check")
        try:
            cp = subprocess.run(
                ["iverilog", "-o", sim_exe, "-Wall", str(path)],
                capture_output=True, timeout=COMPILE_TIMEOUT)
        except FileNotFoundError:
            return None, "TOOL_MISSING"
        except subprocess.TimeoutExpired:
            return None, "TIMEOUT"
        # 中文 Windows 编码兜底：先 UTF-8 再 GBK
        for enc in ("utf-8", "gbk"):
            try:
                return cp.returncode, cp.stderr.decode(enc)
            except UnicodeDecodeError:
                continue
        return cp.returncode, cp.stderr.decode("utf-8", errors="replace")


def auto_fix(source: str, out_dir: str = None):
    """
    对单个 Verilog 源文件执行 编译→修复→重编译 闭环。

    参数:
        source:  源文件路径（只读，绝不修改）
        out_dir: 修复副本输出目录，默认 <源目录>/fixed
    返回:
        结构化 dict（见模块开头格式说明）
    """
    started = time.perf_counter()
    src = Path(source).resolve()
    if not src.exists():
        return _fail(
            {"error_id": "001", "error_type": "compile", "severity": "error",
             "code": "RTL-COMPILE-0006", "file": src.name, "line": None,
             "module_name": None, "message": f"No such file: {src}",
             "column": None, "code_snippet": None,
             "suggestion": f"文件不存在：{src.name}"},
            started, src)

    out_path = Path(out_dir).resolve() if out_dir else src.parent / "fixed"
    out_path.mkdir(parents=True, exist_ok=True)

    # ---------------- 0. 首次编译 ----------------
    rc, stderr = _compile(src)
    if rc is None:
        if stderr == "TOOL_MISSING":
            return _fail(make_tool_error("iverilog"), started, src)
    if rc == 0:
        return _ok("already_ok", started, src,
                   {"verify": "first compile passed, nothing to fix"})

    # 翻译首次报错，确定类型/定位行
    err = classify_error(stderr, stage="compile") or make_unknown_error(stderr, "compile")

    # ---------------- 1. 选策略组（没有规则能处理这类错误则 unsupported，不瞎改文件） ----------------
    if err["error_type"] not in ("syntax", "compile"):
        return {
            "status": "unsupported",
            "data": {
                "source_file": str(src),
                "fixed_file": None,
                "fixer": None,
                "attempts": [],
                "verify": "no fixer registered for error_type=" + err["error_type"],
                "metrics": {
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "rounds": 0},
            },
            "error": err,
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": VERSION,
                "source_file": str(src),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            },
        }
    strategies = _strategies_for(err)

    # ---------------- 2. 多轮修复 → 每轮都重编译验证 ----------------
    lines = src.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    attempts, touched = [], set()
    cur_err_line = err["line"] or 1
    fixed_file = out_path / (src.stem + ".fixed.v")

    for round_no in range(1, MAX_ROUNDS + 1):
        # 组内按优先级依次试，第一条命中的策略生效
        applied = None
        for name, fn in strategies:
            res = fn(lines, cur_err_line, err["message"], touched)
            if res is not None:
                applied = (name,) + res          # (name, new_lines, action, line_no)
                break
        if applied is None:
            break
        name, lines, action, line_no = applied
        touched.add(line_no)                     # 文本级规则 line_no 为 None，无副作用
        attempts.append({"round": round_no, "line": line_no, "action": action})

        # 写修复副本（每轮覆盖同一个文件；源文件始终只读）
        fixed_file.write_text("".join(lines), encoding="utf-8")

        rc2, stderr2 = _compile(fixed_file)
        if rc2 == 0:
            return _ok("success", started, src, {
                "fixed_file": str(fixed_file),
                "fixer": name,
                "attempts": attempts,
                "verify": "iverilog recompile returncode 0",
            })

        # 仍失败：用新报错更新定位（行号 + message，规则③④靠 message 抓信号名）
        err2 = classify_error(stderr2, stage="compile")
        if err2:
            err = err2
            if err2["line"]:
                cur_err_line = err2["line"]

    # 所有轮次都没修好
    if attempts:
        final_err = classify_error(stderr2, stage="compile") or make_unknown_error(stderr2, "compile")
        res = _fail(final_err, started, src, attempts, fixer=attempts[-1]["action"])
        res["data"]["fixed_file"] = str(fixed_file)   # 保留失败副本供人工查看
        return res
    return _fail(err, started, src, attempts)


# ---------------------------- 命令行入口 ----------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Verilog 简单错误自动修复：编译→规则修复→重编译验证")
    ap.add_argument("source", help="待修复的 .v 源文件（原文件只读不改）")
    ap.add_argument("--out", default=None,
                    help="修复副本输出目录（默认 源目录/fixed）")
    args = ap.parse_args()

    result = auto_fix(args.source, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # success / already_ok 退出 0；unsupported / fail 退出 1
    sys.exit(0 if result["status"] in ("success", "already_ok") else 1)


if __name__ == "__main__":
    main()
