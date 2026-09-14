"""Filesystem boundary and atomic publication helpers for assembly bundles."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


OUTPUT_NAMES = {
    "assembly.blend", "textures/print-front.png", "verification.json",
    "preview-perspective.png", "preview-reference.png",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files_below(directory):
    return {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}


def _reject_symlink_components(path, root):
    absolute = Path(path).absolute()
    current = Path(absolute.anchor)
    below_root = False
    for part in absolute.parts[1:]:
        current /= part
        # System-level aliases such as macOS /var are outside the repository
        # boundary.  Reject only symlinks at or below the resolved repository.
        if not below_root and current.resolve() == root:
            below_root = True
            continue
        if below_root and current.is_symlink():
            raise RuntimeError(f"output path must not use a symlink: {current}")


def resolve_output_boundary(repository_root, requested_output, input_paths):
    """Return a safe, repository-contained output directory.

    The output cannot equal or contain any input.  Checking every lexical path
    component prevents a symlinked parent from turning a force replacement into
    a write outside the requested repository boundary.
    """
    root = Path(repository_root).resolve()
    requested = Path(requested_output).absolute()
    _reject_symlink_components(requested, root)
    output = requested.resolve()
    try:
        output.relative_to(root)
    except ValueError as error:
        raise RuntimeError("--output-dir must be a dedicated directory below the repository root") from error
    if output == root:
        raise RuntimeError("--output-dir must not be the repository root")
    for source in input_paths:
        input_path = Path(source).resolve()
        if output == input_path or output in input_path.parents:
            raise RuntimeError(f"--output-dir must not contain an input: {input_path}")
    return output


def assert_replaceable(output, current_input_hashes, force):
    """Reject mutations unless both input and output provenance are unchanged."""
    if not output.exists() or not files_below(output):
        return
    manifest_path = output / "build-manifest.json"
    if not manifest_path.is_file():
        if not force:
            raise RuntimeError("existing output has no build-manifest.json; choose another --output-dir or pass --force")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_outputs = manifest["output_hashes"]
        expected_inputs = manifest["input_hashes"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        if not force:
            raise RuntimeError(f"existing output manifest is invalid: {error}; choose another --output-dir or pass --force")
        return
    actual_names = files_below(output) - {"build-manifest.json"}
    if set(expected_outputs) != actual_names:
        reason = "existing output has missing or unknown files"
    else:
        changed = [name for name, digest in expected_outputs.items() if sha256(output / name) != digest]
        reason = "existing output differs from its manifest: " + ", ".join(changed) if changed else ""
    if not reason and expected_inputs != current_input_hashes:
        reason = "existing output was built from different inputs"
    if reason and not force:
        raise RuntimeError(reason + "; choose another --output-dir or pass --force")


def create_staging(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=output.name + ".staging-", dir=output.parent))


def publish_staging(staging, output, replace=os.replace):
    """Publish staging atomically, rolling back the old bundle on final failure."""
    staging, output = Path(staging), Path(output)
    if not output.exists():
        replace(staging, output)
        return
    backup = Path(tempfile.mkdtemp(prefix=output.name + ".backup-", dir=output.parent))
    backup.rmdir()
    replace(output, backup)
    try:
        replace(staging, output)
    except Exception:
        replace(backup, output)
        raise
    try:
        shutil.rmtree(backup)
    except OSError:
        # Publication is complete.  Preserve the backup for manual recovery
        # rather than deleting the new bundle or reporting it as incomplete.
        pass
