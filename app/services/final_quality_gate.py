from __future__ import annotations
import re
from typing import Any

LEGAL_FORMS = re.compile(r"\b(?:ооо|ао|пао|зао|оао|гк|нпп|группа компаний)\b", re.I)
MODERNIZATION_MARKERS = ("модернизац", "реконструкц", "техническое перевооруж", "обновление производственной линии")
NEW_SITE_MARKERS = ("новый завод", "новое производство", "новая площадка", "строительство", "построить", "создать предприятие", "разместить производство", "локализовать производство")

def _payload(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("qualification") or item

def normalize_company_name(name: str | None) -> str:
    if not name: return ""
    value = LEGAL_FORMS.sub(" ", name.lower().replace("ё", "е"))
    value = re.sub(r"[«»\"'`]", " ", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return " ".join(value.split())

def _inn(item):
    p, e = _payload(item), item.get("enrichment") or {}
    value = e.get("inn") or p.get("inn") or item.get("inn")
    return re.sub(r"\D", "", str(value)) if value else ""

def _company(item):
    p, e = _payload(item), item.get("enrichment") or {}
    return normalize_company_name(e.get("company_legal_name") or e.get("company_name") or p.get("company_name"))

def _words(value):
    value = (value or "").lower().replace("ё", "е")
    return {x for x in re.sub(r"[^a-zа-я0-9]+", " ", value).split()
            if x not in {"промышленное","производство","производственный","завод","предприятие","по","для","и"}}

def _same_project(a, b):
    ia, ib = _inn(a), _inn(b)
    ca, cb = _company(a), _company(b)
    if not ((ia and ib and ia == ib) or (ca and cb and ca == cb)):
        return False
    pa, pb = _payload(a), _payload(b)
    wa, wb = _words(pa.get("project_type")), _words(pb.get("project_type"))
    project_overlap = bool(wa and wb and len(wa & wb) / max(1, min(len(wa), len(wb))) >= .40)
    la = str(pa.get("location") or "").lower()
    lb = str(pb.get("location") or "").lower()
    location_overlap = bool(la and lb and (la in lb or lb in la))
    sa = _words(pa.get("project_summary"))
    sb = _words(pb.get("project_summary"))
    summary_overlap = bool(sa and sb and len(sa & sb) / max(1, min(len(sa), len(sb))) >= .55)
    return project_overlap or (location_overlap and summary_overlap)

def _merge(a, b):
    def richness(x):
        p = _payload(x)
        return (int(p.get("investment_rub") is not None), len(str(p.get("project_summary") or "")), int(x.get("lead_score") or 0))
    primary, secondary = (a,b) if richness(a) >= richness(b) else (b,a)
    out = dict(primary)
    sources = []
    for obj in (a,b):
        for src in obj.get("sources") or []:
            if src not in sources: sources.append(src)
        if obj.get("url"):
            candidate = {"url": obj.get("url"), "title": obj.get("title")}
            if candidate not in sources: sources.append(candidate)
    if sources: out["sources"] = sources
    out["quality_gate"] = {**(out.get("quality_gate") or {}), "merged_duplicate": True}
    return out

def deduplicate_business_projects(items):
    unique, merged = [], 0
    for item in items:
        for i, existing in enumerate(unique):
            if _same_project(existing, item):
                unique[i] = _merge(existing, item); merged += 1; break
        else:
            unique.append(item)
    return {"input_count": len(items), "unique_count": len(unique), "merged_count": merged, "projects": unique}

def apply_business_relevance_gate(item):
    out = dict(item)
    p = _payload(out)
    text = " ".join([str(p.get("project_summary") or ""), str(p.get("project_type") or ""), " ".join(map(str,p.get("evidence") or []))]).lower().replace("ё","е")
    modernization = any(x in text for x in MODERNIZATION_MARKERS) and not any(x in text for x in NEW_SITE_MARKERS)
    temporal = out.get("temporal_quality") or {}
    land_defined = p.get("land_status") == "land_defined"
    out["quality_gate"] = {
        **(out.get("quality_gate") or {}),
        "existing_site_modernization": modernization,
        "land_already_secured": land_defined,
        "needs_current_status_check": bool(temporal.get("needs_current_status_check")),
    }
    return out

def apply_business_relevance(items):
    return [apply_business_relevance_gate(x) for x in items]
