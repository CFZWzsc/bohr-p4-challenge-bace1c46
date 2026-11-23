---
name: evidence-located-quality-appraisal
description: Use when a review task needs risk-of-bias or methodological quality appraisal of included studies, and requires per-domain judgements anchored to verbatim quotes and section locations, explicit cannot_assess/not_reported handling, design-aware applicability, and no invented numeric quality scores in a contract-preserving result.json.
---

# 研究方法质量与偏倚风险评价

## 用途与适用条件

当任务要求对纳入研究做方法学质量/偏倚风险评价，并且必须逐域说明判断依据、定位到原文句子、区分"低风险"与"未报告"时使用。适用于系统综述的质量评价阶段、证据强度分级前的准备与稿件方法学自查。

**适用前提**：输入真实提供研究记录及其可用文本（摘要与/或分节全文），以及可选的域配置或已声明的域判断。只有摘要时仍可评价，但会明确标记 `assessment_scope=abstract_only`，并把方法学细节归为不可评估。

**不适用**：替代专家做最终偏倚判定、全文数据提取、定量 Meta 分析、给出单一"质量分"。不联网、不生成虚构引文。

## 输入

| 输入 | 说明 |
|---|---|
| `/input/case.json` | 必读。常见结构：`studies`/`papers`/`records`，每条含 `title`、`doi`、`design`/`study_type`、`abstract`、`sections`（如 `methods`/`results`）、可选 `domain_signals`（`{"D1": {"judgement": "...", "quote": "...", "section": "..."}}`）；可选 `domains` 配置（`id`、`name`、`applies_to`、`low_cues`、`high_cues`、`some_cues`）。实际键名以文件为准。 |
| `task.md` | 可选，存在时读取用于核对研究类型与评价框架（如 RoB 2、NOS）。 |
| `--work` | 工作目录，默认 `/app/work`。 |

## 处理流程（对应评分维度）

1. **识别研究与设计**（任务完成度）：抽取研究标识、标题、DOI、年份；设计优先取声明字段，缺失时从标题/摘要关键词推断并标记 `design_source=inferred`。
2. **确定文本范围**（可靠体验）：按实际存在的文本块（标题、摘要、`sections` 的 methods/results 等）建立检索范围，并记录 `sections_available` 与 `assessment_scope`，不假装读过没有提供的全文。
3. **逐域判断**（正确性/可核验性）：对每个适用域，先接受输入显式声明的判断；否则在可用文本中匹配风险降低/风险升高/部分报告线索，抽取**含线索的原句**与所在小节。规则：
   - 只找到风险升高线索 → `high`；
   - 只找到风险降低线索 → `low`；
   - 两类线索并存 → `some_concerns`，交人工裁定；
   - 只有部分报告线索 → `some_concerns`；
   - 什么都没找到 → `not_reported`，**不得解释为低风险**。
4. **适用性判定**（正确性）：按设计族（randomized / cohort / case-control / cross-sectional / review / qualitative / other）决定域是否适用；不适用的域标 `not_applicable` 并说明原因，不用 N/A 掩盖缺失信息。
5. **总体判断**（完整性）：按"最差适用域主导"规则给出 `low`/`some_concerns`/`high`/`cannot_assess`；若所有域都不可评估则总体为 `cannot_assess`，不生成数值总分。
6. **证据登记与汇总**（可核验性）：输出逐研究逐域判断表、`domain_table` 计数、总体分布与证据清单（研究、域、小节、原句），并标记 `requires_human_confirmation=true`。

## 输出契约

