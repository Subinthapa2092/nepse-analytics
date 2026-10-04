"""
Test #3: fixed postback using the EXACT fields copied from your browser's
real request:
  - __EVENTTARGET: left EMPTY (not set to the link)
  - ctl00$ScriptManager1: "<panel>|ctl00$ContentPlaceHolder1$CompanyDetail1$btnQuaterlyTab"
    (the BUTTON, not the link)
  - ctl00$ContentPlaceHolder1$CompanyDetail1$hdnActiveTabID: "#divQuaterly"
    (this was the missing piece)

Run from quarterly/:
    python test_quarterly3.py
"""

import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SYMBOL = "ADBL"
BASE_URL = f"https://merolagani.com/CompanyDetail.aspx?symbol={SYMBOL}"

PANEL_ID = "ctl00$ContentPlaceHolder1$CompanyDetail1$tabPanel"
BTN_TARGET = "ctl00$ContentPlaceHolder1$CompanyDetail1$btnQuaterlyTab"


def collect_form_fields(soup):
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
    resp = session.get(BASE_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    fields = collect_form_fields(soup)

    # the fix: match the real browser request exactly
    fields["__EVENTTARGET"] = ""
    fields["__EVENTARGUMENT"] = ""
    fields["ctl00$ScriptManager1"] = f"{PANEL_ID}|{BTN_TARGET}"
    fields["ctl00$ContentPlaceHolder1$CompanyDetail1$hdnActiveTabID"] = "#divQuaterly"
    fields[BTN_TARGET] = ""
    fields["__ASYNCPOST"] = "true"

    post_headers = dict(HEADERS)
    post_headers["X-MicrosoftAjax"] = "Delta=true"
    post_headers["X-Requested-With"] = "XMLHttpRequest"
    post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    post_resp = session.post(BASE_URL, headers=post_headers, data=fields, timeout=20)
    post_resp.raise_for_status()
    print(f"Response status: {post_resp.status_code}, length: {len(post_resp.text)} chars")

    post_soup = BeautifulSoup(post_resp.text, "html.parser")
    container = post_soup.find(id="divQuaterly")

    if container is None:
        print("[FAIL] div#divQuaterly not found in response.")
        with open("postback_response_dump3.txt", "w", encoding="utf-8") as f:
            f.write(post_resp.text)
        return

    table = container.find("table")
    if table is None:
        print("[FAIL] div#divQuaterly found but no table inside.")
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

    print(f"[RESULT] Found {len(rows)} row(s)!")
    for r in rows[:5]:
        print(f"  FY {r['fiscal_year']} | {r['date']} | id={r['announcement_id']} | {r['description'][:70]}")


if __name__ == "__main__":
    main()