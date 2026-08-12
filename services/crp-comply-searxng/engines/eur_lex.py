"""EUR-Lex CELEX search engine for SearXNG (CRP custom).

Queries https://eur-lex.europa.eu's "quick search" JSON endpoint and
returns regulation/directive/decision documents with their CELEX id,
title, official URL, and adoption date. Used by crp-comply-search for
``intent in {regulation_text, case_law, guidance}``.
"""

from __future__ import annotations

from urllib.parse import urlencode

from lxml import html as lxml_html

about = {
    "website": "https://eur-lex.europa.eu/",
    "official_api_documentation": "https://eur-lex.europa.eu/content/help/data-reuse/webservice.html",
    "use_official_api": False,  # Quick-search HTML; the SOAP API needs auth.
    "require_api_key": False,
    "results": "HTML",
}

categories = ["compliance", "regulation_text", "case_law"]
paging = True
time_range_support = False
safesearch = False

base_url = "https://eur-lex.europa.eu"
search_url = base_url + "/search.html?"


def request(query: str, params: dict) -> dict:
    args = {
        "qid": "1700000000000",
        "scope": "EURLEX",
        "text": query,
        "lang": "en",
        "type": "quick",
        "page": params.get("pageno", 1),
    }
    params["url"] = search_url + urlencode(args)
    params["headers"]["Accept"] = "text/html,application/xhtml+xml"
    return params


def response(resp) -> list[dict]:
    results: list[dict] = []
    try:
        dom = lxml_html.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return results
    # EUR-Lex result rows.
    for row in dom.cssselect("div.SearchResult"):
        title_el = row.cssselect("h2 a, h3 a")
        if not title_el:
            continue
        href = title_el[0].get("href", "")
        if href.startswith("/"):
            href = base_url + href
        title = " ".join(title_el[0].text_content().split())
        snippet_el = row.cssselect("p.tt-text, div.SearchResult-text")
        snippet = " ".join(snippet_el[0].text_content().split()) if snippet_el else ""
        meta_el = row.cssselect("div.SearchResultDoc")
        meta = " ".join(meta_el[0].text_content().split()) if meta_el else ""
        results.append(
            {
                "url": href,
                "title": title,
                "content": (snippet + " " + meta).strip(),
            }
        )
    return results
