import asyncio
import os
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


def test_linux_root_installs_system_dependencies_before_browser(monkeypatch):
    renderer = MathJaxRenderer()
    calls = []

    async def fake_installer(*arguments, timeout):
        calls.append((arguments, timeout))

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(renderer, "_run_playwright_installer", fake_installer)
    asyncio.run(renderer._install_browser())

    assert calls[0][0] == ("install-deps", "chromium")
    assert calls[1][0] == ("install", "chromium-headless-shell")


def test_linux_non_root_returns_manual_dependency_command(monkeypatch):
    renderer = MathJaxRenderer()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)

    async def run():
        try:
            await renderer._install_browser()
        except RuntimeError as exc:
            assert "sudo python -m playwright install-deps chromium" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")

    asyncio.run(run())
