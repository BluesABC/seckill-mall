"""S0 static contract checks; NOT Redis/MySQL execution or business acceptance."""
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.platform == "win32":
    sys.path.insert(0, str(ROOT / "build" / "validation-deps"))
# Linux uses its own venv; never import Windows wheels from the mounted checkout.
import sqlglot
from jsonschema import Draft202012Validator, FormatChecker
from lupa import LuaRuntime
import yaml

schema = json.loads((ROOT / "docs/contracts/reserved-event.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())
sample = json.loads((ROOT / "docs/contracts/reserved-event.example.json").read_text(encoding="utf-8"))
validator.validate(sample)
assert sample["eventId"] == sample["reservationId"]
negative_cases = [{"quantity": 2}, {"schemaVersion": 2}, {"priceFen": 1990},
                  {"userId": "0"}, {"eventId": "not-a-uuid"}, {"unknownField": True}]
for mutation in negative_cases:
    invalid = copy.deepcopy(sample)
    invalid.update(mutation)
    assert list(validator.iter_errors(invalid)), f"Unexpected accepted input: {mutation}"

sql = (ROOT / "scripts/sql/001_schema.sql").read_text(encoding="utf-8")
statements = sqlglot.parse(sql, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
assert len(statements) == 10
assert all(s is not None and s.key == "create" for s in statements)

lua = LuaRuntime()
script = (ROOT / "src/seckill/lua/reserve.lua").read_text(encoding="utf-8")
lua.execute("assert(load(...))", script)  # compile only; no mock passed off as Redis

ui = yaml.safe_load((ROOT / ".agents/skills/seckill-mall/agents/openai.yaml").read_text(encoding="utf-8"))
assert ui["policy"]["allow_implicit_invocation"] is True

broken = []
links = 0
files = [ROOT / "README.md", ROOT / "AGENTS.md"]
files += list((ROOT / "docs").rglob("*.md"))
files += list((ROOT / ".agents").rglob("*.md"))
files += list((ROOT / "tests/reports").glob("*.md"))
for path in files:
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if "://" in target or target.startswith("#"):
            continue
        links += 1
        if not (path.parent / target.split("#", 1)[0]).exists():
            broken.append(f"{path}: {target}")
assert not broken, broken

result = {"stage": "S0", "platform": sys.platform, "schemaPositive": 1, "schemaNegative": len(negative_cases),
          "mysqlStatementsParsed": len(statements), "luaSyntax": "pass", "markdownLinks": links,
          "redisExecution": "not_run", "mysqlExecution": "not_run", "businessLoadTest": "not_run"}
report_dir = ROOT / "tests/reports" / ("windows" if sys.platform == "win32" else "wsl")
report_dir.mkdir(parents=True, exist_ok=True)
target = report_dir / "s0-contract-checks.json"
target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
