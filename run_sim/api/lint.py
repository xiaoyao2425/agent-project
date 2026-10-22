#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lint —— Verilog 语法/规范静态检查（Lint 黑盒）
=========================================================
输入 Verilog 源文件，输出评测组标准格式的结构化 JSON。

状态约定（外层 status）：
    "pass"   无任何问题
    "warn"   只有警告（不阻塞，闭环里可继续仿真）
    "fail"   有错误（阻塞，闭环里建议接 auto_fix）
    "unsupported"  不支持的文件类型（如 .vhd——本轮只做 Verilog，
                   架构上留了口子，以后有需求再加）

输出格式（与 run_full_flow / auto_fix 同构）：
    {
      "status": "pass | warn | fail | unsupported",
      "data": {
        "source_file": "xxx.v",
        "linter":      "verilator(native) | verilator(wsl) | iverilog-fallback",
        "note":        "降级/不支持等补充说明，正常时省略",
        "lint_errors": [
          {"line": 15, "column": 5, "rule": "syntax", "severity": "error",
           "file": "xxx.v", "message": "...", "code_snippet": "...",
           "suggestion": "给 RTL 组看的中文建议"}
        ],
        "metrics": {"latency_ms": 耗时, "errors": n, "warnings": m}
      },
      "error": null 或 11 字段标准错误（仅工具级故障时填充）,
      "meta":  {"timestamp": ..., "version": "1.0", "source_file": ...}
    }

用法：
    # 命令行（JSON 打印到屏幕，可用 --out 存档）
    python api/lint.py design/mux.v                       # 在 run_sim 目录下执行
    python api/lint.py design/counter.v design/dff.v      # 有依赖的多文件一起给
    python api/lint.py tests/bad_syntax.v --out tests/evidence/case4_lint_syntax.json

    # 作为函数被闭环调用
    from lint import lint
    result = lint("design/mux.v")
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# 复用同目录的翻译官：工具级故障沿用 11 字段标准错误
sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_translator import (  # noqa: E402
    ERROR_KINDS,
    classify_error,
    make_file_error,
    make_unknown_error,
    _make,
)

VERSION = "1.0"
LINT_TIMEOUT = 30

SUPPORTED_EXTS = {".v", ".sv"}        # 本轮只做 Verilog / SystemVerilog
VHDL_EXTS = {".vhd", ".vhdl", ".vho"}  # 留口子：明确给出“暂不支持”而不是含糊报错

# 中文 Windows 编码兜底：先 UTF-8 再 GBK（与 run_full_flow 一致）
def _decode(raw: bytes) -> str:
    if raw is None:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ======================================================================
# Verilator 发现：native PATH → MSYS2 已知安装路径 → WSL → 都没有则降级 iverilog
# MSYS2 的 verilator_bin.exe 必须配 VERILATOR_ROOT 才能跑（李煜荣机器已验证：
# D:\MSYS2\mingw64\bin\verilator_bin.exe + D:\MSYS2\mingw64\share\verilator）
# 结果缓存在模块级，同进程只探测一次
# ======================================================================
_verilator_cache = None

# 常见 MSYS2 安装位置（按优先级； Roots = 对应 VERILATOR_ROOT）
_MSYS2_CANDIDATES = [
    (r"D:\MSYS2\mingw64\bin\verilator_bin.exe",
     r"D:\MSYS2\mingw64\share\verilator"),
    (r"D:\MSYS2\ucrt64\bin\verilator_bin.exe",
     r"D:\MSYS2\ucrt64\share\verilator"),
    (r"C:\msys64\mingw64\bin\verilator_bin.exe",
     r"C:\msys64\mingw64\share\verilator"),
    (r"C:\msys64\ucrt64\bin\verilator_bin.exe",
     r"C:\msys64\ucrt64\share\verilator"),
]

def _find_verilator():
    """返回 (mode, 命令前缀 list, 额外环境变量 dict 或 None)。
    mode ∈ native | msys2 | wsl | none"""
    global _verilator_cache
    if _verilator_cache is not None:
        return _verilator_cache
    if shutil.which("verilator"):
        _verilator_cache = ("native", ["verilator"], None)
        return _verilator_cache
    for bin_path, root in _MSYS2_CANDIDATES:
        if Path(bin_path).is_file():
            _verilator_cache = ("msys2", [bin_path],
                                {"VERILATOR_ROOT": root})
            return _verilator_cache
    try:
        cp = subprocess.run(
            ["wsl", "-e", "bash", "-lc", "command -v verilator"],
            capture_output=True, timeout=10)
        found = (cp.returncode == 0)
    except (OSError, subprocess.SubprocessError):
        found = False
    _verilator_cache = ("wsl", ["wsl", "-e", "verilator"], None) if found \
        else ("none", None, None)
    return _verilator_cache


