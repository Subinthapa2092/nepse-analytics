"""
Test #2: actually perform the ASP.NET AJAX async postback that loads the
Quarterly Report tab's real data, using the exact field names confirmed
from quarterly_page_dump.html:
  - ScriptManager field: ctl00$ScriptManager1
  - UpdatePanel id:       ctl00$ContentPlaceHolder1$CompanyDetail1$tabPanel
  - Tab link target:      ctl00$ContentPlaceHolder1$CompanyDetail1$lnkQuaterlyTab

Run from quarterly/:
    python test_quarterly2.py
"""

import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SYMBOL = "ADBL"
BASE_URL = f"https://merolagani.com/CompanyDetail.aspx?symbol={SYMBOL}"

PANEL_ID = "ctl00$ContentPlaceHolder1$CompanyDetail1$tabPanel"
TAB_TARGET = "ctl00$ContentPlaceHolder1$CompanyDetail1$lnkQuaterlyTab"


def collect_form_fields(soup):
    """Grab every input/select/textarea's current value -- standard way to
    emulate an ASP.NET WebForms postback without losing any hidden state."""
    fields = {}
    for inp in soup.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()
        if itype in ("checkbox", "radio"):
            if inp.has_attr("checked"):
                fields[name] = inp.get("value", "on")
        else:
            fields[name] = inp.get("value", "")
    for sel in soup.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        chosen = sel.find("option", selected=True) or sel.find("option")
        fields[name] = chosen.get("value", "") if chosen else ""
    for ta in soup.find_all("textarea"):
        name = ta.get("name")
        if name:
            fields[name] = ta.get_text()
    return fields


def main():
    session = requests.Session()

    print(f"Step A: GET {BASE_URL}")
    resp = session.get(BASE_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    fields = collect_form_fields(soup)
    print(f"Collected {len(fields)} form field(s) from the page.")

    fields["__EVENTTARGET"] = TAB_TARGET
    fields["__EVENTARGUMENT"] = ""
    fields["ctl00$ScriptManager1"] = f"{PANEL_ID}|{TAB_TARGET}"
    fields["__ASYNCPOST"] = "true"

    post_headers = dict(HEADERS)
    post_headers["X-MicrosoftAjax"] = "Delta=true"
    post_headers["X-Requested-With"] = "XMLHttpRequest"
    post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    print("\nStep B: POST the async postback for the Quarterly Report tab...")
    post_resp = session.post(BASE_URL, headers=post_headers, data=fields, timeout=20)
    post_resp.raise_for_status()
    print(f"Response status: {post_resp.status_code}, length: {len(post_resp.text)} chars")
    print(f"First 200 chars of response: {post_resp.text[:200]!r}")

    # the response is pipe-delimited; the HTML chunk for our panel is in there
    # somewhere. Just parse the WHOLE response text as HTML -- BeautifulSoup
    # is forgiving of the pipe-delimited wrapper around it.
    post_soup = BeautifulSoup(post_resp.text, "html.parser")
    container = post_soup.find(id="divQuaterly")

    if container is None:
        print("\n[FAIL] div#divQuaterly still not found in the postback response.")
        with open("postback_response_dump.txt", "w", encoding="utf-8") as f:
            f.write(post_resp.text)
        print("Saved full response to postback_response_dump.txt for inspection.")
        return

    table = container.find("table")
    if table is None:
        print("\n[FAIL] Found div#divQuaterly but still no <table> inside.")
        return

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        link = cells[3].find("a", href=True)
        if link is None:
            continue
        m = re.search(r"id=(\d+)", link["href"])
        rows.append({
            "fiscal_year": cells[1].get_text(strip=True),
            "date": cells[2].get_text(" ", strip=True),
            "announcement_id": m.group(1) if m else None,
            "description": link.get_text(strip=True),
        })

    print(f"\n[RESULT] Found {len(rows)} row(s)!")
    for r in rows[:5]:
        print(f"  FY {r['fiscal_year']} | {r['date']} | id={r['announcement_id']} | {r['description'][:70]}")


if __name__ == "__main__":
    main()