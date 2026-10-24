"""Headless end-to-end run of the whole pipeline (no UI) – handy to verify a Groq setup.

python scripts/cli_pipeline.py [REQ-1_purpose_code]      # uses LLM_PROVIDER from .env
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.init_db import DEMO_PASSWORD  # noqa: E402
from app.services.auth import authenticate  # noqa: E402
from app.services.container import build_services  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "REQ-1_purpose_code"
req_file = next((get_settings().sample_data_dir / "requirements").glob(f"{name}*.md"))
svc, o = build_services(), None
o = svc.orchestrator
ba, tl, dev, qa = (authenticate(u, DEMO_PASSWORD) for u in ("ba", "techlead", "dev", "qa"))
print(f"LLM provider: {svc.llm.name}")

req = o.create_requirement(ba, name, req_file.read_text("utf-8"))
imp = o.run_impact_analysis(ba, req)
print(f"1. impact analysis #{imp.id} PENDING_REVIEW")
o.review(tl, "IMPACT_ANALYSIS", imp.id, "APPROVED")
story = o.generate_story(ba, imp.id)
o.review(ba, "USER_STORY", story.id, "APPROVED")
print(f"2. user story #{story.id} approved, ADO work item created")
code = o.generate_code(dev, story.id)
for cid in code.ids:
    o.review(dev, "CODE_CHANGE", cid, "APPROVED")
print(f"3. code adopted at {o.adopt_code(dev, story.id)}")
tests = o.generate_tests(qa, story.id)
for tid in tests.ids:
    o.review(qa, "TEST_SCENARIO", tid, "APPROVED")
o.run_tests(qa, story.id)
print("4. automated tests executed (run 1)")
