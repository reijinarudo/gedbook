from pathlib import Path

from gedbook.dates import GDate
from gedbook.gedcom import load
from gedbook.media import accepted, read_csv, scan, write_csv
from gedbook.privacy import Privacy
from gedbook.selection import build_plan

ROOT = Path(__file__).resolve().parents[1]
GED = ROOT / "examples" / "sample_family.ged"
MEDIA = ROOT / "examples" / "media"


def test_dates():
    assert GDate.parse("12 MAR 1890").display() == "12 March 1890"
    assert GDate.parse("ABT 1860").display() == "about 1860"
    assert GDate.parse("BET 1896 AND 1899").display() == "between 1896 and 1899"
    assert GDate.parse("12 MAR 1890").display(year_only=True) == "1890"


def test_parse_and_relationships():
    tree = load(GED)
    assert len(tree.people) == 23
    assert tree.people["@I9@"].suffix == "Sr."
    assert set(tree.parents("@I1@")) == {"@I3@", "@I4@"}
    assert sum(1 for e in tree.people["@I9@"].events if e.is_census) == 3


def test_plan_branches():
    tree = load(GED)
    plan = build_plan(tree, "@I1@", branch_generation=2)
    assert [b.title for b in plan.branches] == ["Hollis", "Pruitt", "Merriweather", "Calloway"]
    assert plan.stats["not_connected"] == 2
    assert "@I14@" in plan.brick_walls or "@I15@" in plan.brick_walls


def test_living_rules():
    tree = load(GED)
    pv = Privacy(tree, "year-only", current_year=2026)
    assert pv.is_living("@I1@")
    assert not pv.is_living("@I5@")
    birth = tree.people["@I1@"].birth
    assert pv.date("@I1@", birth) == "1988"
    hidden = Privacy(tree, "hidden", current_year=2026)
    assert hidden.name("@I1@") == "Living Hollis"


def test_media_matching(tmp_path):
    tree = load(GED)
    rows = {r.file: r for r in scan(tree, MEDIA)}
    assert rows["walter_hollis_1952.jpg"].status == "AUTO"
    assert rows["walter_hollis_1952 (2).jpg"].status == "DUPLICATE"
    assert rows["thumb_walter_hollis_1952.jpg"].status == "THUMBNAIL"
    assert rows["IMG_0423.jpg"].person_id == "@I7@"          # name found in EXIF caption
    assert rows["samuel_hollis_1918.jpg"].person_id == "@I9@"  # year rules out Jr.
    assert rows["samuel_hollis.jpg"].status == "REVIEW"        # Sr. or Jr.?
    assert rows["1930_census_samuel_hollis.jpg"].use == "no"   # record image
    out = tmp_path / "m.csv"
    write_csv(list(rows.values()), out)
    use = accepted(read_csv(out), tree)
    assert "@I5@" in use and "@I18@" not in use
