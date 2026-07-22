"""Registry of the Facebook GraphQL queries active mode replays.

Every ``doc_id`` and default-variable set here was captured from a live,
logged-in browser session (recon §2, re-validated §7) — they are a snapshot,
not constants. Facebook rotates them as it ships client builds, which is why
every active call is treated as fallible and falls back to the passive
browser transport rather than crashing (recon §6).

Two findings shape this module's shape:

- **The relay-provider flags are required.** Omitting them does not fail, it
  *degrades*: the same query returned 0 errors with them and 25
  ``missing_required_variable_value`` warnings without (recon §7.4).
- **One shared flag set serves every query.** Across all seven captured
  queries no flag value ever disagreed, and sending the full 31-flag union to
  a query that declares only a subset returns 0 errors (measured). So the
  flags live here once, not copied per query.

Instance-specific values (profile/group/feedback ids, cursors, search text,
session uuids) are deliberately NOT baked into the defaults — they are
caller-supplied, and committing captured ones would commit third-party PII.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Sent with every query. See module docstring for why these are not optional
#: and why one shared set is correct.
RELAY_PROVIDER_FLAGS: dict[str, object] = {
    "__relay_internal__pv__CometFeedShareMedia_shouldPrefetchShareImagerelayprovider": True,
    # Facebook's own flag name; too long to wrap and not ours to shorten.
    "__relay_internal__pv__CometFeedStory_enable_post_permalink_white_space_clickrelayprovider": False,  # noqa: E501
    "__relay_internal__pv__CometFeedStory_enable_reactor_facepilerelayprovider": False,
    "__relay_internal__pv__CometFeedStory_enable_social_bubblesrelayprovider": False,
    "__relay_internal__pv__CometImmersivePhotoCanUserDisable3DMotionrelayprovider": False,
    "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
    "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
    "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
    "__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider": False,
    "__relay_internal__pv__CometUFIShareActionMigrationrelayprovider": True,
    "__relay_internal__pv__CometUFISingleLineUFIrelayprovider": True,
    "__relay_internal__pv__CometUFI_dedicated_comment_routable_dialog_gkrelayprovider": True,
    "__relay_internal__pv__FBReelsIFUTileContent_reelsIFUPlayOnHoverrelayprovider": True,
    "__relay_internal__pv__FBReelsMediaFooter_comet_enable_reels_ads_gkrelayprovider": True,
    "__relay_internal__pv__FBReels_deprecate_short_form_video_context_gkrelayprovider": True,
    "__relay_internal__pv__FBReels_enable_view_dubbed_audio_type_gkrelayprovider": True,
    "__relay_internal__pv__GHLShouldChangeAdIdFieldNamerelayprovider": False,
    "__relay_internal__pv__GHLShouldChangeSponsoredAuctionDistanceFieldNamerelayprovider": False,
    "__relay_internal__pv__GHLShouldChangeSponsoredDataFieldNamerelayprovider": False,
    "__relay_internal__pv__GHLShouldUseSponsoredAuctionLabelFieldNameV1relayprovider": False,
    "__relay_internal__pv__GHLShouldUseSponsoredAuctionLabelFieldNameV2relayprovider": False,
    "__relay_internal__pv__GroupsCometGYSJFeedItemHeightrelayprovider": 206,
    "__relay_internal__pv__IsMergQAPollsrelayprovider": False,
    "__relay_internal__pv__IsWorkUserrelayprovider": False,
    "__relay_internal__pv__ProfileCometSeoIsViewerLoggedOutrelayprovider": False,
    "__relay_internal__pv__ReelsIFUCard_reelsIFULikeCountrelayprovider": False,
    "__relay_internal__pv__ShouldEnableBakedInTextStoriesrelayprovider": False,
    "__relay_internal__pv__StoriesShouldIncludeFbNotesrelayprovider": False,
    "__relay_internal__pv__TestPilotShouldIncludeDemoAdUseCaserelayprovider": False,
    "__relay_internal__pv__WorkCometIsEmployeeGKProviderrelayprovider": False,
    "__relay_internal__pv__relay_provider_comet_ufi_ssr_seo_deferrelayprovider": True,
}


@dataclass(frozen=True)
class QuerySpec:
    """One replayable GraphQL query.

    ``connection_key`` names the connection that paginates. It is the lookup
    key for the next cursor, which arrives in one of two shapes — inline, or
    as a trailing ``@defer`` chunk addressed by ``path[-1]`` (recon §7.5).
    ``None`` means the query returns a single object and does not paginate.
    """

    name: str
    doc_id: str
    connection_key: str | None
    cursor_var: str | None
    referer: str
    variables: dict = field(default_factory=dict)


#: Keyed by the surface name the CLI uses, not by the Facebook query name.
QUERIES: dict[str, QuerySpec] = {
    "timeline": QuerySpec(
        name="ProfileCometTimelineFeedRefetchQuery",
        doc_id="27676223615330440",
        connection_key="timeline_list_feed_units",
        cursor_var="cursor",
        referer="https://www.facebook.com/me",
        variables={
            # afterTime/beforeTime are enforced server-side (recon §7.3) — this
            # is what makes active-mode --since/--until precise rather than
            # scroll-until-you-see-it.
            "afterTime": None,
            "beforeTime": None,
            "count": 5,
            "cursor": None,
            "feedLocation": "TIMELINE",
            "feedbackSource": 0,
            "focusCommentID": None,
            "memorializedSplitTimeFilter": None,
            "omitPinnedPost": False,
            "postedBy": None,
            "privacy": None,
            "privacySelectorRenderLocation": "COMET_STREAM",
            "referringStoryRenderLocation": None,
            "renderLocation": "timeline",
            "scale": 2,
            "stream_count": 1,
            "taggedInOnly": None,
            "trackingCode": None,
            "useDefaultActor": False,
        },
    ),
    "newsfeed": QuerySpec(
        name="CometNewsFeedPaginationQuery",
        doc_id="27790894430578947",
        connection_key="news_feed",
        cursor_var="cursor",
        referer="https://www.facebook.com/",
        variables={
            "RELAY_INCREMENTAL_DELIVERY": True,
            "clientSession": None,
            "connectionClass": "EXCELLENT",
            "count": 5,
            "cursor": None,
            "experimentalValues": None,
            "feedLocation": "NEWSFEED",
            "feedStyle": "DEFAULT",
            "feedbackSource": 1,
            "focusCommentID": None,
            "orderby": ["TOP_STORIES"],
            "privacySelectorRenderLocation": "COMET_STREAM",
            # The captured request carried a recentVPVs array of view-tracking
            # tokens. Sending an empty one works and reports nothing back about
            # what was viewed, so it stays empty.
            "recentVPVs": [],
            "referringStoryRenderLocation": None,
            "refreshMode": "AUTO",
            "renderLocation": "homepage_stream",
            "scale": 2,
            "shouldChangeBRSLabelFieldName": False,
            "shouldObfuscateCategoryField": False,
            "shouldUseBRSLabelFieldNameV1": False,
            "shouldUseBRSLabelFieldNameV2": False,
            "useDefaultActor": False,
        },
    ),
    "group": QuerySpec(
        name="GroupsCometFeedRegularStoriesPaginationQuery",
        doc_id="27489248654050164",
        connection_key="group_feed",
        cursor_var="cursor",
        referer="https://www.facebook.com/groups/",
        variables={
            "count": 5,
            "cursor": None,
            "feedLocation": "GROUP",
            "feedType": "DISCUSSION",
            "feedbackSource": 0,
            "filterTopicId": None,
            "focusCommentID": None,
            "privacySelectorRenderLocation": "COMET_STREAM",
            "referringStoryRenderLocation": None,
            "renderLocation": "group",
            "scale": 2,
            "sortingSetting": "TOP_POSTS",
            "stream_initial_count": 1,
            "useDefaultActor": False,
        },
    ),
    "search": QuerySpec(
        name="SearchCometResultsPaginatedResultsQuery",
        doc_id="28091046377146459",
        connection_key="results",
        cursor_var="cursor",
        referer="https://www.facebook.com/search/top/",
        variables={
            "allow_streaming": False,
            "args": {
                "callsite": "COMET_GLOBAL_SEARCH",
                "config": {
                    "exact_match": False,
                    "high_confidence_config": None,
                    "intercept_config": None,
                    "sts_disambiguation": None,
                    "watch_config": None,
                },
                "context": {"bsid": None, "tsid": None},
                "experience": {
                    "client_defined_experiences": ["ADS_PARALLEL_FETCH"],
                    "encoded_server_defined_params": None,
                    "fbid": None,
                    "type": "GLOBAL_SEARCH",
                },
                "filters": [],
                "text": "",
            },
            "count": 5,
            "cursor": None,
            "feedLocation": "SEARCH",
            "feedbackSource": 23,
            "fetch_filters": True,
            "focusCommentID": None,
            "locale": None,
            "privacySelectorRenderLocation": "COMET_STREAM",
            "referringStoryRenderLocation": None,
            "renderLocation": "search_results_page",
            "scale": 2,
            "stream_initial_count": 0,
            "useDefaultActor": False,
        },
    ),
    "post": QuerySpec(
        name="CometSinglePostDialogContentQuery",
        doc_id="27371991432470815",
        connection_key=None,
        cursor_var=None,
        referer="https://www.facebook.com/",
        variables={
            "feedLocation": "POST_PERMALINK_DIALOG",
            "feedbackSource": 2,
            "focusCommentID": None,
            "privacySelectorRenderLocation": "COMET_STREAM",
            "renderLocation": "permalink",
            "scale": 2,
            "shouldChangeNodeFieldName": True,
            "useDefaultActor": False,
        },
    ),
    "comments": QuerySpec(
        name="CommentListComponentsRootQuery",
        doc_id="27659404140378758",
        connection_key="comments",
        cursor_var=None,
        referer="https://www.facebook.com/",
        variables={
            "commentsIntentToken": None,
            "feedLocation": "POST_PERMALINK_DIALOG",
            "feedbackSource": 2,
            "focusCommentID": None,
            "scale": 2,
            "useDefaultActor": False,
        },
    ),
    "comments_page": QuerySpec(
        name="CommentsListComponentsPaginationQuery",
        doc_id="27806180149070312",
        connection_key="comments",
        cursor_var="commentsAfterCursor",
        referer="https://www.facebook.com/",
        variables={
            "commentsAfterCount": -1,
            "commentsAfterCursor": None,
            "commentsBeforeCount": None,
            "commentsBeforeCursor": None,
            "commentsIntentToken": None,
            "feedLocation": "POST_PERMALINK_DIALOG",
            "focusCommentID": None,
            "scale": 2,
            "useDefaultActor": False,
        },
    ),
}

QUERIES["replies"] = QuerySpec(
    name="Depth1CommentsListPaginationQuery",
    doc_id="27888228590762910",
    connection_key=None,
    cursor_var=None,
    referer="https://www.facebook.com/",
    # Takes the COMMENT's own feedback id plus the `expansion_token` found on
    # that comment (comments.expansion_token). Replies are never inline —
    # replies_connection.edges is empty even when total_count is not — so each
    # comment with replies costs one extra request.
    variables={
        "clientKey": None,
        "expansionToken": None,
        "feedLocation": "POST_PERMALINK_DIALOG",
        "focusCommentID": None,
        "repliesAfterCount": None,
        "repliesAfterCursor": None,
        "repliesBeforeCount": None,
        "repliesBeforeCursor": None,
        "scale": 2,
        "useDefaultActor": False,
    },
)

#: ``commentsIntentToken`` values, captured from the comment sort control.
COMMENT_SORT_TOKENS = {
    "top": "RANKED_UNFILTERED_INTENT_V1",
    "recent": "REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1",
}


def build_variables(spec: QuerySpec, overrides: dict | None = None) -> dict:
    """The spec's defaults, plus the shared relay flags, plus caller overrides."""
    variables = dict(spec.variables)
    variables.update(RELAY_PROVIDER_FLAGS)
    if overrides:
        variables.update(overrides)
    return variables
