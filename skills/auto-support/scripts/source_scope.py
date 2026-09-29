"""Source-bound Markdown dependencies, separate from legacy semantic heuristics.

The graph records syntactic ancestry, grouping decisions and explicit references. It
does not prove that unannotated prose has no additional semantic dependencies.
"""
from dataclasses import dataclass
import hashlib
import re
from urllib.parse import unquote


_ALL_SECTIONS = re.compile(
    r"\b(?:all|every|each)\s+(?:the\s+)?sections?\s+(?:below\s+)?"
    r"(?:are|is)\s+(?:mandatory|required)\b", re.I)
_LINK = re.compile(r"(?<!!)\[[^\]\r\n]*\]\(\s*<?#([^\s)>]+)>?(?:\s+[^)]*)?\)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_EXPLICIT_ID = re.compile(r"\s*\{#([^{}\s]+)\}\s*$")


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class SourceRange:
    """Zero-based, half-open lines with a digest of their original text."""
    start: int
    end: int
    sha256: str


@dataclass(frozen=True)
class Section:
    key: int
    source: SourceRange


@dataclass(frozen=True)
class Dependency:
    source: int
    target: int
    reason: str
    evidence: SourceRange


@dataclass(frozen=True)
class ScopeRelation:
    left: int
    right: int
    relation: str
    evidence: tuple[SourceRange, SourceRange]
    explanation: str


@dataclass(frozen=True)
class SourceScope:
    source_sha256: str
    sections: tuple[Section, ...]
    dependencies: tuple[Dependency, ...]
    unresolved_references: tuple[SourceRange, ...] = ()
    interpretation: str = 'explicit references and legacy grouping; implicit semantics unresolved'
    semantic_relations: tuple[ScopeRelation, ...] = ()

    def verify_source(self, lines):
        if _digest(''.join(lines)) != self.source_sha256:
            return False
        keys = {section.key for section in self.sections}
        if len(keys) != len(self.sections):
            return False
        ranges = [section.source for section in self.sections]
        ranges += [edge.evidence for edge in self.dependencies]
        ranges += list(self.unresolved_references)
        ranges += [span for relation in self.semantic_relations for span in relation.evidence]
        return (all(edge.source in keys and edge.target in keys for edge in self.dependencies)
                and all(relation.left in keys and relation.right in keys
                        for relation in self.semantic_relations)
                and all(0 <= span.start < span.end <= len(lines)
                        and _digest(''.join(lines[span.start:span.end])) == span.sha256
                        for span in ranges))

    def required_sections(self, selected):
        required = set(selected)
        keys = {section.key for section in self.sections}
        if not required <= keys:
            raise ValueError('unknown source section')
        pending = list(required)
        while pending:
            current = pending.pop()
            for edge in self.dependencies:
                if edge.source == current and edge.target not in required:
                    required.add(edge.target)
                    pending.append(edge.target)
        return required


def build_scope(lines, spans, headings, groups):
    """Bind exact source intervals to explicit edges and declared legacy groups.

    A document preamble is inherited as its own range. Only an explicit all-sections
    declaration expands that preamble to every peer. Same-document Markdown links
    resolve against heading anchors; unresolved targets invalidate the extraction.
    """
    def source_range(start, end):
        return SourceRange(start, end, _digest(''.join(lines[start:end])))

    sections = [Section(index, source_range(start, end)) for index, (start, end) in enumerate(spans)]
    preamble_end = spans[0][0] if spans else 0
    if preamble_end:
        sections.insert(0, Section(-1, source_range(0, preamble_end)))
    dependencies = []
    unresolved = []

    def owner(line):
        return next(section.key for section in sections if section.source.start <= line < section.source.end)

    if preamble_end:
        preamble = source_range(0, preamble_end)
        dependencies.extend(Dependency(index, -1, 'document-preamble', preamble) for index in range(len(spans)))
        for index, line in enumerate(lines[:preamble_end]):
            if _ALL_SECTIONS.search(line):
                dependencies.extend(Dependency(-1, target, 'document-scope', source_range(index, index+1))
                                    for target in range(len(spans)))

    for start, end in groups:
        members = [index for index, (begin, finish) in enumerate(spans) if start <= begin and finish <= end]
        for left, right in zip(members, members[1:]):
            evidence = source_range(start, end)
            dependencies.extend((Dependency(left, right, 'legacy-group', evidence),
                                 Dependency(right, left, 'legacy-group', evidence)))

    anchors = {}
    seen = {}
    for line, _ in headings:
        title = re.sub(r'^ {0,3}#{1,6}\s+', '', lines[line]).strip()
        title = re.sub(r'\s+#+\s*$', '', title)
        explicit = _EXPLICIT_ID.search(title)
        if explicit:
            name = explicit[1]
            if name in anchors:
                unresolved.append(source_range(line, line+1))
            anchors[name] = owner(line)
            title = title[:explicit.start()]
        slug = re.sub(r'[^\w\-\s]', '', title.casefold()).strip().replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors[slug + ('-'+str(count) if count else '')] = owner(line)

    fence = None
    for index, line in enumerate(lines):
        marker = _FENCE.match(line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        # Inline code contains examples of link syntax, not authored links.
        comparison = re.sub(r'(`+).*?\1', '', line)
        for link in _LINK.finditer(comparison):
            target = anchors.get(unquote(link[1]))
            evidence = source_range(index, index+1)
            if target is None:
                unresolved.append(evidence)
            else:
                dependencies.append(Dependency(owner(index), target, 'markdown-reference', evidence))
    graph = SourceScope(_digest(''.join(lines)), tuple(sections), tuple(dependencies), tuple(unresolved))
    if not graph.verify_source(lines):
        raise ValueError('source-scope graph is not bound to this document')
    return graph
