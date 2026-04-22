# Integrating hailo from an API webservice

This document describes the subset of hailo's surface that an API
webservice (e.g. an IRC-bot backend) can rely on when invoking hailo as
a subprocess and parsing its output. It also documents the creativity
knobs added on top of the `Default` engine and the emergent behaviors
that the backend should be careful not to break.

This document assumes hailo is invoked as a subprocess via the `hailo`
CLI, not embedded in a Perl process.

---

## Invocation contract

The webservice should shell out to the `hailo` CLI with a fixed brain
file. The two operations the bot needs are **reply** and **learn-reply**.

### Reply to an input line

```
hailo --brain PATH --reply "INPUT"
```

- stdout: the reply, followed by a newline.
- stdout is empty when the brain does not yet know any expressions.
- Exit code is `0` on success even when the reply is empty; callers must
  check for an empty/whitespace-only stdout and fall back (e.g. emit
  nothing, or retry with `--random-reply`).
- stderr is reserved for diagnostics. Parse stdout only.

### Learn the input and reply in one call

```
hailo --brain PATH --learn-reply "INPUT"
```

Same stdout contract. This is the call an IRC bot typically makes per
line it observes — it both updates the brain and returns something
quotable. Prefer this over a learn-then-reply pair; it avoids a second
SQLite open.

### Other operations the webservice should know about

| Flag                    | Effect                                                 |
|-------------------------|--------------------------------------------------------|
| `--random-reply`        | Reply without conditioning on input. Good fallback.    |
| `--train FILE`          | Bulk-train from a file (one utterance per line).       |
| `--stats`               | Print brain statistics to stdout.                      |
| `--order N`             | Set n-gram order. **Train-time only.** Changing this   |
|                         | on an existing brain is rejected by the storage layer. |

---

## Brain file compatibility

The brain is a SQLite file. Its schema has no explicit version field;
hailo detects compatibility by probing the `info` table for
`markov_order` and `tokenizer_class` and aborts if either disagrees
with the caller's configuration (see `lib/Hailo/Storage.pm:134-197`).

**Implication for the webservice:** once a brain is trained with a
given `--order` and tokenizer, those are pinned forever. Store that
configuration alongside the brain file and pass it on every invocation,
or just rely on the defaults (`order=2`, tokenizer `Words`) on both
sides.

The creativity knobs described below are all **read-time** — they
affect reply selection, never what is written into the brain. You can
change them freely without breaking the brain.

---

## Creativity knobs (read-time, brain-safe)

These are arguments to the `Default` engine. Pass them as JSON via
`--engine-args`. They were added so the webservice can tune reply style
without retraining or writing new engine code.

### `rareness` (integer, default `2`)

Minimum occurrence count for a token to be eligible as a reply pivot.

- `rareness=1` — admit every token including hapax legomena (words seen
  only once). More surprising replies; reply style wanders further from
  the input. Typos and rare shout tokens get used as pivots more often,
  which **amplifies** the all-caps-input → all-caps-reply behavior.
- `rareness=2` — historical default. Excludes single-occurrence tokens,
  which are usually typos.
- `rareness=5..10` — restricts pivots to well-attested tokens. Replies
  feel more canned and predictable. May partially suppress the all-caps
  mirroring behavior because rare shout tokens get filtered.
- `rareness=999` — effectively all pivots filtered. Engine falls back
  to a random expression. Reply is still produced, but is unconditioned
  on the input; equivalent to `--random-reply`.

Example:

```
hailo --brain /var/lib/hailo/brain.brn \
      --engine-args '{"rareness":1}' \
      --learn-reply "HELLO WHAT IS THIS NOW"
```

### `repeat_limit` (integer, default `min(order*10, 50)`)

Soft cap on how many tokens the forward/backward chain walk will emit
before terminating. Raise to allow longer replies, lower for terseness.
In practice the default is fine; don't touch it unless you have a
specific reason.

### Combining

Args are merged, so:

```
--engine-args '{"rareness":1,"repeat_limit":30}'
```

sets both at once.

---

## MegaHAL-style scored replies (optional)

Hailo ships a second engine, `Scored`, that generates N candidate
replies and picks the highest-scoring one by entropy (`-log2 p`). It
reads the same brain file.

```
hailo --brain PATH \
      --engine Hailo::Engine::Scored \
      --engine-args '{"interval":0.5}' \
      --reply "INPUT"
```

- `interval` — seconds to spend generating candidates (default `0.5`).
- `iterations` — exact number of candidates to generate (mutually
  exclusive with `interval`).

**Trade-off:** ~10× CPU per reply. Quality improvement is real for
well-trained brains. The Scored engine does *not* currently honor the
`rareness` knob (it uses its own pivot probability distribution); if
you want the `rareness` effect, stay on the `Default` engine.

---

## Behaviors to preserve

These are emergent from hailo's tokenizer + storage + engine
interaction and are worth protecting if the webservice adds its own
post-processing:

### All-caps mirroring

**Input in ALL CAPS tends to produce ALL-CAPS replies.** The mechanism:

1. The Words tokenizer (`lib/Hailo/Tokenizer/Words.pm:131-137`)
   selectively preserves case — all-caps and mixed-case words are
   stored verbatim; other words are lowercased. So `HELLO` and `hello`
   are distinct tokens in the brain.
2. The `token` table has no case-folding and lookups are case-exact
   (`lib/Hailo/Engine/Default.pm` `_token_resolve`). `HELLO` only
   matches `HELLO`.
3. All-caps tokens are typically rare in the brain, and the engine
   prefers rarer tokens as pivots. An all-caps input hits exactly the
   rare-pivot sweet spot.
4. The walk from a shouty pivot follows expressions that originally
   contained that pivot — i.e. other shouty contexts. The chain
   propagates the all-caps neighborhood.

**Do not lowercase input before passing it to hailo.** Doing so kills
this behavior. Do not apply a `tr/A-Z/a-z/` post-processor to replies
either.

### Punctuation and spacing

The tokenizer attaches spacing metadata to each token and
`make_output` reassembles replies with correct spacing around
punctuation, quotes, and apostrophes. Do not tokenize, split, or
re-join hailo's stdout — emit it verbatim.

### Empty replies

An empty stdout is a valid signal that the brain does not know enough
to respond to the input. The webservice should treat it as "stay
quiet" rather than as an error.

---

## Recommended webservice defaults

- Invoke `--learn-reply` per observed line so the brain grows.
- Pass the brain path absolute; hailo opens SQLite in the CWD otherwise.
- Do not set `--engine-args` by default. Add a per-request override if
  you want to expose a "be weird" button (e.g. `?rareness=1`).
- Cap subprocess wall-time (10s is generous). A runaway `Scored` reply
  with a large `interval` is the only realistic way hailo hangs.
- Do not modify or mutate the SQLite file out-of-band. Hailo holds a
  connection; concurrent writers will corrupt it. Serialize all calls
  through a single queue if you have concurrent IRC channels.

---

## File references

- CLI entry: `bin/hailo`
- Command dispatch: `lib/Hailo/Command.pm`
- Core reply: `lib/Hailo.pm` `reply()`
- Default engine: `lib/Hailo/Engine/Default.pm`
- Scored engine: `lib/Hailo/Engine/Scored.pm`
- Schema: `lib/Hailo/Storage/Schema.pm`
- Storage compat checks: `lib/Hailo/Storage.pm:134-197`
- Tokenizer case rule: `lib/Hailo/Tokenizer/Words.pm:131-137`
