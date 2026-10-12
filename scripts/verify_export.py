"""Verify an explicit public-export mapping; never claim original byte identity."""
import hashlib, json
from pathlib import Path

def verify_original_files(root, manifest):
    root = Path(root).resolve(); base = root.parent
    export = json.loads((base/'EXPORT_PROVENANCE.json').read_text())
    commitment = export['commitments'][root.name]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(root/'manifest.json') != commitment['original_manifest_sha256']:
        raise ValueError('ORIGINAL_COMMITMENT_DRIFT')
    if set(commitment['files']) != set(manifest['files']):
        raise ValueError('INCOMPLETE_EXPORT_MAPPING')
    for name, original in manifest['files'].items():
        row = commitment['files'][name]; path = root/name
        if not path.resolve().is_relative_to(base) or path.is_symlink():
            raise ValueError('EXPORT_PATH_BOUNDARY')
        if row['original_sha256'] != original or digest(path) != row['exported_sha256']:
            raise ValueError('PUBLIC_EXPORT_DRIFT:'+name)
