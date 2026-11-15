"""Validate a run folder against the Tsunami contracts.
Usage: python scripts/validate.py runs/nfl/2026-11-12_thursday
Exit code 1 if any file is invalid. Missing files are reported, not fatal."""
import json, sys, pathlib
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
HERE = pathlib.Path(__file__).resolve().parent.parent / "schemas"
schemas = {p.name: json.loads(p.read_text()) for p in HERE.glob("*.schema.json")}
reg = Registry().with_resources([(n, Resource.from_contents(s)) for n, s in schemas.items()])
FILES = {"manifest.json": "manifest", "odds.json": "odds", "injuries.json": "injuries", "models.json": "models",
         "stats.json": "stats", "scored.json": "scored", "audit.json": "audit"}
def check(path, schema_name, data=None):
    v = Draft202012Validator(schemas[f"{schema_name}.schema.json"], registry=reg, format_checker=FormatChecker())
    data = data if data is not None else json.loads(path.read_text())
    errs = sorted(v.iter_errors(data), key=lambda e: list(e.path))
    for e in errs[:20]:
        print(f"  ✗ {path.name} @ {'/'.join(map(str, e.path)) or '(root)'}: {e.message[:160]}")
    return not errs
def main(folder):
    folder = pathlib.Path(folder); ok = True
    for f, sname in FILES.items():
        p = folder / f
        if not p.exists(): print(f"  – {f}: missing"); continue
        good = check(p, sname); ok &= good
        if good: print(f"  ✓ {f}")
    ev = folder / "events.jsonl"
    if ev.exists():
        bad = sum(not check(ev, "event", json.loads(l)) for l in ev.read_text().splitlines() if l.strip())
        print(f"  {'✓' if not bad else '✗'} events.jsonl ({bad} bad lines)"); ok &= not bad
    sys.exit(0 if ok else 1)
if __name__ == "__main__":
    main(sys.argv[1])
