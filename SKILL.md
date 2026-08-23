---
name: endpoint-verify
description: 对任意 OpenAI 兼容 API 端点（中转站/匿名模型/官方 API）做真身审计。用户怀疑中转掺假、模型降级、匿名模型身份、API 账单与模型不符时使用。通过 L1 tokenizer 指纹（usage.prompt_tokens 恒定偏移判定）+ L2 官方编码器本地重建（0 差定位）给出确定性判定，输出 report.json + report.md。
---

# endpoint-verify — API 端点真身审计

## 何时使用

- 用户怀疑 API 中转站"偷梁换柱"（付了贵的模型钱，实际跑便宜模型）
- 遇到匿名模型/新上线的未知模型，想确认它到底是谁家的
- API 账单与声称模型不符、usage 数字可疑
- 多级转包链路上想验证最终真身

## 前置条件

- 本技能目录下有 `pylibs/`（tokenizers 库）与 `cache/<model>/`（官方 tokenizer + 编码器缓存）。
  若缺失，先执行安装步骤（见 README.md），或运行：
  ```bash
  python3 scripts/fetch_registry.py --model <model> --hf-repo <owner>/<Repo> \
      --tokenizer-file tokenizer.json [--encoder-path encoding/encoding_xxx.py]
  ```
- API key 一律通过环境变量提供（如 `--api-key-env DEEPSEEK_API_KEY`），**绝不在命令行或文件中传明文 key**。

## 执行流程

### 1. L1 指纹采集

```bash
python3 scripts/probe.py --base-url <端点URL> --api-key-env <KEY环境变量名> \
    --model <API模型名> --output /tmp/probe.json
```

- 发送 10 组判别力提示词（CJK/代码/数字/URL/emoji/校准），采集 `usage.prompt_tokens`
- 每组请求 `max_tokens=1, temperature=0, stream=false`

### 2. L2 判定

```bash
python3 scripts/verify.py --model <registry条目名> --api-tokens /tmp/probe.json \
    --output /tmp/verdict.json
```

- 按声称模型的指纹条目，用官方 tokenizer + 编码器本地重建期望 token 数
- 判定规则：
  - 默认配置 **0 差** → `authentic`（真身，高置信）
  - 默认配置**恒定差 ≠ 0** → 候选矩阵扫描：有 0 差候选 → `same-family-downgrade`（同族降级，定位真实模型）；无 → `same-family`
  - 默认配置**波动** → 矩阵搜索仍无 0 差 → `cross-family`（跨家族冒充）
  - 缓存/数据缺失 → `inconclusive`

### 3. 报告

```bash
python3 scripts/report.py --verdict /tmp/verdict.json --probe /tmp/probe.json --output report.md
```

- report.md 给用户看（结论 + 证据表 + 建议）
- report.json 给流程用

## 判定解读速查

| verdict | 含义 | 置信度 |
|---|---|---|
| `authentic` | 端点就是声称的模型 | high |
| `same-family` | tokenizer 一致，有固定开销差（系统提示或未知同族） | medium |
| `same-family-downgrade` | 同族降级，候选矩阵已定位真实模型 | high |
| `cross-family` | 跨家族冒充 | high |
| `inconclusive` | 数据/缓存不完整 | low |

## 安全红线

- **绝不把用户的 API key 写进任何文件、命令历史、日志或报告**
- 指纹库条目（registry/*.json）只含公开元数据，不含任何密钥
- 检测只发 10 组短提示词（max_tokens=1），费用可忽略

## 已知局限（报告时如实说明）

- 指纹只到"家族级 + 编码配置级"：同族共用词表时（如 DeepSeek V3.2/V4），依赖系统提示开销差（如 79）区分；部分模型可能无法区分 → 标注置信度
- 若中转恶意改写 usage 字段且按官方编码精确伪造，L1/L2 均失效 → 建议核对账单（usage × 单价 vs 实际扣费）
- 判定是证据报告，非法律结论
