"""Historical-context prompts for the writer.

These appear only in draft builds, in a shaded box labeled as prompts.
They point the writer toward the history a person lived through and make
no claim about the person's part in it. Edit or extend ERAS for the
places your family lived. Each entry: (start, end, title, places, prompt).
An empty places tuple means the prompt applies anywhere.
"""
from __future__ import annotations

SOUTH = ("alabama", "arkansas", "florida", "georgia", "kentucky", "louisiana", "mississippi",
         "north carolina", "south carolina", "tennessee", "texas", "virginia", ", al", ", ar",
         ", fl", ", ga", ", ky", ", la", ", ms", ", nc", ", sc", ", tn", ", tx", ", va")

ERAS = [
    (1775, 1783, "American Revolutionary War", (), "Where did the household live during the war, and which side controlled the area?"),
    (1820, 1860, "Expansion of slavery into the Deep South", SOUTH,
     "If the person was enslaved, look for them in the enslaver's probate, deed, and tax records, and for the domestic slave trade route that brought the family west."),
    (1861, 1865, "U.S. Civil War", (), "Check Union and Confederate service records, the U.S. Colored Troops, and pension files."),
    (1865, 1877, "Reconstruction", (), "Look for Freedmen's Bureau records, Freedman's Bank records, 1867 voter registrations, and the first marriage records for formerly enslaved couples."),
    (1877, 1965, "Jim Crow segregation", SOUTH, "How did segregation laws shape schooling, work, voting, and travel in this town?"),
    (1880, 1924, "Mass immigration to the United States", (), "Check passenger lists, naturalization papers, and the immigration columns of the 1900 to 1930 censuses."),
    (1910, 1970, "The Great Migration", SOUTH, "Did the family leave the South? Compare census residences across decades to trace the move."),
    (1917, 1918, "World War I (U.S. involvement)", (), "Men born 1872 to 1900 registered for the WWI draft; the draft card records height, build, and employer."),
    (1918, 1919, "Influenza pandemic", (), "Check death records from late 1918 and early 1919 for the household."),
    (1929, 1939, "Great Depression", (), "Compare the 1930 and 1940 census entries for changes in work, income, and household size."),
    (1941, 1945, "World War II", (), "Check WWII draft registrations (1940 to 1947), enlistment records, and local newspapers."),
    (1954, 1968, "Civil rights movement", (), "Look for local newspapers, church histories, and oral histories from relatives who remember these years."),
]


def prompts_for(birth_year: int | None, death_year: int | None, places: list[str]) -> list[tuple[str, str]]:
    if birth_year is None and death_year is None:
        return []
    start = birth_year if birth_year is not None else death_year - 70
    end = death_year if death_year is not None else start + 80
    where = " ".join(places).lower()
    out = []
    for lo, hi, title, region, prompt in ERAS:
        if start <= hi and end >= lo and (not region or any(r in where for r in region)):
            out.append((f"{title} ({lo}–{hi})", prompt))
    return out
