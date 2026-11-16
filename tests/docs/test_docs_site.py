"""The documentation site (mkdocs.yml over docs/): every page is in the navigation, every
navigation entry exists, relative links resolve, and the README points to the site."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCS = REPO / "docs"
SITE = "https://sebbenjamin.github.io/groundwork-qgis/"
OLD_GUIDES = ("user/import.md", "user/boreholes.md", "user/plates.md")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def nav_pages() -> list[str]:
    """The docs-relative .md paths in mkdocs.yml's navigation (by pattern: QGIS's Python
    has no YAML library)."""
    text = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
    nav = text[text.index("\nnav:"):]
    return re.findall(r"([\w./-]+\.md)\s*$", nav, re.M)


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def headings(path: str) -> set[str]:
    """The anchors (slugs) of the #, ## and ### headings of a docs-relative page."""
    lines = (DOCS / path).read_text(encoding="utf-8").splitlines()
    return {_slug(m.group(1)) for line in lines if (m := re.match(r"#{1,3}\s+(.+)", line))}


def _site_pages() -> list[Path]:
    pages = [DOCS / "index.md"] + sorted((DOCS / "user").rglob("*.md")) + \
        sorted((DOCS / "releases").glob("*.md"))
    return [p for p in pages if p.exists()]


def test_every_nav_page_exists():
    pages = nav_pages()
    assert pages, "mkdocs.yml has no navigation"
    for page in pages:
        assert (DOCS / page).is_file(), page


def test_every_user_page_is_in_nav():
    nav = set(nav_pages())
    for page in _site_pages():
        assert page.relative_to(DOCS).as_posix() in nav, page


def test_relative_links_resolve():
    for page in _site_pages():
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#")[0]
            assert (page.parent / path).exists(), f"{page.relative_to(DOCS)} → {target}"


def test_old_guides_removed():
    """Links to them anywhere in the site fail test_relative_links_resolve."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for old in OLD_GUIDES:
        assert not (DOCS / old).exists(), old
        assert f"docs/{old}" not in readme, old


def test_readme_links_to_site():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert SITE in text
    for target in LINK.findall(text):
        if target.startswith("docs/"):
            assert (REPO / target.split("#")[0]).exists(), target


def test_lists_have_a_blank_line_before():
    """The site's Markdown runs a list straight after a text line into that paragraph
    (GitHub does not); a blank line before each list keeps both the same."""
    item = re.compile(r"(- |\* |\d+\. )")
    for page in _site_pages():
        lines, fence = page.read_text(encoding="utf-8").splitlines(), False
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                fence = not fence
            if fence or i == 0 or not item.match(line):
                continue
            prev = lines[i - 1]
            # a list line or a heading/table/quote may come right before; an item's indented
            # continuation paragraph may not (the next item would run into it)
            ok = not prev.strip() or re.match(r"\s*(- |\* |\d+\. )", prev) or \
                prev.startswith(("#", "|", ">"))
            if not ok and prev.startswith("  "):        # wrapped text of the item above is
                k = i - 1                               # fine; a paragraph of its own is not
                while k > 0 and lines[k].startswith("  ") and \
                        not re.match(r"\s*(- |\* |\d+\. )", lines[k]):
                    k -= 1
                ok = bool(lines[k].strip())
            assert ok, f"{page.relative_to(DOCS)}:{i + 1}"


def test_add_data_page_is_built_around_its_picture():
    """The pattern for dialog pages: the annotated picture, a legend with its numbers that
    links to the parts, then the text."""
    text = (DOCS / "user/howto/add-data.md").read_text(encoding="utf-8")
    picture = "../../images/howto/add-data.png"
    assert f"]({picture})" in text
    legend = text.index("①")
    assert text.index(picture) < legend < text.index("## ")      # picture, legend, then sections
    for mark, anchor in zip("①②③④⑤", ("file-format-text-tables-only", "what-the-columns-are",
                                        "where-the-line-runs", "preview", "the-check-result")):
        row = next(line for line in text.splitlines() if line.startswith(f"| {mark} "))
        assert f"(#{anchor})" in row, mark
        assert anchor in headings("user/howto/add-data.md"), anchor
    assert len(text[:legend].split()) < 90                      # short lead: the picture is on top
