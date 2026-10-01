"""Build compressed and obfuscated frontend assets.

Run:
    python build_assets.py

Production mode serves files from static/dist through app.asset(). CSS is only
minified. JavaScript is minified first, then passed through
javascript-obfuscator with compatibility-focused options.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DIST_DIR = STATIC_DIR / "dist"
NODE_BIN_DIR = BASE_DIR / "node_modules" / ".bin"
OBFUSCATOR = NODE_BIN_DIR / ("javascript-obfuscator.cmd" if os.name == "nt" else "javascript-obfuscator")

CSS_FILES = ["css/style.css"]
JS_FILES = ["js/app.js", "js/editor.js"]


class BuildError(RuntimeError):
    pass


def require_python_minifiers():
    try:
        import rcssmin
        import rjsmin
    except ImportError as exc:
        raise BuildError(
            "Missing Python minifiers. Run: pip install -r requirements.txt"
        ) from exc
    return rcssmin, rjsmin


def require_js_obfuscator() -> Path:
    if not shutil.which("node") or not shutil.which("npm"):
        raise BuildError("Node.js and npm are required for JavaScript obfuscation.")
    if not OBFUSCATOR.exists():
        raise BuildError(
            "javascript-obfuscator is not installed. Run: npm install"
        )
    return OBFUSCATOR


def minify_css(rcssmin) -> tuple[int, int]:
    total_before = 0
    total_after = 0
    for rel in CSS_FILES:
        src = STATIC_DIR / rel
        if not src.exists():
            raise BuildError(f"Missing CSS source: {src}")
        original = src.read_text(encoding="utf-8")
        minified = rcssmin.cssmin(original)
        out = DIST_DIR / f"{src.stem}.min.css"
        out.write_text(minified, encoding="utf-8")
        total_before += len(original.encode("utf-8"))
        total_after += len(minified.encode("utf-8"))
        print(f"  CSS  {rel} -> static/dist/{out.name}")
    return total_before, total_after


def obfuscate_js_file(obfuscator: Path, source: Path, minified_code: str, output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="mellowday-build-") as tmp_dir:
        tmp_file = Path(tmp_dir) / source.name
        tmp_file.write_text(minified_code, encoding="utf-8")
        cmd = [
            str(obfuscator),
            str(tmp_file),
            "--output",
            str(output),
            "--compact",
            "true",
            "--identifier-names-generator",
            "hexadecimal",
            "--string-array",
            "true",
            "--string-array-encoding",
            "base64",
            "--string-array-threshold",
            "0.55",
            "--control-flow-flattening",
            "false",
            "--dead-code-injection",
            "false",
            "--debug-protection",
            "false",
            "--disable-console-output",
            "false",
            "--self-defending",
            "false",
            "--source-map",
            "false",
        ]
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    if result.returncode != 0:
        if output.exists():
            output.unlink()
        raise BuildError(
            f"javascript-obfuscator failed for {source.name}:\n{result.stdout.strip()}"
        )
    if not output.exists() or output.stat().st_size == 0:
        raise BuildError(f"Obfuscated output was not created: {output}")


def minify_and_obfuscate_js(rjsmin, obfuscator: Path) -> tuple[int, int]:
    total_before = 0
    total_after = 0
    for rel in JS_FILES:
        src = STATIC_DIR / rel
        if not src.exists():
            raise BuildError(f"Missing JS source: {src}")
        original = src.read_text(encoding="utf-8")
        minified = rjsmin.jsmin(original)
        out = DIST_DIR / f"{src.stem}.min.js"
        obfuscate_js_file(obfuscator, src, minified, out)
        total_before += len(original.encode("utf-8"))
        total_after += out.stat().st_size
        print(f"  JS   {rel} -> static/dist/{out.name} (minified + obfuscated)")
    return total_before, total_after


def main() -> int:
    try:
        rcssmin, rjsmin = require_python_minifiers()
        obfuscator = require_js_obfuscator()
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        total_before = total_after = 0

        before, after = minify_css(rcssmin)
        total_before += before
        total_after += after

        before, after = minify_and_obfuscate_js(rjsmin, obfuscator)
        total_before += before
        total_after += after

        saved = 100 * (1 - total_after / total_before) if total_before else 0
        print(f"[OK] Build complete: {total_before} -> {total_after} bytes ({saved:.0f}% change).")
        return 0
    except BuildError as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
