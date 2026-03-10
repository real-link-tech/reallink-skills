#!/usr/bin/env python3
"""
RDC Analysis Skill - Export Runner
===================================
Ensure runtime is deployed, then run rdc_export.py with the bundled
Python 3.6 + renderdoc environment.

Usage:
    python run_export.py <capture.rdc>
    python run_export.py --eid -1 <capture.rdc>
    python run_export.py --eid 1234 <capture.rdc>
    python run_export.py --eid 1000-2000 <capture.rdc>

All arguments after run_export.py are forwarded to rdc_export.py.
"""

import sys
import os
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

# Import setup module
sys.path.insert(0, SCRIPT_DIR)
import setup


def main():
    # Ensure runtime is deployed
    deploy_dir = setup.deploy()

    python_exe = os.path.join(deploy_dir, "python.exe")
    export_script = os.path.join(deploy_dir, "rdc_export.py")
    pymodules_dir = os.path.join(deploy_dir, "pymodules")

    if not os.path.isfile(python_exe):
        print("[run_export] ERROR: python.exe not found at: %s" % python_exe)
        sys.exit(1)
    if not os.path.isfile(export_script):
        print("[run_export] ERROR: rdc_export.py not found at: %s" % export_script)
        sys.exit(1)

    # Build command: use bundled python.exe to run rdc_export.py
    # Pass --renderdoc-path to point at pymodules directory
    cmd = [python_exe, export_script, "--renderdoc-path", pymodules_dir]
    cmd.extend(sys.argv[1:])

    # Set up environment
    env = os.environ.copy()
    # Ensure renderdoc.dll can be found
    env["PATH"] = deploy_dir + os.pathsep + env.get("PATH", "")
    env["RENDERDOC_PATH"] = pymodules_dir
    # Non-interactive mode
    env["RDC_EXPORT_NO_PAUSE"] = "1"

    if sys.platform == "win32" and sys.version_info >= (3, 8):
        # Python 3.8+ needs explicit DLL directory
        try:
            os.add_dll_directory(deploy_dir)
        except Exception:
            pass

    print("[run_export] Runtime: %s" % deploy_dir)
    print("[run_export] Command: %s" % " ".join(cmd))
    print()

    result = subprocess.run(cmd, env=env, cwd=os.getcwd())
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