def _to_wsl_path(p: Path) -> str:
    """D:\\dir\\x.v → /mnt/d/dir/x.v（其他路径原样把反斜杠换成正斜杠）。"""
    s = str(p.resolve())
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if not m:
        return s.replace("\\", "/")
    return f"/mnt/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}"


# ======================================================================
# Verilator 输出解析
#   %Warning-WIDTHEXPAND: design/mux.v:12:20: Bits of signal are discarded
#   %Error: tests/bad_syntax.v:7: syntax error, unexpected ...
#   （v4 老格式为 %Error: file:line: msg，两种都兼容）
# ======================================================================
_MSG_RE = re.compile(
    r"^%(?P<sev>Error|Warning|Fatal)(?:-(?P<rule>[A-Za-z][A-Za-z0-9_]*))?"
    r":\s*(?P<rest>.*)$")
_LOC_RE = re.compile(
    r"^(?P<file>[^:\n]+?):(?P<line>\d+)(?:[.:](?P<col>\d+))?:\s*(?P<msg>.+)$")

_SEV_MAP = {"Error": "error", "Warning": "warn", "Fatal": "fatal"}

# 高频 Verilator 规则的中文建议（rule 名与 -Wno-<rule> 一致，方便屏蔽误报）
_RULE_SUGGESTIONS = {
    "WIDTH": "位宽不匹配：检查赋值两侧信号位宽，必要时显式扩展或截位",
    "WIDTHEXPAND": "右侧位宽小于左侧、被自动零扩展：确认是有意为之，否则修改信号宽度",
    "WIDTHTRUNC": "右侧位宽大于左侧、高位被自动丢弃：会丢数据，加位或显式截取",
    "UNUSEDSIGNAL": "信号声明了但从未使用：删除，或按规范加 /* unused */ 标记",
    "UNDRIVEN": "信号没有驱动源：检查是否漏写 assign 或 always 赋值",
    "DECLFILENAME": "文件名与模块名不一致：规范要求 xxx.v 里定义 xxx 模块",
    "PINCONNECTEMPTY": "端口悬空连接（.pin()）：确认是否应显式连接",
    "PINMISSING": "例化时漏接端口：补上未连接的端口",
    "COMBDLY": "组合逻辑用了非阻塞赋值 <=：组合 always 块应使用阻塞赋值 =",
    "BLKSEQ": "时序逻辑用了阻塞赋值 =：时序 always 块应使用非阻塞赋值 <=",
    "LATCH": "always 块部分分支未赋值、可能推断出锁存器：补全 else / default 分支",
    "CASEINCOMPLETE": "case 未覆盖所有取值且无 default：补 default 分支",
    "SYNCASYNCNET": "同一信号混用同步与异步复位：统一复位风格",
    "TIMESCALEMOD": "使用了时间单位但缺 `timescale：文件头补 `timescale 1ns/1ps",
    "VARHIDDEN": "变量名遮蔽了上层同名声明：重命名避免混淆",
    "syntax": "语法错误：检查是否少分号、begin/end 不配对、括号不匹配"
              "（工具报错行可能在真正出错行的下一行，应向上回溯）",
}
_DEFAULT_SUGGESTION = ("Verilator 规范检查未通过：按规则名 {rule} 在 "
                       "verilator.org/guide 查对应章节；确认是误报可用 "
                       "-Wno-{rule} 屏蔽")


def _read_snippet(snippet_map, file_name, line_no):
    """从已知文件里读出错行源码，读不到返回 None。"""
    if not file_name or not line_no:
        return None
    src = snippet_map.get(file_name)
    if src is None:
        return None
    try:
        lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip()
    except OSError:
        pass
    return None


def _parse_verilator(text: str, snippet_map: dict):
    """把 verilator 输出解析成 lint_errors 列表。"""
    issues = []
    for raw in text.splitlines():
        line = raw.strip()
        m = _MSG_RE.match(line)
        if not m:
            continue  # 源码上下文行（" 12 | ..."）等一律跳过
        sev = _SEV_MAP[m.group("sev")]
        rest = m.group("rest")
        lm = _LOC_RE.match(rest)
        if lm:
            file_b = Path(lm.group("file")).name
            line_no = int(lm.group("line"))
            col = int(lm.group("col")) if lm.group("col") else None
            msg = lm.group("msg").strip()
        else:  # 无文件定位的全局错误（如命令行参数问题）
            file_b, line_no, col, msg = None, None, None, rest.strip()

        rule = m.group("rule")
        if rule is None:
            # 无规则名的 %Error 基本是语法/用法错；报文里带 syntax 就归 syntax
            rule = "syntax" if "syntax" in msg.lower() else "misc"
        issues.append({
            "line": line_no,
            "column": col,
            "rule": rule,
            "severity": sev,
            "file": file_b,
            "message": msg,
            "code_snippet": _read_snippet(snippet_map, file_b, line_no),
            "suggestion": _RULE_SUGGESTIONS.get(rule)
                          or _DEFAULT_SUGGESTION.format(rule=rule),
        })
    return issues


