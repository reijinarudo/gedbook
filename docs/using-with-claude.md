# Using gedbook with Claude

You can run gedbook by hand from the command line. An AI assistant helps most in the parts that take judgment: reviewing photo matches, deciding how the book is organized, and turning dry facts into readable stories.

## Setup

1. Download or clone this repository.
2. Open the folder in Claude Code (terminal) or Claude Cowork (desktop app, "Add folder").
3. Put your GEDCOM file and photo folder somewhere the assistant can read, for example inside this folder in `my_tree/` and `photos/`. Both names are ignored by git.
4. Say: "Read CLAUDE.md and help me build my family book."

The assistant reads `CLAUDE.md`, which tells it the workflow, the evidence rules, and the privacy rules for this project. You do not need to explain them yourself.

## Prompts that work

- "Summarize my tree. How many direct ancestors do I have, and how far back does each line go?"
- "Show me the REVIEW rows in media_matches.csv ten at a time, with both candidates' dates, and record my answers."
- "Which direct ancestors have no photo yet?"
- "Draft a story for I9 using only the facts in the GEDCOM. Mark anything inferred."
- "What was happening in Lowndes County, Alabama, between 1900 and 1930 that would help me tell Samuel's story? Cite sources I can check."
- "Compare the 1910 and 1920 census entries for this family and list what changed."

## Checking the assistant's work

An assistant can misread a record, merge two people who share a name, or state a historical claim with more confidence than the sources allow. Before anything goes into the final book:

- Check every date and place in a story against the record it came from.
- Ask for sources on historical context and open them yourself.
- Keep the evidence labels (documented, family report, inferred) in the text, or in your notes, until you have checked each claim.

## Teaching the assistant your research habits

If you search record sites with an assistant that can drive a browser, give it `docs/research-protocol.md` at the start of each research session. It sets the matching standard (three independent anchors, never a name alone), the evidence labels, and file-naming rules. Edit it to fit your own practice.
