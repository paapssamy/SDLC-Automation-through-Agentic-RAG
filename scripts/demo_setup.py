"""Prepare the demo environment.

python scripts/demo_setup.py            # create DB objects + seed users (keeps data)
python scripts/demo_setup.py --reset    # wipe everything first
python scripts/demo_setup.py --kb       # also generate + approve the as-is documentation
                                        # (so RAG has a knowledge base on first login)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import models  # noqa: E402
from app.db.base import session_scope  # noqa: E402
from app.db.init_db import DEMO_PASSWORD, init_db  # noqa: E402
from app.services.auth import authenticate  # noqa: E402
from app.services.container import build_services  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop all tables first")
    ap.add_argument("--kb", action="store_true", help="generate and approve as-is documentation")
    args = ap.parse_args()

    init_db(reset=args.reset)
    print("Database ready (tables, HNSW index, audit trigger, seed users, guidelines).")

    if args.kb:
        svc = build_services()
        tl = authenticate("techlead", DEMO_PASSWORD)
        with session_scope() as s:
            existing = len(s.scalars(select(models.ServiceDocument)).all())
        if existing:
            print(f"Knowledge base already has {existing} section(s) – skipped.")
        else:
            print(f"Generating documentation with LLM provider '{svc.llm.name}' …")
            results = svc.orchestrator.generate_documentation(tl)
            for r in results:
                svc.orchestrator.review(
                    tl, "SERVICE_DOCUMENT", r.id, "APPROVED", "Auto-approved by demo setup"
                )
            print(
                f"{len(results)} documentation sections generated, approved by "
                "techlead and published to workspace/confluence/."
            )

    print("\nDemo users (password for all: %s):" % DEMO_PASSWORD)
    print("  ba=Business Analyst  techlead=Technical Lead  dev=Developer  qa=QA Lead  admin=Admin")
    print("\nStart the UI:  streamlit run app/ui/Home.py")


if __name__ == "__main__":
    main()
