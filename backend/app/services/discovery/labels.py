"""Display names for posting sources, shared by Apply (the application's
`source` text), the API and the backup sheet. The frontend's `sourceLabel`
mirrors this map."""

from app.models.posting import PostingSource

SOURCE_LABELS: dict[PostingSource, str] = {
    PostingSource.SIMPLIFY: "Simplify",
    PostingSource.VANSHB03: "vanshb03 list",
    PostingSource.LIST: "Community list",
    PostingSource.GREENHOUSE: "Greenhouse",
    PostingSource.LEVER: "Lever",
    PostingSource.ASHBY: "Ashby",
    PostingSource.WORKDAY: "Workday",
    PostingSource.PASTED: "Pasted",
}


def source_label(source: PostingSource) -> str:
    return SOURCE_LABELS[source]


def application_source(source: PostingSource) -> str:
    """The `applications.source` text Apply writes: "Discover: Simplify"."""
    return f"Discover: {source_label(source)}"
