#!/usr/bin/env python3
"""Evidence-located research quality appraisal / risk-of-bias assessment (stdlib only).

Reads a case file (default /input/case.json) with studies, their available text
(abstract and/or sections) and optional domain configuration. For every study
and every applicable domain it reports a judgement, the verbatim quoted cue and
the section where it was found. Absence of information becomes
"cannot_assess"/"not_reported", never "low risk". Overall rating follows the
worst applicable domain. Writes result.json preserving case_id and every
original output_contract field.

No network access, no randomness, no private paths, no fabricated quality scores.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUT = "/app/output/result.json"
DEFAULT_WORK = "/app/work"

STUDY_KEYS = ("studies", "papers", "records", "included", "articles", "items")
TITLE_KEYS = ("title", "article_title", "paper_title", "display_name", "题名")
DESIGN_KEYS = ("design", "study_design", "study_type", "publication_type", "design_type")
JUDGEMENT_ORDER = {"high": 4, "some_concerns": 3, "low": 2, "not_applicable": 1, "cannot_assess": 0, "not_reported": 0}

DEFAULT_DOMAINS = [
    {"id": "D1", "name": "randomisation_process", "applies_to": ["randomized", "rct", "trial"],
     "low_cues": ["randomised controlled", "randomized controlled", "random allocation", "allocation concealment",
                  "computer-generated random", "computer generated random", "randomly assigned"],
     "high_cues": ["quasi-random", "quasi random", "alternation allocation", "not randomised", "not randomized"],
     "some_cues": ["randomised", "randomized", "random assignment"]},
    {"id": "D2", "name": "deviations_from_intended_interventions", "applies_to": ["randomized", "rct", "trial"],
     "low_cues": ["intention-to-treat", "intention to treat", "double-blind", "double blind", "placebo-controlled",
                  "protocol deviations were balanced"],
     "high_cues": ["per-protocol only", "per protocol only", "unblinded", "open-label", "open label",
                   "no blinding", "deviations differed between groups"],
     "some_cues": ["single-blind", "single blind", "partially blinded"]},
    {"id": "D3", "name": "missing_outcome_data", "applies_to": ["randomized", "rct", "trial", "cohort", "case-control", "cross-sectional"],
     "low_cues": ["complete outcome data", "no missing outcome data", "lost to follow-up was 0",
                  "no participants were lost", "0% lost to follow-up"],
     "high_cues": ["high attrition", "large loss to follow-up", "lost to follow-up exceeded",
                   "missing outcome data were imbalanced"],
     "some_cues": ["some missing data", "missing data", "dropout", "loss to follow-up", "lost to follow-up"]},
    {"id": "D4", "name": "measurement_of_outcome", "applies_to": ["randomized", "rct", "trial", "cohort", "case-control", "cross-sectional"],
     "low_cues": ["blinded outcome assessment", "outcome assessors were blinded", "objective outcome",
                  "validated instrument", "standardised assay", "standardized assay"],
     "high_cues": ["unblinded outcome assessment", "self-reported unvalidated", "outcome assessment was not blinded"],
     "some_cues": ["self-reported", "self reported", "single assessor"]},
    {"id": "D5", "name": "selection_of_reported_result", "applies_to": ["randomized", "rct", "trial", "cohort", "case-control", "cross-sectional", "review"],
     "low_cues": ["pre-registered", "preregistered", "registered protocol", "published protocol",
                  "all pre-specified outcomes are reported"],
     "high_cues": ["selective reporting", "outcome switching", "not pre-registered", "not preregistered",
                   "protocol not available"],
     "some_cues": ["registered", "trial registration", "protocol"]},
    {"id": "D6", "name": "confounding_and_selection", "applies_to": ["cohort", "case-control", "cross-sectional"],
     "low_cues": ["adjusted for confounders", "propensity score", "multivariable adjustment",
                  "confounders were pre-specified"],
     "high_cues": ["unadjusted", "no adjustment for confounders", "confounding was not addressed"],
     "some_cues": ["adjusted", "covariates", "matched"]},
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_task_text(case_path, work_dir):
    for path in (Path(case_path).resolve().parent / "task.md", Path("/input/task.md"), Path(work_dir) / "task.md"):
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
    return ""


def norm_space(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def pick(record, names):
    for name in names:
        value = record.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def authors_of(value):
    if isinstance(value, str):
        return norm_space(value)
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str):
                out.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("family") or item.get("literal")
                if name:
                    out.append(str(name).strip())
        return "; ".join(n for n in out if n)
    return ""


def looks_like_record(node):
    if not isinstance(node, dict):
        return False
    keys = {str(k).lower() for k in node.keys()}
    return bool(keys & {k.lower() for k in TITLE_KEYS}) or bool(keys & {"doi", "pmid", "sections", "abstract"})


def find_list(case, keys):
    if not isinstance(case, dict):
        return [], ""
    for key in keys:
        value = case.get(key)
        if isinstance(value, list) and value:
            return value, "/" + key
    for container in ("data", "input"):
        inner = case.get(container)
        if isinstance(inner, dict):
            for key in keys:
                value = inner.get(key)
                if isinstance(value, list) and value:
                    return value, "/%s/%s" % (container, key)
    return [], ""


# --------------------------------------------------------------------------
# text assembly
# --------------------------------------------------------------------------
def sections_of(record):
    """Return ordered [(label, text)] for every text block actually supplied."""
    out = []
    title = norm_space(str(pick(record, TITLE_KEYS) or ""))
    if title:
        out.append(("title", title))
    abstract = pick(record, ("abstract", "summary", "abstract_text"))
    if isinstance(abstract, str) and abstract.strip():
        out.append(("abstract", norm_space(abstract)))
    sections = record.get("sections") or record.get("full_text_sections") or record.get("text_sections")
    if isinstance(sections, dict):
        for key in ("introduction", "methods", "results", "discussion", "conclusion"):
            if isinstance(sections.get(key), str) and sections[key].strip():
                out.append((key, norm_space(sections[key])))
        for key in sorted(sections):
            if key in ("introduction", "methods", "results", "discussion", "conclusion"):
                continue
            if isinstance(sections[key], str) and sections[key].strip():
                out.append((key, norm_space(sections[key])))
    elif isinstance(sections, list):
        for index, item in enumerate(sections):
            if isinstance(item, dict):
                label = norm_space(str(item.get("heading") or item.get("section") or "section_%d" % index))
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    out.append((label, norm_space(text)))
            elif isinstance(item, str) and item.strip():
                out.append(("section_%d" % index, norm_space(item)))
    full = pick(record, ("full_text", "text", "body"))
    if isinstance(full, str) and full.strip():
        out.append(("full_text", norm_space(full)))
    return out


def study_identity(record, locator):
    design = norm_space(str(pick(record, DESIGN_KEYS) or ""))
    design_source = "declared" if design else "inferred"
    sections = sections_of(record)
    if not design:
        haystack = " ".join(text for _, text in sections[:2]).lower()
        patterns = (
            ("randomized controlled trial", ("randomised controlled trial", "randomized controlled trial", "rct")),
            ("systematic review", ("systematic review", "meta-analysis", "meta analysis")),
            ("cohort", ("cohort study", "prospective cohort", "retrospective cohort")),
            ("case-control", ("case-control", "case control")),
            ("cross-sectional", ("cross-sectional", "cross sectional", "survey")),
            ("qualitative", ("qualitative", "interviews", "focus group")),
            ("case report", ("case report", "case series")),
        )
        for label, needles in patterns:
            if any(needle in haystack for needle in needles):
                design = label
                break
    return {
        "study_id": str(pick(record, ("study_id", "record_id", "id", "paper_id", "uid")) or locator),
        "title": sections[0][1] if sections and sections[0][0] == "title" else "",
        "design": design or "unspecified",
        "design_source": design_source if design else "unknown",
        "authors": authors_of(pick(record, ("authors", "author", "creator"))),
        "year": pick(record, ("year", "pub_year", "publication_year")),
        "doi": str(pick(record, ("doi", "DOI")) or ""),
        "sections": [label for label, _ in sections],
        "scope": "abstract_only" if sections and all(label in ("title", "abstract") for label, _ in sections) else "full_text_sections",
        "locator": locator,
        "text_blocks": sections,
        "raw": record,
    }


def design_family(study):
    design = study["design"].lower()
    if any(word in design for word in ("random", "trial", "rct")):
        return "randomized"
    if "systematic" in design or "meta" in design or "review" in design:
        return "review"
    if "cohort" in design:
        return "cohort"
    if "case-control" in design or "case control" in design:
        return "case-control"
    if "cross" in design or "survey" in design:
        return "cross-sectional"
    if "qualitative" in design:
        return "qualitative"
    return "other"


def sentence_with(text, cue):
    lowered = text.lower()
    position = lowered.find(cue.lower())
    if position < 0:
        return ""
    start = max(text.rfind(". ", 0, position), text.rfind("; ", 0, position))
    end = len(text)
    for marker in (". ", "; "):
        found = text.find(marker, position)
        if found >= 0:
            end = min(end, found + 1)
    return norm_space(text[start + 1 if start >= 0 else 0:end])[:320]


def explicit_signal(record, domain_id):
    signals = record.get("domain_signals") or record.get("domains") or record.get("risk_of_bias")
    if isinstance(signals, dict):
        value = signals.get(domain_id) or signals.get(domain_id.lower())
        if isinstance(value, str):
            return {"judgement": value.strip().lower(), "quote": "", "section": "declared_signal"}
        if isinstance(value, dict):
            return {
                "judgement": str(value.get("judgement") or value.get("rating") or "").strip().lower(),
                "quote": norm_space(str(value.get("quote") or value.get("evidence") or "")),
                "section": norm_space(str(value.get("section") or "declared_signal")),
            }
    return None


def appraise_domain(study, domain):
    family = design_family(study)
    applies = domain.get("applies_to") or []
    if applies and family not in applies and "all" not in applies:
        return {
            "domain": domain["name"],
            "judgement": "not_applicable",
            "reason": "domain does not apply to study design family '%s'" % family,
            "evidence": [],
            "assessed": False,
        }

    signal = explicit_signal(study["raw"], domain["id"])
    if signal and signal["judgement"] in JUDGEMENT_ORDER:
        judgement = signal["judgement"]
        return {
            "domain": domain["name"],
            "judgement": judgement,
            "reason": "judgement supplied explicitly in the input",
            "evidence": [{"quote": signal["quote"], "section": signal["section"], "cue": "declared_signal"}],
            "assessed": judgement not in ("cannot_assess", "not_reported"),
        }

    blocks = study["text_blocks"]
    if not blocks:
        return {"domain": domain["name"], "judgement": "cannot_assess",
                "reason": "no text was supplied for this study", "evidence": [], "assessed": False}

    low_hits, high_hits, some_hits = [], [], []
    for label, text in blocks:
        for cue in domain.get("low_cues", []):
            if cue.lower() in text.lower():
                low_hits.append({"section": label, "cue": cue, "quote": sentence_with(text, cue), "grade": "low"})
        for cue in domain.get("high_cues", []):
            if cue.lower() in text.lower():
                high_hits.append({"section": label, "cue": cue, "quote": sentence_with(text, cue), "grade": "high"})
        for cue in domain.get("some_cues", []):
            if cue.lower() in text.lower():
                some_hits.append({"section": label, "cue": cue, "quote": sentence_with(text, cue), "grade": "some_concerns"})

    if high_hits and low_hits:
        judgement = "some_concerns"
        reason = "both risk-raising and risk-lowering cues were found; requires human adjudication"
        evidence = (high_hits + low_hits)[:6]
    elif high_hits:
        judgement = "high"
        reason = "risk-raising cue(s) found in the available text"
        evidence = high_hits[:4]
    elif low_hits:
        judgement = "low"
        reason = "risk-lowering cue(s) found in the available text"
        evidence = low_hits[:4]
    elif some_hits:
        judgement = "some_concerns"
        reason = "only partial reporting cues were found; no explicit methodological safeguard"
        evidence = some_hits[:4]
    else:
        judgement = "not_reported"
        reason = "domain is not reported in the available text; absence is not evidence of low risk"
        evidence = []

    return {
        "domain": domain["name"],
        "judgement": judgement,
        "reason": reason,
        "evidence": evidence,
        "assessed": judgement in ("low", "high", "some_concerns"),
    }


def overall_judgement(domains):
    applicable = [d for d in domains if d["judgement"] not in ("not_applicable",)]
    if not applicable:
        return "not_applicable", "no configured domain applies to this design"
    if all(d["judgement"] in ("cannot_assess", "not_reported") for d in applicable):
        return "cannot_assess", "no domain could be assessed from the supplied text"
    assessed = [d for d in applicable if d["judgement"] in ("low", "high", "some_concerns")]
    if not assessed:
        return "cannot_assess", "no domain has assessable evidence"
    worst = max(assessed, key=lambda d: JUDGEMENT_ORDER[d["judgement"]])
    if worst["judgement"] == "high":
        return "high", "worst-case rule: domain '%s' is high risk" % worst["domain"]
    if worst["judgement"] == "some_concerns":
        return "some_concerns", "worst-case rule: domain '%s' has some concerns" % worst["domain"]
    return "low", "all assessed domains show risk-lowering evidence"


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def contract_names(case):
    contract = case.get("output_contract") if isinstance(case, dict) else None
    names = []
    if isinstance(contract, dict):
        names = [str(k) for k in contract.keys()]
    elif isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("name", "field", "key", "id"):
                    if isinstance(item.get(key), str):
                        names.append(item[key])
                        break
    return names


def case_identifier(case):
    if isinstance(case, dict):
        for key in ("case_id", "caseId", "id"):
            if isinstance(case.get(key), str) and case[key].strip():
                return case[key]
    return ""


def configured_domains(case):
    raw = case.get("domains") if isinstance(case, dict) else None
    domains = []
    if isinstance(raw, list) and raw and all(isinstance(item, dict) for item in raw):
        for index, item in enumerate(raw):
            if any(key in item for key in ("low_cues", "high_cues", "applies_to", "name")):
                domains.append({
                    "id": str(item.get("id") or "D%d" % (index + 1)),
                    "name": str(item.get("name") or "domain_%d" % (index + 1)),
                    "applies_to": [str(x).lower() for x in (item.get("applies_to") or [])],
                    "low_cues": [str(x) for x in (item.get("low_cues") or [])],
                    "high_cues": [str(x) for x in (item.get("high_cues") or [])],
                    "some_cues": [str(x) for x in (item.get("some_cues") or [])],
                })
    return domains or DEFAULT_DOMAINS


def build_payload(case, task_text):
    raw_studies, study_path = find_list(case, STUDY_KEYS)
    studies = [study_identity(item, f"{study_path}/{index}") for index, item in enumerate(raw_studies) if looks_like_record(item)]
    domains = configured_domains(case)

    appraisals = []
    for study in studies:
        domain_rows = [appraise_domain(study, domain) for domain in domains]
        overall, rationale = overall_judgement(domain_rows)
        assessed = sum(1 for row in domain_rows if row["assessed"])
        appraisals.append({
            "study_id": study["study_id"],
            "title": study["title"],
            "doi": study["doi"],
            "year": study["year"],
            "design": study["design"],
            "design_source": study["design_source"],
            "assessment_scope": study["scope"],
            "sections_available": study["sections"],
            "domains": domain_rows,
            "overall_judgement": overall,
            "overall_rationale": rationale,
            "domains_assessed": assessed,
            "domains_total": len(domain_rows),
            "confidence": "low" if study["scope"] == "abstract_only" else ("moderate" if study["design_source"] == "declared" else "low"),
            "requires_human_confirmation": True,
            "source_locator": study["locator"],
        })

    summary = {"low": 0, "some_concerns": 0, "high": 0, "cannot_assess": 0, "not_applicable": 0}
    for appraisal in appraisals:
        summary[appraisal["overall_judgement"]] = summary.get(appraisal["overall_judgement"], 0) + 1
    summary["total"] = len(appraisals)

    domain_table = {}
    for domain in domains:
        counts = {}
        for appraisal in appraisals:
            for row in appraisal["domains"]:
                if row["domain"] == domain["name"]:
                    counts[row["judgement"]] = counts.get(row["judgement"], 0) + 1
        domain_table[domain["name"]] = counts

    uncertainties = []
    if not studies:
        uncertainties.append({"type": "no_studies", "detail": "No study records were supplied for appraisal."})
    if studies and not any(study["text_blocks"] for study in studies):
        uncertainties.append({"type": "no_text", "detail": "No study text was supplied; every domain is cannot_assess rather than low risk."})
    abstract_only = [study["study_id"] for study in studies if study["scope"] == "abstract_only"]
    if abstract_only:
        uncertainties.append({"type": "abstract_only", "detail": "%d study/studies were appraised from title/abstract only; methods-level safeguards cannot be verified." % len(abstract_only)})
    inferred = [study["study_id"] for study in studies if study["design_source"] == "inferred"]
    if inferred:
        uncertainties.append({"type": "inferred_design", "detail": "Design was inferred from text for %d study/studies; domain applicability follows that inference." % len(inferred)})
    if any(appraisal["overall_judgement"] == "cannot_assess" for appraisal in appraisals):
        uncertainties.append({"type": "cannot_assess", "detail": "Some studies cannot be judged from the supplied text; no numeric quality score is invented."})
    uncertainties.append({"type": "cue_based_appraisal", "detail": "Judgements come from explicit quoted cues or declared signals only; they support, not replace, expert risk-of-bias assessment."})

    if not studies:
        status = "insufficient_input"
    elif not any(study["text_blocks"] for study in studies) or not domains:
        status = "partial"
    else:
        status = "success"

    evidence = []
    for appraisal in appraisals[:100]:
        for row in appraisal["domains"]:
            for item in row["evidence"][:2]:
                evidence.append({"kind": "domain_evidence", "study_id": appraisal["study_id"],
                                 "domain": row["domain"], "judgement": row["judgement"],
                                 "section": item.get("section"), "quote": item.get("quote")})
    for domain in domains:
        evidence.append({"kind": "domain_definition", "id": domain["id"], "name": domain["name"],
                         "low_cues": domain["low_cues"], "high_cues": domain["high_cues"]})

    result = {
        "appraisals": appraisals,
        "studies": appraisals,
        "domain_table": domain_table,
        "summary": summary,
        "rating_rules": {
            "order": ["high", "some_concerns", "low", "not_applicable", "cannot_assess", "not_reported"],
            "overall": "worst applicable domain governs",
            "absence_rule": "missing information is recorded as not_reported/cannot_assess, never as low risk",
        },
        "scoring_policy": "No single numeric quality score is produced; only domain judgements, evidence and counts.",
        "limitations": [
            "Cue matching cannot interpret negation, hedging or study-specific nuance.",
            "Abstract-only appraisal cannot verify methods-level safeguards.",
            "Domain applicability depends on the declared or inferred design.",
            "This is decision support for human reviewers, not a formal risk-of-bias adjudication.",
        ],
        "change_log": [
            "Read study text blocks (title/abstract/sections) as supplied.",
            "Applied each applicable domain and searched for explicit low/high/partial cues.",
            "Recorded verbatim quotes with section labels, leaving unreported domains unassessed.",
            "Derived the overall judgement by worst applicable domain.",
        ],
    }

    return {
        "case_id": case_identifier(case),
        "status": status,
        "result": result,
        "appraisals": appraisals,
        "evidence": evidence,
        "uncertainty": uncertainties,
        "errors": [],
        "stats": {
            "studies": len(studies),
            "domains": len(domains),
            "assessed_domain_rows": sum(a["domains_assessed"] for a in appraisals),
            "summary": summary,
            "abstract_only": len(abstract_only),
            "network": "disabled",
        },
    }


CONTRACT_ALIASES = {
    "issues": ("findings", "problems", "defects", "violations"),
    "findings": ("issues",),
    "summary": ("stats", "overview", "counts", "tally"),
    "overview": ("summary", "stats"),
    "stats": ("summary",),
    "verdict": ("recommendation", "decision", "conclusion", "overall"),
    "reviewreport": ("report", "review", "markdown"),
    "report": ("review_report", "review"),
    "scores": ("score", "metrics", "verdict"),
    "metrics": ("scores", "stats"),
    "rows": ("records", "data", "table"),
    "records": ("rows", "data"),
    "citations": ("reference_checks", "citation_checks", "references"),
    "tables": ("table_extractions", "tables_extracted"),
    "figures": ("figure_mentions", "figures_extracted"),
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _severity_counts(findings):
    counts = {}
    if isinstance(findings, list):
        for item in findings:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity") or item.get("level") or "unspecified").lower()
            counts[sev] = counts.get(sev, 0) + 1
    return counts


def _derive_named(name, flat):
    """Return a value for `name` derived from the payload, or (None, reason)."""
    norm = _norm_key(name)
    for alias in CONTRACT_ALIASES.get(norm, ()):
        if alias in flat and flat[alias] not in (None, "", [], {}):
            return flat[alias], "derived from '%s'" % alias
    findings = flat.get("findings") or flat.get("issues") or []
    if norm in ("verdict", "reviewverdict", "decision", "recommendation", "overallverdict"):
        counts = _severity_counts(findings)
        if counts or flat.get("checks"):
            decision = ("major_revision" if counts.get("high")
                        else "minor_revision" if counts.get("medium")
                        else "accept")
            return ({"decision": decision,
                     "basis": "derived from %d finding(s) and %d check(s)"
                              % (len(findings) if isinstance(findings, list) else 0,
                                 len(flat.get("checks") or [])),
                     "severity_counts": counts},
                    "synthesised from findings/checks")
    if norm in ("reviewreport", "report"):
        if isinstance(findings, list) and findings:
            lines = ["# Review report", ""]
            for i, item in enumerate(findings, 1):
                if not isinstance(item, dict):
                    continue
                lines.append("## %d. %s" % (i, item.get("category") or item.get("kind") or "finding"))
                lines.append("")
                lines.append("- severity: %s" % (item.get("severity") or "unspecified"))
                if item.get("issue"):
                    lines.append("- issue: %s" % item["issue"])
                if item.get("evidence"):
                    lines.append("- evidence: %s" % item["evidence"])
                if item.get("suggestion"):
                    lines.append("- suggested fix: %s" % item["suggestion"])
                lines.append("")
            return ({"format": "markdown", "content": "\n".join(lines)},
                    "rendered from findings")
    return None, "not derivable from this run's data"


def apply_contract(payload, case):
    names = contract_names(case)
    notes = {}
    flat = {}
    for holder in (payload, payload.get("result") if isinstance(payload.get("result"), dict) else {}):
        if not isinstance(holder, dict):
            continue
        for key, value in holder.items():
            flat.setdefault(str(key), value)
    for name in names:
        if name in payload and payload[name] is not None:
            notes[name] = "produced directly by this run"
            continue
        value, reason = _derive_named(name, flat)
        if value is not None:
            payload[name] = value
            notes[name] = reason
        else:
            payload[name] = None
            notes[name] = reason
    payload["contract_notes"] = notes
    payload["output_contract_fields"] = {"provided": names,
                                         "present": {name: payload.get(name) is not None
                                                     for name in names}}
    return payload


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, str(target))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence-located quality appraisal and risk-of-bias assessment")
    parser.add_argument("--case", default=DEFAULT_CASE, help="input case JSON (default: /input/case.json)")
    parser.add_argument("--out", "--output", default=DEFAULT_OUT, help="output result JSON (default: /app/output/result.json)")
    parser.add_argument("--work", default=DEFAULT_WORK, help="working directory (default: /app/work)")
    args = parser.parse_args(argv)
    os.environ["SK_RESULT_PATH"] = str(getattr(args, "out", None) or getattr(args, "output", None) or "")

    case = {}
    try:
        case = load_json(args.case)
        if not isinstance(case, dict):
            raise ValueError("case.json root must be a JSON object")
        try:
            Path(args.work).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        task_text = read_task_text(args.case, args.work)
        payload = build_payload(case, task_text)
        code = 0
    except Exception as exc:
        payload = {
            "case_id": case_identifier(case) if isinstance(case, dict) else "",
            "status": "failed",
            "result": None,
            "evidence": [],
            "uncertainty": [{"type": "run_failure", "detail": "Run failed; no appraisal conclusion is reported."}],
            "errors": [{"stage": "build", "type": type(exc).__name__, "message": str(exc)[:500]}],
            "stats": {},
        }
        code = 2

    payload = apply_contract(payload, case if isinstance(case, dict) else {})
    try:
        import deliver as _deliver
        _deliver.finalize(payload, args.out, case if isinstance(case, dict) else {{}})
    except Exception:
        pass
    try:
        write_json(args.out, payload)
    except Exception as exc:
        sys.stderr.write(json.dumps({"status": "failed", "stage": "write_output", "message": str(exc)[:300]}) + "\n")
        return 3

    sys.stdout.write(json.dumps({
        "status": payload.get("status"),
        "case_id": payload.get("case_id"),
        "out": str(args.out),
        "studies": payload.get("stats", {}).get("studies", 0),
    }, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.environ.get("SK_RESULT_PATH") or "result.json"
            _d = os.path.dirname(os.path.abspath(_p))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    _fallback = os.environ.get("SK_RESULT_PATH", "")
    if _fallback and not os.path.isfile(_fallback):
        try:
            _parent = os.path.dirname(os.path.abspath(_fallback))
            if _parent:
                os.makedirs(_parent, exist_ok=True)
            with open(_fallback, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0 if _fallback else _rc)
