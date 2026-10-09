"""Living-person detection and display rules.

A person counts as living when the tree records no death, burial, or
cremation AND the best available birth estimate falls inside the
threshold (default 100 years). When the tree gives no usable year, the
person is treated as living. That choice errs toward privacy.
"""
from __future__ import annotations

import datetime as _dt

from .gedcom import Event, Individual, Tree

MODES = ("full", "year-only", "private", "hidden")


class Privacy:
    def __init__(self, tree: Tree, mode: str = "year-only", threshold: int = 100,
                 current_year: int | None = None):
        if mode not in MODES:
            raise ValueError(f"living mode must be one of {MODES}")
        self.tree = tree
        self.mode = mode
        self.threshold = threshold
        self.year = current_year or _dt.date.today().year
        self._cache: dict[str, bool] = {}

    # ---- detection ------------------------------------------------------
    def estimated_birth_year(self, pid: str) -> int | None:
        p = self.tree.people[pid]
        if p.birth_year:
            return p.birth_year
        years = [e.date.year for e in p.events if e.date.year]
        if years:
            return min(years) - 1
        child_years = [self.tree.people[c].birth_year for c in self.tree.children(pid)
                       if c in self.tree.people and self.tree.people[c].birth_year]
        if child_years:
            return min(child_years) - 25
        parent_years = [self.tree.people[x].birth_year for x in self.tree.parents(pid)
                        if x in self.tree.people and self.tree.people[x].birth_year]
        if parent_years:
            return max(parent_years) + 25
        return None

    def is_living(self, pid: str) -> bool:
        if pid in self._cache:
            return self._cache[pid]
        p = self.tree.people[pid]
        if p.death is not None:
            result = False
        else:
            by = self.estimated_birth_year(pid)
            result = True if by is None else by > self.year - self.threshold
        self._cache[pid] = result
        return result

    # ---- display --------------------------------------------------------
    def restricted(self, pid: str) -> bool:
        return self.mode != "full" and self.is_living(pid)

    def show_details(self, pid: str) -> bool:
        """False when only the name (or nothing) may be printed."""
        return not (self.restricted(pid) and self.mode in ("private", "hidden"))

    def name(self, pid: str) -> str:
        p = self.tree.people[pid]
        if self.restricted(pid) and self.mode == "hidden":
            return f"Living {p.surname}".strip()
        return p.name

    def date(self, pid: str, ev: Event | None) -> str:
        if ev is None or not ev.date:
            return ""
        if self.restricted(pid):
            if self.mode == "year-only":
                return ev.date.display(year_only=True)
            return ""
        return ev.date.display()

    def place(self, pid: str, ev: Event | None) -> str:
        if ev is None:
            return ""
        if self.restricted(pid) and self.mode in ("private", "hidden"):
            return ""
        return ev.place

    def lifespan(self, pid: str) -> str:
        p: Individual = self.tree.people[pid]
        if not self.show_details(pid):
            return "living" if self.mode == "private" else ""
        b = p.birth.date.year if p.birth and p.birth.date else None
        d = p.death.date.year if p.death and p.death.date else None
        if self.is_living(pid) and self.mode != "full":
            return f"b. {b}" if b else "living"
        if b or d:
            return f"{b or '?'}–{d or '?'}" if d or not self.is_living(pid) else f"b. {b}"
        return ""

    def photos_allowed(self, pid: str) -> bool:
        return self.show_details(pid)
