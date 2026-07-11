import sys
import types

from core.mathjax_renderer import MathJaxRenderer


class FakeMarkdown(types.ModuleType):
    def markdown(self, text, extensions=None):
        return f"<p>{text}</p>"


def install_fake_dependencies(monkeypatch):
    markdown = FakeMarkdown("markdown")
    playwright = types.ModuleType("playwright")
    playwright.__path__ = []
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = object()
    monkeypatch.setitem(sys.modules, "markdown", markdown)
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)


def test_markdown_conversion_preserves_math_for_mathjax(monkeypatch):
    install_fake_dependencies(monkeypatch)
    rendered = MathJaxRenderer._markdown_html(
        "说明 $x^2$。\n\n$$\\Biggl[1+\\frac{a}{b}\\Biggr]$$"
    )
    assert '<span class="math-inline">$x^2$</span>' in rendered
    assert '<div class="math-display">$$\\Biggl' in rendered
    assert "MATHJAXTOKEN" not in rendered


def test_document_uses_configured_mathjax_and_layout(monkeypatch):
    install_fake_dependencies(monkeypatch)
    document = MathJaxRenderer._document(
        "$x$",
        {
            "rich_render_width": 880,
            "rich_render_font_size": 28,
            "rich_render_mathjax_cdn_url": "https://example.test/mathjax.js",
        },
    )
    assert "max-width: 880px" in document
    assert "font-size: 28px" in document
    assert 'src="https://example.test/mathjax.js"' in document
    assert "tex-chtml" not in document


def test_markdown_html_removes_executable_html(monkeypatch):
    install_fake_dependencies(monkeypatch)
    rendered = MathJaxRenderer._markdown_html(
        '<script>alert(1)</script><img src=x onerror="alert(2)"><b>内容</b> $x$'
    )
    assert "script" not in rendered
    assert "onerror" not in rendered
    assert "<img" not in rendered
    assert "内容" in rendered
    assert "$x$" in rendered
