from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import content_hash, relative_path


_DECL_RE = re.compile(
    r"^\s*(?P<prefix>(?:@[A-Za-z_][\w.]*(?:\([^)]*\))?\s+|"
    r"public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|"
    r"final\s+|static\s+|class\s+|mutating\s+|nonisolated\s+|override\s+|"
    r"indirect\s+|lazy\s+|weak\s+|unowned\s+)*)"
    r"(?P<kind>class|struct|enum|protocol|actor|extension)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
    r"(?P<rest>[^\{]*)"
)
_FUNC_RE = re.compile(
    r"^\s*(?P<prefix>(?:@[A-Za-z_][\w.]*(?:\([^)]*\))?\s+|"
    r"public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|"
    r"static\s+|class\s+|mutating\s+|nonisolated\s+|override\s+)*)"
    r"func\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*|[+\-*/%=!<>~&|^]+)\s*(?P<rest>.*)"
)
_PROP_RE = re.compile(
    r"^\s*(?P<prefix>(?:@[A-Za-z_][\w.]*(?:\([^)]*\))?\s+|"
    r"public\s+|private\s+|fileprivate\s+|internal\s+|open\s+|"
    r"static\s+|class\s+|private\(set\)\s+|lazy\s+|weak\s+|unowned\s+)*)"
    r"(?P<kind>let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b(?P<rest>.*)"
)
_IMPORT_RE = re.compile(r"^\s*(?:@testable\s+)?import\s+(?P<module>[A-Za-z_][A-Za-z0-9_.]*)")
_CASE_RE = re.compile(
    r"^\s*case\s+"
    r"(?P<cases>[A-Za-z_][A-Za-z0-9_]*(?:\s*=\s*[^,]+)?"
    r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*(?:\s*=\s*[^,]+)?)*)"
)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_TYPE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")

_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "guard",
    "return",
    "super",
    "self",
    "init",
    "deinit",
    "where",
    "try",
    "await",
    "Task",
}
_TYPE_WORDS_TO_IGNORE = {
    "String",
    "Int",
    "Double",
    "Float",
    "Bool",
    "Decimal",
    "Date",
    "UUID",
    "URL",
    "Data",
    "Array",
    "Dictionary",
    "Set",
    "Optional",
    "Any",
    "Never",
    "Void",
    "Result",
    "Error",
}
_SCOPE_TYPES = {"class", "method", "function", "enum", "protocol", "extension"}


@dataclass
class _SymbolDraft:
    id: str
    type: str
    name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    parent_id: str | None = None
    signature: str | None = None
    docstring: str | None = None
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    calls: set[str] = field(default_factory=set)
    references: set[str] = field(default_factory=set)
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def freeze(self) -> AstSymbol:
        return AstSymbol(
            id=self.id,
            type=self.type,
            name=self.name,
            file_path=self.file_path,
            language=self.language,
            start_line=self.start_line,
            end_line=max(self.end_line, self.start_line),
            parent_id=self.parent_id,
            signature=self.signature,
            docstring=self.docstring,
            imports=self.imports,
            exports=self.exports,
            bases=self.bases,
            implements=self.implements,
            decorators=self.decorators,
            calls=sorted(self.calls),
            references=sorted(self.references),
            hash=self.hash,
            metadata=self.metadata,
        )


