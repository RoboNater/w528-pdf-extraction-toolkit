"""Pydantic result models for pdfx core functions.

Every per-page result carries both numbering schemes: physical_page is the
1-based physical position in the file; labeled_page is the display label from
the PDF's /PageLabels table (what PDF readers show), or None when the document
defines no labels.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    creator: str | None = None
    producer: str | None = None
    creation_date: str | None = None
    modification_date: str | None = None


class OutlineItem(BaseModel):
    title: str
    physical_page: int | None = None  # destination page, if resolvable
    labeled_page: str | None = None
    children: list[OutlineItem] = Field(default_factory=list)


class PageSummary(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    width: float
    height: float
    rotation: int
    has_text: bool


class DocumentIndex(BaseModel):
    path: str
    page_count: int
    has_page_labels: bool = False
    metadata: DocumentMetadata
    outline: list[OutlineItem]
    pages: list[PageSummary]


class PageText(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    text: str
    has_text: bool


class Table(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    index: int  # position of the table on its page, 0-based
    rows: list[list[str | None]]


class ImageInfo(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    index: int  # position of the image on its page, 0-based
    name: str
    width: int
    height: int
    format: str | None = None
    saved_path: str | None = None


class SearchHit(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    before: str  # context preceding the match (whitespace-normalized unless regex)
    match: str  # the exact matched text
    after: str  # context following the match


class MarkdownPage(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    markdown: str  # page body only; the joined document adds provenance delimiters
    has_text: bool  # False when the page has no text layer, tables, or images
    ai_refined: bool = False  # True when the AI review pass replaced the draft


class MarkdownResult(BaseModel):
    path: str
    pages: list[MarkdownPage]
    markdown: str  # full document: page bodies joined with provenance delimiters
    warnings: list[str] = Field(default_factory=list)  # per-page AI fallbacks etc.


class RenderedPage(BaseModel):
    physical_page: int
    labeled_page: str | None = None
    path: str
    width: int
    height: int
    dpi: int
