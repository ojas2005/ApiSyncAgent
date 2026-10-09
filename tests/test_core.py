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


