# hailo-browser

A read-only TUI for browsing [Hailo](../../) SQLite brains — inspect metadata,
sort tokens by count, filter expressions, and walk the Markov chain node by
node.

Issue: https://github.com/ruok5/hailo/issues/4

## Run it

Easiest, no install, requires [`uv`](https://docs.astral.sh/uv/):

```sh
uv run contrib/hailo-browser/hailo-browser.py path/to/brain.sqlite
```

The script has a PEP 723 inline-deps header; `uv` pulls Textual into a cache on
first run and reuses it thereafter.

If the script is executable (it is, out of the repo) and `uv` is on `$PATH`,
the shebang also works:

```sh
./contrib/hailo-browser/hailo-browser.py path/to/brain.sqlite
```

For a permanent install instead:

```sh
pipx install textual
python3 contrib/hailo-browser/hailo-browser.py path/to/brain.sqlite
```

## What you can do

Tabs (switch with `1`–`5`):

1. **Info** — rows from the `info` table (markov order, tokenizer class, …).
2. **Stats** — counts of tokens, expressions, prev/next links; top-10 tokens.
3. **Tokens** — table of tokens sorted by count; `/` to filter by substring.
   Pressing Enter on a row drills into Expressions, showing only n-grams that
   reference that exact token id (not a substring match).
4. **Expressions** — table of n-grams with next/prev link counts and the
   reconstructed text. Filter semantics:
   - one word → substring match against any slot
   - multiple words → positional phrase match (a consecutive window of slots
     must match each word in order, substring per word)
   - longer than the brain's order → no results
   Typing in the filter clears any active token drill-down.
5. **Chain walk** — the main attraction. Select an expression in tab 4 and
   press Enter: the walk tab opens a tree rooted at that expression with two
   subtrees, `→ forward` (children are `next_token` candidates) and
   `← backward` (children are `prev_token` candidates). Each child shows the
   token, its count, and its probability. Expanding a child slides the n-gram
   window in that direction and reveals the next level of the chain. Children
   that hit a sentence boundary are tagged `sentence start` / `sentence end`;
   genuinely unreachable windows are tagged `dead end`.

## Keys

| key          | action                                             |
|--------------|----------------------------------------------------|
| `1`–`5`      | switch tab                                         |
| `/`          | focus the filter input (Tokens / Expressions tabs) |
| `Enter`      | apply filter, or open an expression in chain walk  |
| `Escape`     | unfocus filter                                     |
| `q`, `Ctrl-C`| quit                                               |

Arrow keys and the mouse work throughout (Textual handles both).

## Read-only guarantee

The brain is opened with SQLite's `file:…?mode=ro` URI and
`PRAGMA query_only = ON`. The tool never issues INSERT / UPDATE / DELETE.

## Scope

- SQLite brains only. PostgreSQL and MySQL backends would need a driver
  dependency, which defeats the zero-install story.
- No writes, no exports. If those turn out to be useful, they're separate
  features.
- Works against any `markov_order` — the number of token columns in `expr` is
  read from the `info` table.
