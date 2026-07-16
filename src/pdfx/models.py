"""Pydantic result models for pdfx core functions.

All page numbers are 1-based.
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
    page: int | None = None  # destination page, if resolvable
    children: list[OutlineItem] = Field(default_factory=list)


class PageSummary(BaseModel):
    page: int
    label: str | None = None  # display label from the PDF's /PageLabels, if any
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
    page: int
    text: str
    has_text: bool


class Table(BaseModel):
    page: int
    index: int  # position of the table on its page, 0-based
    rows: list[list[str | None]]


class ImageInfo(BaseModel):
    page: int
    index: int  # position of the image on its page, 0-based
    name: str
    width: int
    height: int
    format: str | None = None
    saved_path: str | None = None


class RenderedPage(BaseModel):
    page: int
    path: str
    width: int
    height: int
    dpi: int
