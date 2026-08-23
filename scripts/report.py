#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
endpoint-verify — 判定报告生成（markdown，人/agent 可读）

用法:
    python3 scripts/report.py --verdict verdict.json [--probe probe_result.json] [--output report.md]

输入: verify.py 的判定 JSON（可选附带 probe.py 的原始指纹）。
"""
import argparse
import json
import os
import sys

VERDICT_LABEL = {
    "authentic": ("✅ 真身", "端点就是声称的模型本身"),
    "same-family": ("⚠️ 同族", "tokenizer 一致但存在固定开销差，未定位到具体候选"),
    "same-family-downgrade": ("🚨 同族降级", "端点实际运行的是同家族的另一个模型（候选矩阵定位）"),
    "cross-family": ("❌ 跨家族冒充", "tokenizer 指纹不匹配，端点不是声称模型的家族成员"),
    "inconclusive": ("❓ 无法判定", "数据不完整或缓存缺失"),
}


def build_report(verdict, probe=None):
    label, explain = VERDICT_LABEL.get(verdict.get("verdict", "inconclusive"),
                                       ("❓ 无法判定", ""))
    lines = []
    lines.append("# endpoint-verify 真身判定报告\n")
    lines.append(f"- 声称模型: `{verdict.get('claimed_model')}`")
    lines.append(f"- **判定: {label}**（{explain}）")
    lines.append(f"- 置信度: {verdict.get('confidence')}")
    if verdict.get("located_model"):
        lines.append(f"- 定位模型: `{verdict['located_model']}`")
    if probe:
        lines.append(f"- 端点: `{probe.get('base_url')}`（探测时间 {probe.get('collected_at')}）")

    lines.append("\n## 证据\n")
    ev = verdict.get("evidence", {})
    if "error" in ev:
        lines.append(f"> 错误: {ev['error']}\n")
    if "claimed_default" in ev:
        self_ = ev["claimed_default"]
        ds = self_.get("diffs") or {}
        lines.append("### 声称模型自身（默认配置）")
        lines.append(f"- 编码配置: `{self_.get('config')}`")
        lines.append(f"- 差异: Δ∈[{ds.get('min')},{ds.get('max')}] std={ds.get('std', 0):.2f} "
                     f"{'（恒定偏移）' if ds.get('constant') else '（波动）'}")
    if "note" in ev:
        lines.append(f"- 备注: {ev['note']}")

    cands = verdict.get("candidates", {})
    if cands:
        lines.append("\n### 候选矩阵扫描\n")
        lines.append("| 候选模型 | 最优配置 | Δ范围 | 恒定? |")
        lines.append("|---|---|---|---|")
        for name, c in cands.items():
            if "error" in c:
                lines.append(f"| {name} | 错误: {c['error']} | - | - |")
                continue
            ds = c.get("diffs") or {}
            lines.append(f"| {name} | `{c.get('config')}` | "
                         f"[{ds.get('min')},{ds.get('max')}] | "
                         f"{'✅' if ds.get('constant') else '❌'} |")

    lines.append("\n## 建议\n")
    v = verdict.get("verdict")
    if v == "authentic":
        lines.append("- 端点与声称模型一致，可正常使用。")
    elif v == "same-family-downgrade":
        lines.append("- 端点被降级到同家族模型，价格与声称不符时建议投诉/换平台。")
        lines.append("- 用能力蜜罐（v2）进一步确认能力差异。")
    elif v == "cross-family":
        lines.append("- 端点与声称模型家族不符，强烈建议停止使用并核对账单。")
    elif v == "inconclusive":
        lines.append("- 检查缓存与指纹库完整性后重试。")
    else:
        lines.append("- 恒定偏移可能来自系统提示差异；候选矩阵未命中时建议补充指纹库。")

    lines.append("\n---\n*endpoint-verify 生成。判定为证据报告，非法律结论。*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成 markdown 判定报告")
    parser.add_argument("--verdict", required=True, help="verify.py 输出的判定 JSON")
    parser.add_argument("--probe", default=None, help="可选：probe.py 输出的指纹 JSON")
    parser.add_argument("--output", default=None, help="输出路径（缺省 stdout）")
    args = parser.parse_args()

    with open(args.verdict, encoding="utf-8") as f:
        verdict = json.load(f)
    probe = None
    if args.probe:
        with open(args.probe, encoding="utf-8") as f:
            probe = json.load(f)

    md = build_report(verdict, probe)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[done] 报告已写入 {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
