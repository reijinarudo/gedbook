"""Match a folder of images to people in the tree.

Signals, strongest first:
  1. The GEDCOM links the person to a file with the same name (OBJE FILE).
  2. Names written inside the image's own metadata (EXIF description,
     Windows title/subject/tags/comments, IPTC caption and keywords,
     XMP title, description, subject, PersonInImage, and face-region names).
  3. The GEDCOM links the person to a media object whose TITLE resembles
     the file name (Ancestry exports carry titles but no file names).
  4. Names in the file name itself, e.g. ``mary_ellen_hollis_1921.jpg``.

Every result lands in a CSV the user reviews. Nothing is final until a
person confirms it, and the CSV is read back on the next build.
"""
from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, IptcImagePlugin
from rapidfuzz import fuzz

from .gedcom import Tree

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp", ".bmp"}
THUMB_RE = re.compile(r"(^thumb[_-])|([_-]thumb(nail)?$)|(^tn[_-])", re.I)
YEAR_RE = re.compile(r"(?<!\d)(1[5-9]\d\d|20[0-4]\d)(?!\d)")
STOP = {"jr", "sr", "ii", "iii", "iv", "the", "and", "of", "mr", "mrs", "miss", "dr",
        "img", "dsc", "scan", "photo", "picture", "copy", "edit", "final", "front", "back",
        "page", "pg", "restored", "colorized", "sharpened", "original", "crop", "cropped"}

KIND_WORDS = {
    "headstone": {"headstone", "grave", "gravestone", "tombstone", "cemetery", "marker", "burial"},
    "obituary": {"obituary", "obit", "funeral", "program", "memorial"},
    "certificate": {"certificate", "cert", "license", "licence", "birth", "death", "marriage",
                    "deed", "will", "probate", "registration", "draft", "passport", "naturalization"},
    "census": {"census", "enumeration", "schedule"},
    "letter": {"letter", "postcard", "card", "note", "diary"},
    "group": {"family", "group", "reunion", "wedding", "class", "siblings", "children"},
}

# Record images from subscription sites can carry reuse restrictions.
# They default to "use = no" so the book carries a transcription instead.
RESTRICTED_KINDS = {"census"}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # camelCase file names
    text = re.sub(r"[^A-Za-z0-9']+", " ", text).lower().replace("'", "")
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in norm(text).split() if t not in STOP and not t.isdigit() and len(t) > 1]


# ---- metadata ------------------------------------------------------------

