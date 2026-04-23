#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=0.60"]
# ///
"""hailo-browser — a read-only TUI for Hailo SQLite brains.

Hailo stores its Markov chain in a handful of tables (see
lib/Hailo/Storage/Schema.pm): `info` (metadata), `token` (id, spacing, text,
count), `expr` (id plus `token0_id..token{order-1}_id` for an n-gram), and
`next_token` / `prev_token` (expr_id, token_id, count) that encode the chain's
transitions.

This tool opens such a brain read-only and lets you browse the schema
interactively: inspect metadata, sort tokens by count, filter expressions by
substring, and most importantly walk the chain forward from any expression to
see what tokens can follow it and how likely each is.

Issue: https://github.com/ruok5/hailo/issues/4
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.tree import TreeNode


SPACING_NORMAL = 0
SPACING_PREFIX = 1   # no whitespace follows this token
SPACING_POSTFIX = 2  # no whitespace precedes this token
SPACING_INFIX = 3    # no whitespace on either side


@dataclass
class Token:
    id: int
    spacing: int
    text: str
    count: int


class BrainDB:
    """Read-only view over a Hailo SQLite brain."""

    def __init__(self, path: Path) -> None:
        self.path = path
        uri = f"file:{path}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True)
        self.conn.execute("PRAGMA query_only = ON")
        self._load_order()

    def _load_order(self) -> None:
        row = self.conn.execute(
            "SELECT text FROM info WHERE attribute = 'markov_order'"
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"{self.path}: not a Hailo brain (info.markov_order missing)"
            )
        self.order = int(row[0])
        self.token_cols = [f"token{i}_id" for i in range(self.order)]

    def info(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT attribute, text FROM info ORDER BY attribute"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def stats(self) -> dict[str, int]:
        def count(table: str) -> int:
            r = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(r[0])

        return {
            "tokens": count("token"),
            "expressions": count("expr"),
            "prev_links": count("prev_token"),
            "next_links": count("next_token"),
        }

    def token(self, token_id: int) -> Token | None:
        r = self.conn.execute(
            "SELECT id, spacing, text, count FROM token WHERE id = ?",
            (token_id,),
        ).fetchone()
        if r is None:
            return None
        return Token(id=r[0], spacing=r[1], text=r[2], count=r[3])

    def tokens(
        self,
        filter_text: str = "",
        order_by: str = "count DESC, text ASC",
        limit: int = 500,
    ) -> list[Token]:
        sql = "SELECT id, spacing, text, count FROM token"
        params: list[Any] = []
        if filter_text:
            sql += " WHERE text LIKE ?"
            params.append(f"%{filter_text}%")
        sql += f" ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        return [
            Token(id=r[0], spacing=r[1], text=r[2], count=r[3])
            for r in self.conn.execute(sql, params).fetchall()
        ]

    def expr_tokens(self, expr_id: int) -> list[Token] | None:
        cols = ", ".join(self.token_cols)
        row = self.conn.execute(
            f"SELECT {cols} FROM expr WHERE id = ?", (expr_id,)
        ).fetchone()
        if row is None:
            return None
        out: list[Token] = []
        for tid in row:
            tok = self.token(int(tid))
            if tok is None:
                return None
            out.append(tok)
        return out

    def expr_by_token_ids(self, token_ids: list[int]) -> int | None:
        if len(token_ids) != self.order:
            return None
        where = " AND ".join(f"{c} = ?" for c in self.token_cols)
        r = self.conn.execute(
            f"SELECT id FROM expr WHERE {where} LIMIT 1", token_ids
        ).fetchone()
        return int(r[0]) if r else None

    def expressions(
        self, filter_text: str = "", limit: int = 500
    ) -> list[tuple[int, list[Token], int, int]]:
        """Return rows of (expr_id, tokens, n_next, n_prev).

        Filter semantics:
          - empty     → no filter
          - one word  → substring match against any slot's token text
          - K words (K ≤ order) → positional phrase match: the K words must
            appear in order, consecutively, somewhere in the expression's
            token slots; each word is substring-matched (LIKE '%w%')
          - K > order → no results (a phrase longer than the n-gram can't fit)
        """
        cols_sel = ", ".join(f"e.{c}" for c in self.token_cols)
        base = (
            f"SELECT e.id, {cols_sel}, "
            "(SELECT COUNT(*) FROM next_token WHERE expr_id = e.id) AS n_next, "
            "(SELECT COUNT(*) FROM prev_token WHERE expr_id = e.id) AS n_prev "
            "FROM expr e"
        )
        params: list[Any] = []
        words = filter_text.split() if filter_text else []

        if not words:
            sql = f"{base} ORDER BY e.id LIMIT ?"
        elif len(words) > self.order:
            return []
        elif len(words) == 1:
            ors = " OR ".join(
                f"EXISTS (SELECT 1 FROM token WHERE token.id = e.{c} AND token.text LIKE ?)"
                for c in self.token_cols
            )
            sql = f"{base} WHERE {ors} ORDER BY e.id LIMIT ?"
            params.extend([f"%{words[0]}%"] * self.order)
        else:
            # K words, K>=2: any consecutive window of length K in the slots
            window_clauses: list[str] = []
            for start in range(self.order - len(words) + 1):
                parts = [
                    f"EXISTS (SELECT 1 FROM token WHERE token.id = e.{self.token_cols[start + j]} "
                    f"AND token.text LIKE ?)"
                    for j in range(len(words))
                ]
                window_clauses.append("(" + " AND ".join(parts) + ")")
                params.extend(f"%{w}%" for w in words)
            sql = f"{base} WHERE ({' OR '.join(window_clauses)}) ORDER BY e.id LIMIT ?"
        params.append(limit)

        out: list[tuple[int, list[Token], int, int]] = []
        for row in self.conn.execute(sql, params).fetchall():
            expr_id = int(row[0])
            token_ids = [int(x) for x in row[1 : 1 + self.order]]
            n_next = int(row[1 + self.order])
            n_prev = int(row[2 + self.order])
            tokens: list[Token] = []
            ok = True
            for tid in token_ids:
                t = self.token(tid)
                if t is None:
                    ok = False
                    break
                tokens.append(t)
            if ok:
                out.append((expr_id, tokens, n_next, n_prev))
        return out

    def next_tokens(self, expr_id: int) -> list[tuple[Token, int]]:
        rows = self.conn.execute(
            """
            SELECT t.id, t.spacing, t.text, t.count, n.count
            FROM next_token n JOIN token t ON t.id = n.token_id
            WHERE n.expr_id = ?
            ORDER BY n.count DESC, t.text ASC
            """,
            (expr_id,),
        ).fetchall()
        return [(Token(r[0], r[1], r[2], r[3]), int(r[4])) for r in rows]

    def prev_tokens(self, expr_id: int) -> list[tuple[Token, int]]:
        rows = self.conn.execute(
            """
            SELECT t.id, t.spacing, t.text, t.count, p.count
            FROM prev_token p JOIN token t ON t.id = p.token_id
            WHERE p.expr_id = ?
            ORDER BY p.count DESC, t.text ASC
            """,
            (expr_id,),
        ).fetchall()
        return [(Token(r[0], r[1], r[2], r[3]), int(r[4])) for r in rows]


def token_display(tok: Token) -> str:
    return tok.text if tok.text else "«boundary»"


def render_ngram(tokens: list[Token]) -> str:
    """Reconstruct readable text from tokens using Hailo's spacing rules.

    Mirrors the join logic in Hailo::Tokenizer::Words::make_output: a space is
    inserted between two adjacent tokens unless the first is prefix/infix or
    the second is postfix/infix.
    """
    parts: list[str] = []
    n = len(tokens)
    for i, tok in enumerate(tokens):
        parts.append(token_display(tok))
        if i == n - 1:
            continue
        if tok.spacing in (SPACING_PREFIX, SPACING_INFIX):
            continue
        nxt = tokens[i + 1]
        if nxt.spacing in (SPACING_POSTFIX, SPACING_INFIX):
            continue
        parts.append(" ")
    return "".join(parts)


class HailoBrowser(App):
    CSS = """
    #footer-info {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    Input { margin: 0 1; }
    DataTable { height: 1fr; }
    Tree { height: 1fr; }
    .pane-text { padding: 1 2; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("slash", "focus_filter", "Filter"),
        Binding("escape", "blur_filter", "Unfocus", show=False),
        Binding("1", "show_tab('info')", "Info"),
        Binding("2", "show_tab('stats')", "Stats"),
        Binding("3", "show_tab('tokens')", "Tokens"),
        Binding("4", "show_tab('exprs')", "Expressions"),
        Binding("5", "show_tab('walk')", "Walk"),
    ]

    def __init__(self, db: BrainDB) -> None:
        super().__init__()
        self.db = db

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(id="tabs"):
            with TabPane("Info", id="info"):
                yield Static(self._render_info(), classes="pane-text", id="info-body")
            with TabPane("Stats", id="stats"):
                yield Static(self._render_stats(), classes="pane-text", id="stats-body")
            with TabPane("Tokens", id="tokens"):
                yield Input(
                    placeholder="filter by substring, press Enter…",
                    id="tokens-filter",
                )
                tokens_tbl = DataTable(
                    id="tokens-table", cursor_type="row", zebra_stripes=True
                )
                tokens_tbl.add_columns("id", "count", "spacing", "text")
                yield tokens_tbl
            with TabPane("Expressions", id="exprs"):
                yield Input(
                    placeholder="filter: one word = substring; "
                    "multiple words = phrase match (Enter)…",
                    id="exprs-filter",
                )
                exprs_tbl = DataTable(
                    id="exprs-table", cursor_type="row", zebra_stripes=True
                )
                exprs_tbl.add_columns("expr id", "next", "prev", "reconstructed")
                yield exprs_tbl
            with TabPane("Chain walk", id="walk"):
                yield Static(
                    "Select an expression (tab 4), press Enter, then expand "
                    "nodes here to follow the chain.",
                    classes="pane-text",
                )
                yield Tree("(no expression selected)", id="walk-tree")
        yield Static(self._footer_text(), id="footer-info")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"hailo-browser — {self.db.path.name}"
        self._reload_tokens()
        self._reload_exprs()

    def _footer_text(self) -> str:
        info = dict(self.db.info())
        order = info.get("markov_order", "?")
        tok = info.get("tokenizer_class", "?")
        return (
            f"brain: {self.db.path}  |  order: {order}  |  "
            f"tokenizer: {tok}  |  read-only"
        )

    def _render_info(self) -> str:
        rows = self.db.info()
        if not rows:
            return "(info table is empty)"
        width = max(len(k) for k, _ in rows)
        return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)

    def _render_stats(self) -> str:
        s = self.db.stats()
        lines = [
            f"tokens:       {s['tokens']:>12,}",
            f"expressions:  {s['expressions']:>12,}",
            f"prev_links:   {s['prev_links']:>12,}",
            f"next_links:   {s['next_links']:>12,}",
        ]
        if s["expressions"]:
            lines += [
                "",
                f"avg next links / expr:  {s['next_links'] / s['expressions']:>7.2f}",
                f"avg prev links / expr:  {s['prev_links'] / s['expressions']:>7.2f}",
            ]
        top = self.db.tokens(limit=10)
        if top:
            lines += ["", "top 10 tokens by count:"]
            for tok in top:
                lines.append(f"  {tok.count:>8,}  {token_display(tok)}")
        return "\n".join(lines)

    def _reload_tokens(self, filter_text: str = "") -> None:
        tbl = self.query_one("#tokens-table", DataTable)
        tbl.clear()
        for tok in self.db.tokens(filter_text=filter_text, limit=500):
            tbl.add_row(
                str(tok.id),
                f"{tok.count:,}",
                str(tok.spacing),
                token_display(tok),
                key=str(tok.id),
            )

    def _reload_exprs(self, filter_text: str = "") -> None:
        tbl = self.query_one("#exprs-table", DataTable)
        tbl.clear()
        for expr_id, tokens, n_next, n_prev in self.db.expressions(
            filter_text=filter_text, limit=500
        ):
            tbl.add_row(
                str(expr_id),
                str(n_next),
                str(n_prev),
                render_ngram(tokens),
                key=str(expr_id),
            )

    def _start_walk(self, expr_id: int) -> None:
        tokens = self.db.expr_tokens(expr_id)
        if tokens is None:
            self.bell()
            return
        tree = self.query_one("#walk-tree", Tree)
        tree.reset(f"[{expr_id}] {render_ngram(tokens)}")
        tree.root.data = {"expr_id": expr_id, "tokens": tokens}
        self._populate_children(tree.root)
        tree.root.expand()
        self.query_one("#tabs", TabbedContent).active = "walk"
        tree.focus()

    def _populate_children(self, node: TreeNode) -> None:
        if node.children or node.data is None:
            return
        expr_id: int = node.data["expr_id"]
        tokens: list[Token] = node.data["tokens"]
        nexts = self.db.next_tokens(expr_id)
        total = sum(c for _, c in nexts)
        if total == 0:
            node.add_leaf("(no outgoing links)")
            return
        for tok, count in nexts:
            prob = count / total * 100
            new_tokens = tokens[1:] + [tok]
            new_expr_id = self.db.expr_by_token_ids([t.id for t in new_tokens])
            label = f"[{count:>4}/{total}  {prob:5.1f}%]  {token_display(tok)}"
            if new_expr_id is None:
                node.add_leaf(f"{label}   (dead end)")
            else:
                node.add(
                    label,
                    data={"expr_id": new_expr_id, "tokens": new_tokens},
                    allow_expand=True,
                )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tokens-filter":
            self._reload_tokens(event.value.strip())
        elif event.input.id == "exprs-filter":
            self._reload_exprs(event.value.strip())

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "exprs-table":
            return
        raw = event.row_key.value
        if raw is None:
            return
        try:
            expr_id = int(raw)
        except ValueError:
            return
        self._start_walk(expr_id)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        self._populate_children(event.node)

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id

    def action_focus_filter(self) -> None:
        tab = self.query_one("#tabs", TabbedContent).active
        if tab == "tokens":
            self.query_one("#tokens-filter", Input).focus()
        elif tab == "exprs":
            self.query_one("#exprs-filter", Input).focus()

    def action_blur_filter(self) -> None:
        self.set_focus(None)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only TUI browser for Hailo SQLite brains."
    )
    p.add_argument("brain", type=Path, help="path to a Hailo SQLite brain file")
    args = p.parse_args()
    if not args.brain.exists():
        print(f"error: {args.brain}: file not found", file=sys.stderr)
        return 1
    try:
        db = BrainDB(args.brain)
    except sqlite3.DatabaseError as e:
        print(f"error: {args.brain}: not a valid SQLite database ({e})", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    HailoBrowser(db).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
