"""
One-time fixup for frontend/index.html:
  1. Strips the old dead HTML document that got left wrapped in an HTML
     comment at the top of the file (from an earlier edit) -- keeps only
     the live version.
  2. Adds an Adjusted/Unadjusted toggle checkbox next to the symbol picker.
  3. Wires that checkbox into the price-history fetch call.

Makes a .bak backup before touching anything.
"""

import re

PATH = "frontend/index.html"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

with open(PATH + ".bak", "w", encoding="utf-8") as f:
    f.write(content)
print(f"Backed up original to {PATH}.bak")

# 1. Strip everything before the SECOND <!DOCTYPE html> (the dead commented-out copy)
matches = [m.start() for m in re.finditer(r"<!DOCTYPE html>", content)]
if len(matches) >= 2:
    content = content[matches[1]:]
    print(f"Stripped {matches[1]} characters of dead code from the top of the file.")
else:
    print("Only one <!DOCTYPE html> found -- nothing to strip (file may already be clean).")

# 2. Add the Adjusted/Unadjusted checkbox next to the Load button
old_header = '<select id="symbolInput"></select>\n  <button onclick="loadChart()">Load</button>'
new_header = ('<select id="symbolInput"></select>\n'
              '  <button onclick="loadChart()">Load</button>\n'
              '  <label class="chk-label on" id="lbl-adjusted">'
              '<input type="checkbox" id="chk-adjusted" checked onchange="loadChart()"> Adjusted</label>')
if old_header in content:
    content = content.replace(old_header, new_header)
    print("Added Adjusted/Unadjusted toggle to header.")
else:
    print("WARNING: couldn't find the header block to patch -- toggle not added.")

# 3. Wire the checkbox into the fetch call
old_fetch = 'const res = await fetch(`${API_BASE}/prices/${symbol}/history`);'
new_fetch = ('const adjusted = document.getElementById(\'chk-adjusted\').checked;\n'
             '      const res = await fetch(`${API_BASE}/prices/${symbol}/history?adjusted=${adjusted}`);')
if old_fetch in content:
    content = content.replace(old_fetch, new_fetch)
    print("Wired toggle into the price-history fetch call.")
else:
    print("WARNING: couldn't find the fetch call to patch -- toggle won't actually do anything yet.")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(content)
print("\nDone. Saved updated frontend/index.html.")