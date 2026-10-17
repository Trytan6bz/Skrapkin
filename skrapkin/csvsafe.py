"""Neutralise spreadsheet formula injection in CSV output.

Business names and emails come from scraped web pages, so they are untrusted. A cell that starts with
`=`, `@`, `+` or `-` can run as a formula when the file is opened in Excel or Sheets. Prefixing an
apostrophe makes the spreadsheet treat it as plain text.
"""

import re

# Phone numbers legitimately start with "+" or "(": digits, spaces, and phone punctuation only.
_PHONE_LIKE = re.compile(r"[\d\s().;+\-]+")


def safe_cell(value):
    if not isinstance(value, str) or not value:
        return value
    first = value[0]
    if first in "=@\t\r" or (first in "+-" and not _PHONE_LIKE.fullmatch(value)):
        return "'" + value
    return value


def safe_row(row):
    """Sanitise a dict (for DictWriter) or a list/tuple (for writer)."""
    if isinstance(row, dict):
        return {k: safe_cell(v) for k, v in row.items()}
    return [safe_cell(v) for v in row]
