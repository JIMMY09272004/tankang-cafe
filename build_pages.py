"""Export only public templates and starter content, without importing Flask.

No .env, SQLite database, text overrides, uploads or member pages are read.
"""
from __future__ import annotations

import argparse
import ast
import copy
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
NEWS = [
    {"id": 1, "title": "今天想喝哪一杯？", "body": "喜歡奶香，可以選招牌拿鐵；想喝清爽一點，試試手沖或冷萃。搭份喜歡的甜點，慢慢喝。", "created_at": "2026-01-01", "pinned": True},
    {"id": 2, "title": "咖啡旁邊，留個位子給甜點", "body": "焦糖布丁有微苦的甜香，可頌帶著酥脆奶油香。和朋友分一份，或留給自己，都很好。", "created_at": "2026-01-01", "pinned": False},
]


def starter_content(source: Path) -> tuple[dict, list[dict]]:
    tree = ast.parse((source / "app.py").read_text(encoding="utf-8-sig"))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"CAFE_SITE_CONTENT", "CAFE_PRODUCTS"}:
                values[target.id] = ast.literal_eval(node.value)
    return copy.deepcopy(values["CAFE_SITE_CONTENT"]), copy.deepcopy(values["CAFE_PRODUCTS"])


def build(output: Path, base_path: str = "", source: Path = ROOT) -> None:
    if output.exists():
        raise ValueError("Output already exists. Choose a new directory; existing files will not be overwritten.")
    if base_path and not re.fullmatch(r"/[A-Za-z0-9_.-]+/?", base_path):
        raise ValueError("Use an empty base path or a repository path such as /tankang-cafe.")
    prefix = base_path.rstrip("/")
    content, products = starter_content(source)

    def public_url(endpoint: str, **kwargs) -> str:
        if endpoint == "static":
            return f"{prefix}/static/{quote(kwargs['filename'], safe='/')}"
        routes = {"home": "/", "shop": "/shop/", "news": "/news/"}
        if endpoint == "product_detail":
            return f"{prefix}/products/{quote(kwargs['slug'], safe='')}/"
        if endpoint == "news_detail":
            return f"{prefix}/news/{int(kwargs['announcement_id'])}/"
        if endpoint not in routes:
            raise ValueError(f"Non-public endpoint in Pages output: {endpoint}")
        return prefix + routes[endpoint]

    def asset(filename: str) -> str:
        built = {"css/style.css": "dist/style.min.css", "js/app.js": "dist/app.min.js"}.get(filename)
        return public_url("static", filename=built if built and (ROOT / "static" / built).is_file() else filename)

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    env.globals.update(
        pages_mode=True,
        brand=content["brand"],
        url_for=public_url,
        asset=asset,
        ed=lambda key, default="": default,
        current_user=None,
        editor_enabled=False,
        turnstile_enabled=False,
        get_flashed_messages=lambda **kwargs: [],
    )
    images = {"buna-night-hero.webp", "buna-coffee-gold.webp", "buna-delicacies.webp", "buna-paper-dark.webp", "buna-pour-beans.webp", content["brand"]["logo"]}
    for product in products:
        images.add(product["image"])
        product["image_url"] = public_url("static", filename="images/" + product["image"])
    for image in images:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:png|webp|jpg|jpeg)", image):
            raise ValueError("Only checked-in image filenames can be published.")
        if not (ROOT / "static/images" / image).is_file():
            raise ValueError(f"Missing public image: {image}")

    pages = [
        ("index.html", "home.html", {"active": "home", "site_content": content, "featured_products": [item for item in products if item["featured"]][:4], "latest_news": NEWS}),
        ("shop/index.html", "shop.html", {"active": "shop", "products": products, "categories": sorted({item["category"] for item in products})}),
        ("news/index.html", "news.html", {"active": "news", "announcements": NEWS}),
        ("404.html", "404.html", {"active": ""}),
    ]
    for product in products:
        if not re.fullmatch(r"[a-z0-9-]+", product["slug"]):
            raise ValueError("Invalid starter product slug.")
        related = sorted([item for item in products if item is not product], key=lambda item: item["category"] != product["category"])[:3]
        pages.append((f"products/{product['slug']}/index.html", "product_detail.html", {"active": "shop", "product": product, "related_products": related}))
    for item in NEWS:
        pages.append((f"news/{item['id']}/index.html", "news_detail.html", {"active": "news", "item": item, "others": [other for other in NEWS if other is not item]}))

    # Render everything before creating the output to fail closed on template errors.
    rendered = [(path, env.get_template(template).render(**context)) for path, template, context in pages]
    output.mkdir(parents=True)
    for path, html in rendered:
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(html, encoding="utf-8")
    for filename in ("css/style.css", "js/app.js"):
        built = {"css/style.css": "dist/style.min.css", "js/app.js": "dist/app.min.js"}[filename]
        selected = built if (ROOT / "static" / built).is_file() else filename
        destination = output / "static" / selected
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "static" / selected, destination)
    for image in images:
        destination = output / "static/images" / image
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "static/images" / image, destination)
    (output / ".nojekyll").touch()
    print(f"Built {len(rendered)} public pages. No backend data or credentials included.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    parser.add_argument("--base-path", default="")
    parser.add_argument("--source", type=Path, default=ROOT, help="Read starter constants from this directory, never import its app.")
    args = parser.parse_args()
    try:
        build(args.output.resolve(), args.base_path, args.source.resolve())
    except (ValueError, KeyError) as exc:
        parser.exit(1, f"Build refused: {exc}\n")


if __name__ == "__main__":
    main()
