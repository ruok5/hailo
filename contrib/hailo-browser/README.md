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
4. **Expressions** — table of n-grams with next/prev link counts and the
   reconstructed text; `/` to filter by any contained token.
5. **Chain walk** — the main attraction. Select an expression in tab 4 and
   press Enter: the walk tab opens a tree rooted at that expression, children
   are the possible next tokens with their counts and probabilities. Expand a
   child to slide the window forward and see what can follow *that*
   expression. Dead-end tokens (no matching expression on the other side) are
   marked.

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
