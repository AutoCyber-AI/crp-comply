"""European Data Protection Board document register engine."""

from __future__ import annotations

from urllib.parse import urlencode

from lxml import html as lxml_html

about = {
    "website": "https://www.edpb.europa.eu/",
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["compliance", "guidance", "enforcement"]
paging = True
time_range_support = True
safesearch = False

base_url = "https://www.edpb.europa.eu"
search_path = "/search/site/"


def request(query, params):
    page = params.get("pageno", 1)
    params["url"] = f"{base_url}{search_path}{urlencode({'q': query})}&page={page - 1}"
    params["headers"]["Accept"] = "text/html"
    return params


def response(resp):
    out = []
    try:
        dom = lxml_html.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return out
    for row in dom.cssselect("li.search-result, div.search-result"):
        a = row.cssselect("h3 a, h2 a, a.search-result__title")
        if not a:
            continue
        href = a[0].get("href", "")
        if href.startswith("/"):
            href = base_url + href
        title = " ".join(a[0].text_content().split())
        snippet_el = row.cssselect("p.search-snippet, div.search-snippet")
        snippet = " ".join(snippet_el[0].text_content().split()) if snippet_el else ""
        out.append({"url": href, "title": title, "content": snippet})
    return out
