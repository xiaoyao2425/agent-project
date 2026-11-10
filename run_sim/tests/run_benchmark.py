#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_benchmark —— auto_fix 统一评测基准（评测组用）
==================================================
对 tests/benchmark/ 下的 7 条标准语料逐条调用 api/auto_fix.py，
从五个维度打分并产出报告（tests/evidence/benchmark_report.json）：

  1. 修复成功率    status 是否符合预期（success / already_ok / fail）
  2. 修复轮数      data.metrics.rounds（越少越好）
  3. 耗时          data.metrics.latency_ms
  4. 源文件安全    修复前后源文件 SHA256 必须一致（田玉伟版直接改源文件，此项为红线）
  5. JSON 合规性   输出可解析且含 11 字段标准外壳（status/data/error/meta）

语料设计（4 规则命中 + 3 边界）：
  case01 缺分号          → 期望 success + missing_semicolon
  case02 SV→2001         → 期望 success + sv_to_2001
  case03 reg+assign      → 期望 success + reg_to_wire
  case04 wire+always     → 期望 success + wire_to_reg
  case05 语义错误(未声明) → 期望 fail（拒绝乱修，边界清晰性）
  case06 干净文件        → 期望 already_ok（不动一个字节）
  case07 复合错误        → 期望 success（sv_to_2001 与 missing_semicolon 接力）

用法（在 run_sim 目录下执行）：
    python tests/run_benchmark.py
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

RUN_SIM = Path(__file__).resolve().parent.parent
BENCH = RUN_SIM / "tests" / "benchmark"
EVIDENCE = RUN_SIM / "tests" / "evidence"

CASES = [
    {"file": "case01_missing_semicolon.v", "expect_status": "success",
     "expect_fixer": "missing_semicolon", "note": "缺分号"},
    {"file": "case02_sv_to_2001.v", "expect_status": "success",
     "expect_fixer": "sv_to_2001", "note": "SV语法混入"},
    {"file": "case03_reg_to_wire.v", "expect_status": "success",
     "expect_fixer": "reg_to_wire", "note": "reg被assign驱动"},
    {"file": "case04_wire_to_reg.v", "expect_status": "success",
     "expect_fixer": "wire_to_reg", "note": "wire在always被赋值"},
    {"file": "case05_semantic_undeclared.v", "expect_status": "fail",
     "expect_fixer": None, "note": "语义错误应拒修"},
    {"file": "case06_clean.v", "expect_status": "already_ok",
     "expect_fixer": None, "note": "干净文件不动"},
    {"file": "case07_multi_error.v", "expect_status": "success",
     "expect_fixer": None, "note": "复合错误规则接力"},
]

REQUIRED_KEYS = {"status", "data", "error", "meta"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def iverilog_compiles(vfile: Path) -> bool:
    """独立验证：修复产物能否通过 iverilog 编译（不采信 auto_fix 自报的 verify）。"""
    out = RUN_SIM / "output" / ("bench_" + vfile.stem + ".vvp")
    out.parent.mkdir(exist_ok=True)
    cp = subprocess.run(
        ["iverilog", "-o", str(out), str(vfile)],
        capture_output=True, timeout=30)
    return cp.returncode == 0


def run_case(case: dict) -> dict:
    src = BENCH / case["file"]
    row = {"file": case["file"], "note": case["note"],
           "expect_status": case["expect_status"]}
    hash_before = sha256(src)

    t0 = time.perf_counter()
    cp = subprocess.run(
        [sys.executable, str(RUN_SIM / "api" / "auto_fix.py"), str(src)],
        cwd=RUN_SIM, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120)
    row["wall_ms"] = int((time.perf_counter() - t0) * 1000)

    # 维度5：JSON 合规性
    try:
        result = json.loads(cp.stdout)
        row["json_valid"] = REQUIRED_KEYS.issubset(result.keys())
    except json.JSONDecodeError:
        row.update(json_valid=False, status="unparseable", status_match=False,
                   source_safe=(sha256(src) == hash_before), compile_ok=False,
                   rounds=None, latency_ms=None, fixer=None)
        return row

    status = result.get("status")
    data = result.get("data") or {}
    metrics = data.get("metrics") or {}
    row.update(
        status=status,
        fixer=data.get("fixer"),
        rounds=metrics.get("rounds"),
        latency_ms=metrics.get("latency_ms"),
        status_match=(status == case["expect_status"]),
        # 维度4：源文件安全（红线）
        source_safe=(sha256(src) == hash_before),
    )
    if case["expect_fixer"]:
        row["fixer_match"] = (data.get("fixer") == case["expect_fixer"])

    # success 时独立验证修复产物可编译
    if status == "success":
        fixed = data.get("fixed_file")
        fixed_path = (RUN_SIM / fixed) if fixed and not Path(fixed).is_absolute() \
            else Path(fixed) if fixed else None
        row["compile_ok"] = bool(fixed_path and fixed_path.exists()
                                 and iverilog_compiles(fixed_path))
    else:
        row["compile_ok"] = None
    return row


def main():
    rows = [run_case(c) for c in CASES]

    total = len(rows)
    passed = sum(1 for r in rows if r["status_match"])
    json_ok = sum(1 for r in rows if r.get("json_valid"))
    safe = sum(1 for r in rows if r.get("source_safe"))
    fixable = [r for r in rows if r["expect_status"] == "success"]
    fix_ok = [r for r in fixable if r["status"] == "success" and r["compile_ok"]]
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]

    report = {
        "tool": "run_sim/api/auto_fix.py v1.1（4 规则合并版）",
        "benchmark": "tests/benchmark 7 条语料（4 规则命中 + 3 边界）",
        "summary": {
            "cases": total,
            "status_match": f"{passed}/{total}",
            "fix_success_rate": f"{len(fix_ok)}/{len(fixable)}",
            "json_valid": f"{json_ok}/{total}",
            "source_safe": f"{safe}/{total}（红线：源文件零改动）",
            "avg_latency_ms": int(sum(lat) / len(lat)) if lat else None,
            "avg_rounds": round(sum(r["rounds"] for r in fix_ok) / len(fix_ok), 2)
            if fix_ok else None,
        },
        "rows": rows,
    }
    EVIDENCE.mkdir(exist_ok=True)
    out = EVIDENCE / "benchmark_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    # 控制台打印简表
    print(f"\n{'文件':<32} {'期望':<10} {'实际':<10} {'规则':<18} "
          f"{'轮数':<4} {'源安全':<6} {'编译':<6}")
    for r in rows:
        print(f"{r['file']:<32} {r['expect_status']:<10} {r['status']:<10} "
              f"{str(r.get('fixer')):<18} {str(r.get('rounds')):<4} "
              f"{'OK' if r.get('source_safe') else 'DIRTY!':<6} "
              f"{('OK' if r.get('compile_ok') else '-') if r.get('compile_ok') is not None else '-':<6}")
    print("\n汇总:", json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\n完整报告: {out}")

    ok = (passed == total and json_ok == total and safe == total
          and len(fix_ok) == len(fixable))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
