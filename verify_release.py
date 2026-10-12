from pathlib import Path
import hashlib, json, sys
root = Path(__file__).resolve().parent
m = json.loads((root / "RELEASE_MANIFEST.json").read_text())
errors = []
for name, expected in m["files"].items():
    target = root / name
    if Path(name).is_absolute() or not target.resolve().is_relative_to(root):
        errors.append([name, "path outside root"])
    elif not target.is_file():
        errors.append([name, "missing"])
    elif hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        errors.append([name, "hash mismatch"])
print(json.dumps({"status": "FAIL" if errors else "PASS_RELEASE_FILE_HASHES", "listed_files": len(m["files"]), "errors": errors}))
sys.exit(bool(errors))
