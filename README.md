# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-bace1c46` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `evidence-located-quality-appraisal`
- Summary: Use when a review task needs risk-of-bias or methodological quality appraisal of included studies, and requires per-domain judgements anchored to verbatim quotes and section locations, explicit cannot_assess/not_reported handling, design-aware applicability, and no invented numeric quality scores in a contract-preserving result.json.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
