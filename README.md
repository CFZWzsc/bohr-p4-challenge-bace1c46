# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-bace1c46` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `evidence-located-quality-appraisal`
- Summary: Use when a review task needs risk-of-bias or methodological quality appraisal of included studies, and requires per-domain judgements anchored to verbatim quotes and section locations, explicit cannot_assess/not_reported handling, design-aware applicability, and no invented numeric quality scores in a contract-preserving result.json.

## Contents

| File |
|------|
| `SKILL.md` |
| `examples/demo-case/case.json` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
