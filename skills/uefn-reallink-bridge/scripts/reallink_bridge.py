"""
UefnReallink — External client script.

Sends Python code to the UEFN editor for main-thread execution via HTTP.
Reads code from stdin or a command-line argument.

Usage:
    python uefn_reallink.py "import unreal; result = unreal.Paths.project_dir()"
    echo <code> | python uefn_reallink.py

Environment:
    UEFN_HOST    (default 127.0.0.1)
    UEFN_PORT    (default 9877)
    UEFN_TIMEOUT (default 30)
"""

import json
import sys
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

HOST    = os.environ.get("UEFN_HOST", "127.0.0.1")
PORT    = int(os.environ.get("UEFN_PORT", "9877"))
TIMEOUT = float(os.environ.get("UEFN_TIMEOUT", "30"))


def execute(code: str) -> str:
    url = f"http://{HOST}:{PORT}/execute"
    req = Request(url, data=code.encode("utf-8"), method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return json.dumps(data, indent=2, ensure_ascii=False)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps({"success": False, "error": f"HTTP {e.code}: {body}"}, ensure_ascii=False)
    except URLError as e:
        return json.dumps({"success": False, "error": f"Cannot connect to UEFN ({e.reason}). Is the editor running?"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def main():
    if len(sys.argv) > 1:
        code = sys.argv[1]
    elif not sys.stdin.isatty():
        code = sys.stdin.read()
    else:
        print(json.dumps({"error": "No code provided. Pipe code via stdin or pass as argument."}))
        sys.exit(1)

    print(execute(code))


if __name__ == "__main__":
    main()
