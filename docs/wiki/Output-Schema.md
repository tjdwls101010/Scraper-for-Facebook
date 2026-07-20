# Output Schema

Field-by-field reference for the three object types `scrape-fb` emits — **Post**, **Comment**, and **Entity** — including how to tell them apart once outputs from different commands land in the same pile.

Every command writes either a JSON array or NDJSON (one object per line). Which object type you get depends only on the command:

| Command | Emits |
|---|---|
| `fetch` | Post (`source: "timeline"`) |
| `feed` | Post (`source: "newsfeed"`) |
| `group` | Post (`source: "group"`) |
| `post` | Post (`source: "timeline"`) |
| `search --type posts` / `--type top` | Post (`source: "search"`); `top` also returns Entities |
| `search --type people\|pages\|groups` | Entity |
| `comments` | Comment |

This page is written by hand and can lag the code. The machine-readable, always-current version ships inside the tool itself:

```bash
scrape-fb schema           # human-readable, all three objects
scrape-fb schema --json    # JSON Schema (draft 2020-12), keyed by "Post", "Comment", "Entity"
```

Both run offline and need no login. If this page and `scrape-fb schema --json` ever disagree, the command is right — it is generated from the same dataclasses that produce the output.

## Contents

- [Telling the three apart](#telling-the-three-apart)
- [Two traps worth reading first](#two-traps-worth-reading-first)
- [Post](#post)
- [Comment](#comment)
- [Entity](#entity)
- [Stability contract](#stability-contract)

## Telling the three apart

Chained pipelines mix these freely: you search for people, fetch each one's timeline, then pull comments on the interesting posts, and everything ends up in one directory (or one `jq` invocation). Each object type therefore carries a discriminator key that the other two never have:

| If the object has… | It is a… |
|---|---|
| `source` | **Post** |
| `kind` | **Entity** |
| `depth` | **Comment** |

These are always present on their own type and never present on the other two, so a single key test is enough:

```bash
# Split one merged pile into three
jq -c 'select(has("source"))' merged.ndjson > posts.ndjson
jq -c 'select(has("kind"))'   merged.ndjson > entities.ndjson
jq -c 'select(has("depth"))'  merged.ndjson > comments.ndjson
```

Don't discriminate on `id` (all three have one), on `author_name` (Post and Comment both have it), or on `url` (Post and Entity both have it).

## Two traps worth reading first

### 1. `captured_at` is not a dedup key and not a sort key

`captured_at` is when **this tool** captured the response — a property of your scraping run, not of the content. It changes on every run. Two objects with different `captured_at` values are very often the same post fetched twice.

- **To deduplicate:** use `id`. It is the stable identity of the post, comment, or entity.
- **To sort chronologically:** use `created_at`. That is when the content was actually published.
- **`captured_at` is only good for:** "how stale is this snapshot", and provenance/audit trails.

```bash
# Correct: dedup on id, newest content first
jq -s 'unique_by(.id) | sort_by(.created_at) | reverse' posts.json
```

### 2. `created_at` can be `null` — filter before you compare

`created_at` is `null` whenever the timestamp could not be located in the captured payload. This is not an error, and it is not rare enough to ignore. A comparison against `null` will either throw or silently mis-sort depending on the language, and a date-window filter that doesn't handle it will quietly drop (or quietly keep) those posts.

```bash
# Filter out undated posts before doing date math
jq '[.[] | select(.created_at != null)] | map(select(.created_at >= "2026-01-01T00:00:00Z"))' posts.json
```

```python
# Python: partition, don't assume
dated = [p for p in posts if p["created_at"] is not None]
undated = [p for p in posts if p["created_at"] is None]
dated.sort(key=lambda p: p["created_at"], reverse=True)
```

The same applies to `Comment.created_at`. `Entity` has no `created_at` at all.

Related: pinned posts and posts whose `created_at` is `null` deliberately **bypass** `--since`/`--until` windowing — the tool refuses to judge a date it could not place. If you need a hard date window, apply it yourself downstream, after filtering out the nulls.

Every timestamp that is present is ISO-8601 UTC with a `Z` suffix (e.g. `2026-03-14T09:21:07Z`).

## Post

Emitted by `fetch`, `feed`, `post`, `group`, and `search` (for post-shaped hits). 21 keys, plus `raw` which appears only under `--raw`.

| Field | JSON type | Meaning |
|---|---|---|
| `id` | `string` | Feedback id. **The dedup/merge key.** Stable across runs. |
| `url` | `string \| null` | Permalink to the post; `null` if one could not be located. |
| `type` | `string` | One of `status`, `photo`, `video`, `shared`, `link`, `reel`, `life_event`, `unknown`. |
| `is_pinned` | `boolean` | `true` for a pinned post. Pinned posts bypass `--since`/`--until` and always sort first. |
| `author_name` | `string \| null` | Display name of the author. |
| `author_url` | `string \| null` | Profile URL of the author — the handle to chain back into `fetch`. |
| `author_id` | `string \| null` | Numeric id of the author. |
| `created_at` | `string \| null` | ISO-8601 UTC publish time; `null` if it could not be located. **Sort on this.** |
| `edited_at` | `string \| null` | ISO-8601 UTC time of the last edit; `null` if never edited. |
| `text` | `string` | Full post body, truncation-resolved when possible; `""` if the post has none. |
| `text_truncated` | `boolean` | The captured payload carried a truncation marker, resolved or not. |
| `text_resolved` | `boolean` | A follow-up permalink fetch recovered the full truncated body. |
| `media` | `array<object>` | List of Media objects (see below). Empty array if none. |
| `links` | `array<object>` | List of LinkAttachment objects (see below). Empty array if none. |
| `reaction_count` | `integer \| null` | Reactions, or `null` if unavailable. |
| `comment_count` | `integer \| null` | Comments, or `null` if unavailable. |
| `share_count` | `integer \| null` | Shares, or `null` if unavailable. |
| `shared_post` | `object \| null` | A nested Post for an attached/shared story (see below). |
| `source` | `string` | `timeline` \| `newsfeed` \| `group` \| `search`. **The Post discriminator.** |
| `captured_at` | `string` | ISO-8601 UTC time this tool captured the response. Never a dedup key. |
| `raw` | `object` | **Only present with `--raw`.** The raw captured story node, redacted unless `--no-redact` was also passed. |

### `source` (added in v0.3.0)

`source` records which surface a post came from, so merged outputs don't lose their provenance:

- `"timeline"` — a profile timeline (`fetch`) or a single permalink (`post`)
- `"newsfeed"` — your home feed (`feed`)
- `"group"` — a group's feed (`group`)
- `"search"` — a post-shaped search hit (`search`)

Because it is always present on a Post and never present on a Comment or Entity, it doubles as the type discriminator. A `shared_post` inherits its parent's `source` — it arrived on the same surface.

### Nested: Media (`media[]`)

```json
{ "kind": "image", "url": "https://scontent.xx.fbcdn.net/v/t39.30808-6/example_signed_asset.jpg", "width": 2048, "height": 1536 }
```

| Field | JSON type | Meaning |
|---|---|---|
| `kind` | `string` | `image`, `video`, or `unknown`. |
| `url` | `string` | The CDN link. |
| `width` | `integer \| null` | Pixel width, or `null` if the payload omits it. |
| `height` | `integer \| null` | Pixel height, or `null` if the payload omits it. |

**`media[].url` is sensitive.** fbcdn/scontent URLs are signed, time-limited, and viewer-scoped: they encode your session's entitlement to that asset. They expire (so they are useless as a long-term reference), and while they live they are a working link to content that may not be public. Never print them unredacted in logs, issues, or bug reports. See [Security & Privacy](Security-and-Privacy.md).

### Nested: LinkAttachment (`links[]`)

```json
{ "url": "https://example.org/article", "title": "The article headline", "description": "Preview text from the link card." }
```

| Field | JSON type | Meaning |
|---|---|---|
| `url` | `string` | The external link target. |
| `title` | `string \| null` | Link card title, or `null`. |
| `description` | `string \| null` | Link card description, or `null`. |

### Nested: `shared_post` recursion

`shared_post` is a **complete Post object** — the same 21 keys — representing the quoted/shared story. It is not a stub or a reference.

Crucially, **the nesting is not capped at one level**. A share of a share produces a `shared_post` whose own `shared_post` is non-null. If you flatten or walk these, recurse until you hit `null`:

```python
def flatten(post):
    yield post
    if post.get("shared_post") is not None:
        yield from flatten(post["shared_post"])
```

A nested `shared_post` carries its own `id`. If you flatten shares into your main pile, dedup by `id` afterwards — the same original post can appear both standalone and inside several people's `shared_post`.

### Post example

```json
{
  "id": "1234567890123456",
  "url": "https://www.facebook.com/permalink.php?story_fbid=1234567890123456&id=100001234567890",
  "type": "shared",
  "is_pinned": false,
  "author_name": "Jordan Reyes",
  "author_url": "https://www.facebook.com/jordan.reyes.90",
  "author_id": "100001234567890",
  "created_at": "2026-03-14T09:21:07Z",
  "edited_at": null,
  "text": "This matches what we saw at the meetup last week.",
  "text_truncated": false,
  "text_resolved": false,
  "media": [],
  "links": [],
  "reaction_count": 42,
  "comment_count": 7,
  "share_count": 3,
  "shared_post": {
    "id": "9876543210987654",
    "url": "https://www.facebook.com/coastalbirders/posts/9876543210987654",
    "type": "photo",
    "is_pinned": false,
    "author_name": "Coastal Birders",
    "author_url": "https://www.facebook.com/coastalbirders",
    "author_id": "100009876543210",
    "created_at": "2026-03-13T18:02:44Z",
    "edited_at": null,
    "text": "Three sandhill cranes on the north flats this morning.",
    "text_truncated": false,
    "text_resolved": false,
    "media": [
      {
        "kind": "image",
        "url": "https://scontent.xx.fbcdn.net/v/t39.30808-6/example_signed_asset.jpg",
        "width": 2048,
        "height": 1536
      }
    ],
    "links": [],
    "reaction_count": 310,
    "comment_count": 28,
    "share_count": 15,
    "shared_post": null,
    "source": "timeline",
    "captured_at": "2026-03-20T11:45:02Z"
  },
  "source": "timeline",
  "captured_at": "2026-03-20T11:45:02Z"
}
```

## Comment

Emitted by `comments`. 12 keys, all always present.

| Field | JSON type | Meaning |
|---|---|---|
| `id` | `string` | Stable identity/dedup key for this comment. |
| `post_id` | `string` | Feedback id of the post this comment belongs to — **matches a Post's `id`**, so comments and posts join cleanly. |
| `author_name` | `string \| null` | Display name of the commenter. |
| `author_url` | `string \| null` | Profile URL of the commenter — the handle to chain into `fetch`. |
| `author_id` | `string \| null` | Numeric id of the commenter. |
| `text` | `string` | The comment body; `""` if it has none (e.g. a sticker-only reply). |
| `created_at` | `string \| null` | ISO-8601 UTC publish time; `null` if it could not be located. |
| `depth` | `integer` | `0` for a top-level comment, `1` or more for a reply. **The Comment discriminator.** |
| `parent_id` | `string \| null` | Id of the comment this one replies to; `null` at depth 0. |
| `reaction_count` | `integer \| null` | Reactions on this comment, or `null` if unavailable. |
| `reply_count` | `integer \| null` | Replies to this comment, or `null` if unavailable. |
| `captured_at` | `string` | ISO-8601 UTC time this tool captured the response. Never a dedup key. |

### Reading the thread structure

`depth` and `parent_id` together reconstruct the tree:

- `depth == 0` → a top-level comment on the post; `parent_id` is `null`.
- `depth >= 1` → a reply; `parent_id` holds the `id` of the comment it replies to, which is itself somewhere in the same output.

```bash
# Top-level comments only
jq '[.[] | select(.depth == 0)]' comments.json

# All replies to one specific comment
jq --arg pid "17851234567890123" '[.[] | select(.parent_id == $pid)]' comments.json
```

Two caveats grounded in how Facebook actually serves this data:

- **Replies are never delivered inline.** A comment with a non-zero `reply_count` costs an extra request to expand, so `reply_count` may exceed the number of depth-1 comments you actually received.
- **`reaction_count` is best-effort.** A comment's exact reaction integer lives in a side subtree; when only an abbreviated display string (`"1.2K"`) is available, the field is `null` rather than a guessed number.

### Comment example

A top-level comment:

```json
{
  "id": "17851234567890123",
  "post_id": "1234567890123456",
  "author_name": "Priya Nandakumar",
  "author_url": "https://www.facebook.com/priya.nandakumar",
  "author_id": "100005551234567",
  "text": "Was this the same flock from the causeway?",
  "created_at": "2026-03-14T10:05:31Z",
  "depth": 0,
  "parent_id": null,
  "reaction_count": 6,
  "reply_count": 2,
  "captured_at": "2026-03-20T11:47:19Z"
}
```

And a reply to it:

```json
{
  "id": "17851234567890988",
  "post_id": "1234567890123456",
  "author_name": "Jordan Reyes",
  "author_url": "https://www.facebook.com/jordan.reyes.90",
  "author_id": "100001234567890",
  "text": "Same flock, two days later.",
  "created_at": "2026-03-14T10:22:08Z",
  "depth": 1,
  "parent_id": "17851234567890123",
  "reaction_count": 1,
  "reply_count": null,
  "captured_at": "2026-03-20T11:47:19Z"
}
```

## Entity

Emitted by `search --type people|pages|groups`, and mixed in with Posts by `search --type top`. 6 keys, all always present.

| Field | JSON type | Meaning |
|---|---|---|
| `kind` | `string` | `person`, `page`, or `group`. **The Entity discriminator.** |
| `id` | `string` | Numeric id — the handle to chain into `fetch` (person/page) or `group`. |
| `name` | `string \| null` | Display name. |
| `url` | `string \| null` | Facebook URL for this person, page, or group. |
| `verified` | `boolean \| null` | Verified badge, or `null` when the payload omits it. |
| `captured_at` | `string` | ISO-8601 UTC time this tool captured the response. |

### How `kind` is decided

The `--type` you requested is authoritative. Facebook returns Pages tagged with the same internal typename as Users in these results, so the payload alone cannot reliably tell a page from a person — `--type pages` is what makes a hit a `"page"`. Only `--type top`, which has no requested vertical, has to infer `kind` from the payload, and there it can only distinguish groups from everything else (non-group hits come back as `"person"`). If the person/page distinction matters to your analysis, run the vertical searches (`--type people`, `--type pages`) separately rather than sifting `top`.

### Entity example

A group hit:

```json
{
  "kind": "group",
  "id": "1029384756102938",
  "name": "Coastal Birders — Pacific Northwest",
  "url": "https://www.facebook.com/groups/1029384756102938",
  "verified": null,
  "captured_at": "2026-03-20T11:52:40Z"
}
```

A person hit:

```json
{
  "kind": "person",
  "id": "100001234567890",
  "name": "Jordan Reyes",
  "url": "https://www.facebook.com/jordan.reyes.90",
  "verified": false,
  "captured_at": "2026-03-20T11:52:40Z"
}
```

## Stability contract

Decided pre-1.0 and worth relying on:

- **Adding a field is a minor version bump.** `source` arriving in v0.3.0 is the model case. Write consumers that tolerate unknown keys.
- **Reinterpreting an existing field's meaning is a breaking change.** If `created_at` still exists, it still means what this page says it means.
- **Field order in the output matches the order in these tables** and matches `scrape-fb schema`. Don't depend on it, but it isn't random.

Every field description on this page comes from the same source as `scrape-fb schema`: the `FIELD_DESCRIPTIONS` tables that sit next to the dataclasses in `model.py`, `comments.py`, and `search.py`. Pipe `scrape-fb schema --json` into your validator and you get a real JSON Schema (draft 2020-12) per object type, with `required` reflecting exactly which keys are always present.

---

**Next:** [Python API Reference](Python-API-Reference.md) for driving the scraper from Python, then [FAQ & Troubleshooting](FAQ-and-Troubleshooting.md) when a field comes back empty. Back to the [wiki index](README.md).
