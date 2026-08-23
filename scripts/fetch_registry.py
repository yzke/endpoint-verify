#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
endpoint-verify — 指纹缓存拉取（HuggingFace → cache/<model>/）

用法:
    python3 scripts/fetch_registry.py --model deepseek-v4-flash \\
        --hf-repo deepseek-ai/DeepSeek-V4-Flash \\
        --tokenizer-file tokenizer.json \\
        --encoder-path encoding/encoding_dsv4.py

说明: 只下载小文件（tokenizer + 编码器参考实现），不下载模型权重。
      HTTPS_PROXY 环境变量已配时自动走代理（HF 在国内需代理）。
      已存在的文件跳过（断点续传），下载后校验非空。
"""
import argparse
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "cache")


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"[skip] {dest} 已存在")
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"[get ] {url}")
    headers = {"User-Agent": "endpoint-verify"}
    hf_token = os.environ.get("HF_TOKEN", "")
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        if os.path.getsize(dest) == 0:
            print(f"[FAIL] {dest} 为空文件", file=sys.stderr)
            return False
        print(f"[done] {dest} ({os.path.getsize(dest)} bytes)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 下载失败: {exc}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="从 HuggingFace 拉取 tokenizer/编码器到缓存")
    parser.add_argument("--model", required=True, help="缓存目录名（registry 条目名）")
    parser.add_argument("--hf-repo", required=True, help="HF 仓库，如 deepseek-ai/DeepSeek-V4-Flash")
    parser.add_argument("--tokenizer-file", default="tokenizer.json", help="仓库内 tokenizer 文件路径")
    parser.add_argument("--tokenizer-config", default="tokenizer_config.json",
                        help="仓库内 tokenizer_config.json 路径（chat_template 来源，chat_template 类型条目需要）")
    parser.add_argument("--encoder-path", default=None, help="仓库内编码器参考实现路径（可选，dsv4 类型条目需要）")
    args = parser.parse_args()

    base = f"https://huggingface.co/{args.hf_repo}/resolve/main"
    out_dir = os.path.join(CACHE, args.model)
    ok = fetch(f"{base}/{args.tokenizer_file}", os.path.join(out_dir, "tokenizer.json"))
    if args.tokenizer_config:
        ok &= fetch(f"{base}/{args.tokenizer_config}", os.path.join(out_dir, "tokenizer_config.json"))
    if args.encoder_path:
        ok &= fetch(f"{base}/{args.encoder_path}",
                    os.path.join(out_dir, os.path.basename(args.encoder_path)))

    if ok:
        print("\n下一步：在 registry/<model>.json 中登记指纹条目（见 registry/README.md）")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
