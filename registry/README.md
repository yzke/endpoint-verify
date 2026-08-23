# 指纹库（registry）贡献指南

`registry/<model>.json` 描述一个已知模型的指纹条目，配合 `cache/<model>/` 下的
官方 tokenizer 与编码器脚本使用。

## 添加新模型的步骤

1. **拉取缓存**：

   ```bash
   python3 scripts/fetch_registry.py --model <model> \
       --hf-repo <owner>/<Repo> \
       --tokenizer-file tokenizer.json \
       --encoder-path encoding/encoding_xxx.py
   ```

   注意：tokenizer.json 与编码器参考脚本通常在 HF 仓库根或 `encoding/` 子目录；
   `--encoder-path` 可选（有些模型只有 tokenizer 没有编码器参考，此时 L2 将退化为
   仅 tokenizer 编码验证：用 chat_template 渲染）。

2. **登记指纹条目** `registry/<model>.json`：

   ```json
   {
     "model": "<model>",
     "hf_repo": "<owner>/<Repo>",
     "tokenizer_path": "cache/<model>/tokenizer.json",
     "encoder_path": "cache/<model>/encoding_xxx.py",
     "encode_config": {"thinking_mode": "thinking", "reasoning_effort": null, "add_default_bos_token": true},
     "expected_tokens": [10 个整数，可先留空数组],
     "system_prefix_tokens": 0,
     "verified": {"by": "<你的名字>", "date": "YYYY-MM-DD", "method": "说明验证方法"}
   }
   ```

3. **验证**（需要该模型的真实 API）：

   ```bash
   python3 scripts/probe.py --base-url <base_url> --api-key-env <ENV_VAR> --model <model> --output /tmp/probe.json
   python3 scripts/verify.py --model <model> --api-tokens /tmp/probe.json
   ```

   期望输出 `verdict: authentic`。通过后把 `expected_tokens` 补成实测序列并提交 PR。

## 家族共用词表

同家族模型（如 DeepSeek V3.2 / V4-Flash）共用 tokenizer 时，`tokenizer_path` /
`encoder_path` 可指向家族内已缓存模型的文件，并在 `note` 中说明（见
`deepseek-v3.2.json` 的示例）。判定引擎的候选矩阵扫描会遍历全部条目自动匹配。

## 判定规则速查

- 声称模型 0 差 → `authentic`
- 声称模型恒定差 ≠ 0 且候选矩阵有 0 差 → `same-family-downgrade`（定位到候选）
- 声称模型恒定差 ≠ 0 且无 0 差候选 → `same-family`（系统提示差异或未知同族）
- 声称模型波动 → `cross-family`
