"""
Test #5: using the real announcement ID we just got from the Quarterly
Report list (66659, ADBL's latest quarter), check:
  1. The structured fields (Bookclose Date, % Cash Dividend, etc.)
  2. THE BIG QUESTION: is "Total Assets" present as real text on this page,
     or is the embedded statement an image/canvas Playwright's page content
     won't contain either?

Run from quarterly/:
    python test_announcement_detail.py
"""

from playwright.sync_api import sync_playwright

ANNOUNCEMENT_ID = "66659"
URL = f"https://merolagani.com/AnnouncementDetail.aspx?id={ANNOUNCEMENT_ID}"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"Loading {URL} ...")
        page.goto(URL, timeout=30000)
        page.wait_for_timeout(2000)  # let any embedded viewer finish rendering

        full_text = page.inner_text("body")
        browser.close()

    print(f"Page text length: {len(full_text)} chars\n")

    print("=== Structured fields (looking for known labels) ===")
    for label in ["Symbol", "Fiscal Year", "Bookclose Date", "% Cash Dividend",
                  "% Bonus Share", "Right Share Ratio", "Announcement Date"]:
        idx = full_text.find(label)
        if idx != -1:
            snippet = full_text[idx:idx+120].replace("\n", " | ")
            print(f"  FOUND '{label}': ...{snippet}...")
        else:
            print(f"  NOT FOUND: '{label}'")

    print("\n=== THE BIG QUESTION: embedded financial statement ===")
    for term in ["Total Assets", "Total assets", "Net profit", "Net Profit",
                 "Total Equity", "Earning Per Share", "Earnings Per Share"]:
        found = term in full_text
        print(f"  '{term}' present: {found}")

    with open("announcement_detail_dump.txt", "w", encoding="utf-8") as f:
        f.write(full_text)
    print("\nFull extracted text saved to announcement_detail_dump.txt")


if __name__ == "__main__":
    main()