def _issue_from_11(err: dict):
    """把 11 字段标准错误转成 lint_errors 里的一条（降级/工具故障时复用）。"""
    return {
        "line": err.get("line"),
        "column": err.get("column"),
        "rule": err.get("error_type"),
        "severity": err.get("severity"),
        "file": err.get("file"),
        "message": err.get("message"),
        "code_snippet": err.get("code_snippet"),
        "suggestion": err.get("suggestion"),
    }


# ======================================================================
# 结果组装
# ======================================================================
def _result(status, source, linter, issues, started,
            error=None, note=None):
    latency = int((time.perf_counter() - started) * 1000)
    data = {
        "source_file": str(source),
        "linter": linter,
        "lint_errors": issues,
        "metrics": {
            "latency_ms": latency,
            "errors": sum(1 for i in issues if i["severity"] in ("error", "fatal")),
            "warnings": sum(1 for i in issues if i["severity"] == "warn"),
        },
    }
    if note:
        data["note"] = note
    return {
        "status": status,
        "data": data,
        "error": error,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "source_file": str(source),
            "latency_ms": latency,
        },
    }


def _verdict(issues):
    """按问题列表定级：有错 fail / 只有警告 warn / 干净 pass。"""
    if any(i["severity"] in ("error", "fatal") for i in issues):
        return "fail"
    if any(i["severity"] == "warn" for i in issues):
        return "warn"
    return "pass"


# ======================================================================
# 两条检查路径
# ======================================================================
def _lint_verilator(src, extras, top, mode, cmd, env_extra, snippet_map,
                    started, skip_rules=None):
    args = cmd + ["--lint-only", "-Wall"]
    # 屏蔽指定规则（如生成文件名带 _tryN 后缀时屏蔽 DECLFILENAME）
    args += [f"-Wno-{r}" for r in (skip_rules or [])]
    if top:
        args += ["--top-module", top]
    paths = ([_to_wsl_path(p) for p in [src] + extras] if mode == "wsl"
             else [str(p) for p in [src] + extras])
    args += paths
    env = {**os.environ, **(env_extra or {})} if env_extra else None

    try:
        cp = subprocess.run(args, capture_output=True, timeout=LINT_TIMEOUT,
                            cwd=str(Path(__file__).resolve().parent), env=env)
    except subprocess.TimeoutExpired:
        err = _make("timeout", f"lint timeout after {LINT_TIMEOUT}s",
                    f"Lint 超时（超过 {LINT_TIMEOUT} 秒）：检查文件是否异常巨大"
                    "或磁盘/WSL 是否卡死")
        return _result("fail", src, f"verilator({mode})",
                       [_issue_from_11(err)], started, error=err)
    except FileNotFoundError:
        err = _make("tool_missing", "FileNotFoundError: verilator",
                    "找不到工具 verilator：Windows 可用 MSYS2 安装原生版"
                    "（pacman -S mingw-w64-ucrt-x86_64-verilator，并把 "
                    "ucrt64\\bin 加入 PATH），或 WSL: sudo apt install verilator")
        return _result("fail", src, f"verilator({mode})",
                       [_issue_from_11(err)], started, error=err)

    output = _decode(cp.stderr) or _decode(cp.stdout)
    issues = _parse_verilator(output, snippet_map)

    # 退出码非 0 但一条都没解析出来：verilator 本身崩了，兜底成未知错误
    if cp.returncode != 0 and not any(
            i["severity"] in ("error", "fatal") for i in issues):
        err = make_unknown_error(output or "verilator lint failed", "compile")
        issues.append(_issue_from_11(err))
        return _result("fail", src, f"verilator({mode})", issues, started,
                       error=err)
    return _result(_verdict(issues), src, f"verilator({mode})", issues, started)


