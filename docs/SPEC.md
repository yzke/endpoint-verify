# endpoint-verify — API 端点真身审计技能 Spec

日期: 2026-08-23
状态: v1 草案（待用户 review）
作者: dengdeng（本会话实测验证）

## 1. 背景与问题

- 中转站/匿名模型生态中，主流骗局是"改 model 字段套利"：收高价模型的钱、转发时换成低价同族模型。usage 字段通常是真实模型算出的真值（因为 usage 是中转的计费依据）。
- 本会话已实测验证两条确定性检测路径：
  - **L1 tokenizer 指纹**：10 组提示词 → `usage.prompt_tokens` 差分 → 恒定偏移判定。实测：硅基 v4-flash 与官方 Δ=0 完全一致；v3.2 与 v4 Δ=79 恒定；Qwen/GLM 波动不匹配。
  - **L2 官方编码器重建**：下载官方 `tokenizer.json` + 编码器，本地重建期望 token 数，配置矩阵搜索 0 差。实测：`thinking + effort=max + BOS` 与 API 十组 0 差；79 = 官方 `REASONING_EFFORT_MAX` 常量精确归因。
- 现有工具（modelprint、claude-detector 等）均为行为探针 + 概率打分，没有"官方编码器重建 0 差"的确定性定位；同族降级（v3.2 装 v4）是普遍盲区；无共享模型指纹库。

## 2. 目标

交付一个 agent 技能包 `endpoint-verify`：

- 对任意 OpenAI 兼容 API 端点（中转站/匿名模型/官方 API）做"真身审计"，输出确定性判定报告。
- 可安装到 Hermes / Claude Code / Codex / DSH 等 agent 工具（SKILL.md 事实标准）。
- 指纹库可社区扩展：预置常见模型 + 运行时从 HuggingFace 拉取。

## 3. 范围

### In（v1）

- L1：10 组提示词 usage 指纹探测 + 恒定偏移判定
- L2：官方 tokenizer/编码器本地重建 + 配置矩阵 0 差定位
- 指纹库：预置 DeepSeek 系（deepseek-v4-flash、deepseek-v3.2，已验证），运行时从 HF 拉取未知模型
- 判定引擎：三态结论（真身 / 同族降级+定位 / 跨家族冒充）+ usage 伪造警示
- 报告：report.json + report.md（agent 可读）
- 回归测试：golden.json（本会话 5 模型实测数据）
- 双语：SKILL.md 中文主文档 + README 英文

### Out（v1 明确不做）

- L3 行为蜜罐（能力题/logprobs/缓存行为）——v2，探针清单借鉴 claude-detector 19 探针目录
- 视觉 token 预算指纹（ffmpeg + processor）——v2 候选
- 持续监控/时间线追踪——v2
- Web 服务、信誉榜——v2+，形态不与 claude-detector 重复

## 4. 生态定位与复用决策（对比 claude-detector）

| 维度 | claude-detector | endpoint-verify | 决策 |
|---|---|---|---|
| 协议 | Anthropic Messages API（Claude 专用） | OpenAI 兼容（通用） | 互补 |
| 形态 | Web 平台（Astro/React） | Agent skill（Python CLI） | 互补 |
| 方法 | 19 行为探针 + 权重打分 | tokenizer 指纹 + 编码器重建 0 差 | 差异化 |
| 代码 | TS 全栈 | Python | ❌ 不复用 |
| 探针清单 | 19 探针目录 | v2 L3 扩展清单模板 | ✅ 借鉴目录结构 |
| 判定 | 真伪×渠道二维 | 三态 + 置信度（v2 升级二维） | ✅ 借鉴分级思想 |

README 需包含生态对比表与致谢。

## 5. 目录结构

```
endpoint-verify/
├── SKILL.md                    # 技能主文档（中文）：触发场景、执行流程、判定规则
├── README.md                   # 英文：定位、安装、用法、生态对比
├── LICENSE                     # MIT
├── scripts/
│   ├── probe.py                # L1：10 组提示词指纹探测（现有 probe.py 泛化）
│   ├── verify.py               # L2：官方编码器重建 + 0 差定位（现有 verify_local.py 泛化）
│   ├── fetch_registry.py       # 指纹库拉取与缓存（HF → 本地，断点续传）
│   └── report.py               # 判定报告（JSON + markdown）
├── registry/
│   ├── deepseek-v4-flash.json  # 预置（已验证，含黄金数据）
│   ├── deepseek-v3.2.json      # 预置（已验证）
│   └── README.md               # 指纹库贡献指南（schema + PR 流程）
├── tests/
│   ├── golden.json             # 回归基线：5 模型 10 组实测 token 序列
│   └── run_tests.py            # 回归测试入口
└── docs/
    └── SPEC.md                 # 本文档
```

