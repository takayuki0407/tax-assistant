from __future__ import annotations
from pydantic import BaseModel


class SubItem(BaseModel):
    num: str
    text: str


class Item(BaseModel):
    num: str
    text: str
    sub_items: list[SubItem] = []


class Paragraph(BaseModel):
    num: str
    text: str
    items: list[Item] = []


class Article(BaseModel):
    num: str
    caption: str | None = None
    paragraphs: list[Paragraph] = []


class Section(BaseModel):
    num: str
    title: str
    articles: list[Article] = []


class Chapter(BaseModel):
    num: str
    title: str
    sections: list[Section] = []
    articles: list[Article] = []


class LawDocument(BaseModel):
    law_id: str
    law_num: str
    law_title: str
    law_type: str
    promulgation_date: str | None = None
    last_amended: str | None = None
    chapters: list[Chapter] = []


class LawSearchResult(BaseModel):
    law_id: str
    law_num: str
    law_title: str
    law_type: str
    promulgation_date: str | None = None


class MarkdownResponse(BaseModel):
    filename: str
    content: str
    char_count: int
    article_count: int
    is_split: bool = False
