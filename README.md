# endpoint-verify

**Who is really behind that API?** An agent skill that audits any
OpenAI-compatible endpoint (API resellers / stealth models / official APIs)
and determines the true model identity with deterministic evidence.

- **L1 — tokenizer fingerprint**: send 10 discriminating prompts, read
  `usage.prompt_tokens`, and test for *constant offset* (Δ all equal ⇒ same
  tokenizer + fixed system-prompt overhead).
- **L2 — official encoder rebuild**: download the model's official
  `tokenizer.json` + encoding reference from HuggingFace, rebuild expected
  token counts locally, and locate the true model by exact 0-difference match
  (e.g. `thinking + effort=max + BOS` for DeepSeek V4-Flash; the 79-token
  offset is the official `REASONING_EFFORT_MAX` constant).

Verdicts: `authentic` / `same-family` / `same-family-downgrade` (with located
model) / `cross-family` / `inconclusive`.

## Why

API resellers commonly *swap the model field* while keeping usage truthful
(usage is their billing basis), so `usage.prompt_tokens` is a reliable,
hard-to-hide fingerprint. Existing tools (modelprint, claude-detector) rely on
behavior probes with probabilistic scores; this skill adds the deterministic
layer: rebuilding expected token counts with the vendor's *own* encoder and
matching at zero difference — which also catches same-family downgrades
(e.g. DeepSeek-V3.2 served as V4-Flash).

## Install

```bash
# 1. clone and prepare dependencies
git clone https://github.com/yzke/endpoint-verify.git endpoint-verify && cd endpoint-verify
pip install --target=pylibs --break-system-packages tokenizers

# 2. fetch official tokenizer/encoder caches (HuggingFace; set HTTPS_PROXY if needed)
python3 scripts/fetch_registry.py --model deepseek-v4-flash \
    --hf-repo deepseek-ai/DeepSeek-V4-Flash --tokenizer-file tokenizer.json \
    --encoder-path encoding/encoding_dsv4.py
```

### Agent skill installation

| Agent | Path |
|---|---|
| DSH | `~/.agents/skills/endpoint-verify/` |
| Claude Code | `~/.claude/skills/endpoint-verify/` |
| Codex | `~/.codex/skills/endpoint-verify/` |
| Hermes | per hermes skill dir |

## Usage

```bash
# L1: collect the fingerprint
python3 scripts/probe.py --base-url https://api.example.com/v1/chat/completions \
    --api-key-env MY_KEY_ENV --model claimed-model --output /tmp/probe.json

# L2: verify against the fingerprint registry
python3 scripts/verify.py --model claimed-model --api-tokens /tmp/probe.json \
    --output /tmp/verdict.json

# Report
python3 scripts/report.py --verdict /tmp/verdict.json --probe /tmp/probe.json --output report.md
```

**Security**: API keys are read from environment variables only
(`--api-key-env`). Never pass keys inline; they are excluded via `.gitignore`.

## Registry

`registry/<model>.json` describes each known model: HF repo, tokenizer/encoder
paths, default encode config, expected token sequence, system-prefix overhead,
and verification provenance. Same-family models reuse the shared tokenizer
(see `deepseek-v3.2.json`). See `registry/README.md` for contribution guide.

### Supported models (v1.1)

| Model | Encoder type | Verified against |
|---|---|---|
| deepseek-v4-flash | official script (dsv4) | DeepSeek official + SiliconFlow, Δ=0 |
| deepseek-v3.2 | official script (dsv4, shared tokenizer) | SiliconFlow, Δ=0 |
| qwen3.6-27b | HF chat_template | SiliconFlow, Δ=0 |
| glm4.5-air | HF chat_template (chat_template.jinja, no gen prompt) | SiliconFlow, Δ=0 |
| mistral-small-3.1 | HF chat_template | tokenizer cached, expected_tokens pending |

Encoder types: `dsv4` = vendor encoding reference script; `chat_template` =
HF Jinja template rendered with `tokenizers` (optionally without
`add_generation_prompt`, configurable per entry).

Notes:
- **Kimi-K3**: tokenizer is `tiktoken.model` + custom code (`tokenization_kimi.py`);
  not yet supported by this skill (roadmap: tiktoken adapter).
- **Meta Llama**: gated repo; set `HF_TOKEN` env var (HF account with access)
  before `fetch_registry.py`.
- **Closed models (GPT/Claude/Gemini)**: tokenizers are not public, so L2
  0-diff rebuild is impossible; only L1 differential against community golden
  sequences applies (roadmap).
- **Reasoning models** (e.g. GLM-4.5): servers often run full reasoning even
  with `max_tokens=1`; probing is slow and urllib may time out — retry or
  rely on offline golden verification.

## Tests

```bash
python3 tests/run_tests.py          # offline: cache integrity + verdict scenarios + key-leak scan
python3 tests/run_tests.py --online # requires DEEPSEEK_API_KEY / SILICONFLOW_API_KEY env vars
```

## Ecosystem

| | claude-detector (anthropic.mom) | **endpoint-verify** |
|---|---|---|
| Protocol | Anthropic Messages API (Claude only) | OpenAI-compatible (any vendor) |
| Form | Web platform (Astro/React) | Agent skill (Python CLI) |
| Method | 19 behavior probes, weighted scores | tokenizer fingerprint + official-encoder 0-diff rebuild |
| Determinism | probabilistic | deterministic (0-diff locate) |

Complementary, not duplicate. Probe-list taxonomy from claude-detector is
acknowledged as the reference for future L3 behavior probes.

## Limitations

- Family-level resolution: models sharing a tokenizer (DeepSeek V3.2/V4) are
  distinguished via encoding-config overhead; some may be indistinguishable —
  confidence is reported.
- A malicious relay that rewrites `usage` and forges it to match the official
  encoder escapes L1/L2; cross-check billing (usage × price vs charged).
- Verdicts are evidence reports, not legal conclusions.

## License

MIT
