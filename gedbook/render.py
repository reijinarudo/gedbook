"""Turn the plan, the tree, and the approved photos into HTML and PDF."""
from __future__ import annotations

import datetime as _dt
import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageOps

from . import __version__
from .eras import prompts_for
from .gedcom import Event, Tree
from .privacy import Privacy
from .selection import Plan, RegisterEntry

TEMPLATES = Path(__file__).parent / "templates"
CORE_TAGS = ("BIRT", "CHR", "BAPM", "DEAT", "BURI", "CREM")


def anchor(pid: str) -> str:
    return "p-" + re.sub(r"[^A-Za-z0-9_-]", "", pid)


# ---- tiny Markdown subset for user-written stories ----------------------

def md_to_html(text: str) -> str:
    blocks = re.split(r"\n\s*\n", text.strip())
    out = []
    for b in blocks:
        b = html.escape(b.strip())
        b = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", b)
        b = re.sub(r"\*(.+?)\*", r"<em>\1</em>", b)
        if b.startswith("### "):
            out.append(f"<h4>{b[4:]}</h4>")
        elif b.startswith("## "):
            out.append(f"<h3>{b[3:]}</h3>")
        elif b.startswith("&gt; "):
            out.append(f"<blockquote>{b[5:]}</blockquote>")
        elif all(line.startswith("- ") for line in b.splitlines()):
            items = "".join(f"<li>{line[2:]}</li>" for line in b.splitlines())
            out.append(f"<ul>{items}</ul>")
        else:
            out.append(f"<p>{b.replace(chr(10), ' ')}</p>")
    return "\n".join(out)


def load_story(stories_dir: Path | None, key: str) -> str:
    if not stories_dir:
        return ""
    clean = key.strip("@")
    for name in (f"{clean}.md", f"{clean}.txt"):
        f = stories_dir / name
        if f.exists():
            return md_to_html(f.read_text(encoding="utf-8"))
    return ""


# ---- images ---------------------------------------------------------------

def prepare_image(src: Path, cache: Path, grayscale: bool, max_px: int = 1800) -> str | None:
    """Copy an image into the build folder as a print-ready JPEG."""
    cache.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9_-]", "_", src.stem)[:60]
    out = cache / f"{key}{'_g' if grayscale else ''}.jpg"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out.relative_to(cache.parent).as_posix()
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("L" if grayscale else "RGB")
            im.thumbnail((max_px, max_px))
            im.save(out, "JPEG", quality=88)
    except Exception as exc:  # unreadable or unsupported file
        print(f"  skipped image {src.name}: {exc}")
        return None
    return out.relative_to(cache.parent).as_posix()


# ---- view models ----------------------------------------------------------

@dataclass
class PersonView:
    id: str
    anchor: str
    name: str
    lifespan: str
    restricted: bool
    details: bool
    number: int | None = None
    photo: dict | None = None
    gallery: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    parents: list[dict] = field(default_factory=list)
    unions: list[dict] = field(default_factory=list)
    census: list[dict] = field(default_factory=list)
    other: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    story: str = ""
    prompts: list[tuple[str, str]] = field(default_factory=list)


