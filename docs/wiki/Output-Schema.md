# Output Schema

Every post `scrape-fb fetch` writes — whether to the default JSON file, `--format ndjson`, or a `Post` object from the [Python API](Python-API-Reference.md) — follows the same shape: one `Post` per top-level story, with `Media`, `LinkAttachment`, and (optionally) a nested `Post` inside it.

This page is a field-by-field reference generated from `src/scraper_for_facebook/model.py`. If a field here ever disagrees with what you actually get out of the tool, that's a bug — [file an issue](../README.md).

## Contents

- [Post](#post)
- [Media](#media)
- [LinkAttachment](#linkattachment)
- [Full example: a post with a shared post](#full-example-a-post-with-a-shared-post)
- [Full example: a post with media and links](#full-example-a-post-with-media-and-links)
- [Datetime fields](#datetime-fields)

## Post

| Field | Type | Null? | Meaning |
|---|---|---|---|
| `id` | `string` | never | The post's `feedback` id from Facebook's GraphQL response. Stable across fetches — use it as your dedup/merge key. |
| `url` | `string` or `null` | when a permalink couldn't be located in the payload | Permalink to the post (`story.wwwURL`). |
| `type` | `string` | never | One of `"status"`, `"photo"`, `"video"`, `"shared"`, `"link"`, `"reel"`, `"life_event"`, `"unknown"`. Best-effort classification from the post's own content — see [Type classification](#type-classification) below. |
| `is_pinned` | `boolean` | never | Whether the post is pinned to the top of the profile. **Pinned posts are always included in the output, regardless of `--since`/`--until`** — the tool can't safely judge a pinned post's position against a date window (a pinned post from 2019 would otherwise look like it broke a `--since 2026-01-01` boundary), so pinned posts bypass date filtering entirely and always sort first. |
| `author_name` | `string` or `null` | when the actor's name wasn't present in the payload | Display name of the post's author. |
| `author_url` | `string` or `null` | same as above | Profile URL of the post's author. |
| `author_id` | `string` or `null` | same as above | Facebook's internal id for the author, stringified. |
| `created_at` | `datetime` or `null` | when a creation timestamp couldn't be located anywhere in the payload | When the post was made, parsed from `creation_time`. **If `null`, the post is never excluded by `--since`/`--until`** (there's nothing to check it against) **and always sorts last** in the output — the tool won't guess a date it can't verify. See [Datetime fields](#datetime-fields). |
| `edited_at` | `datetime` or `null` | when the post has no edit-time field, i.e. it was never edited (or editing wasn't detected — see caveat below) | When the post was last edited, if at all. |
| `text` | `string` | never (empty string `""` if the post has no body text) | The post's full body text. If the payload carried a truncation marker, this is the *truncation-resolved* text where possible (see `text_truncated`/`text_resolved` below), not the cut-off version. |
| `text_truncated` | `boolean` | never | Whether the payload carried a marker suggesting the body text might be cut short (e.g. a "See more" field), **regardless of whether it was actually resolved**. This is a raw signal, not a guarantee of missing text — see [text_truncated vs. text_resolved](#text_truncated-vs-text_resolved) below. |
| `text_resolved` | `boolean` | never | Whether a fallback permalink refetch actually ran and recovered a full body for this post. `False` doesn't necessarily mean `text` is incomplete — most posts never needed resolving in the first place. |
| `media` | `list[Media]` | never (empty list `[]` if no media) | Photos/videos attached directly to this post. See [Media](#media). |
| `links` | `list[LinkAttachment]` | never (empty list `[]` if no links) | External link previews attached to this post. See [LinkAttachment](#linkattachment). |
| `reaction_count` | `integer` or `null` | when the count couldn't be located in the payload | Total reactions (likes + all other reaction types combined), from `feedback.reaction_count.count`. |
| `comment_count` | `integer` or `null` | same as above | Total comment count, from `feedback.comment_rendering_instance.comments.total_count`. |
| `share_count` | `integer` or `null` | same as above | Total share count, from `feedback.share_count.count`. |
| `shared_post` | `Post` or `null` | when this post isn't a reshare/quote of another post | The reshared or quoted post, as a **full nested `Post` object** — same schema, recursively. **One level deep only**: if `shared_post` is itself a reshare of some other post, that inner post's own `shared_post` is not followed further and will be `null` even if the original Facebook payload nests deeper. |
| `captured_at` | `datetime` | never | When *this tool* captured the GraphQL response containing this post — not when the post was made. See [Datetime fields](#datetime-fields). |
| `raw` | `object` or `null` | present only when `--raw`/`raw=True` was requested | The raw, deep-merged story node this `Post` was parsed from. Absent (not just `null` — the key doesn't exist in the dict) on a normal run. Contains everything Facebook sent, including fields this tool doesn't otherwise expose. Treat it as sensitive — see [DISCLAIMER.md §4](../DISCLAIMER.md) and [Security & Privacy](Security-and-Privacy.md). |

### Type classification

`type` is a best-effort guess, checked in this order: `reel` or `life_event` (if the payload's own keys mention either), then `shared` (if it has a `shared_post`), then `video` or `photo` (by inspecting attached media), then `link` (if it has link attachments), then `status` (if it has any body text at all), falling back to `unknown`. `reel`/`life_event`/`edited_at`/pinned-detection and the media/link extraction paths are the least-exercised parts of this classification — the live captures used to validate this parser didn't happen to include any pinned, edited, reel, or life-event posts, or posts with media/link attachments. If you hit a post that gets misclassified, or an `edited_at`/`is_pinned` that looks wrong, that's useful to report.

### text_truncated vs. text_resolved

These two fields answer different questions:

- **`text_truncated`** — did the raw payload contain *any* key that looks truncation-related (e.g. a `preferred_body` or "see more" marker)? This is checked on every post, unconditionally.
- **`text_resolved`** — did a fallback fetch (revisiting the post's own permalink) run and actually recover a full body?

In practice, **`text_truncated` should rarely be `True` for an ordinary post.** Facebook expands "See more" client-side with no extra network call for most text posts, which is evidence the full body already shipped in the initial response — and one specific payload key (`message_truncation_line_limit`) that looks truncation-shaped by name is in fact a universal client-rendering config present on every text post regardless of length, not a real truncation signal, so it's explicitly excluded from the check. If you do see `text_truncated: true`, it's usually on link- or mention-heavy posts, which truncate server-side more often than plain text.

### is_pinned and date filtering

Two things are exempt from `--since`/`--until`: posts with `is_pinned: true`, and posts with `created_at: null`. Both also get pushed to fixed positions in the output ordering rather than sorted by date: pinned posts always come first (newest-pinned-first among themselves), unpinned dated posts follow in newest-first order, and posts with no locatable date come last of all — pinned or not, since there's nothing to sort them by.

## Media

| Field | Type | Null? | Meaning |
|---|---|---|---|
| `kind` | `string` | never | One of `"image"`, `"video"`, or `"unknown"`. |
| `url` | `string` | never | The direct `scontent`/`fbcdn` media URL. **This URL is signed, expires, and is scoped to your logged-in viewing session** — treat it as sensitive, don't share it, and expect it to stop working after some time. See [DISCLAIMER.md](../DISCLAIMER.md) and [Security & Privacy](Security-and-Privacy.md). |
| `width` | `integer` or `null` | when the payload didn't include a width for this media | Pixel width, if known. |
| `height` | `integer` or `null` | same as above | Pixel height, if known. |

## LinkAttachment

| Field | Type | Null? | Meaning |
|---|---|---|---|
| `url` | `string` | never | The external link target (the URL this attachment points to — not a Facebook URL). |
| `title` | `string` or `null` | when the link preview had no title in the payload | The link preview's title, as Facebook rendered it. |
| `description` | `string` or `null` | same as above | The link preview's description/subtitle text, if any. |

## Full example: a post with a shared post

A quote/reshare has its own `type: "shared"`, its own (possibly empty) `text` for whatever the resharer added, and a fully-populated `shared_post` for the original. Note the inner post's own `shared_post` is `null` even though in this synthetic example the original poster is imagined to have also been resharing something else — that deeper level simply isn't followed:

```json
{
  "id": "ZmVlZGJhY2s6OTg3NjU0MzIxMDk4NzY1",
  "url": "https://www.facebook.com/some.profile/posts/pfbid03reshare",
  "type": "shared",
  "is_pinned": false,
  "author_name": "Jane Example",
  "author_url": "https://www.facebook.com/some.profile",
  "author_id": "100000000000001",
  "created_at": "2026-07-02T14:05:00Z",
  "edited_at": null,
  "text": "This is exactly what I meant.",
  "text_truncated": false,
  "text_resolved": false,
  "media": [],
  "links": [],
  "reaction_count": 12,
  "comment_count": 1,
  "share_count": 0,
  "shared_post": {
    "id": "ZmVlZGJhY2s6MTExMTExMTExMTExMTEx",
    "url": "https://www.facebook.com/another.profile/posts/pfbid04original",
    "type": "status",
    "is_pinned": false,
    "author_name": "John Original",
    "author_url": "https://www.facebook.com/another.profile",
    "author_id": "100000000000002",
    "created_at": "2026-07-01T08:30:00Z",
    "edited_at": null,
    "text": "The original post text goes here, in full.",
    "text_truncated": false,
    "text_resolved": false,
    "media": [],
    "links": [],
    "reaction_count": 210,
    "comment_count": 18,
    "share_count": 40,
    "shared_post": null,
    "captured_at": "2026-07-05T03:18:13.385206Z"
  },
  "captured_at": "2026-07-05T03:18:13.385206Z"
}
```

## Full example: a post with media and links

```json
{
  "id": "ZmVlZGJhY2s6NTU1NTU1NTU1NTU1NTU1",
  "url": "https://www.facebook.com/some.profile/posts/pfbid05photolink",
  "type": "photo",
  "is_pinned": true,
  "author_name": "Jane Example",
  "author_url": "https://www.facebook.com/some.profile",
  "author_id": "100000000000001",
  "created_at": "2026-05-14T19:42:11Z",
  "edited_at": "2026-05-14T20:03:47Z",
  "text": "Check out this article — and here are some photos from the trip.",
  "text_truncated": false,
  "text_resolved": false,
  "media": [
    {
      "kind": "image",
      "url": "https://scontent.example.fbcdn.net/v/t39.example/signed-example-token",
      "width": 1440,
      "height": 1080
    },
    {
      "kind": "image",
      "url": "https://scontent.example.fbcdn.net/v/t39.example/signed-example-token-2",
      "width": 1440,
      "height": 1080
    }
  ],
  "links": [
    {
      "url": "https://example.com/some-article",
      "title": "An Example Article Title",
      "description": "A short description of the linked article, as Facebook's preview rendered it."
    }
  ],
  "reaction_count": 88,
  "comment_count": 5,
  "share_count": 2,
  "shared_post": null,
  "captured_at": "2026-07-05T03:18:13.385206Z"
}
```

Note `is_pinned: true` here — this post would appear first in the output and would be included even if it falls outside a `--since`/`--until` window that would otherwise have excluded it.

## Datetime fields

All datetime fields (`created_at`, `edited_at`, `captured_at`) are serialized as **ISO 8601 in UTC, with a `Z` suffix** — e.g. `"2026-06-30T09:15:36Z"`. There is no local-timezone output; everything is normalized to UTC before serialization.

Two of these fields look similar but answer different questions, and are easy to conflate:

- **`created_at`** — when the *post* was made, according to Facebook's `creation_time`. This can be `null` (see the [Post](#post) table above).
- **`captured_at`** — when *this tool* captured the GraphQL response that contained this post. This is never `null`, and will typically carry sub-second precision (e.g. `"2026-07-05T03:18:13.385206Z"`) since it's generated locally at parse time rather than read off a payload field. It tells you nothing about when the post itself was made — a post from 2019 fetched today will have a 2019 `created_at` and a today's-date `captured_at`.

If you're deduplicating or diffing across repeated fetches of the same profile, use `id`, not `captured_at` — `captured_at` will differ on every run even for a post you've already seen.

## See also

- [CLI Reference](CLI-Reference.md) — how `--since`/`--until`/`--raw` map onto this schema
- [Security & Privacy](Security-and-Privacy.md) — why `media[].url` and `raw` are sensitive
- [../README.md](../README.md) — the short version of this page, in "Example output"