def _lint_iverilog(src, extras, snippet_map, started):
    """降级路径：iverilog -Wall 只能查语法级问题，语义检查不可用。"""
    with tempfile.TemporaryDirectory() as td:
        sim_exe = str(Path(td) / "sim_lint_check")
        compile_cmd = (["iverilog", "-o", sim_exe, "-Wall"]
                       + [str(p) for p in extras] + [str(src)])
        try:
            cp = subprocess.run(compile_cmd, capture_output=True,
                                timeout=LINT_TIMEOUT)
        except subprocess.TimeoutExpired:
            err = _make("timeout", f"lint timeout after {LINT_TIMEOUT}s",
                        f"Lint（iverilog 降级模式）超时：超过 {LINT_TIMEOUT} 秒未结束")
            return _result("fail", src, "iverilog-fallback",
                           [_issue_from_11(err)], started, error=err)
        except FileNotFoundError:
            err = _make("tool_missing", "FileNotFoundError: iverilog",
                        "找不到工具 iverilog：请确认 Icarus Verilog 已安装"
                        "且所在目录已加入系统 PATH")
            return _result("fail", src, "iverilog-fallback",
                           [_issue_from_11(err)], started, error=err)

        stderr = _decode(cp.stderr)
        note = ("iverilog 降级模式：仅语法级检查，位宽/未驱动等语义问题查不出；"
                "Windows 可用 MSYS2 装原生 verilator（pacman -S "
                "mingw-w64-ucrt-x86_64-verilator，把 ucrt64\\bin 加入 PATH），"
                "装好后本模块自动升级为语义级检查")

        if cp.returncode == 0:
            return _result("pass", src, "iverilog-fallback", [], started,
                           note=note)

        # iverilog 一轮通常只报第一个错，取 classify 的首条即可
        err = classify_error(stderr, stage="compile") \
            or make_unknown_error(stderr, "compile")
        issues = [_issue_from_11(err)]
        return _result("fail", src, "iverilog-fallback", issues, started,
                       error=err, note=note)


# ======================================================================
# 对外主接口
# ======================================================================
def lint(source: str, extra_files=None, top: str = None, skip_rules=None):
    """
    对 Verilog 源文件执行静态检查，返回标准结构化 JSON dict。

    参数:
        source:      主检查文件（.v/.sv）
        extra_files: 一起参与检查的依赖文件列表（如 counter.v 依赖 dff.v）
        top:         顶层模块名（多顶层时指定，传给 verilator --top-module）
        skip_rules:  屏蔽的 verilator 规则名列表（如 ["DECLFILENAME"]，
                     转成 -Wno-<rule>；仅 verilator 模式生效）
    返回:
        dict（见模块开头格式说明；status ∈ pass/warn/fail/unsupported）
    """
    started = time.perf_counter()
    src = Path(source).resolve()
    extras = [Path(f).resolve() for f in (extra_files or [])]

    # ---- 0. 类型口子：本轮只做 Verilog，VHDL 明确拒绝并说明 ----
    ext = src.suffix.lower()
    if ext in VHDL_EXTS:
        return _result("unsupported", src, None, [], started,
                       note=f"VHDL（{ext}）本轮暂不支持，当前仅支持 "
                            ".v/.sv；架构已预留，后续按需求接入 ghdl")
    if ext not in SUPPORTED_EXTS:
        return _result("unsupported", src, None, [], started,
                       note=f"不认识的文件类型 {ext}，仅支持 .v/.sv")

    # ---- 1. 文件存在性 ----
    if not src.exists():
        err = make_file_error(str(src))
        return _result("fail", src, None, [_issue_from_11(err)], started,
                       error=err)
    missing = [f for f in extras if not f.exists()]
    if missing:
        err = make_file_error(str(missing[0]))
        return _result("fail", src, None, [_issue_from_11(err)], started,
                       error=err)

    # code_snippet 用：基名 → 路径
    snippet_map = {p.name: p for p in [src] + extras}

    # ---- 2. 分发到 verilator / iverilog 降级 ----
    mode, cmd, env_extra = _find_verilator()
    if mode != "none":
        return _lint_verilator(src, extras, top, mode, cmd, env_extra,
                               snippet_map, started, skip_rules=skip_rules)
    return _lint_iverilog(src, extras, snippet_map, started)


# ---------------------------- 命令行入口 ----------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Verilog Lint：verilator --lint-only（无则降级 iverilog），"
                    "输出标准结构化 JSON")
    ap.add_argument("source", help="待检查的 .v/.sv 源文件")
    ap.add_argument("extra", nargs="*", help="依赖文件（一起参与检查）")
    ap.add_argument("--top", default=None, help="顶层模块名")
    ap.add_argument("--skip-rule", action="append", default=[],
                    help="屏蔽的 verilator 规则名，如 DECLFILENAME，可多次")
    ap.add_argument("--out", default=None, help="把 JSON 结果同时写入该文件")
    args = ap.parse_args()

    result = lint(args.source, args.extra, top=args.top,
                  skip_rules=args.skip_rule)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\n[已存档] {out_path}", file=sys.stderr)

    # pass/warn → 0，fail → 1，unsupported → 2（方便闭环和 CI 判定）
    sys.exit({"pass": 0, "warn": 0, "fail": 1, "unsupported": 2}[result["status"]])


if __name__ == "__main__":
    main()
