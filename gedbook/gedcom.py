"""Minimal, dependency-free GEDCOM 5.5 / 5.5.1 reader.

Reads the line structure into a node tree, then builds Individual and Family
objects with the facts the book needs: names, events, families, media
references, notes, and source citations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .dates import GDate

LINE_RE = re.compile(r"^\s*(\d+)\s+(@[^@]+@\s+)?(\S+)(?:\s(.*))?$")

# Events that describe a single point in a life.
INDIVIDUAL_EVENT_TAGS = {
    "BIRT": "Birth", "CHR": "Christening", "BAPM": "Baptism", "DEAT": "Death",
    "BURI": "Burial", "CREM": "Cremation", "CENS": "Census", "RESI": "Residence",
    "OCCU": "Occupation", "EDUC": "Education", "GRAD": "Graduation",
    "MILI": "Military service", "_MILT": "Military service", "IMMI": "Immigration",
    "EMIG": "Emigration", "NATU": "Naturalization", "RELI": "Religion",
    "RETI": "Retirement", "PROB": "Probate", "WILL": "Will", "ADOP": "Adoption",
    "CONF": "Confirmation", "TITL": "Title", "DSCR": "Description",
    "SSN": None,  # never printed
    "EVEN": "Event", "FACT": "Fact",
}
FAMILY_EVENT_TAGS = {
    "MARR": "Marriage", "MARL": "Marriage license", "MARB": "Marriage banns",
    "DIV": "Divorce", "ENGA": "Engagement", "EVEN": "Event",
}


@dataclass
class Node:
    level: int
    tag: str
    value: str = ""
    xref: str | None = None
    children: list["Node"] = field(default_factory=list)

    def first(self, tag: str) -> "Node | None":
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def all(self, tag: str) -> list["Node"]:
        return [c for c in self.children if c.tag == tag]

    def val(self, tag: str, default: str = "") -> str:
        n = self.first(tag)
        return n.value if n is not None else default


@dataclass
class Citation:
    source_id: str | None
    title: str
    page: str = ""


@dataclass
class Event:
    tag: str
    label: str
    date: GDate
    place: str = ""
    value: str = ""
    type: str = ""
    age: str = ""
    note: str = ""
    citations: list[Citation] = field(default_factory=list)

    @property
    def is_census(self) -> bool:
        if self.tag == "CENS":
            return True
        text = " ".join([self.type, self.note] + [c.title + " " + c.page for c in self.citations]).lower()
        return self.tag in {"RESI", "EVEN", "FACT"} and "census" in text


@dataclass
class MediaRef:
    file: str = ""
    title: str = ""
    form: str = ""


@dataclass
class Individual:
    id: str
    given: str = ""
    surname: str = ""
    suffix: str = ""
    nickname: str = ""
    alt_names: list[str] = field(default_factory=list)
    sex: str = "U"
    events: list[Event] = field(default_factory=list)
    famc: list[str] = field(default_factory=list)
    fams: list[str] = field(default_factory=list)
    media: list[MediaRef] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        parts = [self.given, self.surname]
        n = " ".join(p for p in parts if p).strip()
        if self.suffix:
            n = f"{n} {self.suffix}"
        return n or "(unknown)"

    @property
    def sort_key(self) -> tuple:
        return (self.surname.lower() or "~", self.given.lower(), self.birth_year or 9999)

    def event(self, *tags: str) -> Event | None:
        for t in tags:
            for e in self.events:
                if e.tag == t:
                    return e
        return None

    @property
    def birth(self) -> Event | None:
        return self.event("BIRT", "CHR", "BAPM")

    @property
    def death(self) -> Event | None:
        return self.event("DEAT", "BURI", "CREM")

    @property
    def birth_year(self) -> int | None:
        b = self.birth
        return b.date.year if b else None

    @property
    def death_year(self) -> int | None:
        d = self.death
        return d.date.year if d else None


@dataclass
class Family:
    id: str
    husb: str | None = None
    wife: str | None = None
    children: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def spouses(self) -> list[str]:
        return [x for x in (self.husb, self.wife) if x]

    @property
    def marriage(self) -> Event | None:
        for e in self.events:
            if e.tag == "MARR":
                return e
        return None


@dataclass
class Tree:
    people: dict[str, Individual]
    families: dict[str, Family]
    sources: dict[str, str]
    media_objects: dict[str, MediaRef]
    header_source: str = ""

    # ---- relationships -------------------------------------------------
    def parents(self, pid: str) -> list[str]:
        out: list[str] = []
        for fid in self.people[pid].famc:
            fam = self.families.get(fid)
            if fam:
                out.extend(fam.spouses())
        return out

    def father_mother(self, pid: str) -> tuple[str | None, str | None]:
        p = self.people[pid]
        for fid in p.famc:
            fam = self.families.get(fid)
            if fam:
                return fam.husb, fam.wife
        return None, None

    def spouse_families(self, pid: str) -> list[Family]:
        return [self.families[f] for f in self.people[pid].fams if f in self.families]

    def spouse_in(self, fam: Family, pid: str) -> str | None:
        return fam.wife if fam.husb == pid else fam.husb

    def children(self, pid: str) -> list[str]:
        out: list[str] = []
        for fam in self.spouse_families(pid):
            out.extend(fam.children)
        return out

    def siblings(self, pid: str) -> list[str]:
        out: list[str] = []
        for fid in self.people[pid].famc:
            fam = self.families.get(fid)
            if fam:
                out.extend(c for c in fam.children if c != pid and c not in out)
        return out

    def find(self, query: str) -> list[Individual]:
        q = query.lower().split()
        return [p for p in self.people.values() if all(t in p.name.lower() for t in q)]


# ---- low-level parsing -------------------------------------------------

def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # ANSEL and ANSI files: latin-1 keeps every byte; a few accented
        # characters may print incorrectly. Re-export as UTF-8 if so.
        return raw.decode("latin-1")


def parse_nodes(text: str) -> list[Node]:
    roots: list[Node] = []
    stack: list[Node] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            continue
        level = int(m.group(1))
        xref = m.group(2).strip() if m.group(2) else None
        tag = m.group(3).upper()
        value = m.group(4) or ""
        if tag in ("CONC", "CONT") and stack:
            parent = next((n for n in reversed(stack) if n.level == level - 1), stack[-1])
            parent.value += ("\n" if tag == "CONT" else "") + value
            continue
        node = Node(level, tag, value, xref)
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def _citations(node: Node, sources: dict[str, str]) -> list[Citation]:
    out = []
    for s in node.all("SOUR"):
        sid = s.value.strip() if s.value.startswith("@") else None
        title = sources.get(sid, "") if sid else s.value
        out.append(Citation(sid, title, s.val("PAGE")))
    return out


def _event(node: Node, label: str, sources: dict[str, str]) -> Event:
    note = "\n".join(n.value for n in node.all("NOTE") if not n.value.startswith("@"))
    return Event(
        tag=node.tag,
        label=label,
        date=GDate.parse(node.val("DATE")),
        place=node.val("PLAC").strip(),
        value=node.value.strip() if node.value.strip() not in ("Y", "") else "",
        type=node.val("TYPE"),
        age=node.val("AGE"),
        note=note.strip(),
        citations=_citations(node, sources),
    )


def _media(node: Node, objects: dict[str, MediaRef]) -> MediaRef | None:
    if node.value.startswith("@"):
        return objects.get(node.value.strip())
    f = node.first("FILE")
    title = node.val("TITL") or (f.val("TITL") if f else "")
    form = node.val("FORM") or (f.val("FORM") if f else "")
    return MediaRef(file=f.value.strip() if f else "", title=title.strip(), form=form)


def _split_name(value: str) -> tuple[str, str, str]:
    m = re.match(r"^(.*?)/(.*?)/(.*)$", value)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    return value.strip(), "", ""


def load(path: str | Path) -> Tree:
    text = _decode(Path(path).read_bytes())
    roots = parse_nodes(text)

    sources: dict[str, str] = {}
    objects: dict[str, MediaRef] = {}
    header_source = ""
    for r in roots:
        if r.tag == "HEAD":
            header_source = r.val("SOUR")
        elif r.tag == "SOUR" and r.xref:
            sources[r.xref] = (r.val("TITL") or r.val("ABBR") or r.xref).strip()
        elif r.tag == "OBJE" and r.xref:
            m = _media(r, {})
            if m:
                objects[r.xref] = m
    notes_by_id = {r.xref: r.value for r in roots if r.tag == "NOTE" and r.xref}

    people: dict[str, Individual] = {}
    families: dict[str, Family] = {}
    for r in roots:
        if r.tag == "INDI" and r.xref:
            ind = Individual(id=r.xref)
            names = r.all("NAME")
            for i, n in enumerate(names):
                given = n.val("GIVN")
                surname = n.val("SURN")
                g2, s2, sfx = _split_name(n.value)
                given = given or g2
                surname = surname or s2
                sfx = n.val("NSFX") or sfx
                if i == 0:
                    ind.given, ind.surname, ind.suffix = given, surname, sfx
                    ind.nickname = n.val("NICK")
                else:
                    ind.alt_names.append(" ".join(x for x in (given, surname) if x))
            ind.sex = (r.val("SEX") or "U")[:1].upper()
            for c in r.children:
                if c.tag in INDIVIDUAL_EVENT_TAGS and INDIVIDUAL_EVENT_TAGS[c.tag]:
                    label = INDIVIDUAL_EVENT_TAGS[c.tag]
                    if c.tag in ("EVEN", "FACT") and c.val("TYPE"):
                        label = c.val("TYPE")
                    ind.events.append(_event(c, label, sources))
                elif c.tag == "FAMC":
                    ind.famc.append(c.value.strip())
                elif c.tag == "FAMS":
                    ind.fams.append(c.value.strip())
                elif c.tag == "OBJE":
                    m = _media(c, objects)
                    if m:
                        ind.media.append(m)
                elif c.tag == "NOTE":
                    v = notes_by_id.get(c.value.strip(), c.value) if c.value.startswith("@") else c.value
                    if v.strip():
                        ind.notes.append(v.strip())
            people[ind.id] = ind
        elif r.tag == "FAM" and r.xref:
            fam = Family(id=r.xref)
            fam.husb = r.val("HUSB").strip() or None
            fam.wife = r.val("WIFE").strip() or None
            fam.children = [c.value.strip() for c in r.all("CHIL")]
            for c in r.children:
                if c.tag in FAMILY_EVENT_TAGS:
                    label = FAMILY_EVENT_TAGS[c.tag]
                    if c.tag == "EVEN" and c.val("TYPE"):
                        label = c.val("TYPE")
                    fam.events.append(_event(c, label, sources))
            families[fam.id] = fam

    # Repair one-sided links (some exporters write only FAM-side links).
    for fam in families.values():
        for sp in fam.spouses():
            if sp in people and fam.id not in people[sp].fams:
                people[sp].fams.append(fam.id)
        for ch in fam.children:
            if ch in people and fam.id not in people[ch].famc:
                people[ch].famc.append(fam.id)

    for p in people.values():
        p.events.sort(key=lambda e: e.date.sort_key)
    return Tree(people, families, sources, objects, header_source)
