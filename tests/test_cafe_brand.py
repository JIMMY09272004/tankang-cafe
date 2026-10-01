"""Verify branding and startup persistence using an isolated database."""

import gc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class CafeBrandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="cafe-brand-test-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.addClassCleanup(gc.collect)
        source = Path(cls.directory.name) / "app.py"
        shutil.copy2(ROOT / "app.py", source)
        spec = importlib.util.spec_from_file_location("cafe_brand_test_app", source)
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        cls.addClassCleanup(sys.modules.pop, spec.name)
        with patch.dict(os.environ, {
            "APP_ENV": "development",
            "ADMIN_USERNAME": "fixture_admin",
            "ADMIN_PASSWORD": "FixtureOnly123",
            "ENABLE_DEMO_ACCOUNT": "true",
        }, clear=True):
            spec.loader.exec_module(cls.module)
        cls.module.app.template_folder = str(ROOT / "templates")
        cls.module.app.static_folder = str(ROOT / "static")
        cls.module.app.config.update(TESTING=True)
        cls.module.send_email = lambda *args, **kwargs: False

    def test_existing_menu_edits_survive_startup_and_copy_migration(self):
        module = self.module
        with module.app.app_context():
            db = module.get_db()
            db.execute(
                "UPDATE products SET name = ?, description = ?, price = 299, stock = 7, active = 0 WHERE slug = ?",
                ("沐光招牌拿鐵", "店家自訂的餐點說明", "signature-latte"),
            )
            db.commit()
        module.init_db()
        module.init_db()
        with module.app.app_context():
            row = module.get_db().execute(
                "SELECT name, description, price, stock, active FROM products WHERE slug = 'signature-latte'"
            ).fetchone()
            self.assertEqual(tuple(row), ("淡江招牌拿鐵", "店家自訂的餐點說明", 299, 7, 0))

    def test_site_content_and_editor_copy_survive_startup(self):
        module = self.module
        original = module.SITE_CONTENT_PATH.read_bytes()
        content = json.loads(original)
        content["hero"]["title"] = "店家自訂首頁文字"
        module.SITE_CONTENT_PATH.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(module.SITE_CONTENT_PATH.write_bytes, original)
        overrides = {"footer.tagline": "店家自訂頁尾文字"}
        module.save_text_overrides(overrides)
        self.addCleanup(module.save_text_overrides, {})
        module.init_db()
        self.assertEqual(module.load_site_content(), content)
        self.assertEqual(module.load_text_overrides(), overrides)

    def test_admin_and_member_pages_render_with_new_brand(self):
        module = self.module
        for role, paths in (
            ("admin", ("/admin", "/admin/products", "/admin/announcements", "/admin/reservations", "/admin/messages", "/admin/members", "/admin/security")),
            ("user", ("/profile",)),
        ):
            with module.app.app_context():
                member_id = module.get_db().execute("SELECT id FROM users WHERE role = ? LIMIT 1", (role,)).fetchone()[0]
            with module.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = member_id
                for path in paths:
                    with self.subTest(path=path):
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("淡江咖啡館", response.get_data(as_text=True))
                        self.assertIn("images/tankang-cafe-logo.png", response.get_data(as_text=True))

    def test_brand_and_original_logo_render_on_public_pages(self):
        with self.module.app.test_client() as client:
            for path in ("/", "/shop", "/news", "/login", "/register", "/reservation", "/contact", "/forgot-password"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertIn("淡江咖啡館", html)
                    self.assertIn("TANKANG CAFE", html)
                    self.assertIn("images/tankang-cafe-logo.png", html)
                    self.assertNotIn("Mellow Day", html)
                    self.assertNotIn("沐光咖啡", html)
                    self.assertNotIn("built-in method", html)
            icon = client.get("/favicon.ico", follow_redirects=True)
            self.assertEqual(icon.status_code, 200)
            self.assertEqual(icon.data, (ROOT / "static/images/tankang-cafe-logo.png").read_bytes())
            icon.close()


if __name__ == "__main__":
    unittest.main()
