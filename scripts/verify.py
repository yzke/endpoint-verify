#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
endpoint-verify — L2 官方编码器重建 + 三态真身判定

用法:
    python3 scripts/verify.py --model deepseek-v4-flash \\
        --api-tokens probe_result.json [--registry-dir registry] [--cache-dir cache]

判定规则:
    0 差        -> authentic（真身）
    恒定差 != 0 -> same-family（同 tokenizer + 固定开销，候选矩阵扫描定位）
    波动        -> cross-family（跨家族冒充）
    无任何匹配  -> inconclusive（疑似 usage 伪造/未知模型）
"""
import argparse
import importlib.util
import itertools
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 本地依赖（tokenizers 等）若装在 pylibs/ 则自动加入
PYLIBS = os.path.join(ROOT, "pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

from prompts import DEFAULT_PROMPTS  # noqa: E402

ENCODE_MATRIX = list(itertools.product(
    ["thinking", "chat"],   # thinking_mode
    [None, "max"],          # reasoning_effort
    [True, False],          # add_default_bos_token
))


def load_encoder(encoder_path):
    """动态加载官方编码器脚本（如 encoding_dsv4.py），返回模块。"""
    spec = importlib.util.spec_from_file_location("dsv4_enc", encoder_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rebuild_chat_template(tokenizer, chat_template, prompts, add_generation_prompt=True):
    """用 HF chat_template（Jinja）渲染消息并编码，返回 token 数序列。

    适用于没有官方编码器参考脚本的模型（Qwen/GLM/Llama/Mistral 等）。
    add_generation_prompt 可配置（部分服务端渲染时不加 assistant 提示符）。
    """
    import jinja2
    env = jinja2.Environment(
        undefined=jinja2.ChainableUndefined,
        extensions=[],
    )
    template = env.from_string(chat_template)
    tokens = []
    for p in prompts:
        rendered = template.render(
            messages=[{"role": "user", "content": p}],
            add_generation_prompt=add_generation_prompt,
        )
        tokens.append(len(tokenizer.encode(rendered).ids))
    return tokens


def rebuild_with_entry(tokenizer, encoder, prompts, entry, cfg):
    """按条目编码器类型重建：dsv4=官方脚本；chat_template=Jinja 模板。"""
    enc_type = entry.get("encoder_type", "chat_template")
    if enc_type == "dsv4":
        return rebuild_tokens(tokenizer, encoder, prompts, cfg)
    agp = entry.get("encode_config", {}).get("add_generation_prompt", True)
    return rebuild_chat_template(tokenizer, entry.get("chat_template", ""), prompts, agp)


def rebuild_tokens(tokenizer, encoder, prompts, cfg):
    """按配置重建一组提示词的本地期望 token 数。"""
    tokens = []
    for p in prompts:
        messages = [{"role": "user", "content": p}]
        rendered = encoder.encode_messages(
            messages,
            thinking_mode=cfg[0],
            reasoning_effort=cfg[1],
            add_default_bos_token=cfg[2],
        )
        tokens.append(len(tokenizer.encode(rendered).ids))
    return tokens


def diff_stats(api_tokens, local_tokens):
    pairs = [(a, b) for a, b in zip(api_tokens, local_tokens) if a is not None]
    diffs = [a - b for a, b in pairs]
    if not diffs:
        return None
    return {
        "diffs": diffs,
        "min": min(diffs),
        "max": max(diffs),
        "std": statistics.stdev(diffs) if len(diffs) > 1 else 0.0,
        "constant": len(set(diffs)) == 1,
    }


def best_match(tokenizer, encoder, prompts, api_tokens):
    """配置矩阵穷举，返回 (cfg, diff_stats, local_tokens) 最优者。"""
    best = None
    for cfg in ENCODE_MATRIX:
        local = rebuild_tokens(tokenizer, encoder, prompts, cfg)
        ds = diff_stats(api_tokens, local)
        if ds is None:
            continue
        # 排序键：恒定偏移优先，其次 std 小
        key = (0 if ds["constant"] else 1, ds["std"])
        if best is None or key < best[0]:
            best = (key, cfg, ds, local)
    return best[1], best[2], best[3] if best else (None, None, None)


def load_registry(registry_dir):
    entries = {}
    for fn in sorted(os.listdir(registry_dir)):
        if fn.endswith(".json"):
            with open(os.path.join(registry_dir, fn), encoding="utf-8") as f:
                entries[fn[:-5]] = json.load(f)
    return entries


def classify(claimed, api_tokens, registry, prompts=DEFAULT_PROMPTS):
    """执行完整判定，返回 verdict 字典。

    判定规则（默认配置优先，矩阵搜索仅用于配置发现/解释）:
      声称条目默认配置 0 差          -> authentic（高置信）
      默认配置恒定差 != 0            -> 候选扫描：有 0 差候选 => same-family-downgrade
                                      （定位真实模型）；无 => same-family
      默认配置波动                   -> 矩阵搜索声称条目：能找到 0 差配置
                                      => authentic（低置信，条目配置漂移）；
                                      否则 cross-family
    """
    verdict = {
        "claimed_model": claimed,
        "verdict": "inconclusive",
        "confidence": "low",
        "located_model": None,
        "evidence": {},
        "candidates": {},
    }
    if any(t is None for t in api_tokens):
        verdict["evidence"]["error"] = "API 指纹数据不完整"
        return verdict

    entry = registry.get(claimed)
    if entry is None:
        verdict["evidence"]["error"] = f"registry 中无 {claimed} 条目（用 fetch_registry.py 添加）"
        return verdict

    enc_path = os.path.join(ROOT, entry.get("encoder_path", ""))
    tok_path = os.path.join(ROOT, entry.get("tokenizer_path", ""))
    if not (os.path.exists(enc_path) and os.path.exists(tok_path)):
        verdict["evidence"]["error"] = f"缓存缺失: {enc_path} / {tok_path}（用 fetch_registry.py 拉取）"
        return verdict

    from tokenizers import Tokenizer
    tok_path = os.path.join(ROOT, entry.get("tokenizer_path", ""))
    if not os.path.exists(tok_path):
        verdict["evidence"]["error"] = f"缓存缺失: {tok_path}（用 fetch_registry.py 拉取）"
        return verdict
    tokenizer = Tokenizer.from_file(tok_path)

    # 编码器：dsv4=官方脚本；chat_template=从 tokenizer_config.json 读 Jinja 模板
    enc_type = entry.get("encoder_type", "chat_template")
    encoder = None
    if enc_type == "dsv4":
        enc_path = os.path.join(ROOT, entry.get("encoder_path", ""))
        if not os.path.exists(enc_path):
            verdict["evidence"]["error"] = f"编码器脚本缺失: {enc_path}"
            return verdict
        encoder = load_encoder(enc_path)
    else:
        # chat_template：优先 tokenizer_config.json 的 chat_template 字段，
        # 缺失时回退独立模板文件（如 chat_template.jinja）
        entry["chat_template"] = ""
        tc_path = os.path.join(ROOT, entry.get("tokenizer_config_path", ""))
        if os.path.exists(tc_path):
            with open(tc_path, encoding="utf-8") as f:
                entry["chat_template"] = json.load(f).get("chat_template", "") or ""
        if not entry["chat_template"]:
            tf_path = os.path.join(ROOT, entry.get("chat_template_file", ""))
            if os.path.exists(tf_path):
                with open(tf_path, encoding="utf-8") as f:
                    entry["chat_template"] = f.read()
        if not entry["chat_template"]:
            verdict["evidence"]["error"] = "缺少 chat_template（tokenizer_config.json 与 chat_template.jinja 均无）"
            return verdict

    def entry_config(e):
        ec = e.get("encode_config", {})
        return (ec.get("thinking_mode", "thinking"),
                ec.get("reasoning_effort"),
                ec.get("add_default_bos_token", True))

    # 1) 声称模型：默认配置比对
    cfg0 = entry_config(entry)
    local0 = rebuild_with_entry(tokenizer, encoder, prompts, entry, cfg0)
    ds0 = diff_stats(api_tokens, local0)
    verdict["evidence"]["claimed_default"] = {
        "config": cfg0, "encoder_type": enc_type, "diffs": ds0,
    }

    # 2) 候选矩阵扫描：registry 全部条目（各自默认编码）
    for name, e in registry.items():
        if name == claimed:
            continue
        e_tok = os.path.join(ROOT, e.get("tokenizer_path", ""))
        if not os.path.exists(e_tok):
            continue
        try:
            e_tok_obj = Tokenizer.from_file(e_tok)
            e_enc_mod = None
            if e.get("encoder_type", "chat_template") == "dsv4":
                e_enc_path = os.path.join(ROOT, e.get("encoder_path", ""))
                if not os.path.exists(e_enc_path):
                    continue
                e_enc_mod = load_encoder(e_enc_path)
            else:
                e_tc = os.path.join(ROOT, e.get("tokenizer_config_path", ""))
                if os.path.exists(e_tc):
                    with open(e_tc, encoding="utf-8") as f:
                        e["chat_template"] = json.load(f).get("chat_template", "")
                else:
                    e["chat_template"] = ""
            c_cfg = entry_config(e)
            c_local = rebuild_with_entry(e_tok_obj, e_enc_mod, prompts, e, c_cfg)
            c_ds = diff_stats(api_tokens, c_local)
            verdict["candidates"][name] = {"config": c_cfg, "diffs": c_ds}
        except Exception as exc:  # noqa: BLE001
            verdict["candidates"][name] = {"error": str(exc)[:120]}

    # 3) 三态判定
    if ds0 and ds0["constant"] and ds0["max"] == 0:
        verdict["verdict"] = "authentic"
        verdict["confidence"] = "high"
    elif ds0 and ds0["constant"]:
        # 同 tokenizer + 固定开销：候选扫描找 0 差定位
        for name, c in verdict["candidates"].items():
            if c.get("diffs") and c["diffs"]["constant"] and c["diffs"]["max"] == 0:
                verdict["verdict"] = "same-family-downgrade"
                verdict["located_model"] = name
                verdict["confidence"] = "high"
                break
        else:
            verdict["verdict"] = "same-family"
            verdict["located_model"] = claimed
            verdict["confidence"] = "medium"
            verdict["evidence"]["note"] = "恒定偏移但候选矩阵无 0 差匹配：可能为系统提示差异或未知同族模型"
    elif ds0 is not None:
        # 波动：dsv4 类型可矩阵搜索声称条目，看是否存在 0 差配置（服务端配置与条目默认不符）
        ds_best = None
        if enc_type == "dsv4":
            _, ds_best, _ = best_match(tokenizer, encoder, prompts, api_tokens)
        if ds_best and ds_best["constant"] and ds_best["max"] == 0:
            verdict["verdict"] = "authentic"
            verdict["confidence"] = "low"
            verdict["evidence"]["note"] = "默认配置波动但矩阵搜索 0 差：服务端编码配置与条目 encode_config 不符，建议更新指纹库"
        else:
            verdict["verdict"] = "cross-family"
            verdict["confidence"] = "high"
            for name, c in verdict["candidates"].items():
                if c.get("diffs") and c["diffs"]["constant"] and c["diffs"]["max"] == 0:
                    verdict["located_model"] = name
                    break
    else:
        verdict["evidence"]["error"] = "无法计算差异"
    return verdict


def main():
    parser = argparse.ArgumentParser(description="L2 官方编码器重建 + 三态真身判定")
    parser.add_argument("--model", required=True, help="声称的模型名（registry 条目）")
    parser.add_argument("--api-tokens", required=True, help="probe.py 的输出 JSON 文件")
    parser.add_argument("--registry-dir", default=os.path.join(ROOT, "registry"))
    parser.add_argument("--cache-dir", default=os.path.join(ROOT, "cache"))
    parser.add_argument("--output", default=None, help="判定 JSON 输出路径（缺省 stdout）")
    args = parser.parse_args()

    with open(args.api_tokens, encoding="utf-8") as f:
        probe_result = json.load(f)
    api_tokens = probe_result.get("tokens")

    registry = load_registry(args.registry_dir)
    verdict = classify(args.model, api_tokens, registry)

    text = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[done] 判定已写入 {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