def _xp(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-16-le", errors="ignore").rstrip("\x00")
    if isinstance(value, tuple):
        return bytes(value).decode("utf-16-le", errors="ignore").rstrip("\x00")
    return str(value or "")


XMP_FIELDS = re.compile(
    r"<(dc:title|dc:description|dc:subject|Iptc4xmpExt:PersonInImage|MP:PersonDisplayName|"
    r"mwg-rs:Name|photoshop:Headline|digiKam:TagsList|lr:hierarchicalSubject)[^>]*>(.*?)</\1>",
    re.S)
XMP_ATTR = re.compile(r'(?:mwg-rs:Name|MPReg:PersonDisplayName)="([^"]+)"')


def read_metadata_text(path: Path) -> str:
    """Return every human-written caption, title, or tag found in the file."""
    found: list[str] = []
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            for tag in (0x010E, 0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F):  # desc, XP* fields
                v = exif.get(tag)
                if v:
                    found.append(_xp(v) if tag >= 0x9C9B else str(v))
            try:
                iptc = IptcImagePlugin.getiptcinfo(im) or {}
                for key in ((2, 120), (2, 25), (2, 5), (2, 105)):  # caption, keywords, object name, headline
                    v = iptc.get(key)
                    if isinstance(v, list):
                        found.extend(x.decode("utf-8", "ignore") for x in v)
                    elif v:
                        found.append(v.decode("utf-8", "ignore"))
            except Exception:
                pass
            xmp = im.info.get("xmp") or im.info.get("XML:com.adobe.xmp")
            if xmp:
                if isinstance(xmp, bytes):
                    xmp = xmp.decode("utf-8", "ignore")
                for _, body in XMP_FIELDS.findall(xmp):
                    found.extend(re.findall(r">([^<>]+)<", f">{body}<") or [body])
                found.extend(XMP_ATTR.findall(xmp))
    except Exception:
        pass
    text = " ; ".join(s.strip() for s in found if s and s.strip())
    return re.sub(r"\s+", " ", text)


def image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def guess_kind(text: str) -> str:
    words = set(norm(text).split())
    for kind, keys in KIND_WORDS.items():
        if words & keys:
            return kind
    return "portrait"


# ---- matching -------------------------------------------------------------

@dataclass
class Candidate:
    pid: str
    score: float
    signals: list[str] = field(default_factory=list)


@dataclass
class MatchRow:
    file: str
    sha1: str
    status: str            # AUTO, REVIEW, UNMATCHED, DUPLICATE, THUMBNAIL
    person_id: str = ""
    person_name: str = ""
    lifespan: str = ""
    score: int = 0
    signals: str = ""
    alternatives: str = ""
    kind: str = "portrait"
    use: str = "yes"
    confirm: str = ""
    override_person_id: str = ""
    caption: str = ""
    metadata_text: str = ""

    FIELDS = ["file", "status", "person_id", "person_name", "lifespan", "score", "kind",
              "use", "confirm", "override_person_id", "caption", "signals", "alternatives",
              "metadata_text", "sha1"]


NOISE = set().union(*KIND_WORDS.values()) | STOP


class Matcher:
    def __init__(self, tree: Tree):
        self.tree = tree
        self.by_surname: dict[str, set[str]] = {}
        self.by_file: dict[str, set[str]] = {}
        self.titles: list[tuple[str, str]] = []
        # variants[pid] = [(given tokens, surname token, other surnames), ...]
        self.variants: dict[str, list[tuple[list[str], str, set[str]]]] = {}
        for p in tree.people.values():
            vs = []
            for nm in [p.name] + p.alt_names:
                toks = tokens(nm)
                if toks:
                    vs.append((toks[:-1], toks[-1], set()))
            # Married names: given names + a spouse's surname, birth surname as a bonus.
            own = tokens(p.surname)
            for fam in tree.spouse_families(p.id):
                sp = tree.spouse_in(fam, p.id)
                if sp and sp in tree.people:
                    st = tokens(tree.people[sp].surname)
                    if st and st != own and vs:
                        vs.append((vs[0][0], st[-1], set(own)))
            if p.nickname and vs:
                vs.append((tokens(p.nickname), vs[0][1], set()))
            self.variants[p.id] = vs
            for _, surname, _ in vs:
                self.by_surname.setdefault(surname, set()).add(p.id)
            for m in p.media:
                if m.file:
                    self.by_file.setdefault(Path(m.file.replace("\\", "/")).name.lower(), set()).add(p.id)
                if m.title:
                    self.titles.append((p.id, norm(m.title)))

    def _suffix_adjust(self, raw: set[str], pid: str) -> float:
        """Sr./Jr./II/III in the text: reward a match, penalize a conflict."""
        sfx = norm(self.tree.people[pid].suffix)
        marks = raw & {"sr", "jr", "ii", "iii", "iv"}
        if not marks:
            return 0.0
        if sfx and sfx in marks:
            return 5.0
        return -10.0 if sfx or marks & {"jr", "ii", "iii", "iv"} else 0.0

    def _name_score(self, text_tokens: list[str], pid: str) -> float:
        """Score 0-100 for how well the text names this person.

        Surname and first given name (or its initial) must both appear.
        Missing middle names cost little; unexplained extra words cost a bit;
        a birth surname next to a married surname adds a little.
        """
        tset = set(text_tokens)
        initials = {t for t in tset if len(t) == 1}
        best = 0.0
        for given, surname, others in self.variants.get(pid, []):
            if surname not in tset:
                continue
            if not given:
                best = max(best, 55.0)
                continue
            first = given[0]
            if first in tset:
                score = 86.0
            elif first[0] in initials:
                score = 80.0
            else:
                continue
            middle = given[1:]
            if middle:
                hit = sum(1 for g in middle if g in tset or g[0] in initials)
                score += 6 * hit / len(middle)
            else:
                score += 6
            if others & tset:
                score += 5
            explained = set(given) | {surname} | others | NOISE
            extra = [t for t in tset if t not in explained and len(t) > 1]
            score -= 2 * min(len(extra), 4)
            best = max(best, score)
        return best

    def _year_adjust(self, text: str, pid: str) -> tuple[float, str]:
        years = [int(y) for y in YEAR_RE.findall(text)]
        if not years:
            return 0.0, ""
        p = self.tree.people[pid]
        b, d = p.birth_year, p.death_year
        if b is None and d is None:
            return 0.0, ""
        lo, hi = (b or (d - 100)), (d + 10 if d else b + 105)
        if any(lo <= y <= hi for y in years):
            return 6.0, "year fits lifespan"
        return -12.0, "year outside lifespan"

    def candidates(self, path: Path, meta_text: str) -> list[Candidate]:
        cands: dict[str, Candidate] = {}

        def add(pid: str, score: float, signal: str):
            c = cands.setdefault(pid, Candidate(pid, 0.0))
            if score > c.score:
                c.score = score
            c.signals.append(signal)

        for pid in self.by_file.get(path.name.lower(), ()):
            add(pid, 100, "linked in GEDCOM")

        for label, text in (("metadata", meta_text), ("file name", path.stem)):
            if not text:
                continue
            tt = tokens(text)
            pool: set[str] = set()
            for t in tt:
                pool |= self.by_surname.get(t, set())
            for pid in pool:
                s = self._name_score(tt, pid)
                if s:
                    s += self._suffix_adjust(set(norm(text).split()), pid)
                    adj, why = self._year_adjust(text, pid)
                    bonus = 4 if label == "metadata" else 0
                    add(pid, min(99, s + adj + bonus), label + (f", {why}" if why else ""))

        stem = norm(path.stem)
        if self.titles and len(stem) > 5:
            for pid, title in self.titles:
                r = fuzz.token_set_ratio(stem, title)
                if r >= 88:
                    add(pid, min(97, r), "GEDCOM media title")

        return sorted(cands.values(), key=lambda c: -c.score)


def lifespan_text(tree: Tree, pid: str) -> str:
    p = tree.people[pid]
    b, d = p.birth_year, p.death_year
    if b or d:
        return f"{b or '?'}-{d or '?'}"
    return ""


def scan(tree: Tree, media_dir: Path, auto_threshold: int = 90, review_threshold: int = 70,
         margin: int = 6) -> list[MatchRow]:
    matcher = Matcher(tree)
    rows: list[MatchRow] = []
    seen_hash: dict[str, str] = {}
    copy_mark = re.compile(r"(\(\d+\)|\bcopy\b|[-_ ]\d$)", re.I)
    files = sorted((p for p in media_dir.rglob("*") if p.suffix.lower() in IMAGE_EXT and p.is_file()),
                   key=lambda p: (bool(copy_mark.search(p.stem)), p.as_posix().lower()))
    for path in files:
        rel = path.relative_to(media_dir).as_posix()
        digest = sha1(path)
        if THUMB_RE.search(path.stem):
            rows.append(MatchRow(rel, digest[:12], "THUMBNAIL", use="no"))
            continue
        if digest in seen_hash:
            rows.append(MatchRow(rel, digest[:12], "DUPLICATE", use="no",
                                 signals=f"same file as {seen_hash[digest]}"))
            continue
        seen_hash[digest] = rel
        w, h = image_size(path)
        meta = read_metadata_text(path)
        cands = matcher.candidates(path, meta)
        kind = guess_kind(f"{path.stem} {meta}")
        row = MatchRow(rel, digest[:12], "UNMATCHED", kind=kind, metadata_text=meta[:300])
        if min(w, h) and min(w, h) < 150:
            row.signals = "very small image; may be a thumbnail"
        if cands:
            top = cands[0]
            row.person_id = top.pid
            row.person_name = tree.people[top.pid].name
            row.lifespan = lifespan_text(tree, top.pid)
            row.score = int(round(top.score))
            row.signals = "; ".join(dict.fromkeys(top.signals + ([row.signals] if row.signals else [])))
            close = [c for c in cands[1:] if top.score - c.score < margin]
            row.alternatives = " | ".join(
                f"{c.pid} {tree.people[c.pid].name} ({lifespan_text(tree, c.pid)}) {int(c.score)}"
                for c in cands[1:4])
            if top.score >= auto_threshold and not close:
                row.status = "AUTO"
            elif top.score >= review_threshold:
                row.status = "REVIEW"
                if close:
                    row.signals += "; similar names in tree"
            else:
                row.status = "UNMATCHED"
        if kind in RESTRICTED_KINDS:
            row.use = "no"
            row.signals = (row.signals + "; record image: transcribe it instead of printing it").strip("; ")
        rows.append(row)
    return rows


def write_csv(rows: list[MatchRow], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=MatchRow.FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: getattr(r, k) for k in MatchRow.FIELDS})


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def accepted(rows: list[dict], tree: Tree) -> dict[str, list[dict]]:
    """Return {person_id: [row, ...]} for rows the book should use.

    A row is used when ``use`` is not "no" and either the user filled in
    ``override_person_id``, wrote yes/y/x in ``confirm``, or the status is AUTO
    and ``confirm`` is not "no".
    """
    out: dict[str, list[dict]] = {}
    for r in rows:
        if (r.get("use") or "yes").strip().lower() in ("no", "n", "0"):
            continue
        confirm = (r.get("confirm") or "").strip().lower()
        pid = (r.get("override_person_id") or "").strip()
        if pid and not pid.startswith("@"):
            pid = f"@{pid.strip('@')}@"
        if not pid:
            if confirm in ("no", "n"):
                continue
            if r.get("status") == "AUTO" or confirm in ("yes", "y", "x", "ok"):
                pid = (r.get("person_id") or "").strip()
        if pid and pid in tree.people:
            out.setdefault(pid, []).append(r)
    return out
