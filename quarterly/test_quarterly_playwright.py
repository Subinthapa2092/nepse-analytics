"""
Test #4: use a real (headless) browser via Playwright to click the Quarterly
Report tab, instead of simulating the ASP.NET postback by hand -- same fix
your floorsheet scraper already uses for this exact class of problem.

If Playwright's browser isn't installed yet, run this first:
    playwright install chromium

Run from quarterly/:
    python test_quarterly_playwright.py
"""

import re

from playwright.sync_api import sync_playwright

SYMBOL = "ADBL"
URL = f"https://merolagani.com/CompanyDetail.aspx?symbol={SYMBOL}"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"Loading {URL} ...")
        page.goto(URL, timeout=30000)

        print("Clicking the Quarterly Report tab...")
        page.click("#ctl00_ContentPlaceHolder1_CompanyDetail1_lnkQuaterlyTab")

        # wait for the table to actually have rows (not just the empty shell)
        page.wait_for_selector("#divQuaterly table tr td a[href*='AnnouncementDetail']", timeout=15000)

        rows_html = page.inner_html("#divQuaterly")
        browser.close()

    # quick parse: just find announcement links + their row text
    matches = re.findall(
        r'<tr>.*?(\d{3}-\d{3}).*?(\d{4}/\d{2}/\d{2} AD).*?href="([^"]*AnnouncementDetail[^"]*)".*?>([^<]*)</a>',
        rows_html,
        re.DOTALL,
    )
    print(f"\n[RESULT] Found {len(matches)} row(s) via regex scan!")
    for fy, date, href, desc in matches[:5]:
        print(f"  FY {fy} | {date} | {href} | {desc[:70]}")

    if not matches:
        with open("playwright_divquaterly_dump.html", "w", encoding="utf-8") as f:
            f.write(rows_html)
        print("No matches -- saved raw div#divQuaterly HTML to playwright_divquaterly_dump.html for inspection.")


if __name__ == "__main__":
    main()