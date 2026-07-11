"""MathJax-based Markdown rendering for complex mathematical replies."""

from __future__ import annotations

import asyncio
import html
import os
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


_MATH_TOKEN_RE = re.compile(
    r"(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<![\\$])\$(?!\$)(.+?)(?<![\\$])\$(?!\$)",
    re.DOTALL,
)
_ALLOWED_TAGS = {
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "blockquote",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "span",
    "div",
}
_VOID_TAGS = {"br", "hr"}


class _SafeHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in _ALLOWED_TAGS:
            return
        class_name = next((value for name, value in attrs if name == "class"), None)
        class_attr = ""
        if class_name and re.fullmatch(r"[A-Za-z0-9_ -]{1,80}", class_name):
            class_attr = f' class="{html.escape(class_name, quote=True)}"'
        self.parts.append(f"<{tag}{class_attr}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if not self.blocked_depth and tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(html.escape(data, quote=False))

    def get_html(self) -> str:
        return "".join(self.parts)


class MathJaxRenderer:
    """Render Markdown and LaTeX with a reusable Playwright browser."""

    def __init__(self) -> None:
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._page_cdn_url: str | None = None
        self._startup_lock = asyncio.Lock()
        self._render_lock = asyncio.Lock()
        self._paths: set[str] = set()
        self._cleanup_tasks: set[asyncio.Task] = set()

    @staticmethod
    def _load_dependencies() -> tuple[Any, Any]:
        try:
            import markdown
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 MathJax 渲染依赖，请重新安装插件依赖 playwright 和 markdown"
            ) from exc
        return markdown, async_playwright

    @staticmethod
    def _find_system_browser() -> str | None:
        candidates = [
            shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "msedge")
        ]
        if os.name == "nt":
            roots = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            for root in filter(None, roots):
                candidates.extend(
                    [
                        str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                        str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
                    ]
                )
        return next((path for path in candidates if path and Path(path).is_file()), None)

    async def _run_playwright_installer(
        self, *arguments: str, timeout: int
    ) -> None:
        env = os.environ.copy()
        env.setdefault("DEBIAN_FRONTEND", "noninteractive")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError(
                f"Playwright {' '.join(arguments)} 执行超时"
            ) from exc
        if process.returncode:
            output = (stdout + stderr).decode("utf-8", errors="ignore").strip()
            raise RuntimeError(
                f"Playwright {' '.join(arguments)} 失败: {output[-1000:]}"
            )

    async def _install_browser(self) -> None:
        if sys.platform.startswith("linux"):
            getuid = getattr(os, "geteuid", None)
            if callable(getuid) and getuid() != 0:
                raise RuntimeError(
                    "Linux 缺少 Chromium 系统依赖且当前进程不是 root；请在宿主机执行 "
                    "sudo python -m playwright install-deps chromium"
                )
            await self._run_playwright_installer(
                "install-deps", "chromium", timeout=900
            )
        await self._run_playwright_installer(
            "install", "chromium-headless-shell", timeout=600
        )

    async def _launch_browser(self, settings: dict) -> None:
        _, async_playwright = self._load_dependencies()
        self._playwright = await async_playwright().start()
        launch_options = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        try:
            self._browser = await self._playwright.chromium.launch(**launch_options)
        except Exception as first_error:
            executable = self._find_system_browser()
            if executable:
                try:
                    self._browser = await self._playwright.chromium.launch(
                        **launch_options,
                        executable_path=executable,
                    )
                except Exception:
                    self._browser = None
            if self._browser is None and bool(
                settings.get("rich_render_mathjax_auto_install_browser", True)
            ):
                await self._install_browser()
                self._browser = await self._playwright.chromium.launch(**launch_options)
            if self._browser is None:
                raise RuntimeError(
                    "无法启动 Chromium；请安装 Playwright Chromium 或开启自动安装"
                ) from first_error
        self._context = await self._browser.new_context(
            device_scale_factor=max(
                1, min(int(settings.get("rich_render_scale", 2) or 2), 3)
            ),
            bypass_csp=True,
        )

    async def _ensure_context(self, settings: dict) -> Any:
        if self._context is not None:
            return self._context
        async with self._startup_lock:
            if self._context is None:
                await self._launch_browser(settings)
        return self._context

    async def _ensure_page(self, settings: dict) -> Any:
        context = await self._ensure_context(settings)
        cdn_url = str(
            settings.get(
                "rich_render_mathjax_cdn_url",
                "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js",
            )
            or "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js"
        )
        if self._page is not None and self._page_cdn_url == cdn_url:
            return self._page
        if self._page is not None:
            await self._page.close()
        self._page = await context.new_page()
        self._page_cdn_url = cdn_url
        timeout_ms = max(
            3000,
            min(
                int(settings.get("rich_render_mathjax_timeout", 20) or 20) * 1000,
                120000,
            ),
        )
        await self._page.set_content(
            self._document("", settings), wait_until="load", timeout=timeout_ms
        )
        await self._page.wait_for_function(
            "window.__mathjaxDone === true", timeout=timeout_ms
        )
        return self._page

    @staticmethod
    def _markdown_html(text: str) -> str:
        markdown, _ = MathJaxRenderer._load_dependencies()
        formulas: list[tuple[str, bool]] = []

        def protect(match: re.Match[str]) -> str:
            display = match.group(1) is not None
            formulas.append((match.group(0), display))
            return f"MATHJAXTOKEN{len(formulas) - 1}END"

        protected = _MATH_TOKEN_RE.sub(protect, text)
        rendered = markdown.markdown(
            protected,
            extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        )
        for index, (formula, display) in enumerate(formulas):
            escaped = html.escape(formula, quote=False)
            replacement = (
                f'<div class="math-display">{escaped}</div>'
                if display
                else f'<span class="math-inline">{escaped}</span>'
            )
            rendered = rendered.replace(f"MATHJAXTOKEN{index}END", replacement)
        sanitizer = _SafeHtmlParser()
        sanitizer.feed(rendered)
        sanitizer.close()
        return sanitizer.get_html()

    @staticmethod
    def _document(text: str, settings: dict) -> str:
        content = MathJaxRenderer._markdown_html(text)
        width = max(320, min(int(settings.get("rich_render_width", 1000) or 1000), 2400))
        font_size = max(14, min(int(settings.get("rich_render_font_size", 25) or 25), 64))
        transparent = bool(settings.get("rich_render_transparent_background", False))
        background = "transparent" if transparent else "#263b52"
        panel = "transparent" if transparent else "#263b52"
        mathjax_url = html.escape(
            str(
                settings.get(
                    "rich_render_mathjax_cdn_url",
                    "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js",
                )
                or "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js"
            ),
            quote=True,
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
html, body {{ margin: 0; padding: 0; background: {background}; }}
body {{ display: inline-block; color: #f5f7fa; font-family: "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; }}
#content {{ box-sizing: border-box; display: inline-block; min-width: 280px; max-width: {width}px; padding: 28px 32px; background: {panel}; font-size: {font_size}px; line-height: 1.65; overflow-wrap: anywhere; }}
p {{ margin: 0 0 0.85em; }} p:last-child {{ margin-bottom: 0; }}
h1, h2, h3 {{ margin: 0.8em 0 0.45em; line-height: 1.3; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.7em 0; }}
th, td {{ border: 1px solid #7890a8; padding: 0.42em 0.65em; text-align: left; }}
th {{ background: rgba(255,255,255,0.09); }}
code {{ background: rgba(0,0,0,0.22); padding: 0.1em 0.28em; }}
pre {{ white-space: pre-wrap; background: rgba(0,0,0,0.25); padding: 0.8em; }}
.math-display {{ overflow-x: visible; margin: 0.65em 0; text-align: center; }}
mjx-container {{ color: #f8fbff !important; }}
</style>
<script>
window.__mathjaxDone = false;
window.MathJax = {{
  tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']], packages: {{'[+]': ['ams']}} }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre','code'] }},
  startup: {{ pageReady: () => MathJax.startup.defaultPageReady().then(() => document.fonts.ready).then(() => {{ window.__mathjaxDone = true; }}) }}
}};
</script>
<script defer src="{mathjax_url}"></script></head>
<body><main id="content">{content}</main></body></html>"""

    async def render(self, text: str, settings: dict) -> str:
        timeout_ms = max(
            3000, min(int(settings.get("rich_render_mathjax_timeout", 20) or 20) * 1000, 120000)
        )
        handle, path = tempfile.mkstemp(prefix="astrbot-mathjax-", suffix=".png")
        os.close(handle)
        try:
            async with self._render_lock:
                page = await self._ensure_page(settings)
                width = max(
                    320,
                    min(int(settings.get("rich_render_width", 1000) or 1000), 2400),
                )
                await page.set_viewport_size({"width": width + 100, "height": 800})
                transparent = bool(
                    settings.get("rich_render_transparent_background", False)
                )
                await asyncio.wait_for(
                    page.evaluate(
                        """async ({content, width, fontSize, transparent}) => {
                        const target = document.getElementById('content');
                        MathJax.typesetClear([target]);
                        target.innerHTML = content;
                        target.style.maxWidth = `${width}px`;
                        target.style.fontSize = `${fontSize}px`;
                        const background = transparent ? 'transparent' : '#263b52';
                        document.documentElement.style.background = background;
                        document.body.style.background = background;
                        target.style.background = background;
                        await MathJax.typesetPromise([target]);
                        await document.fonts.ready;
                    }""",
                        {
                            "content": self._markdown_html(text),
                            "width": width,
                            "fontSize": max(
                                14,
                                min(
                                    int(
                                        settings.get("rich_render_font_size", 25) or 25
                                    ),
                                    64,
                                ),
                            ),
                            "transparent": transparent,
                        },
                    ),
                    timeout=timeout_ms / 1000,
                )
                await page.locator("#content").screenshot(
                    path=path,
                    omit_background=transparent,
                )
        except Exception:
            self._remove_path(path)
            raise

        self._paths.add(path)
        ttl = max(1, int(settings.get("rich_render_cache_ttl", 180) or 180))
        task = asyncio.create_task(self._delete_later(path, ttl))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)
        return path

    async def _delete_later(self, path: str, ttl: int) -> None:
        try:
            await asyncio.sleep(ttl)
            await asyncio.to_thread(self._remove_path, path)
        except asyncio.CancelledError:
            raise

    def _remove_path(self, path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        finally:
            self._paths.discard(path)

    async def close(self) -> None:
        tasks = list(self._cleanup_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._cleanup_tasks.clear()
        for path in list(self._paths):
            await asyncio.to_thread(self._remove_path, path)
        if self._page is not None:
            await self._page.close()
            self._page = None
            self._page_cdn_url = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
