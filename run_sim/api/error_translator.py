#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报错翻译官（v2 新版报错格式）
=====================================
把 iverilog/vvp 满屏英文报错，翻译并归类成评测组规定的 11 字段标准 JSON：

    {
      "error_id":     "001",               # 本次运行内的错误序号（字符串）
      "error_type":   "syntax | simulation | assertion | timeout | uvm_fatal | compile",
      "severity":     "error | warn | fatal",
      "code":         "RTL-SYNTAX-0001",   # 错误码 = RTL-<类型大写>-4位编号
      "file":         "fifo.sv",           # 文件基名（解析不到为 null）
      "line":         123,                 # 出错行号（解析不到为 null）
      "module_name":  "top.dut.u_fifo",    # 层次化模块路径（解析不到为 null）
      "message":      "Assertion failed: valid && ready",   # 英文原始报错关键行
      "column":       45,                  # 列号（解析不到为 null）
      "code_snippet": "assert(valid && ready);",   # 出错行源码（读不到为 null）
      "suggestion":   "检查 valid/ready 握手时序"           # 给 RTL 组看的中文建议
    }

对外接口：
    classify_error(stderr, stage="compile", error_id="001") -> dict | None
    make_file_error(path) / make_tool_error(tool) /
    make_timeout_error(stage, seconds) / make_wave_error() /
    make_unknown_error(stderr, stage) -> dict（均为 11 字段格式）
