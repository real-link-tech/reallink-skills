#!/usr/bin/env python3
"""
RDC Analysis Skill - Runtime Setup
===================================
Deploy the bundled Python 3.6 + renderdoc runtime from assets/runtime/
to a working directory so rdc_export.py can run standalone.

Usage:
    python setup.py                       # Deploy to default location
    python setup.py --target <dir>        # Deploy to specific directory
    python setup.py --check               # Check if runtime is deployed
"""

import sys
import os
import shutil
import hashlib

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
RUNTIME_SRC = os.path.join(ASSETS_DIR, "runtime")


def _default_deploy_dir():
    """Default deployment target: <workspace>/.rdc-analysis-runtime/"""
    # Walk up from skill dir to find workspace root (look for .git or .claude)
    d = SKILL_DIR
    for _ in range(10):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
        if os.path.isdir(os.path.join(d, ".git")) or os.path.isdir(os.path.join(d, ".claude")):
            return os.path.join(d, ".rdc-analysis-runtime")
    # Fallback: next to skill dir
    return os.path.join(os.path.dirname(SKILL_DIR), ".rdc-analysis-runtime")


def _compute_manifest_hash(src_dir):
    """Hash all files in src_dir to create a version fingerprint."""
    h = hashlib.sha1()
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, src_dir)
            h.update(rel.encode("utf-8"))
            h.update(str(os.path.getsize(fpath)).encode("utf-8"))
    return h.hexdigest()


def _read_deployed_hash(deploy_dir):
    stamp = os.path.join(deploy_dir, ".setup_hash")
    if os.path.isfile(stamp):
        try:
            with open(stamp, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return None


def _write_deployed_hash(deploy_dir, h):
    with open(os.path.join(deploy_dir, ".setup_hash"), "w") as f:
        f.write(h + "\n")


def check_deployed(deploy_dir=None):
    """Return True if runtime is deployed and up-to-date."""
    if deploy_dir is None:
        deploy_dir = _default_deploy_dir()
    if not os.path.isdir(deploy_dir):
        return False
    src_hash = _compute_manifest_hash(RUNTIME_SRC)
    deployed_hash = _read_deployed_hash(deploy_dir)
    return src_hash == deployed_hash


def deploy(deploy_dir=None, force=False):
    """Deploy runtime files to target directory.

    Returns the deploy directory path.
    """
    if deploy_dir is None:
        deploy_dir = _default_deploy_dir()

    if not os.path.isdir(RUNTIME_SRC):
        print("[setup] ERROR: Runtime source not found: %s" % RUNTIME_SRC)
        sys.exit(1)

    src_hash = _compute_manifest_hash(RUNTIME_SRC)

    if not force and os.path.isdir(deploy_dir):
        deployed_hash = _read_deployed_hash(deploy_dir)
        if deployed_hash == src_hash:
            print("[setup] Runtime already deployed and up-to-date at: %s" % deploy_dir)
            return deploy_dir

    print("[setup] Deploying runtime to: %s" % deploy_dir)

    # Clean old deployment
    if os.path.isdir(deploy_dir):
        shutil.rmtree(deploy_dir)

    # Copy runtime
    shutil.copytree(RUNTIME_SRC, deploy_dir)
    print("[setup]   Copied runtime files")

    # Copy rdc_export.py
    export_src = os.path.join(ASSETS_DIR, "rdc_export.py")
    if os.path.isfile(export_src):
        shutil.copy2(export_src, os.path.join(deploy_dir, "rdc_export.py"))
        print("[setup]   Copied rdc_export.py")

    # Copy rdc_export.bat
    bat_src = os.path.join(ASSETS_DIR, "rdc_export.bat")
    if os.path.isfile(bat_src):
        shutil.copy2(bat_src, os.path.join(deploy_dir, "rdc_export.bat"))
        print("[setup]   Copied rdc_export.bat")

    # Write version stamp
    _write_deployed_hash(deploy_dir, src_hash)

    # Verify key files
    required = ["python.exe", "python36.dll", "renderdoc.dll",
                os.path.join("pymodules", "renderdoc.pyd"), "rdc_export.py"]
    missing = [f for f in required if not os.path.isfile(os.path.join(deploy_dir, f))]
    if missing:
        print("[setup] WARNING: Missing files after deploy: %s" % missing)
    else:
        print("[setup] Deployment complete. All %d key files verified." % len(required))

    return deploy_dir


def get_deploy_dir():
    """Return the deployment directory path (for use by other scripts)."""
    return _default_deploy_dir()


if __name__ == "__main__":
    target = None
    check_only = False
    force = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--target" and i + 1 < len(args):
            target = args[i + 1]
            i += 2
        elif args[i] == "--check":
            check_only = True
            i += 1
        elif args[i] == "--force":
            force = True
            i += 1
        else:
            print("Unknown argument: %s" % args[i])
            print("Usage: setup.py [--target <dir>] [--check] [--force]")
            sys.exit(1)

    if check_only:
        ok = check_deployed(target)
        print("[setup] Deployed: %s" % ("yes" if ok else "no"))
        sys.exit(0 if ok else 1)

    deploy(target, force=force)
