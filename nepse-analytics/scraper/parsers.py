"""
Parsing helpers, kept separate from fetch logic so each can be tested
and changed independently (page structure will change over time;
fetching logic shouldn't have to change when parsing does, and vice versa).
"""

from bs4 import BeautifulSoup


def parse_table_rows(html: str, table_id: str) -> list[list[str]]:
    """Given raw HTML and a table id, return rows of cell text."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"id": table_id})
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cols:
            rows.append(cols)
    return rows
