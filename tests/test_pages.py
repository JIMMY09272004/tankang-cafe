"""Pages builds must not read private state or expose backend routes."""
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.urls.extend(value for key, value in attrs if key in {"href", "src"} and value)


class PagesTests(unittest.TestCase):
    def test_export_is_isolated_and_all_local_links_resolve(self):
        builder = ROOT / "build_pages.py"
        self.assertTrue(builder.exists(), "The isolated Pages exporter must exist")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            # Poison private files: importing app or copying a tree would leak these.
            (source / "app.py").write_text((ROOT / "app.py").read_text(encoding="utf-8") + '\nraise RuntimeError("Do not import app for Pages")\n', encoding="utf-8")
            (source / ".env").write_text("MAIL_PASSWORD=PRIVATE_EXPORT_SENTINEL\n", encoding="utf-8")
            (source / "data").mkdir()
            (source / "data/site_content.json").write_text("PRIVATE_EXPORT_SENTINEL", encoding="utf-8")
            output = Path(temporary) / "site"
            result = subprocess.run([sys.executable, str(builder), "--source", str(source), "--output", str(output), "--base-path", "/tankang-cafe"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((output / "app.py").exists())
            self.assertFalse((output / "data").exists())
            self.assertFalse((output / ".env").exists())
            self.assertFalse((output / "static/js/editor.js").exists())
            self.assertTrue((output / "shop/index.html").exists())
            self.assertTrue((output / "products/signature-latte/index.html").exists())
            for page in output.rglob("*.html"):
                with self.subTest(page=page.relative_to(output)):
                    html = page.read_text(encoding="utf-8")
                    self.assertNotIn("PRIVATE_EXPORT_SENTINEL", html)
                    self.assertNotIn('name="csrf', html)
                    self.assertNotIn("challenges.cloudflare.com", html)
                    self.assertNotIn("built-in method", html)
                    self.assertNotRegex(html, r'/(?:admin|api|login|register|reservation|contact)(?:/|["\'])')
                    links = Links()
                    links.feed(html)
                    self.assertNotIn("form", links.tags)
                    for url in links.urls:
                        parsed = urlsplit(url)
                        if not parsed.path or parsed.scheme or parsed.netloc:
                            continue
                        self.assertTrue(parsed.path.startswith("/tankang-cafe/"), url)
                        target = output / unquote(parsed.path.removeprefix("/tankang-cafe/"))
                        self.assertTrue(target.exists(), url)
                    for url in re.findall(r"url\(['\"]?([^)'\"]+)", html):
                        target = output / url.removeprefix("/tankang-cafe/")
                        self.assertTrue(target.exists(), url)

    def test_export_does_not_overwrite_existing_output(self):
        self.assertTrue((ROOT / "build_pages.py").exists(), "The isolated Pages exporter must exist")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing"
            output.mkdir()
            marker = output / "important.txt"
            marker.write_text("keep", encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "build_pages.py"), "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
