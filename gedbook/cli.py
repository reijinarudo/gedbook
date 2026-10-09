"""Command-line interface: gedbook stats | find | match | build."""
from __future__ import annotations

import argparse
import os
import sys
import tomllib
from collections import Counter
from pathlib import Path

from . import __version__
from .gedcom import load
from .media import accepted, read_csv, scan, write_csv
from .privacy import MODES, Privacy
from .render import Builder, render
from .selection import build_plan

ENV_PREFIX = "GEDBOOK_"
BOOL_SETTINGS = {"final", "color", "no_pdf"}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from .env into the environment (existing values win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str | None) -> dict:
    candidates = [Path(path)] if path else [Path("gedbook.toml")]
    for p in candidates:
        if p.exists():
            with open(p, "rb") as fh:
                return tomllib.load(fh)
        if path:
            sys.exit(f"Config file not found: {p}")
    return {}


def setting(args: argparse.Namespace, cfg: dict, name: str, default=None):
    """Command line beats config file beats environment beats default."""
    v = getattr(args, name, None)
    if v not in (None, ""):
        return v
    if name in cfg:
        return cfg[name]
    env = os.environ.get(ENV_PREFIX + name.upper())
    if env not in (None, ""):
        if name in BOOL_SETTINGS:
            return env.strip().lower() in ("true", "yes", "1", "on")
        return env
    return default


def norm_id(pid: str) -> str:
    pid = pid.strip()
    return pid if pid.startswith("@") else f"@{pid}@"


def resolve_root(tree, root: str | None, root_name: str | None) -> str:
    if root:
        return norm_id(root)
    if root_name:
        hits = tree.find(root_name)
        if len(hits) == 1:
            return hits[0].id
        if not hits:
            sys.exit(f'No one in the tree matches "{root_name}".')
        listing = "\n".join(f"  {h.id}  {h.name}  ({h.birth_year or '?'}-{h.death_year or '?'})" for h in hits[:20])
        sys.exit(f'"{root_name}" matches {len(hits)} people. Pass --root with one of these IDs:\n{listing}')
    sys.exit("Name the book's root person with --root ID or --root-name \"Full Name\". "
             "Run 'gedbook find TREE.ged NAME' to look up an ID.")


# ---- commands --------------------------------------------------------------

def cmd_find(args, cfg) -> int:
    tree = load(setting(args, cfg, "gedcom"))
    hits = sorted(tree.find(args.name), key=lambda p: p.sort_key)
    for p in hits[:200]:
        print(f"{p.id:<16} {p.name:<40} {p.birth_year or '?'}-{p.death_year or '?'}")
    print(f"{len(hits)} match(es)")
    return 0


def cmd_stats(args, cfg) -> int:
    tree = load(setting(args, cfg, "gedcom"))
    print(f"People: {len(tree.people)}   Families: {len(tree.families)}   Sources: {len(tree.sources)}")
    print(f"Media references: {sum(len(p.media) for p in tree.people.values())} "
          f"(people with media: {sum(1 for p in tree.people.values() if p.media)})")
    census = sum(1 for p in tree.people.values() for e in p.events if e.is_census)
    print(f"Census or residence events: {census}")
    root = setting(args, cfg, "root")
    root_name = setting(args, cfg, "root_name")
    if root or root_name:
        rid = resolve_root(tree, root, root_name)
        bg = int(setting(args, cfg, "branch_generation", 2))
        plan = build_plan(tree, rid, bg, int(setting(args, cfg, "descendant_depth", 4)))
        s = plan.stats
        print(f"\nRoot: {tree.people[rid].name} ({rid})")
        print(f"Connected by blood or marriage: {s['connected']}   Not connected: {s['not_connected']}")
        print(f"Direct ancestors: {s['direct_ancestors']} across {s['ancestor_generations']} generations")
        print(f"Branches at generation {bg}: " + ", ".join(b.title for b in plan.branches))
        print(f"Full entries: {s['tier1_pages']}   Register entries: {s['tier2_entries']}")
        print(f"Rough page estimate: {s['tier1_pages'] + s['tier2_entries'] // 18 + 12 + len(plan.branches) * 2}")
        if plan.disconnected:
            top = ", ".join(f"{k} ({v})" for k, v in plan.disconnected.most_common(10))
            print(f"Largest unconnected surname pools: {top}")
    return 0


def cmd_match(args, cfg) -> int:
    tree = load(setting(args, cfg, "gedcom"))
    media = Path(setting(args, cfg, "media"))
    rows = scan(tree, media)
    out = Path(args.output or setting(args, cfg, "matches") or "media_matches.csv")
    write_csv(rows, out)
    counts = Counter(r.status for r in rows)
    print(f"Scanned {len(rows)} images in {media}")
    for k in ("AUTO", "REVIEW", "UNMATCHED", "DUPLICATE", "THUMBNAIL"):
        print(f"  {k:<10} {counts.get(k, 0)}")
    print(f"Wrote {out}. Open it in a spreadsheet, check the REVIEW rows, and fill in "
          f"'confirm' (yes/no) or 'override_person_id'. Then pass it to 'gedbook build --matches'.")
    return 0


