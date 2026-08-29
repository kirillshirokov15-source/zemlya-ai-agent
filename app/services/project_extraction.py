from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI


MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
client = OpenAI()

MAX_EXTRACTED_PROJECTS_PER_SOURCE = 8


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "source_type": {
            "type": "string",
            "enum": ["single_project", "multi_project", "discovery_only"],
        },
        "projects": {
            "type": "array",
            "maxItems": MAX_EXTRACTED_PROJECTS_PER_SOURCE,
            "items": {
                "type": "object",
                "properties": {
                    "atomic_title": {"type": "string"},
                    "company_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "project_description": {"type": "string"},
                    "location": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "investment_rub": {
                        "anyOf": [{"type": "number"}, {"type": "null"}]
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                    },
                },
                "required": [
                    "atomic_title",
                    "company_name",
                    "project_description",
                    "location",
                    "investment_rub",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["source_type", "projects", "reason"],
    "additionalProperties": False,
}


SYSTEM_INSTRUCTIONS = """
Ты выделяешь атомарные инвестиционные проекты из одного веб-источника для B2B-лидогенерации
в Московской области.

Главное правило: один элемент projects = один конкретный проект/инвестор/объект.

Не объединяй несколько компаний или несколько объектов в один проект.

Подходящий атомарный проект:
- новое производство, завод, цех, производственный комплекс;
- складской или логистический объект;
- индустриальный проект;
- торговый центр;
- расширение производства, если строительство еще не завершено;
- конкретный инвестор, который подбирает/оформляет площадку или планирует строительство.

Не создавай проект из:
- общей статистики по сотням/тысячам инвестпроектов;
- страницы каталога без конкретного проекта;
- общей страницы индустриального парка без конкретного инвестора;
- описания государственной программы или услуги;
- жилого проекта;
- АЗС;
- уже введенного в эксплуатацию или явно завершенного объекта.

Если источник содержит несколько конкретных проектов, верни каждый отдельно.
Если источник содержит один конкретный проект, верни один.
Если конкретного проекта нет, source_type=discovery_only и projects=[].

Ничего не придумывай.
company_name указывай только если компания явно названа.
investment_rub указывай только если сумма явно относится именно к этому проекту.
project_description должна содержать только факты этого конкретного проекта.
evidence — только короткие факты, явно присутствующие в источнике.
"""


MULTI_URL_PATTERNS = (
    "/investicionnye_proekty_",
    "/stroitelstvo_",
    "/projects/",
    "/map/",
    "/tag/",
)

GENERIC_TITLE_PATTERNS = (
    "инвестиционные проекты",
    "реализация инвестпроектов",
    "инвестпроекты почти",
    "готовые площадки",
    "последние новости",
    "новости с тегом",
)

MULTI_TEXT_MARKERS = (
    "первый проект",
    "второй проект",
    "еще одна компания",
    "ещё одна компания",
    "другой проект",
    "следующий проект",
)


def _looks_like_multi_or_generic(item: dict[str, Any]) -> bool:
    title = (item.get("title") or "").lower()
    url = (item.get("url") or "").lower()
    content = (item.get("content") or "").lower()

    if any(pattern in url for pattern in MULTI_URL_PATTERNS):
        return True

    if any(pattern in title for pattern in GENERIC_TITLE_PATTERNS):
        return True

    if any(marker in content for marker in MULTI_TEXT_MARKERS):
        return True

    # Repeated project/company language is a useful signal that a search result
    # contains a list or an article with several separate projects.
    project_mentions = len(re.findall(r"\bпроект\w*\b", content))
    company_mentions = len(re.findall(r"\bкомпан\w*\b", content))
    construction_mentions = len(re.findall(r"\bстроитель\w*\b", content))

    if project_mentions >= 7 and (company_mentions >= 3 or construction_mentions >= 5):
        return True

    return False


def _extract_with_llm(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "title": item.get("title"),
        "url": item.get("url"),
        "content": item.get("content"),
        "published_date": item.get("published_date"),
    }

    response = client.responses.create(
        model=MODEL,
        store=False,
        instructions=SYSTEM_INSTRUCTIONS,
        input=json.dumps(payload, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "atomic_project_extraction",
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            }
        },
    )

    return json.loads(response.output_text)


def _atomic_item(
    source: dict[str, Any],
    project: dict[str, Any],
    project_index: int,
    source_type: str,
) -> dict[str, Any]:
    evidence = project.get("evidence") or []
    description = project.get("project_description") or ""

    # Qualification sees only the facts for one project instead of a whole
    # article/list page. We still retain original URL and source metadata.
    content_parts = [description]
    if project.get("company_name"):
        content_parts.append(f"Компания: {project['company_name']}.")
    if project.get("location"):
        content_parts.append(f"Локация: {project['location']}.")
    if project.get("investment_rub"):
        content_parts.append(
            f"Инвестиции: {project['investment_rub']:.0f} рублей."
        )
    if evidence:
        content_parts.append("Факты источника: " + " ".join(evidence))

    result = dict(source)
    result["title"] = project.get("atomic_title") or source.get("title")
    result["content"] = "\n".join(content_parts)
    result["extraction"] = {
        "was_split": source_type == "multi_project",
        "source_type": source_type,
        "project_index": project_index,
        "original_title": source.get("title"),
        "original_url": source.get("url"),
        "company_name_hint": project.get("company_name"),
        "location_hint": project.get("location"),
        "investment_rub_hint": project.get("investment_rub"),
    }
    return result


def extract_atomic_projects(
    items: list[dict[str, Any]],
    max_llm_sources: int = 12,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    discovery_only: list[dict[str, Any]] = []

    llm_sources_processed = 0
    split_sources_count = 0
    extracted_projects_count = 0
    passthrough_count = 0

    for item in items:
        if not _looks_like_multi_or_generic(item):
            passthrough = dict(item)
            passthrough["extraction"] = {
                "was_split": False,
                "source_type": "single_project_assumed",
                "project_index": 0,
                "original_title": item.get("title"),
                "original_url": item.get("url"),
            }
            results.append(passthrough)
            passthrough_count += 1
            continue

        if llm_sources_processed >= max_llm_sources:
            # Do not silently discard sources when the extraction budget is hit.
            passthrough = dict(item)
            passthrough["extraction"] = {
                "was_split": False,
                "source_type": "extraction_budget_passthrough",
                "project_index": 0,
                "original_title": item.get("title"),
                "original_url": item.get("url"),
            }
            results.append(passthrough)
            passthrough_count += 1
            continue

        llm_sources_processed += 1

        try:
            extracted = _extract_with_llm(item)
        except Exception as exc:
            passthrough = dict(item)
            passthrough["extraction"] = {
                "was_split": False,
                "source_type": "extraction_error_passthrough",
                "project_index": 0,
                "original_title": item.get("title"),
                "original_url": item.get("url"),
                "error": str(exc)[:500],
            }
            results.append(passthrough)
            passthrough_count += 1
            continue

        source_type = extracted.get("source_type") or "discovery_only"
        projects = extracted.get("projects") or []

        if source_type == "discovery_only" or not projects:
            discovery_only.append(
                {
                    "query": item.get("query"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "score": item.get("score"),
                    "published_date": item.get("published_date"),
                    "reason": extracted.get("reason"),
                }
            )
            continue

        if source_type == "multi_project" or len(projects) > 1:
            split_sources_count += 1

        for index, project in enumerate(projects):
            results.append(
                _atomic_item(
                    source=item,
                    project=project,
                    project_index=index,
                    source_type=source_type,
                )
            )
            extracted_projects_count += 1

    # Keep strongest search signals first so the existing qualification budget
    # continues to operate predictably.
    results.sort(key=lambda x: x.get("score") or 0, reverse=True)

    return {
        "input_sources_count": len(items),
        "llm_sources_processed": llm_sources_processed,
        "split_sources_count": split_sources_count,
        "extracted_projects_count": extracted_projects_count,
        "passthrough_count": passthrough_count,
        "discovery_only_count": len(discovery_only),
        "results_count": len(results),
        "discovery_only": discovery_only,
        "results": results,
    }
