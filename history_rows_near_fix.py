def _history_rows_near(soup, heading_text):
    """Finds the specific panel-link element matching heading_text, then the
    nearest following <table>, and returns [(fiscal_year, value), ...] from
    its rows. Returns [] if nothing matches.

    FIX: the previous version searched span/div/h1-4/th/td for ANY element
    whose text CONTAINED heading_text as a substring, then broke on the
    first hit. On this site, the whole summary block (Sector, Market Price,
    ..., % Dividend, % Bonus, Right Share, ...) sits inside one outer
    container, so that outer wrapper's combined text contains ALL THREE
    labels as substrings -- and since BeautifulSoup yields parents before
    children, that same outer wrapper matched first for every label,
    sending "Dividend", "Bonus" and "Right Share" all to the same
    .find_next("table") call. That's why all three counts always came out
    identical.

    This version searches only <a> tags (the actual panel links, e.g.
    '% Dividend', '% Bonus', 'Right Share') and requires the link's
    stripped text to START WITH heading_text rather than just contain it
    anywhere -- much less likely to accidentally match a large wrapping
    element instead of the specific link.
    """
    heading_el = None
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        # strip a leading '%' so "% Dividend" matches heading_text="Dividend"
        normalized = text.lstrip("%").strip()
        if normalized.lower().startswith(heading_text.lower()):
            heading_el = a
            break

    if heading_el is None:
        return []

    table = heading_el.find_next("table")
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) < 2:
            continue
        fy_cell = next((c for c in cells if re.search(r"\d{2,3}[-/]\d{2,3}", c)), None)
        if fy_cell is None:
            continue
        value_cell = next((c for c in cells if c is not fy_cell), None)
        if value_cell is None:
            continue
        rows.append((fy_cell, value_cell))
    return rows