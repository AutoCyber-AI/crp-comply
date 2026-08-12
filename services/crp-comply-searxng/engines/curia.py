"""CURIA (Court of Justice of the European Union) case-law engine."""

from __future__ import annotations

from urllib.parse import urlencode

from lxml import html as lxml_html

about = {
    "website": "https://curia.europa.eu/",
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["compliance", "case_law"]
paging = True
time_range_support = False

base_url = "https://curia.europa.eu"
search_url = base_url + "/juris/recherche.jsf?"


def request(query, params):
    args = {"language": "en", "td": "ALL", "txt": query, "pageIndex": params.get("pageno", 1)}
    params["url"] = search_url + urlencode(args)
    return params


def response(resp):
    out = []
    try:
        dom = lxml_html.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return out
    for tr in dom.cssselect("table.detail_juris tr, tr.table_juris"):
        a = tr.cssselect("a")
        if not a:
            continue
        href = a[0].get("href", "")
        if href.startswith("/") or href.startswith("./"):
            href = base_url + "/juris/" + href.lstrip("./")
        title = " ".join(a[0].text_content().split())
        snippet = " ".join(tr.text_content().split())
        out.append({"url": href, "title": title, "content": snippet[:400]})
    return out
