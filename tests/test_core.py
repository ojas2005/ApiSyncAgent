import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from api_contract_sync.cli import main
from api_contract_sync.core import (compare_contracts, frontend_uses, parse_sources,
                                    render_report, render_types, scan_git_ref, ts_type)


OLD = '''from pydantic import BaseModel
from fastapi import FastAPI
app = FastAPI()
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
@app.get("/users/{user_id}", response_model=UserResponse)
def user(user_id: int):
    pass
'''

NEW = OLD.replace("username: str", "full_name: str")


class ContractTests(unittest.TestCase):
    def test_rename_finds_breaking_change_and_consumer(self):
        before = parse_sources([("api.py", OLD)])
        after = parse_sources([("api.py", NEW)])
        changes = compare_contracts(before, after)
        self.assertEqual([c["kind"] for c in changes], ["field_added", "field_removed"])
        self.assertEqual([c["breaking"] for c in changes], [False, True])
        self.assertIn("full_name: string", render_types(after))
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "user.ts").write_text(
                'import type { UserResponse } from "./api-contracts";\n'
                'const data = await fetch(`/users/${id}`);\n'
                'console.log(user.username);\n', encoding="utf-8")
            uses = frontend_uses(directory, changes, before, after)
            self.assertEqual(uses[1][0]["line"], 3)
            self.assertIn("user.ts:3", render_report(changes, uses))
            self.assertIn("Possible rename", render_report(changes, uses))
            Path(directory, "profile.tsx").write_text("export const title = user.username;\n", encoding="utf-8")
            broader = frontend_uses(directory, changes, before, after)
            self.assertTrue(any(hit["confidence"] == "field-only" for hit in broader[1]))

    def test_inheritance_alias_and_optional_types(self):
        contract = parse_sources([("models.py", '''from pydantic import BaseModel, Field
from typing import Optional, ClassVar
class Base(BaseModel):
    id: int
    internal: ClassVar[str] = "x"
class User(Base):
    id: int = Field(serialization_alias="user_id")
    name: str = Field(serialization_alias="full_name")
    tags: list[str] = []
    nickname: Optional[str]
''')])
        fields = contract["models"]["User"]["fields"]
        self.assertIn("user_id", fields)
        self.assertNotIn("id", fields)
        self.assertIn("full_name", fields)
        self.assertFalse(fields["tags"]["required"])
        self.assertTrue(fields["nickname"]["required"])
        self.assertNotIn("internal", fields)
        self.assertEqual(ts_type("Optional[list[int]]"), "Array<number> | null")

    def test_cli_snapshot_and_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            (backend / "api.py").write_text(OLD, encoding="utf-8")
            baseline = root / "baseline.json"
            self.assertEqual(main(["snapshot", "--backend", str(backend),
                                   "--output", str(baseline)]), 0)
            self.assertEqual(json.loads(baseline.read_text())["format_version"], 1)
            (backend / "api.py").write_text(NEW, encoding="utf-8")
            types = root / "api-contracts.ts"
            report = root / "report.md"
            self.assertEqual(main(["check", "--backend", str(backend), "--baseline", str(baseline),
                                   "--frontend", str(frontend), "--types-out", str(types),
                                   "--write-types", "--report", str(report),
                                   "--fail-on-breaking"]), 2)
            self.assertTrue(types.exists())
            self.assertIn("BREAKING", report.read_text())
            self.assertEqual(main(["check", "--backend", str(backend), "--baseline", str(baseline),
                                   "--types-out", str(types), "--verify-types"]), 0)

    def test_git_ref_reads_backend_before_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend"
            backend.mkdir()
            (backend / "api.py").write_text(OLD, encoding="utf-8")
            def git(*args):
                subprocess.run(["git", *args], cwd=str(root), check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            git("add", "backend/api.py")
            git("commit", "-m", "baseline")
            (backend / "api.py").write_text(NEW, encoding="utf-8")
            before = scan_git_ref(backend, "HEAD")
            self.assertIn("username", before["models"]["UserResponse"]["fields"])
            self.assertEqual(main(["check", "--backend", str(backend),
                                   "--base-ref", "HEAD", "--fail-on-breaking"]), 2)


if __name__ == "__main__":
    unittest.main()