## 6. 指纹库条目 schema（v1）

```json
{
  "model": "deepseek-v4-flash",
  "hf_repo": "deepseek-ai/DeepSeek-V4-Flash",
  "tokenizer_file": "tokenizer.json",
  "encoder_script": "encoding/encoding_dsv4.py",
  "encode_config": {"thinking_mode": "thinking", "reasoning_effort": "max", "bos": true},
  "expected_tokens": [100, 100, 97, 106, 116, 100, 100, 111, 100, 99],
  "system_prefix_tokens": 79,
  "verified": {"by": "dengdeng", "date": "2026-08-23", "method": "api-diff + local-rebuild"}
}
```

字段说明：
- `encode_config`：L2 配置矩阵搜索的默认起点（允许脚本穷举 2×2×2 组合）
- `expected_tokens`：可选黄金值，用于 L1 快速比对；缺失时仅用 L2
- `system_prefix_tokens`：系统提示/固定开销 token 数（如 79），用于解释恒定偏移
- `verified`：指纹验证溯源（谁、何时、何法验证）

## 7. 判定规则（写进 SKILL.md）

输入：base_url + api_key + 声称模型名（或"匿名模型"）

1. **L1 指纹采集**：10 组提示词 → `usage.prompt_tokens` 序列
2. **L1 判定**：与声称模型 `expected_tokens`（或本地编码）比对
   - Δ 全 0 → ✅ 真身
   - Δ 恒定 ≠ 0 → 同 tokenizer + 固定开销 → 转 L2 定位
   - Δ 波动 → ❌ 跨家族冒充
3. **L2 定位**：按指纹库取官方 tokenizer/编码器 → 本地重建（配置矩阵穷举）→ 0 差者 = 真实模型；候选矩阵扫描定位同族降级目标
4. **usage 伪造警示**：API 返回值与本地期望差离谱且非恒定 → 🚨 疑似 usage 伪造 → 建议账单核对（usage × 单价 vs 实际扣费）
5. **噪声容忍**：判定用"恒定偏移"而非"绝对相等"（框架差异 ±1~2 token 属正常）

输出：report.json（机器可读）+ report.md（人/agent 可读，含证据表、置信度、建议）。

## 8. 验收标准

1. 对 DeepSeek 官方 v4-flash 端点：输出"真身"结论，golden.json 回归通过
2. 对构造的 v3.2 冒充 v4 场景（本地代理改写 model 字段）：输出"同族降级"，定位到 v3.2（Δ=79 证据链）
3. 对 Qwen 声称 DeepSeek 场景：输出"跨家族冒充"
4. skill 可被 DSH（~/.agents/skills）与 Hermes 加载，agent 按 SKILL.md 独立执行完整流程
5. `tests/run_tests.py` 全绿（golden 回归）

## 9. 里程碑

- **M1 骨架**：目录结构 + 现有资产迁移（probe.py / verify_local.py / results.json / hf-dsv4/ → scripts/ + tests/）
- **M2 指纹库**：schema v1 + fetch_registry.py + DeepSeek 两条目（预置黄金数据）
- **M3 判定**：verify.py 泛化（模型参数化 + 配置矩阵）+ report.py + 三态判定引擎
- **M4 回归**：golden.json + run_tests.py + SKILL.md 双语 + DSH 本地安装验证
- **M5 发布**：LICENSE + README（含生态对比/致谢）+ registry 贡献指南 + GitHub 发布

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| HF 拉取失败（网络/仓库不存在） | 降级 L1-only，报告注明证据不足 |
| 服务端改写 usage | L2 失效；账单核对 + v2 L3 蜜罐 |
| tokenizer 版本更新（指纹漂移） | verified 字段溯源 + 重测机制（M4 起） |
| 家族共用 tokenizer（DeepSeek 系），部分模型不可区分 | 报告标注置信度，依赖编码配置差异（如 79 偏移）定位 |
| 与 claude-detector 定位混淆 | README 生态对比表明确互补边界 |

## 11. 非目标与边界（防漂移）

- 不做 Claude/Messages API 专测（那是 claude-detector 的领地；如需覆盖，借鉴其探针而非重写）
- 不做任何"信誉榜/点名"功能（法律与伦理风险）
- 不存储用户 API key；所有请求仅用于检测
- 判定是"证据报告"而非"法律结论"——SKILL.md 明示局限性
