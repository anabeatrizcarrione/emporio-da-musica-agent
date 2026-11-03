"""Store policy manual: PDF -> sections addressable by topic.

The manual is short (~3k tokens) and already organised in ten numbered
sections, so retrieval is done by topic instead of by embeddings: the agent
asks for e.g. "politica_de_trocas_e_devolucoes" and gets that whole section.
This is deterministic, cheap, and the decision to consult policy is visible in
the tool-call trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from emporio.data import slugify

PAGE_HEADER = "Empório da Música Manual de Políticas e Procedimentos"
PAGE_FOOTER = re.compile(r"^Página \d+$")
# Top-level headings look like "4. Política de Trocas e Devoluções". Numbered
# list items inside sections ("1. Saudação: ...") contain a colon, so they are
# excluded; headings must also appear in sequence.
SECTION_HEADING = re.compile(r"^(\d{1,2})\.\s+([^:]+)$")
TABLE_GAP = re.compile(r"\s{3,}")


@dataclass(frozen=True)
class PolicySection:
    number: int
    title: str
    text: str

    @property
    def topic(self) -> str:
        return slugify(self.title)


def _clean_lines(page_text: str) -> list[str]:
    lines = []
    for raw in page_text.splitlines():
        line = raw.strip()
        if line == PAGE_HEADER or PAGE_FOOTER.match(line):
            continue
        # Normalise list markers first, then turn the long runs of spaces that
        # layout extraction uses to align table cells into column separators.
        line = re.sub(r"^•\s+", "- ", line)
        line = re.sub(r"^(\d+\.)\s+", r"\1 ", line)
        line = TABLE_GAP.sub(" | ", line)
        lines.append(line)
    return lines


def parse_policy_text(pages: list[str]) -> list[PolicySection]:
    sections: list[PolicySection] = []
    number, title, body = 0, "", []

    def flush() -> None:
        if number:
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip()
            sections.append(PolicySection(number, title, text))

    for page in pages:
        for line in _clean_lines(page):
            match = SECTION_HEADING.match(line)
            if match and int(match.group(1)) == number + 1:
                flush()
                number, title, body = int(match.group(1)), match.group(2).strip(), []
            elif number:  # text before section 1 is the cover page
                body.append(line)
    flush()
    return sections


class PolicyManual:
    def __init__(self, sections: list[PolicySection]):
        self.sections = {s.topic: s for s in sections}

    @classmethod
    def from_pdf(cls, path: Path) -> PolicyManual:
        reader = PdfReader(path)
        pages = [page.extract_text(extraction_mode="layout") for page in reader.pages]
        return cls(parse_policy_text(pages))

    @property
    def topics(self) -> list[str]:
        return list(self.sections)

    def get(self, topic: str) -> PolicySection | None:
        return self.sections.get(topic)