class Builder:
    def __init__(self, tree: Tree, plan: Plan, privacy: Privacy, photos: dict[str, list[dict]],
                 media_dir: Path | None, out_dir: Path, stories_dir: Path | None,
                 draft: bool, grayscale: bool, title: str, subtitle: str, author: str):
        self.tree, self.plan, self.pv = tree, plan, privacy
        self.photos, self.media_dir = photos, media_dir
        self.out_dir, self.stories_dir = out_dir, stories_dir
        self.draft, self.grayscale = draft, grayscale
        self.title, self.subtitle, self.author = title, subtitle, author
        self.homes: dict[str, str] = {}   # pid -> html anchor of its main entry
        self.printed: set[str] = set()
        self.emitted: set[str] = set()
        self._refs: list[dict] = []

    # -- helpers --
    def ref(self, pid: str | None) -> dict | None:
        if not pid or pid not in self.tree.people:
            return None
        r = {"id": pid, "name": self.pv.name(pid), "lifespan": self.pv.lifespan(pid),
             "href": "#" + anchor(pid), "linked": False}
        self._refs.append(r)
        return r

    def _fact(self, pid: str, ev: Event) -> dict:
        detail = ev.value if ev.tag not in ("BIRT", "DEAT") else ""
        if ev.tag == "DEAT" and ev.note:
            detail = ev.note
        return {"label": ev.label, "date": self.pv.date(pid, ev),
                "place": self.pv.place(pid, ev), "detail": detail}

    def _images_for(self, pid: str) -> tuple[dict | None, list[dict]]:
        if not self.media_dir or not self.pv.photos_allowed(pid):
            return None, []
        rows = self.photos.get(pid, [])
        prepared = []
        for r in rows:
            rel = prepare_image(self.media_dir / r["file"], self.out_dir / "_images", self.grayscale)
            if rel:
                prepared.append({"src": rel, "kind": r.get("kind") or "portrait",
                                 "caption": r.get("caption") or "",
                                 "review": r.get("status") != "AUTO" and not (r.get("confirm") or r.get("override_person_id"))})
        portrait = next((p for p in prepared if p["kind"] == "portrait"), None)
        gallery = [p for p in prepared if p is not portrait]
        return portrait, gallery

    def person(self, pid: str, number: int | None = None, full: bool = True) -> PersonView:
        p = self.tree.people[pid]
        details = self.pv.show_details(pid)
        v = PersonView(pid, anchor(pid), self.pv.name(pid), self.pv.lifespan(pid),
                       self.pv.restricted(pid), details, number)
        f, m = self.tree.father_mother(pid)
        v.parents = [x for x in (self.ref(f), self.ref(m)) if x]
        for fam in self.tree.spouse_families(pid):
            sp = self.tree.spouse_in(fam, pid)
            marr = fam.marriage
            kids = [self.ref(c) for c in fam.children if c in self.tree.people]
            union = {"spouse": self.ref(sp), "children": kids, "date": "", "place": ""}
            if marr and details and (not sp or self.pv.show_details(sp)):
                union["date"] = self.pv.date(pid, marr) if not sp else (
                    self.pv.date(sp, marr) if self.pv.restricted(sp) else self.pv.date(pid, marr))
                union["place"] = self.pv.place(pid, marr)
            v.unions.append(union)
        if not details:
            return v
        for tag in CORE_TAGS:
            ev = p.event(tag)
            if ev:
                v.facts.append(self._fact(pid, ev))
        if not full:
            return v
        srcs: dict[str, None] = {}
        for ev in p.events:
            for c in ev.citations:
                if c.title:
                    srcs[c.title] = None
            if ev.tag in CORE_TAGS:
                continue
            if ev.is_census:
                v.census.append({"year": ev.date.year or "", "place": self.pv.place(pid, ev),
                                 "age": ev.age, "detail": ev.note or ev.value,
                                 "citation": "; ".join(c.page for c in ev.citations if c.page)[:160]})
            else:
                v.other.append(self._fact(pid, ev))
        for fam in self.tree.spouse_families(pid):
            for ev in fam.events:
                for c in ev.citations:
                    if c.title:
                        srcs[c.title] = None
        v.sources = list(srcs)
        v.notes = p.notes if not v.restricted else []
        v.photo, v.gallery = self._images_for(pid)
        v.story = load_story(self.stories_dir, pid)
        if self.draft and not v.restricted:
            places = [e.place for e in p.events if e.place]
            v.prompts = prompts_for(p.birth_year, p.death_year, places)
        return v

    def pedigree(self, pid: str, gens: int = 4) -> list[list[dict]]:
        """Rows for a left-to-right pedigree table (rowspan layout)."""
        nums = {1: pid}
        for n in range(1, 2 ** (gens - 1)):
            if n in nums:
                f, m = self.tree.father_mother(nums[n])
                if f:
                    nums[2 * n] = f
                if m:
                    nums[2 * n + 1] = m
        rows_n = 2 ** (gens - 1)
        rows: list[list[dict]] = []
        for r in range(rows_n):
            cells = []
            for g in range(gens):
                span = 2 ** (gens - 1 - g)
                if r % span == 0:
                    n = 2 ** g + r // span
                    cells.append({"span": span, "gen": g, "person": self.ref(nums.get(n))})
            rows.append(cells)
        return rows

    def _assign_register_homes(self, entry: RegisterEntry) -> None:
        for pid in [entry.pid] + entry.spouses:
            self.homes.setdefault(pid, anchor(pid))
        for c in entry.children:
            self._assign_register_homes(c)

    def _claim(self, pid: str) -> bool:
        """True the first time a person's anchor is written into the book."""
        if pid in self.emitted:
            return False
        self.emitted.add(pid)
        self.printed.add(pid)
        return True

    def register(self, entry: RegisterEntry, label: str = "1") -> dict:
        pid = entry.pid
        node = {"person": self.ref(pid), "label": label, "home": self._claim(pid),
                "facts": "", "spouses": [], "children": []}
        if self.pv.show_details(pid):
            p = self.tree.people[pid]
            bits = []
            for prefix, ev in (("b.", p.birth), ("d.", p.death)):
                if ev:
                    when = ", ".join(x for x in (self.pv.date(pid, ev), self.pv.place(pid, ev)) if x)
                    if when:
                        bits.append(f"{prefix} {when}")
            node["facts"] = "; ".join(bits)
        for sp in entry.spouses:
            r = dict(self.ref(sp), home=self._claim(sp))
            node["spouses"].append(r)
        for i, c in enumerate(entry.children, 1):
            node["children"].append(self.register(c, f"{label}.{i}"))
        return node

    # -- whole book --
    def context(self) -> dict:
        plan, tree = self.plan, self.tree
        # Full-page homes are assigned first so register entries can link to them.
        order: list[tuple[str, int, str]] = []
        for n, pid in plan.root_line:
            order.append(("present", n, pid))
        for b in plan.branches:
            for n, pid in b.ancestors:
                order.append((b.anchor, n, pid))
        for _, _, pid in order:
            self.homes.setdefault(pid, anchor(pid))
        for b in plan.branches:
            if b.register:
                self._assign_register_homes(b.register)

        present = []
        done: set[str] = set()
        for n, pid in plan.root_line:
            if pid in done:
                continue
            done.add(pid)
            self._claim(pid)
            present.append(self.person(pid, n))

        branches = []
        for b in plan.branches:
            pages = []
            for n, pid in b.ancestors:
                if pid in done:
                    continue  # pedigree collapse: print once, link elsewhere
                done.add(pid)
                self._claim(pid)
                pages.append(self.person(pid, n))
            gen_groups: dict[int, list[PersonView]] = {}
            for pv in pages:
                gen_groups.setdefault((pv.number or 1).bit_length() - 1, []).append(pv)
            branches.append({
                "title": b.title, "anchor": self.ref(b.anchor), "number": b.number,
                "intro": load_story(self.stories_dir, f"branch-{b.anchor}"),
                "chart": self.pedigree(b.anchor),
                "generations": sorted(gen_groups.items()),
                "register": self.register(b.register) if b.register and (b.register.children or b.register.spouses) else None,
            })

        index = sorted(
            ({"name": self.pv.name(pid), "lifespan": self.pv.lifespan(pid), "href": "#" + self.homes[pid],
              "sort": tree.people[pid].sort_key}
             for pid in self.emitted),
            key=lambda x: x["sort"])
        letters: dict[str, list[dict]] = {}
        for item in index:
            letter = item["sort"][0][:1].upper()
            letters.setdefault(letter if letter.isalpha() else "#", []).append(item)

        walls = [self.ref(p) for p in plan.brick_walls if p != plan.root]
        master_chart = self.pedigree(plan.root)
        root_ref = self.ref(plan.root)
        for r in self._refs:  # link only to people who have an entry in the book
            r["linked"] = r["id"] in self.emitted
        frontier = plan.disconnected.most_common(40)
        return {
            "title": self.title, "subtitle": self.subtitle, "author": self.author,
            "date": _dt.date.today().strftime("%B %Y"), "draft": self.draft,
            "version": __version__, "root": root_ref,
            "master_chart": master_chart,
            "introduction": load_story(self.stories_dir, "introduction"),
            "present": present, "branches": branches, "letters": sorted(letters.items()),
            "walls": walls, "frontier": frontier, "stats": plan.stats,
            "living_mode": self.pv.mode, "living_threshold": self.pv.threshold,
        }


