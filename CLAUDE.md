# Instructions for AI assistants working in this repository

This file tells Claude (Claude Code or Cowork) and other coding assistants how to help a user build a family history book with gedbook. Users can open this folder in their assistant and say "help me build my family book."

## What the user is doing

The user has a GEDCOM file exported from their family tree and a folder of photos and documents. gedbook turns those into a draft book (`book.pdf`) plus a photo match sheet (`media_matches.csv`). The draft always needs human review. Your job is to run the tool, explain what it produced, help the user review matches, and help them write stories from the facts in their tree.

## Workflow

Walk the user through one step at a time and wait for confirmation before the next.

1. Confirm Python 3.11 or later and install with `pip install -e .` (see README for WeasyPrint system libraries on Windows and macOS).
2. Run `gedbook stats TREE.ged` and summarize the tree in plain language.
3. Find the root person with `gedbook find TREE.ged "Name"`. Ask the user to confirm the ID.
4. Run `gedbook stats TREE.ged --root ID` with branch generation 1, 2, and 3, show the page estimates, and let the user choose.
5. Run `gedbook match TREE.ged PHOTOS -o media_matches.csv`. Go through the REVIEW rows with the user in small batches. Write their answers into the `confirm` and `override_person_id` columns. Never mark a row confirmed on your own judgment alone; when two people share a name, show both candidates with their dates.
6. Build: `gedbook build TREE.ged --root ID --media PHOTOS --matches media_matches.csv`. Open the PDF and report pages that look wrong.
7. Help write stories into `stories/<ID>.md` (see `stories/README.md`).
8. When the user is ready, build with `--final`.

## Rules for writing stories and captions

- Use only facts present in the GEDCOM, the user's documents, or what the user tells you. Never invent names, dates, places, occupations, or events.
- Label each claim by evidence strength: documented (a record names it), family report (a relative says so), inferred (reasoned from several records), or under review. Records support or indicate a conclusion; never write that a record proves one.
- When two records disagree, say so in the text and say which reading is better supported and why.
- Historical context is welcome: what was happening in the town, county, or country at the time. Keep it general and accurate, and do not place the person in an event unless a record does.
- Treat enslavement, adoption, illegitimacy, institutionalization, race and passing, and violent deaths as evidence to report plainly. The user decides how they appear in the book.
- For people who may be living, follow the `living` setting and ask before adding any detail about them.

## Record images and copyright

Census pages and other record images downloaded from subscription sites (for example Ancestry) may carry reuse restrictions. gedbook marks images whose names contain "census" as `use = no`. Transcribe the facts into the GEDCOM or a story instead of printing the image. Family photographs the user owns, and images from public archives with clear terms, can be printed.

## Research help

If the user asks for help extending the tree, follow `docs/research-protocol.md`. Do not edit shared online trees (FamilySearch Family Tree, public Ancestry trees) on the user's behalf; propose changes in chat.

## Privacy

Never commit or upload the user's GEDCOM, photos, DNA files, interview recordings, `.env`, or `gedbook.toml`. The `.gitignore` covers the usual names; check before any `git add`.
