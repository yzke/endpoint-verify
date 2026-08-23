#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
endpoint-verify 回归测试

离线测试（无需 API key）:
  1. 缓存完整性: v4 默认配置本地重建 == golden expected_tokens
  2. 家族复用:   v3.2 默认配置（effort=null）本地重建 == golden
  3. 判定场景:   authentic / same-family-downgrade / cross-family 三态
  4. key 泄漏扫描: 项目源码与文档中无 sk- 密钥模式

在线集成测试（可选，需 key + 网络）:
  python3 tests/run_tests.py --online
  需要环境变量: DEEPSEEK_API_KEY（官方 v4-flash）、SILICONFLOW_API_KEY（硅基）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "pylibs"))

import verify as verify_mod  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def load_golden():
    with open(os.path.join(HERE, "golden.json"), encoding="utf-8") as f:
        return json.load(f)


def build_registry():
    """测试用 registry：加载全部真实条目（与 verify 一致）。"""
    return verify_mod.load_registry(os.path.join(ROOT, "registry"))


def test_cache_integrity():
    print("\n[测试 1] 缓存完整性：本地重建 == golden")
    golden = load_golden()
    registry = build_registry()
    for name in ["deepseek-v4-flash", "deepseek-v3.2"]:
        entry = registry[name]
        tok_path = os.path.join(ROOT, entry["tokenizer_path"])
        enc_path = os.path.join(ROOT, entry["encoder_path"])
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(tok_path)
        enc = verify_mod.load_encoder(enc_path)
        cfg = (entry["encode_config"]["thinking_mode"],
               entry["encode_config"]["reasoning_effort"],
               entry["encode_config"]["add_default_bos_token"])
        local = verify_mod.rebuild_tokens(tok, enc, verify_mod.DEFAULT_PROMPTS, cfg)
        expected = registry[name]["expected_tokens"]
        check(f"{name} 重建 == 黄金序列", local == expected, f"{local} != {expected}")


def test_verdicts():
    print("\n[测试 2] 判定三态场景")
    golden = load_golden()
    registry = build_registry()

    # 场景 A: 声称 v4，API 序列 = v4 黄金 -> authentic
    v = verify_mod.classify("deepseek-v4-flash", golden["models"]["deepseek-v4-flash"]["tokens"],
                            registry)
    check("A: v4 声称 v4 -> authentic", v["verdict"] == "authentic" and v["confidence"] == "high",
          str(v.get("verdict")))

    # 场景 B: 声称 v4，API 序列 = v3.2（同族降级）-> same-family-downgrade 定位 v3.2
    v = verify_mod.classify("deepseek-v4-flash", golden["models"]["deepseek-v3.2-sf"]["tokens"],
                            registry)
    check("B: v3.2 冒充 v4 -> 降级定位 v3.2",
          v["verdict"] == "same-family-downgrade" and v["located_model"] == "deepseek-v3.2",
          str(v))

    # 场景 C: 声称 v3.2，API 序列 = v3.2 -> authentic
    v = verify_mod.classify("deepseek-v3.2", golden["models"]["deepseek-v3.2-sf"]["tokens"],
                            registry)
    check("C: v3.2 声称 v3.2 -> authentic", v["verdict"] == "authentic",
          str(v.get("verdict")))

    # 场景 D: 声称 v4，API 序列 = qwen（跨家族）-> cross-family
    v = verify_mod.classify("deepseek-v4-flash", golden["models"]["qwen3.6-27b-sf"]["tokens"],
                            registry)
    check("D: qwen 冒充 v4 -> cross-family", v["verdict"] == "cross-family",
          str(v.get("verdict")))

    # 场景 E: 声称 v3.2，API 序列 = v4（反向：升级伪装）-> 降级定位 v4
    v = verify_mod.classify("deepseek-v3.2", golden["models"]["deepseek-v4-flash"]["tokens"],
                            registry)
    check("E: v4 序列声称 v3.2 -> 定位 v4", v["verdict"] == "same-family-downgrade"
          and v["located_model"] == "deepseek-v4-flash", str(v))

    # 场景 F: 声称 qwen3.6-27b，API 序列 = qwen（chat_template 重建）-> authentic
    v = verify_mod.classify("qwen3.6-27b", golden["models"]["qwen3.6-27b-sf"]["tokens"],
                            registry)
    check("F: qwen 声称 qwen（chat_template）-> authentic", v["verdict"] == "authentic",
          str(v.get("verdict")))

    # 场景 G: 声称 glm4.5-air，API 序列 = glm（chat_template 重建）-> authentic
    v = verify_mod.classify("glm4.5-air", golden["models"]["glm4.5-air-sf"]["tokens"],
                            registry)
    check("G: glm 声称 glm（chat_template）-> authentic", v["verdict"] == "authentic",
          str(v.get("verdict")))

    # 场景 H: 声称 glm4.5-air，API 序列 = qwen（异家族）-> cross-family
    v = verify_mod.classify("glm4.5-air", golden["models"]["qwen3.6-27b-sf"]["tokens"],
                            registry)
    check("H: qwen 序列声称 glm -> cross-family", v["verdict"] == "cross-family",
          str(v.get("verdict")))


