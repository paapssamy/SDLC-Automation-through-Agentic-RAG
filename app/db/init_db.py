"""Create the pgvector extension, tables, indexes, audit trigger and seed data.

Run:  python -m app.db.init_db        (add --reset to drop everything first)
"""

from __future__ import annotations

import sys

import bcrypt
from sqlalchemy import select, text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.db import models
from app.db.base import Base, get_engine, new_session

AUDIT_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION audit_log_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log;
CREATE TRIGGER trg_audit_log_no_update
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_block_change();
"""

DEMO_PASSWORD = "Demo@123"
SEED_USERS = [
    ("ba", "Samy Business", "ba@demo.local", "BUSINESS_ANALYST"),
    ("techlead", "Tarun Lead", "techlead@demo.local", "TECHNICAL_LEAD"),
    ("dev", "Dev Kumar", "dev@demo.local", "DEVELOPER"),
    ("qa", "Queenie QA", "qa@demo.local", "QA_LEAD"),
    ("admin", "Adam Admin", "admin@demo.local", "ADMIN"),
]


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=10)).decode()


def create_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(AUDIT_TRIGGER_SQL))


def drop_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS audit_log CASCADE"))
    Base.metadata.drop_all(engine)


def seed(engine: Engine) -> None:
    """Idempotent seed: users, guidelines (from sample_data/guidelines), integration config."""
    from sqlalchemy.orm import Session

    cfg = get_settings()
    with Session(engine) as s:
        if not s.scalars(select(models.User)).first():
            for uname, full, email, role in SEED_USERS:
                s.add(
                    models.User(
                        username=uname,
                        full_name=full,
                        email=email,
                        role=role,
                        password_hash=hash_password(DEMO_PASSWORD),
                    )
                )
        if not s.scalars(select(models.Guideline)).first():
            gdir = cfg.sample_data_dir / "guidelines"
            for f in sorted(gdir.glob("*.md")):
                text_ = f.read_text(encoding="utf-8")
                title = text_.splitlines()[0].lstrip("# ").strip() if text_ else f.stem
                s.add(models.Guideline(category=f.stem, title=title, content=text_))
        if not s.scalars(select(models.IntegrationConfig)).first():
            s.add_all(
                [
                    models.IntegrationConfig(
                        system_name="ADO",
                        base_url=cfg.ado_org_url or None,
                        project_or_space=cfg.ado_project or None,
                        secret_ref="ADO_PAT",
                        settings={"mode": cfg.ado_mode, "last_processed_release_id": None},
                    ),
                    models.IntegrationConfig(
                        system_name="CONFLUENCE",
                        base_url=cfg.confluence_base_url or None,
                        project_or_space=cfg.confluence_space or None,
                        secret_ref="CONFLUENCE_API_TOKEN",
                        settings={"mode": cfg.confluence_mode},
                    ),
                    models.IntegrationConfig(
                        system_name="LLM",
                        base_url=None,
                        project_or_space=None,
                        secret_ref="GROQ_API_KEY",
                        settings={"provider": cfg.llm_provider, "model": cfg.groq_model},
                    ),
                ]
            )
        s.commit()


def init_db(reset: bool = False, engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    if reset:
        drop_schema(engine)
    create_schema(engine)
    seed(engine)


if __name__ == "__main__":
    init_db(reset="--reset" in sys.argv)
    with new_session() as _s:
        n = len(_s.scalars(select(models.User)).all())
    print(f"Database ready. Tables: {len(Base.metadata.tables)}, users seeded: {n}")
