"""GEDCOM date phrases: parsing, sorting, and plain-English display."""
from __future__ import annotations

import re
from dataclasses import dataclass

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
QUALIFIERS = {"ABT": "about", "ABOUT": "about", "CIRCA": "about", "C": "about",
              "EST": "estimated", "CAL": "calculated", "BEF": "before",
              "AFT": "after", "INT": ""}

SIMPLE_RE = re.compile(r"^(?:(\d{1,2})\s+)?(?:([A-Z]{3})\s+)?(\d{3,4})(?:/\d{2})?$")


@dataclass
class GDate:
    raw: str = ""
    year: int | None = None
    month: int | None = None
    day: int | None = None
    qualifier: str = ""      # about / before / after / estimated / calculated
    year2: int | None = None  # second year for BET/FROM ranges
    range_word: str = ""      # "between" or "from"

    @classmethod
    def parse(cls, text: str) -> "GDate":
        raw = (text or "").strip()
        s = raw.upper().replace(".", "")
        d = cls(raw=raw)
        if not s:
            return d
        m = re.match(r"^(BET|FROM)\s+(.+?)\s+(AND|TO)\s+(.+)$", s)
        if m:
            a, b = cls._simple(m.group(2)), cls._simple(m.group(4))
            d.year, d.month, d.day = a
            d.year2 = b[0]
            d.range_word = "between" if m.group(1) == "BET" else "from"
            return d
        parts = s.split(None, 1)
        if parts and parts[0] in QUALIFIERS and len(parts) > 1:
            d.qualifier = QUALIFIERS[parts[0]]
            s = parts[1]
            if s.startswith("(") or not re.search(r"\d", s):
                return d
        if s.startswith("FROM "):
            s = s[5:]
            d.qualifier = "from"
        d.year, d.month, d.day = cls._simple(s)
        return d

    @staticmethod
    def _simple(s: str) -> tuple[int | None, int | None, int | None]:
        s = s.strip()
        m = SIMPLE_RE.match(s)
        if m:
            day = int(m.group(1)) if m.group(1) else None
            mon = MONTHS.get(m.group(2) or "")
            return int(m.group(3)), mon, day
        y = re.search(r"(\d{4})", s)
        return (int(y.group(1)) if y else None), None, None

    @property
    def sort_key(self) -> tuple:
        return (self.year or 9999, self.month or 0, self.day or 0)

    def __bool__(self) -> bool:
        return self.year is not None

    def display(self, year_only: bool = False) -> str:
        if self.year is None:
            return self.raw.lower() if self.raw and not year_only else ""
        if year_only:
            core = str(self.year)
        elif self.month and self.day:
            core = f"{self.day} {MONTH_NAMES[self.month]} {self.year}"
        elif self.month:
            core = f"{MONTH_NAMES[self.month]} {self.year}"
        else:
            core = str(self.year)
        if self.year2:
            joiner = "and" if self.range_word == "between" else "to"
            return f"{self.range_word} {core if not year_only else self.year} {joiner} {self.year2}"
        return f"{self.qualifier} {core}".strip()