class SwiftAstParser:
    """Best-effort Swift parser for CodeWiki symbol indexing.

    Swift does not currently have a tree-sitter dependency in CodeWiki. This parser
    extracts common declarations, imports, enum cases, properties, and simple
    call/reference names without requiring SourceKit or a native grammar.
    """

    language = "swift"

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        return self.parse_content(path, content, repo_root=repo_root)

    def parse_content(
        self,
        path: Path,
        content: str,
        *,
        repo_root: Path | None = None,
    ) -> list[AstSymbol]:
        file_path = relative_path(path, repo_root)
        file_hash = content_hash(content)
        lines = content.splitlines()
        drafts: list[_SymbolDraft] = [
            _SymbolDraft(
                id=f"file:{file_path}",
                type="file",
                name=Path(file_path).name,
                file_path=file_path,
                language=self.language,
                start_line=1,
                end_line=max(1, len(lines)),
                imports=_extract_imports(lines),
                hash=file_hash,
                metadata={"language_enhancer": "swift", "parser": "swift_regex"},
            )
        ]
        stack: list[tuple[int, int]] = []
        brace_depth = 0
        pending_scope_idx: int | None = None
        pending_doc: list[str] = []
        in_block_comment = False

        for line_number, raw_line in enumerate(lines, start=1):
            code, in_block_comment = _strip_comments_and_strings(raw_line, in_block_comment)
            stripped = code.strip()
            raw_stripped = raw_line.strip()
            if raw_stripped.startswith("///") or raw_stripped.startswith("/**"):
                pending_doc.append(raw_stripped.lstrip("/ *"))
            elif stripped and not raw_stripped.startswith("//"):
                # Keep doc comments attached only until the next declaration.
                pass

            while stack and brace_depth < stack[-1][1]:
                idx, _target_depth = stack.pop()
                drafts[idx].end_line = max(drafts[idx].start_line, line_number - 1)

            parent_id = drafts[stack[-1][0]].id if stack else None
            created_idx: int | None = None
            decl_match = _DECL_RE.match(code)
            if decl_match:
                created_idx = self._add_decl(
                    drafts, decl_match, file_path, file_hash, line_number, parent_id, pending_doc
                )
                pending_doc = []
            else:
                func_match = _FUNC_RE.match(code)
                if func_match:
                    created_idx = self._add_func(
                        drafts, func_match, file_path, file_hash, line_number, parent_id, pending_doc
                    )
                    pending_doc = []
                else:
                    prop_match = _PROP_RE.match(code)
                    if prop_match and not _looks_like_local_property(drafts, stack):
                        created_idx = self._add_property(
                            drafts,
                            prop_match,
                            file_path,
                            file_hash,
                            line_number,
                            parent_id,
                            pending_doc,
                        )
                        pending_doc = []
                    else:
                        case_match = _CASE_RE.match(code)
                        if case_match and _parent_is_enum(drafts, stack):
                            self._add_enum_cases(
                                drafts, case_match, file_path, file_hash, line_number, parent_id
                            )

            active_idx = created_idx or pending_scope_idx or (stack[-1][0] if stack else None)
            if active_idx is not None:
                _add_calls_and_refs(drafts[active_idx], code)

            open_braces = code.count("{")
            close_braces = code.count("}")
            new_depth = brace_depth + open_braces - close_braces
            scope_idx = (
                created_idx
                if created_idx is not None and drafts[created_idx].type in _SCOPE_TYPES
                else pending_scope_idx
            )
            if scope_idx is not None and new_depth > brace_depth:
                stack.append((scope_idx, new_depth))
                pending_scope_idx = None
            elif created_idx is not None:
                if drafts[created_idx].type in _SCOPE_TYPES and open_braces == 0:
                    pending_scope_idx = created_idx
                else:
                    drafts[created_idx].end_line = line_number
            brace_depth = max(0, new_depth)

        for idx, _target_depth in stack:
            drafts[idx].end_line = max(drafts[idx].start_line, len(lines))

        drafts[0].exports = _file_exports(drafts)
        return [draft.freeze() for draft in drafts]

    def _add_decl(
        self,
        drafts: list[_SymbolDraft],
        match: re.Match[str],
        file_path: str,
        file_hash: str,
        line_number: int,
        parent_id: str | None,
        pending_doc: list[str],
    ) -> int:
        kind = match.group("kind")
        name = match.group("name")
        symbol_type = {"struct": "class", "actor": "class"}.get(kind, kind)
        prefix = match.group("prefix") or ""
        rest = match.group("rest") or ""
        bases = _parse_type_list(rest)
        symbol_id = _declaration_id(file_path, kind, name, line_number, parent_id)
        draft = _SymbolDraft(
            id=symbol_id,
            type=symbol_type,
            name=name,
            file_path=file_path,
            language=self.language,
            start_line=line_number,
            end_line=line_number,
            parent_id=parent_id,
            signature=_clean_signature(match.string),
            docstring="\n".join(pending_doc).strip() or None,
            bases=bases if kind in {"class", "struct", "actor"} else [],
            implements=bases if kind in {"protocol", "extension"} else [],
            references=set(bases),
            hash=file_hash,
            metadata={
                "parser": "swift_regex",
                "swift_kind": kind,
                "exported": _is_exported(prefix, name),
                "confidence": 0.66,
            },
        )
        drafts.append(draft)
        return len(drafts) - 1

    def _add_func(
        self,
        drafts: list[_SymbolDraft],
        match: re.Match[str],
        file_path: str,
        file_hash: str,
        line_number: int,
        parent_id: str | None,
        pending_doc: list[str],
    ) -> int:
        name = match.group("name")
        prefix = match.group("prefix") or ""
        parent = _find_draft(drafts, parent_id)
        symbol_type = "method" if parent and parent.type in {"class", "protocol", "extension"} else "function"
        draft = _SymbolDraft(
            id=_member_id(file_path, name, parent_id),
            type=symbol_type,
            name=name,
            file_path=file_path,
            language=self.language,
            start_line=line_number,
            end_line=line_number,
            parent_id=parent_id,
            signature=_clean_signature(match.string),
            docstring="\n".join(pending_doc).strip() or None,
            hash=file_hash,
            metadata={
                "parser": "swift_regex",
                "swift_kind": "func",
                "exported": _is_exported(prefix, name),
                "confidence": 0.64,
            },
        )
        drafts.append(draft)
        return len(drafts) - 1

    def _add_property(
        self,
        drafts: list[_SymbolDraft],
        match: re.Match[str],
        file_path: str,
        file_hash: str,
        line_number: int,
        parent_id: str | None,
        pending_doc: list[str],
    ) -> int:
        name = match.group("name")
        prefix = match.group("prefix") or ""
        kind = match.group("kind")
        draft = _SymbolDraft(
            id=_member_id(file_path, name, parent_id),
            type="variable",
            name=name,
            file_path=file_path,
            language=self.language,
            start_line=line_number,
            end_line=line_number,
            parent_id=parent_id,
            signature=_clean_signature(match.string),
            docstring="\n".join(pending_doc).strip() or None,
            hash=file_hash,
            metadata={
                "parser": "swift_regex",
                "swift_kind": kind,
                "exported": _is_exported(prefix, name),
                "confidence": 0.55,
            },
        )
        _add_calls_and_refs(draft, match.group("rest") or "")
        drafts.append(draft)
        return len(drafts) - 1

    def _add_enum_cases(
        self,
        drafts: list[_SymbolDraft],
        match: re.Match[str],
        file_path: str,
        file_hash: str,
        line_number: int,
        parent_id: str | None,
    ) -> None:
        for raw_case in match.group("cases").split(","):
            name = raw_case.strip().split("=", 1)[0].strip()
            if not name:
                continue
            drafts.append(
                _SymbolDraft(
                    id=_member_id(file_path, name, parent_id),
                    type="variable",
                    name=name,
                    file_path=file_path,
                    language=self.language,
                    start_line=line_number,
                    end_line=line_number,
                    parent_id=parent_id,
                    signature=f"case {name}",
                    hash=file_hash,
                    metadata={"parser": "swift_regex", "swift_kind": "case", "confidence": 0.58},
                )
            )


