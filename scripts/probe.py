#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
endpoint-verify — L1 tokenizer 指纹探测

对任意 OpenAI 兼容端点发送 10 组提示词，采集 usage.prompt_tokens 指纹序列。
判定依据：恒定偏移（Δ 全等 = 同一 tokenizer + 固定系统提示开销）。

用法:
    python3 scripts/probe.py --base-url https://api.deepseek.com/chat/completions \\
        --api-key-env DEEPSEEK_API_KEY --model deepseek-v4-flash

安全: API key 只从环境变量读取（--api-key-env 指定变量名），绝不落盘/硬编码。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

from prompts import DEFAULT_PROMPTS


def probe_once(base_url, api_key, model, prompt, timeout=60, retries=3):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(base_url, data=body, headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            usage = data.get("usage", {})
            return usage.get("prompt_tokens")
        except Exception as exc:  # noqa: BLE001 —— 网络/超时/限流统一重试
            if attempt == retries - 1:
                print(f"[WARN] 请求失败（重试耗尽）: {exc}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    return None


def main():
    parser = argparse.ArgumentParser(description="L1 tokenizer 指纹探测")
    parser.add_argument("--base-url", required=True, help="OpenAI 兼容端点 URL")
    parser.add_argument("--api-key-env", required=True, help="API key 的环境变量名（不传明文）")
    parser.add_argument("--model", required=True, help="声称的模型名")
    parser.add_argument("--prompts-file", default=None, help="可选：自定义提示词 JSON 文件（字符串数组）")
    parser.add_argument("--output", default=None, help="可选：结果 JSON 输出路径（缺省打印 stdout）")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print(f"[FATAL] 环境变量 {args.api_key_env} 未设置", file=sys.stderr)
        sys.exit(2)

    prompts = DEFAULT_PROMPTS
    if args.prompts_file:
        with open(args.prompts_file, encoding="utf-8") as f:
            prompts = json.load(f)
        if not isinstance(prompts, list) or not prompts:
            print("[FATAL] prompts 文件必须是字符串数组", file=sys.stderr)
            sys.exit(2)

    tokens = []
    for i, p in enumerate(prompts):
        t = probe_once(args.base_url, api_key, args.model, p)
        tokens.append(t)
        print(f"[{args.model}] {i+1}/{len(prompts)} prompt_tokens={t}", flush=True)
        time.sleep(0.3)

    result = {
        "model": args.model,
        "base_url": args.base_url,
        "tokens": tokens,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[done] 结果已写入 {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
