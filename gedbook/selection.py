"""Decide who appears in the book, in which branch, and at what depth.

Book shape (mirrors a branch-organized family history):
  * The root person (usually the compiler) and the generations between the
    root and the branch anchors form "The Present Generations".
  * Each ancestor at --branch-generation becomes the anchor of one branch.
    Generation 1 = parents (2 branches), 2 = grandparents (4 branches),
    3 = great-grandparents (8 branches).
  * Inside a branch: the anchor's direct ancestors get full pages (Tier 1);
    the anchor's descendants and their spouses get compact register
    entries (Tier 2) down to --descendant-depth generations.
  * Everyone else in the tree is counted, and people with no blood or
    marriage connection to the root are summarized as a research frontier.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field

from .gedcom import Tree


def ahnentafel(tree: Tree, root: str, max_gen: int = 30) -> dict[int, str]:
    """Map Ahnentafel numbers (1 = root, 2 = father, 3 = mother, ...) to IDs."""
    out = {1: root}
    frontier = [(1, root, 0)]
    while frontier:
        n, pid, g = frontier.pop()
        if g >= max_gen:
            continue
        f, m = tree.father_mother(pid)
        if f and f in tree.people:
            out[2 * n] = f
            frontier.append((2 * n, f, g + 1))
        if m and m in tree.people:
            out[2 * n + 1] = m
            frontier.append((2 * n + 1, m, g + 1))
    return out


def generation_of(n: int) -> int:
    return n.bit_length() - 1


def connected(tree: Tree, root: str) -> set[str]:
    seen = {root}
    q = deque([root])
    while q:
        pid = q.popleft()
        nbrs = list(tree.parents(pid)) + tree.children(pid)
        for fam in tree.spouse_families(pid):
            sp = tree.spouse_in(fam, pid)
            if sp:
                nbrs.append(sp)
        for x in nbrs:
            if x in tree.people and x not in seen:
                seen.add(x)
                q.append(x)
    return seen


@dataclass
class RegisterEntry:
    pid: str
    depth: int
    spouses: list[str] = field(default_factory=list)
    children: list["RegisterEntry"] = field(default_factory=list)


@dataclass
class Branch:
    anchor: str
    number: int                      # Ahnentafel number of the anchor
    title: str
    ancestors: list[tuple[int, str]]  # (number relative to anchor, pid), anchor first
    register: RegisterEntry | None = None


@dataclass
class Plan:
    root: str
    root_line: list[tuple[int, str]]     # Ahnentafel numbers below the anchors
    branches: list[Branch]
    tier1: set[str]
    tier2: set[str]
    brick_walls: list[str]
    disconnected: Counter
    stats: dict


def _register(tree: Tree, pid: str, depth: int, max_depth: int, seen: set[str]) -> RegisterEntry:
    entry = RegisterEntry(pid, depth)
    seen.add(pid)
    for fam in tree.spouse_families(pid):
        sp = tree.spouse_in(fam, pid)
        if sp and sp in tree.people:
            entry.spouses.append(sp)
        if depth < max_depth:
            for c in fam.children:
                if c in tree.people and c not in seen:
                    entry.children.append(_register(tree, c, depth + 1, max_depth, seen))
    return entry


def _walk(entry: RegisterEntry):
    yield entry
    for c in entry.children:
        yield from _walk(c)


def build_plan(tree: Tree, root: str, branch_generation: int = 2,
               descendant_depth: int = 4, max_ancestor_gen: int = 12) -> Plan:
    if root not in tree.people:
        raise KeyError(f"Root person {root} is not in the GEDCOM. Use 'gedbook find' to look up IDs.")
    ahn = ahnentafel(tree, root, max_ancestor_gen)
    tier1 = set(ahn.values())

    root_line = sorted((n, p) for n, p in ahn.items() if generation_of(n) < branch_generation)
    anchors = sorted((n, p) for n, p in ahn.items() if generation_of(n) == branch_generation)
    if branch_generation == 0:
        anchors = [(1, root)]
        root_line = []

    branches: list[Branch] = []
    tier2: set[str] = set()
    for n, pid in anchors:
        sub = ahnentafel(tree, pid, max_ancestor_gen - branch_generation)
        title = tree.people[pid].surname or tree.people[pid].name
        reg = _register(tree, pid, 0, descendant_depth, set())
        for e in _walk(reg):
            if e.pid not in tier1:
                tier2.add(e.pid)
            for sp in e.spouses:
                if sp not in tier1:
                    tier2.add(sp)
        branches.append(Branch(pid, n, title, sorted(sub.items()), reg))

    # Two branches can share a surname; add the anchor's given name to tell them apart.
    counts = Counter(b.title for b in branches)
    for b in branches:
        if counts[b.title] > 1:
            b.title = f"{b.title} ({tree.people[b.anchor].given.split()[0] if tree.people[b.anchor].given else b.anchor})"

    brick_walls = [p for n, p in sorted(ahn.items()) if not tree.parents(p)]
    conn = connected(tree, root)
    disconnected = Counter(tree.people[p].surname or "(no surname)"
                           for p in tree.people if p not in conn)
    stats = {
        "individuals": len(tree.people),
        "families": len(tree.families),
        "sources": len(tree.sources),
        "media_refs": sum(len(p.media) for p in tree.people.values()),
        "people_with_media": sum(1 for p in tree.people.values() if p.media),
        "connected": len(conn),
        "not_connected": len(tree.people) - len(conn),
        "direct_ancestors": len(ahn) - 1,
        "ancestor_generations": max(generation_of(n) for n in ahn),
        "branches": len(branches),
        "tier1_pages": len(tier1),
        "tier2_entries": len(tier2),
    }
    return Plan(root, root_line, branches, tier1, tier2, brick_walls, disconnected, stats)