def cmd_build(args, cfg) -> int:
    gedcom = setting(args, cfg, "gedcom")
    tree = load(gedcom)
    rid = resolve_root(tree, setting(args, cfg, "root"), setting(args, cfg, "root_name"))
    out = Path(setting(args, cfg, "out", "book_output"))
    out.mkdir(parents=True, exist_ok=True)
    plan = build_plan(tree, rid, int(setting(args, cfg, "branch_generation", 2)),
                      int(setting(args, cfg, "descendant_depth", 4)),
                      int(setting(args, cfg, "max_generations", 12)))
    privacy = Privacy(tree, setting(args, cfg, "living", "year-only"),
                      int(setting(args, cfg, "living_years", 100)))

    media_dir = setting(args, cfg, "media")
    media_dir = Path(media_dir) if media_dir else None
    photos: dict = {}
    if media_dir:
        matches = setting(args, cfg, "matches")
        if matches and Path(matches).exists():
            rows = read_csv(Path(matches))
            print(f"Using reviewed matches from {matches}")
        else:
            print("No reviewed match file given; matching images now (AUTO matches only).")
            raw = scan(tree, media_dir)
            csv_path = out / "media_matches.csv"
            write_csv(raw, csv_path)
            print(f"  wrote {csv_path} for review")
            rows = read_csv(csv_path)
        photos = accepted(rows, tree)

    stories = setting(args, cfg, "stories", "stories")
    stories_dir = Path(stories) if stories and Path(stories).is_dir() else None
    draft = not bool(setting(args, cfg, "final", False))
    builder = Builder(
        tree, plan, privacy, photos, media_dir, out, stories_dir, draft,
        grayscale=not bool(setting(args, cfg, "color", False)),
        title=setting(args, cfg, "title", f"The Family of {tree.people[rid].name}"),
        subtitle=setting(args, cfg, "subtitle", "A family history"),
        author=setting(args, cfg, "author", "The compiler"),
    )
    ctx = builder.context()
    fonts = Path(setting(args, cfg, "fonts", "fonts"))
    html_path, pdf_path = render(ctx, out, fonts, pdf=not bool(setting(args, cfg, "no_pdf", False)))
    print(f"Branches: {', '.join(b['title'] for b in ctx['branches'])}")
    print(f"Wrote {html_path}" + (f" and {pdf_path}" if pdf_path else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="gedbook", description="Draft a printable family history book from a GEDCOM file.")
    ap.add_argument("--version", action="version", version=f"gedbook {__version__}")
    ap.add_argument("--config", help="TOML settings file (default: gedbook.toml if present)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def tree_arg(p):
        p.add_argument("gedcom", nargs="?", help="path to the .ged file (or set gedcom in the config)")

    p = sub.add_parser("find", help="look up people and their IDs by name")
    tree_arg(p)
    p.add_argument("name")
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("stats", help="summarize the tree and estimate the book")
    tree_arg(p)
    p.add_argument("--root"); p.add_argument("--root-name", dest="root_name")
    p.add_argument("--branch-generation", dest="branch_generation", type=int)
    p.add_argument("--descendant-depth", dest="descendant_depth", type=int)
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("match", help="match a folder of images to people and write a review CSV")
    tree_arg(p)
    p.add_argument("media", nargs="?", help="folder of images (searched recursively)")
    p.add_argument("-o", "--output", help="CSV to write (default media_matches.csv)")
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("build", help="build book.html and book.pdf")
    tree_arg(p)
    p.add_argument("--root", help="ID of the person the book is built around, e.g. I1 or @I1@")
    p.add_argument("--root-name", dest="root_name", help="full name of the root person, if unique")
    p.add_argument("--media", help="folder of images")
    p.add_argument("--matches", help="reviewed media_matches.csv from 'gedbook match'")
    p.add_argument("--stories", help="folder of Markdown stories (default ./stories)")
    p.add_argument("--out", help="output folder (default ./book_output)")
    p.add_argument("--branch-generation", dest="branch_generation", type=int,
                   help="0 = one branch, 1 = parents, 2 = grandparents (default), 3 = great-grandparents")
    p.add_argument("--descendant-depth", dest="descendant_depth", type=int, help="generations of descendants per branch (default 4)")
    p.add_argument("--max-generations", dest="max_generations", type=int, help="ancestor generations to follow (default 12)")
    p.add_argument("--living", choices=MODES, help="how to show people who may be living (default year-only)")
    p.add_argument("--living-years", dest="living_years", type=int, help="birth within this many years counts as possibly living (default 100)")
    p.add_argument("--title"); p.add_argument("--subtitle"); p.add_argument("--author")
    p.add_argument("--fonts", help="folder of .ttf/.otf files to embed (default ./fonts)")
    p.add_argument("--final", action="store_true", default=None, help="hide writer's prompts and review flags")
    p.add_argument("--color", action="store_true", default=None, help="keep photos in color (default grayscale)")
    p.add_argument("--no-pdf", dest="no_pdf", action="store_true", default=None, help="write HTML only")
    p.set_defaults(fn=cmd_build)

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if not setting(args, cfg, "gedcom"):
        ap.error("give the GEDCOM path, or set gedcom in gedbook.toml or GEDBOOK_GEDCOM in .env")
    if args.cmd == "match" and not setting(args, cfg, "media"):
        ap.error("give the image folder, or set media in gedbook.toml or GEDBOOK_MEDIA in .env")
    return args.fn(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