写入 `--out`（默认 `/app/output/result.json`）。顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 原样保留输入 `case_id` |
| `status` | string | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | object | `appraisals`（同时以 `studies` 暴露）、`domain_table`、`summary`、`rating_rules`、`scoring_policy`、`limitations`、`change_log` |
| `appraisals` | array | 顶层镜像：每项含 `domains`（逐域 judgement/reason/evidence）、`overall_judgement`、`assessment_scope`、`confidence` |
| `evidence` | array | 逐域原句与小节、域定义 |
| `uncertainty` | array | 无文本、仅摘要、设计推断、不可评估、线索法边界 |
| `errors` | array | 运行错误；正常为空 |
| `stats` | object | 研究数、域数、已评估域行数、总体分布 |
| `contract_notes` | object | 未产出契约字段说明 |
| `output_contract_fields` | object | `provided` 与 `present` |

输入 `output_contract` 的每个字段名都会出现在顶层；无法产出时写 `null` 并在 `contract_notes` 说明。

`status`：无研究 → `insufficient_input`；有研究但无任何可用文本或域配置 → `partial`；研究与文本齐备 → `success`；解析失败 → `failed`。

## 异常处理

| 情形 | 处理 | 输出标记 |
|---|---|---|
| 无研究记录 | 不生成评价 | `status=insufficient_input` |
| 研究无任何文本 | 全域 `cannot_assess`，不判低风险 | `uncertainty.type=no_text` |
| 仅标题与摘要 | 仍评价，但方法学域多为 `not_reported` | `assessment_scope=abstract_only` |
| 设计未声明 | 关键词推断并标注 | `design_source=inferred` |
| 域与研究设计不匹配 | `not_applicable` 并写原因 | `domains[].reason` |
| 风险线索互相矛盾 | `some_concerns`，全部证据保留 | `reason` 说明需裁定 |
| 输入已给显式判断 | 直接采用并写出来源 | `evidence[].cue=declared_signal` |
| 输出目录不可写 | stderr 简短错误，退出码 3 | 无静默成功 |

## 限制

- 线索匹配无法理解否定、限定与语境，容易把"未设盲"与"设盲"混淆，需人工复核关键判定。
- 仅摘要评价无法验证分配隐藏、盲法等 methods 层细节。
- 域适用性依赖声明或推断的研究设计。
- 不输出单一数值质量分，避免伪精确；跨研究比较应基于逐域判断。
- 本 Skill 是决策支持，不构成正式偏倚风险裁定。

## 最小调用示例（示例，非正式案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --case /input/case.json --out /app/output/result.json --work /app/work
```

输入片段（示例）：

```json
{"case_id": "demo-006",
 "studies": [{"title": "Trial of X", "design": "randomized controlled trial",
              "abstract": "Participants were randomly assigned. Outcome assessors were blinded.",
              "sections": {"methods": "Randomisation used computer-generated random sequence with allocation concealment."}}]}
```

示意输出（示例，已截断）：

```json
{"case_id": "demo-006", "status": "success",
 "appraisals": [{"overall_judgement": "some_concerns", "assessment_scope": "full_text_sections",
                 "domains": [{"domain": "randomisation_process", "judgement": "low",
                              "evidence": [{"section": "methods", "cue": "computer-generated random"}]},
                             {"domain": "missing_outcome_data", "judgement": "not_reported"}]}]}
```

以上为接口示意，不代表任何官方固定案例结果。


## 交付保证与评分对齐

1. 在 Skill 安装目录执行：`cd /skills/weekly-skill && python scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work`；路径不同时显式改 `--case` / `--out` / `--work`，不要假定相对路径可用。
2. 必须产出**完整成品** `result.json`：每项研究逐域给出 judgement、理由与原句证据，总体判断与适用范围完整；禁止 skeleton、`pending`、空占位或只写方法说明。
3. 脚本无法自动完成的实质判断（真实方法学语境、`cannot_assess` 边界）由调用 Agent 依据实际文本补全并写回 `result.json`，不得编造引文。
4. 自检：`case_id` 与输入一致；`output_contract` 每个字段存在；`status` 取本契约值 `success` / `partial` / `insufficient_input` / `failed`（不得写 `completed`）；`not_reported` 未误判为低风险。
5. 输入缺失、JSON 损坏或字段异常时仍写出结构化结果并说明缺口，不崩溃、不静默成功。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