def _declaration_id(file_path: str, kind: str, name: str, line_number: int, parent_id: str | None) -> str:
    if parent_id is not None:
        return _member_id(file_path, name, parent_id)
    if kind == "extension":
        return f"{file_path}::extension:{name}:{line_number}"
    return f"{file_path}::{name}"


def _member_id(file_path: str, name: str, parent_id: str | None) -> str:
    if parent_id is None:
        return f"{file_path}::{name}"
    return f"{parent_id}.{name}"


def _find_draft(drafts: list[_SymbolDraft], symbol_id: str | None) -> _SymbolDraft | None:
    if symbol_id is None:
        return None
    for draft in reversed(drafts):
        if draft.id == symbol_id:
            return draft
    return None


def _file_exports(drafts: list[_SymbolDraft]) -> list[str]:
    exports = [
        draft.name
        for draft in drafts[1:]
        if draft.parent_id is None
        and draft.type in {"class", "enum", "function", "protocol"}
        and draft.metadata.get("exported")
    ]
    return sorted(set(exports))


def _extract_imports(lines: list[str]) -> list[str]:
    imports: list[str] = []
    for line in lines:
        match = _IMPORT_RE.match(line)
        if match:
            imports.append(match.group("module"))
    return sorted(set(imports))


def _strip_comments_and_strings(line: str, in_block_comment: bool) -> tuple[str, bool]:
    out: list[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if not in_string and ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if not in_string and ch == "/" and nxt == "/":
            break
        if ch == '"' and not escape:
            in_string = not in_string
            out.append('""')
            i += 1
            continue
        if in_string:
            escape = ch == "\\" and not escape
            if ch != "\\":
                escape = False
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block_comment


def _clean_signature(line: str) -> str:
    return line.strip().rstrip("{").strip()


def _parse_type_list(rest: str) -> list[str]:
    if ":" not in rest:
        return []
    after_colon = rest.split(":", 1)[1]
    after_colon = after_colon.split("where", 1)[0].split("{", 1)[0]
    values: list[str] = []
    for part in after_colon.split(","):
        value = re.sub(r"<.*>", "", part).strip()
        value = value.split("=", 1)[0].strip()
        if value and re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", value):
            values.append(value)
    return values


def _is_exported(prefix: str, name: str) -> bool:
    return any(token in prefix.split() for token in ("public", "open")) or name[:1].isupper()


def _looks_like_local_property(drafts: list[_SymbolDraft], stack: list[tuple[int, int]]) -> bool:
    return bool(stack and drafts[stack[-1][0]].type in {"function", "method"})


def _parent_is_enum(drafts: list[_SymbolDraft], stack: list[tuple[int, int]]) -> bool:
    return bool(stack and drafts[stack[-1][0]].metadata.get("swift_kind") == "enum")


def _add_calls_and_refs(draft: _SymbolDraft, code: str) -> None:
    for name in _CALL_RE.findall(code):
        if name not in _KEYWORDS and name not in _TYPE_WORDS_TO_IGNORE and name != draft.name:
            draft.calls.add(name)
    for name in _TYPE_RE.findall(code):
        if name not in _TYPE_WORDS_TO_IGNORE and name != draft.name:
            draft.references.add(name)