def test_key_leak():
    print("\n[测试 3] key 泄漏扫描")
    leaks = []
    pattern = re.compile(r"sk-[A-Za-z0-9]{20,}")
    for root, _, files in os.walk(ROOT):
        if ".git" in root or "cache" in root or "pylibs" in root:
            continue
        for fn in files:
            if not fn.endswith((".py", ".json", ".md", ".sh", ".yml", ".yaml", ".toml")):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            leaks.append(f"{p}:{i}")
            except OSError:
                pass
    check("源码/文档无 sk- 密钥模式", not leaks, "; ".join(leaks[:5]))


def test_online():
    print("\n[在线集成] 真实端点全流程（需 key）")
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    sf_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not (ds_key and sf_key):
        print("  ⚠️ 缺少 DEEPSEEK_API_KEY / SILICONFLOW_API_KEY，跳过在线测试")
        return

    # (label, base_url, env_var, api_model(发给API), claimed(registry条目), expect_verdict)
    cases = [
        ("官方 v4-flash", "https://api.deepseek.com/chat/completions", "DEEPSEEK_API_KEY",
         "deepseek-v4-flash", "deepseek-v4-flash", "authentic"),
        ("硅基 v3.2", "https://api.siliconflow.cn/v1/chat/completions", "SILICONFLOW_API_KEY",
         "deepseek-ai/DeepSeek-V3.2", "deepseek-v3.2", "authentic"),
        ("硅基 qwen3.6-27b", "https://api.siliconflow.cn/v1/chat/completions", "SILICONFLOW_API_KEY",
         "Qwen/Qwen3.6-27B", "qwen3.6-27b", "authentic"),
        # GLM-4.5-Air 为 reasoning 模型，硅基端完整推理致 urllib 请求过慢，
        # 在线验证由离线 golden 0 差场景覆盖（tests 场景已验证 authentic）。
        ("硅基 qwen 声称 v4", "https://api.siliconflow.cn/v1/chat/completions", "SILICONFLOW_API_KEY",
         "Qwen/Qwen3.6-27B", "deepseek-v4-flash", "cross-family"),
        # GLM-4.5-Air 在线请求不稳定（reasoning 模型，urllib 偶发超时），
        # 该交叉场景由离线用例 H 覆盖。
    ]
    registry = build_registry()
    for label, base, env, api_model, claimed, expect in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            probe_path = tf.name
        try:
            r = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "probe.py"),
                 "--base-url", base, "--api-key-env", env, "--model", api_model,
                 "--output", probe_path],
                capture_output=True, text=True, timeout=450)
            if r.returncode != 0:
                check(f"[在线] {label}: probe 失败", False, r.stderr[-200:])
                continue
            with open(probe_path, encoding="utf-8") as f:
                probe = json.load(f)
            if any(t is None for t in probe["tokens"]):
                check(f"[在线] {label}: 指纹采集不完整", False, str(probe["tokens"]))
                continue
            v = verify_mod.classify(claimed, probe["tokens"], registry)
            ok = v["verdict"] == expect
            detail = f"verdict={v['verdict']} located={v.get('located_model')} conf={v['confidence']}"
            check(f"[在线] {label}（API={api_model} 声称={claimed}）-> 期望 {expect}", ok, detail)
        finally:
            os.unlink(probe_path)


def main():
    parser = argparse.ArgumentParser(description="endpoint-verify 回归测试")
    parser.add_argument("--online", action="store_true", help="运行在线集成测试（需 key）")
    args = parser.parse_args()

    test_cache_integrity()
    test_verdicts()
    test_key_leak()
    if args.online:
        test_online()

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