"""

import json
import re
from pathlib import Path

# 脚本所在目录：code_snippet 按文件名在这里递归查找源文件
# 锚定 run_sim 根目录（api/ 的上一级），rglob 才能覆盖 tests/ 等全部源码样例
SCRIPT_DIR = Path(__file__).resolve().parent.parent

# ======================================================================
# 内部错误类别 → 11 字段里的 error_type / severity / code 映射表
# error_type 只允许 6 种（评测组《报错类型》规定）：
#   syntax / simulation / assertion / timeout / uvm_fatal / compile
# code 目录：RTL-<类型大写>-4位编号，每种类别里再按细分原因编号
# ======================================================================
ERROR_KINDS = {
    # 内部类别           对外 type      severity   错误码
    "module_not_found": ("compile",    "error", "RTL-COMPILE-0001"),
    "no_top":           ("compile",    "error", "RTL-COMPILE-0002"),
    "undefined":        ("compile",    "error", "RTL-COMPILE-0003"),
    "port_mismatch":    ("compile",    "error", "RTL-COMPILE-0004"),
    "compile":          ("compile",    "error", "RTL-COMPILE-0005"),
    "file_missing":     ("compile",    "error", "RTL-COMPILE-0006"),
    "tool_missing":     ("compile",    "error", "RTL-COMPILE-0007"),
    "lint_warning":     ("compile",    "warn",  "RTL-COMPILE-0008"),
    "invalid_lvalue":   ("compile",    "error", "RTL-COMPILE-0009"),
    "tristate":         ("compile",    "error", "RTL-COMPILE-0010"),
    "syntax":           ("syntax",     "error", "RTL-SYNTAX-0001"),
    "assertion":        ("assertion",  "error", "RTL-ASSERT-0001"),
    "uvm_fatal":        ("uvm_fatal",  "fatal", "RTL-UVM-0001"),
    "simulation":       ("simulation", "error", "RTL-SIM-0001"),
    "wave_missing":     ("simulation", "error", "RTL-SIM-0002"),
    "timeout":          ("timeout",    "fatal", "RTL-TIMEOUT-0001"),
}

# ======================================================================
# 报错关键词映射表
# 规则按“从具体到笼统”的顺序匹配，第一条命中即分类；
# 每条规则 = (内部类别, 关键词列表, 中文建议模板)
# 模板里的 {file} {line} {detail} 会在命中时自动填充
# ======================================================================
ERROR_RULES = [
    # --- 最具体：找不到模块（必须排在 undefined 前面）---
    (
        "module_not_found",
        ["unknown module type", "unable to find the module",
         "cannot find module", "module not found"],
        "找不到模块：{file}第 {line} 行例化了一个不存在的模块"
        "（检查模块名拼写，或编译时是否漏加了它的 .v 文件）",
    ),
    # --- testbench 缺失导致没有顶层 ---
    (
        "no_top",
        ["no top level modules"],
        "没有可仿真的顶层模块（通常是编译列表里漏加了 testbench 文件，"
        "或 testbench 里没有 initial 块）",
    ),
    # --- 超时（必须排在 uvm_fatal 前面：testbench 看门狗常打印 FATAL: TIMEOUT，
    #     不能被裸 'fatal' 关键词抢命中）---
    (
        "timeout",
        ["timeout", "timed out", "watchdog", "never completed within",
         "deadlock"],
        "仿真超时：{detail}（常见原因：valid/ready 握手一直等不到、"
        "testbench 里有死循环、等待条件永远不成立）",
    ),
    # --- UVM 致命错误（只认真正带 UVM 标识的，不再用裸 'fatal:' 兜底）---
    (
        "uvm_fatal",
        ["uvm_fatal", "uvm fatal", "uvm_report_fatal"],
        "UVM 报致命错误（uvm_fatal），仿真已中止：{detail}",
    ),
    # --- Verilator 风格/lint 警告（%Warning-XXX，严重度 warn）---
    (
        "lint_warning",
        ["%warning-", "declfilename", "lint warning"],
        "Lint 风格警告：{detail}（不影响编译，但建议按规范清理；"
        "确认是误报也可用 -Wno-<警告名> 屏蔽）",
    ),
    # --- 断言失败（含 testbench 自检打印的 [FAIL]，中文 TB 同样适用）---
    (
        "assertion",
        ["assertion failed", "assert failed", "$assert",
         "assertion error", "[fail]", "test failed"],
        "断言失败：{detail}（检查 valid/ready 握手时序，"
        "或断言条件涉及的信号是否在正确时刻采样）",
    ),
    # --- 对 wire 做过程赋值（output wire 不能在 always 里 <=）---
    (
        "invalid_lvalue",
        ["not a valid l-value", "invalid lvalue", "is not a lvalue",
         "l-value"],
        "非法左值：{file}第 {line} 行对不能被过程赋值的对象（通常是 wire）"
        "使用了 = 或 <=。两种改法：(1) 常量驱动改成 assign；"
        "(2) 需要随状态变化就把端口/信号声明从 wire 改成 reg",
    ),
    # --- 三态误用：对 reg 赋高阻（ASSIGNDLY 等）---
    (
        "tristate",
        ["unsupported tristate", "assigndly", "tri-state",
         "tristate construct"],
        "三态使用错误：{file}第 {line} 行对寄存器赋了 1'bz——"
        "高阻只能出现在 assign 的三态表达式里，reg 只能存 0/1。"
        "应改为通过输出使能 oe 控制：assign sda = oe ? out : 1'bz",
    ),
    # --- 语法错误 ---
    (
        "syntax",
        ["syntax error", "parse error"],
        "语法错误：{file}第 {line} 行附近写法不合法"
        "（最常见原因：少了分号、begin/end 不配对、括号不匹配；"
        "注意工具报错行可能在真正出错行的下一行，应向上回溯找未闭合语句）",
    ),
    # --- 未声明/未定义（iverilog 与 Verilator 两种措辞都覆盖）---
    (
        "undefined",
        ["undefined variable", "is not declared", "undeclared",
         "unknown identifier", "implicit declaration",
         "has no explicit declaration",
         "unable to bind wire/reg/memory", "unable to bind",
         "can't find definition", "cannot find definition",
         "undeclared identifier", "has not been declared"],
        "未定义：{file}第 {line} 行用到了未声明的信号或变量"
        "（检查是否忘记 wire/reg 声明，或名字大小写/拼写错误；"
        "Verilator 的 Suggested alternative 可能直接给出了正确名字）",
    ),
    # --- 位宽/连接类警告级错误 ---
    (
        "port_mismatch",
        ["port", "does not match", "too few arguments",
         "too many arguments", "connection"],
        "端口连接错误：{file}第 {line} 行模块例化的端口对不上"
        "（检查端口数量、顺序和位宽）",
    ),
    # --- 仿真运行期错误 ---
    (
        "simulation",
        ["execution suspended", "segmentation fault", "out of bounds",
         "array index", "fatal", "abort"],
        "仿真运行期错误：{detail}（常见为数组越界、信号为 X、除零等）",
    ),
]

# 报错定位行：文件名:行号[:列号]: 内容
# 例如：bad_syntax.v:7: syntax error
#       tb_x.v:9: error: Unknown module type: foo
#       other.v:12.4: syntax error      （带列号的格式也能识别）
# Windows 上文件名可能是带盘符的绝对路径：D:\dir\bad_syntax.v:8: syntax error
_LOC_RE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+)"
    r"(?:[.:](?P<col>\d+))?:\s*(?:error:\s*)?(?P<msg>.+)$")

# 层次化模块路径（至少 3 段，如 top.dut.u_fifo），避免把 mux.vcd 这类文件名误判成模块
_MODULE_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){2,})\b")

# 内联行号回退：没有“文件:行号:”定位时，从消息文本里提取行号
# 覆盖 Verilator 的 "(line 27:5)" 与 testbench 打印的 "(... line 41)"
_INLINE_LINE_RE = re.compile(
    r"\bline\s+(?P<line>\d+)(?:[:.](?P<col>\d+))?\b")


def _pick_key_lines(stderr: str):
    """从整段 stderr 里挑出带 '文件:行号:' 定位信息的行。"""
    located = []
    for raw in stderr.splitlines():
        line = raw.strip()
        m = _LOC_RE.match(line)
        if m:
            located.append({
                "file": Path(m.group("file")).name,
                "line": int(m.group("line")),
                "column": int(m.group("col")) if m.group("col") else None,
                "msg": m.group("msg").strip(),
                "raw": line,
            })
    return located


def _find_source(file_name):
    """按文件基名在 run_sim 目录下递归查找源文件（design/、tb/、tests/ 都能找到）。"""
    if not file_name:
        return None
    try:
        for p in SCRIPT_DIR.rglob(file_name):
            return p
    except OSError:
        pass
    return None


def _read_snippet(file_name, line_no):
    """读取出错行源码作为 code_snippet，文件或行号读不到时返回 None。"""
    if not file_name or not line_no:
        return None
    src = _find_source(file_name)
    if src is None:
        return None
    try:
        lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip()
    except OSError:
        pass
    return None


def _find_module_name(text):
    """从报错文本里解析层次化模块路径（如 top.dut.u_fifo），解析不到返回 None。"""
    m = _MODULE_RE.search(text or "")
    return m.group(1) if m else None


def _make(kind, message, suggestion, file=None, line=None, column=None,
          module_name=None, snippet=None, error_id="001"):
    """按评测组规定的 11 字段格式组装错误 dict。"""
    error_type, severity, code = ERROR_KINDS[kind]
    return {
        "error_id": str(error_id).zfill(3),
        "error_type": error_type,
        "severity": severity,
        "code": code,
        "file": file,
        "line": line,
        "module_name": module_name,
        "message": message,
        "column": column,
        "code_snippet": snippet,
        "suggestion": suggestion,
    }


def classify_error(stderr: str, stage: str = "compile", error_id="001"):
    """
    把英文 stderr 归类并翻译成 11 字段标准格式。

    参数:
        stderr:   iverilog/vvp 的标准错误输出
        stage:    "compile"（编译阶段）或 "sim"（仿真阶段）
        error_id: 本次运行内的错误序号（默认 "001"）
    返回:
        dict（11 字段），无法识别时返回 None（调用方按未知错误兜底）。
    """
    if not stderr:
        return None

    text = stderr.lower()
    located = _pick_key_lines(stderr)

    # 1) 按关键词表逐条匹配
    for error_type, keywords, template in ERROR_RULES:
        hit_kw = next((kw for kw in keywords if kw in text), None)
        if hit_kw is None:
            continue

        # 尽量把行号定位到“命中关键词的那一行”
        loc = next((x for x in located if hit_kw in x["msg"].lower()), None)
        if loc is None:
            # 回退1：在所有含关键词的行里，优先选带内联行号的行
            # （避免选到“VCD info: dumpfile timeout_demo.vcd”这种
            #   仅文件名碰巧含关键词的无关行）
            cand = [l.strip() for l in stderr.splitlines()
                    if hit_kw in l.lower()]
            hit_line = next((l for l in cand
                             if _INLINE_LINE_RE.search(l)), None) \
                or (cand[0] if cand else None)
            detail = hit_line or hit_kw
            # 回退2：从该行提取内联行号，如 (line 27:5) / (... line 41)
            if hit_line:
                m = _INLINE_LINE_RE.search(hit_line)
                if m:
                    loc = {
                        "file": None,
                        "line": int(m.group("line")),
                        "column": int(m.group("col")) if m.group("col") else None,
                        "msg": hit_line,
                        "raw": hit_line,
                    }
        else:
            detail = loc["msg"]
        return _build_result(error_type, loc, detail, template, stderr, error_id)

    # 2) 没命中关键词，但有 文件名:行号 定位 —— 按阶段兜底
    if located:
        loc = located[0]
        if stage == "compile":
            return _build_result(
                "compile", loc, loc["msg"],
                "编译未通过：{file}第 {line} 行有错误（详见英文原文）", stderr, error_id)
        return _build_result(
            "simulation", loc, loc["msg"],
            "仿真运行报错：{file}第 {line} 行（详见英文原文）", stderr, error_id)

    return None


def _build_result(error_type, loc, detail, template, stderr, error_id="001"):
    """组装 11 字段错误 dict，定位信息解析不到时对应字段为 null。"""
    file_name = loc["file"] if loc else None
    line_no = loc["line"] if loc else None
    column = loc["column"] if loc else None

    file_disp = f"{file_name} " if file_name else ""
    try:
        suggestion = template.format(
            file=file_disp,
            line=line_no if line_no is not None else "?",
            detail=detail,
        )
    except (KeyError, IndexError):
        suggestion = template

    # message 尽可能完整：优先保留带定位的原始行，否则截取 stderr 第一个非空行
    if loc:
        message = loc["raw"]
    else:
        message = next((l.strip() for l in stderr.splitlines() if l.strip()),
                       stderr.strip()[:200])

    return _make(
        error_type, message, suggestion,
        file=file_name,
        line=line_no,
        column=column,
        module_name=_find_module_name(message),
        snippet=_read_snippet(file_name, line_no),
        error_id=error_id,
    )


# ----------------------------------------------------------------------
# 几个不来自 stderr 的、由 run_full_flow 直接构造的错误
# ----------------------------------------------------------------------

def make_file_error(path: str, error_id="001"):
    """文件不存在类错误。"""
    name = Path(path).name
    return _make(
        "file_missing", f"No such file: {path}",
        f"文件不存在：{name}（检查路径和文件名拼写）",
        file=name, error_id=error_id)


def make_tool_error(tool: str, error_id="001"):
    """iverilog/vvp 没装或不在 PATH。"""
    return _make(
        "tool_missing", f"FileNotFoundError: {tool}",
        f"找不到工具 {tool}：请确认 Icarus Verilog 已安装"
        "且所在目录已加入系统 PATH",
        error_id=error_id)


def make_timeout_error(stage: str, seconds: int, error_id="001"):
    """编译/仿真超时。"""
    where = "编译" if stage == "compile" else "仿真"
    return _make(
        "timeout", f"{stage} timeout after {seconds}s",
        f"{where}超时（超过 {seconds} 秒未结束，"
        "常见原因：testbench 里有死循环，或 ready/valid 一直等不到）",
        error_id=error_id)


def make_wave_error(error_id="001"):
    """仿真跑完但波形文件缺失/为空。"""
    return _make(
        "wave_missing", "waveform (.vcd) not generated or empty",
        "波形文件未生成或为空：检查 testbench 里是否写了 "
        "$dumpfile/$dumpvars，且路径（waves/xx.vcd）可写",
        error_id=error_id)


def make_unknown_error(stderr: str, stage: str, error_id="001"):
    """关键词表没覆盖时的最终兜底。"""
    where = "编译" if stage == "compile" else "仿真"
    first_line = next((l.strip() for l in (stderr or "").splitlines() if l.strip()),
                      "无输出")
    kind = "compile" if stage == "compile" else "simulation"
    return _make(
        kind, first_line,
        f"{where}未成功，但错误不在已知关键词表内，"
        "请把这段英文原文发给环境组人工确认",
        error_id=error_id)


# 自测：python error_translator.py
if __name__ == "__main__":
    samples = [
        ("bad_syntax.v:7: syntax error", "compile"),
        ("tb_x.v:9: error: Unknown module type: nonexistent_mod", "compile"),
        ("foo.v:3: error: `bar' is not declared here", "compile"),
        ("ERROR: assertion failed: valid && ready", "sim"),
        ("some weird unrecognized message", "compile"),
    ]
    # 第 1 条样例打印完整 11 字段 JSON，其余打印摘要
    for i, (text, st) in enumerate(samples):
        print("原文:", text)
        r = classify_error(text, st) or make_unknown_error(text, st)
        if i == 0:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print("  ->", r["error_type"], "|", r["code"], "| 行",
                  r["line"], "|", r["suggestion"])
        print()
