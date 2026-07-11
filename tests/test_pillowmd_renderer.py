import asyncio
import os
import sys
import types

from core.pillowmd_renderer import PillowMarkdownRenderer


class FakeImage:
    def save(self, path, format=None):
        with open(path, "wb") as file:
            file.write(b"png")


class FakePillowMd(types.ModuleType):
    class MdStyle:
        fontSize = 25
        xSizeMax = 1000

    def __init__(self):
        super().__init__("pillowmd")
        self.calls = []

    async def MdToImage(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return types.SimpleNamespace(image=FakeImage())


def test_renderer_saves_png_normalizes_fraction_and_cleans_up(monkeypatch):
    fake = FakePillowMd()
    monkeypatch.setitem(sys.modules, "pillowmd", fake)
    renderer = PillowMarkdownRenderer()
    settings = {
        "rich_render_font_size": 25,
        "rich_render_width": 1000,
        "rich_render_cache_ttl": 180,
    }

    async def run():
        path = await renderer.render(r"$$\dfrac{1}{2}$$", settings)
        assert os.path.isabs(path)
        assert os.path.exists(path)
        assert fake.calls[0][0] == r"$$\frac{1}{2}{}$$"
        await renderer.close()
        assert not os.path.exists(path)

    asyncio.run(run())


def test_renderer_stabilizes_multiple_inline_formulas():
    cleaned = PillowMarkdownRenderer._clean_text("$x$ and $y=x$")
    assert cleaned == "$x{}$ and $y=x{}$"


def test_missing_dependency_has_actionable_error(monkeypatch):
    renderer = PillowMarkdownRenderer()
    monkeypatch.delitem(sys.modules, "pillowmd", raising=False)

    def fail_import(name, *args, **kwargs):
        if name == "pillowmd":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    async def run():
        try:
            await renderer.render("$x$", {})
        except RuntimeError as exc:
            assert "pillowmd" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")

    asyncio.run(run())