def font_faces(fonts_dir: Path) -> str:
    """@font-face rules for any .ttf/.otf files placed in fonts/."""
    rules = []
    if not fonts_dir.is_dir():
        return ""
    for f in sorted(fonts_dir.iterdir()):
        if f.suffix.lower() not in (".ttf", ".otf"):
            continue
        stem = f.stem
        family = re.split(r"[-_]", stem)[0]
        family = re.sub(r"(Variable|VF)$", "", family)
        low = stem.lower()
        weight = 700 if "bold" in low else 600 if "semibold" in low else 400
        style = "italic" if "italic" in low else "normal"
        rules.append(f"@font-face {{ font-family: '{family}'; src: url('{f.resolve().as_uri()}'); "
                     f"font-weight: {weight}; font-style: {style}; }}")
    return "\n".join(rules)


def render(ctx: dict, out_dir: Path, fonts_dir: Path, pdf: bool = True) -> tuple[Path, Path | None]:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    css = (TEMPLATES / "book.css").read_text(encoding="utf-8")
    ctx = dict(ctx, css=font_faces(fonts_dir) + "\n" + css)
    html_text = env.get_template("book.html.j2").render(**ctx)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "book.html"
    html_path.write_text(html_text, encoding="utf-8")
    pdf_path = None
    if pdf:
        from weasyprint import HTML  # imported late: heavy, and HTML-only runs skip it
        pdf_path = out_dir / "book.pdf"
        HTML(filename=str(html_path), base_url=str(out_dir)).write_pdf(str(pdf_path))
    return html_path, pdf_path
