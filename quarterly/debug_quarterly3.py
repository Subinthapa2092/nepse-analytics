"""
Diagnostic: same postback as test_quarterly3.py, but checks WHICH tab-pane
the server thinks is "active" in its response, and saves the full response
so we can compare.

Run from quarterly/:
    python debug_quarterly3.py
"""

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


session = requests.Session()
resp = session.get(BASE_URL, headers=HEADERS, timeout=20)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

fields = collect_form_fields(soup)
fields["__EVENTTARGET"] = ""
fields["__EVENTARGUMENT"] = ""
fields["ctl00$ScriptManager1"] = f"{PANEL_ID}|{BTN_TARGET}"
fields["ctl00$ContentPlaceHolder1$CompanyDetail1$hdnActiveTabID"] = "#divQuaterly"
fields[BTN_TARGET] = ""
fields["__ASYNCPOST"] = "true"

print("Fields we're about to send (sanity check):")
print(f"  __EVENTTARGET = {fields.get('__EVENTTARGET')!r}")
print(f"  ctl00$ScriptManager1 = {fields.get('ctl00$ScriptManager1')!r}")
print(f"  hdnActiveTabID = {fields.get('ctl00$ContentPlaceHolder1$CompanyDetail1$hdnActiveTabID')!r}")
print(f"  btnQuaterlyTab present = {BTN_TARGET in fields!r}")
print(f"  Total fields: {len(fields)}")

post_headers = dict(HEADERS)
post_headers["X-MicrosoftAjax"] = "Delta=true"
post_headers["X-Requested-With"] = "XMLHttpRequest"
post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

post_resp = session.post(BASE_URL, headers=post_headers, data=fields, timeout=20)
post_resp.raise_for_status()

with open("postback_response_dump3.txt", "w", encoding="utf-8") as f:
    f.write(post_resp.text)
print(f"\nSaved response ({len(post_resp.text)} chars) to postback_response_dump3.txt")

post_soup = BeautifulSoup(post_resp.text, "html.parser")
active_panes = post_soup.find_all(class_="tab-pane")
print("\nWhich tab-pane is marked 'active' in the response:")
for pane in active_panes:
    classes = pane.get("class", [])
    pane_id = pane.get("id", "?")
    is_active = "active" in classes
    print(f"  id={pane_id!r} active={is_active}")