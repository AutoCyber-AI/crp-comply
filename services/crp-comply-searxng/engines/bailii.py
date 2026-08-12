"""BAILII (British and Irish Legal Information Institute) case-law engine."""

from __future__ import annotations

from urllib.parse import urlencode

from lxml import html as lxml_html

about = {
    "website": "https://www.bailii.org/",
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["compliance", "case_law"]
paging = False
time_range_support = False

base_url = "https://www.bailii.org"
search_url = base_url + "/cgi-bin/sino_search_1.cgi?"


def request(query, params):
    args = {"method": "boolean", "query": query, "mask_path": "", "highlight": "1"}
    params["url"] = search_url + urlencode(args)
    return params


def response(resp):
    out = []
    try:
        dom = lxml_html.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return out
    for li in dom.cssselect("ol li"):
        a = li.cssselect("a")
        if not a:
            continue
        href = a[0].get("href", "")
        if href.startswith("/"):
            href = base_url + href
        title = " ".join(a[0].text_content().split())
        snippet = " ".join(li.text_content().split())
        out.append({"url": href, "title": title, "content": snippet[:400]})
    return out
