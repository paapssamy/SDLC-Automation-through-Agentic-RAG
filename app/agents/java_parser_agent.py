"""Agent 1 – Java Parser Agent (module 3.1, As-Is Documentation).

Parses Java source with `javalang` (packages, classes, nested classes, interfaces, enums,
methods, fields, imports), groups classes into services (one service per package) and asks the
LLM to write the functional description. Maker = this agent, Checker = Technical Lead.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import javalang
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base_agent import BaseAgent
from app.db import models
from app.errors import GenerationError
from app.prompts import render
from app.rag.context_builder import Context
from app.rag.embedding_service import get_embedder
from app.services.approval_service import SubmitResult

log = logging.getLogger(__name__)


# ------------------------------------------------------------------------------ parsing
@dataclass
class ClassInfo:
    name: str
    kind: str  # class | interface | enum
    package: str
    methods: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    extends: str | None = None
    parent: str | None = None  # name of the enclosing class for nested classes
    file: str = ""
    description: str = ""  # first sentence of the Javadoc comment

    @property
    def is_nested(self) -> bool:
        return self.parent is not None


def _first_sentence(doc: str | None) -> str:
    if not doc:
        return ""
    text = " ".join(line.strip(" */") for line in doc.splitlines()).strip()
    return text.split(". ")[0].rstrip(".")


def _collect(
    decl, package: str, imports: list[str], parent: str | None, file: str, out: list[ClassInfo]
) -> None:
    kind = {
        "ClassDeclaration": "class",
        "InterfaceDeclaration": "interface",
        "EnumDeclaration": "enum",
    }.get(type(decl).__name__)
    if kind is None:
        return
    info = ClassInfo(
        decl.name,
        kind,
        package,
        imports=imports,
        parent=parent,
        file=file,
        description=_first_sentence(decl.documentation),
    )
    if kind == "class":
        info.extends = decl.extends.name if decl.extends else None
        info.implements = [i.name for i in (decl.implements or [])]
    elif kind == "interface":
        info.extends = decl.extends[0].name if decl.extends else None
    out.append(info)
    body = decl.body.declarations if kind == "enum" else decl.body
    for member in body or []:
        mname = type(member).__name__
        if mname == "MethodDeclaration":
            params = ", ".join(p.type.name for p in member.parameters)
            info.methods.append(f"{member.name}({params})")
        elif mname == "ConstructorDeclaration":
            info.methods.append(f"{member.name}(...)")
        elif mname == "FieldDeclaration":
            for d in member.declarators:
                info.fields.append(f"{member.type.name} {d.name}")
        else:  # nested class / interface / enum: walk into it
            _collect(member, package, imports, decl.name, file, out)


def parse_java_source(code: str, file: str = "") -> list[ClassInfo]:
    """Parse one Java file; returns every top-level and nested type."""
    tree = javalang.parse.parse(code)
    package = tree.package.name if tree.package else ""
    imports = [i.path for i in tree.imports]
    out: list[ClassInfo] = []
    for t in tree.types:
        _collect(t, package, imports, None, file, out)
    return out


def parse_folder(folder: Path) -> list[ClassInfo]:
    classes: list[ClassInfo] = []
    for f in sorted(Path(folder).rglob("*.java")):
        try:
            classes += parse_java_source(f.read_text(encoding="utf-8"), str(f))
        except (javalang.parser.JavaSyntaxError, javalang.tokenizer.LexerError) as exc:
            log.warning("Skipping %s: %s", f, exc)
    return classes


@dataclass
class ServiceGroup:
    name: str
    package: str
    classes: list[ClassInfo]

    def structure_text(self, project_classes: set[str]) -> str:
        lines = []
        for c in self.classes:
            head = f"{c.kind} {c.name}"
            if c.parent:
                head += f" (nested in {c.parent})"
            if c.implements:
                head += f" implements {', '.join(c.implements)}"
            if c.extends:
                head += f" extends {c.extends}"
            deps = sorted({i.rsplit(".", 1)[-1] for i in c.imports} & project_classes - {c.name})
            if c.description:
                head += f' - "{c.description}"'
            lines.append(
                f"{head}: methods: {', '.join(c.methods) or '-'} | fields: "
                f"{', '.join(c.fields) or '-'} | depends on: {', '.join(deps) or '-'}"
            )
        return "\n".join(lines)


_ROLE_SUFFIXES = (
    "Service",
    "Controller",
    "Builder",
    "Mapper",
    "Validator",
    "Calculator",
    "Repository",
    "Notifier",
)


def group_into_services(classes: list[ClassInfo]) -> list[ServiceGroup]:
    """One service per package; the name is the anchor class (most methods, not an interface)."""
    by_pkg: dict[str, list[ClassInfo]] = {}
    for c in classes:
        by_pkg.setdefault(c.package, []).append(c)
    groups = []
    for pkg, items in sorted(by_pkg.items()):
        top = [c for c in items if not c.is_nested]
        candidates = [c for c in top if c.kind == "class" and c.methods] or top
        anchor = max(
            candidates, key=lambda c: (c.name.endswith(_ROLE_SUFFIXES), len(c.methods), c.name)
        )
        groups.append(ServiceGroup(anchor.name, pkg, items))
    return groups


# ------------------------------------------------------------------------------ the agent
@dataclass
class DocTask:
    user_id: int | None
    group: ServiceGroup
    structure: str
    market: str = "SG"
    product: str = "PAYMENTS"
    key_entities: list[str] = field(default_factory=list)


class JavaParserAgent(BaseAgent):
    artifact_type = "SERVICE_DOCUMENT"
    name = "JavaParserAgent"
    guideline_categories = ["documentation_style"]

    def document_folder(
        self,
        folder: Path,
        user_id: int | None = None,
        market: str = "SG",
        product: str = "PAYMENTS",
    ) -> list[SubmitResult]:
        """Parse a folder and submit one documentation section per service for review."""
        classes = parse_folder(Path(folder))
        if not classes:
            raise GenerationError(f"No Java classes found in {folder}")
        project_names = {c.name for c in classes}
        results = []
        for g in group_into_services(classes):
            task = DocTask(
                user_id,
                g,
                g.structure_text(project_names),
                market,
                product,
                key_entities=[c.name for c in g.classes],
            )
            existing = self._existing(g.name, market, product)
            if existing and existing.status not in ("REJECTED", "SUPERSEDED", "CHANGES_REQUESTED"):
                log.info("Service %s already documented (%s) – skipped", g.name, existing.status)
                continue
            results.append(self.run(task))
        return results

    @staticmethod
    def _existing(name: str, market: str, product: str):
        from app.db.base import session_scope
        from app.db.repositories import DocumentRepository

        with session_scope() as s:
            return DocumentRepository.by_name(s, name, market, product)

    # -- template steps ---------------------------------------------------------------------
    def build_query(self, task: DocTask) -> str:
        return f"{task.group.name} {' '.join(c.name for c in task.group.classes)}"

    def build_prompt(self, task: DocTask, context: Context) -> str:
        return render(
            "document_service", service_name=task.group.name, structure=task.structure
        ) + (f"\n## GUIDELINES\n{context.guidelines}\n" if context.guidelines else "")

    def validate(self, raw: str, context: Context) -> str:
        text = raw.strip()
        if len(text) < 40:
            raise GenerationError("Documentation text is too short")
        return text

    def persist(self, session: Session, result: str, task: DocTask, context: Context):
        emb = get_embedder().embed(f"{task.group.name}\n{result}")
        digest = hashlib.sha256(result.encode()).hexdigest()
        existing = session.scalars(
            select(models.ServiceDocument).where(
                models.ServiceDocument.service_name == task.group.name,
                models.ServiceDocument.market == task.market,
                models.ServiceDocument.product == task.product,
                models.ServiceDocument.status == "CHANGES_REQUESTED",
            )
        ).first()
        if existing:
            self.approvals.reopen(session, existing, self.name)
            existing.content, existing.content_hash, existing.embedding = result, digest, emb
            return existing
        doc = models.ServiceDocument(
            market=task.market,
            product=task.product,
            service_name=task.group.name,
            content=result,
            content_hash=digest,
            embedding=emb,
            current_version=1,
            created_by=task.user_id,
        )
        session.add(doc)
        session.flush()
        session.add(
            models.DocumentVersion(
                doc_id=doc.doc_id,
                release_id=None,
                version_no=1,
                content=result,
                change_summary="Initial as-is documentation",
            )
        )
        return doc
