"""Local Markdown rendering backed by pillowmd."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class PillowMarkdownRenderer:
    """Render Markdown to temporary PNG files without a browser process."""

    def __init__(self) -> None:
        self._pillowmd: Any | None = None
        self._style_key: tuple[str, int, int] | None = None
        self._style: Any | None = None
        self._paths: set[str] = set()
        self._cleanup_tasks: set[asyncio.Task] = set()

    @staticmethod
    def _clean_text(text: str) -> str:
        # pillowlatex 0.x does not understand these display-style aliases.
        text = re.sub(r"\\[dt]frac(?![A-Za-z])", r"\\frac", text)

        # pillowmd <= 0.7.3 can retain a completed one-character formula and
        # render later formulas literally. An empty TeX group is invisible but
        # ensures the renderer advances past every formula's source window.
        patterns = (
            re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL),
            re.compile(r"(?<![\\$])\$(?!\$)(.+?)(?<![\\$])\$(?!\$)", re.DOTALL),
            re.compile(r"\\\((.+?)\\\)", re.DOTALL),
            re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
        )

        def stabilize(match: re.Match[str]) -> str:
            content = match.group(1)
            if content.rstrip().endswith("{}"):
                return match.group(0)
            content_end = match.group(0).find(content) + len(content)
            return match.group(0)[:content_end] + "{}" + match.group(0)[content_end:]

        for pattern in patterns:
            text = pattern.sub(stabilize, text)
        return text.strip()

    def _load_module(self) -> Any:
        if self._pillowmd is None:
            try:
                import pillowmd
            except ImportError as exc:
                raise RuntimeError(
                    "缺少 pillowmd 依赖，请重新安装或更新插件依赖"
                ) from exc
            self._pillowmd = pillowmd
        return self._pillowmd

    async def _get_style(self, settings: dict) -> Any:
        pillowmd = self._load_module()
        style_path = str(settings.get("rich_render_style_path", "") or "").strip()
        font_size = max(8, min(int(settings.get("rich_render_font_size", 25) or 25), 200))
        width = max(200, min(int(settings.get("rich_render_width", 1000) or 1000), 4000))
        key = (style_path, font_size, width)
        if self._style is not None and self._style_key == key:
            return self._style

        if style_path:
            path = Path(style_path).expanduser()
            if not path.exists():
                raise RuntimeError(f"PillowMD 样式路径不存在: {path}")
            base_style = await asyncio.to_thread(pillowmd.LoadMarkdownStyles, path)
        else:
            base_style = pillowmd.MdStyle()

        if dataclasses.is_dataclass(base_style):
            base_style = dataclasses.replace(
                base_style,
                fontSize=font_size,
                xSizeMax=width,
            )
        self._style_key = key
        self._style = base_style
        return base_style

    async def render(self, text: str, settings: dict) -> str:
        pillowmd = self._load_module()
        style = await self._get_style(settings)
        cleaned = self._clean_text(text)
        result = await pillowmd.MdToImage(
            cleaned,
            style=style,
            autoPage=bool(settings.get("rich_render_auto_page", False)),
            noDecoration=bool(
                settings.get("rich_render_transparent_background", False)
            ),
        )
        image = getattr(result, "image", result)
        if not hasattr(image, "save"):
            raise RuntimeError("PillowMD 返回了无法保存的图片对象")

        handle, path = tempfile.mkstemp(prefix="astrbot-rich-", suffix=".png")
        os.close(handle)
        try:
            await asyncio.to_thread(image.save, path, format="PNG")
        except Exception:
            await asyncio.to_thread(self._remove_path, path)
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
        paths = list(self._paths)
        if paths:
            await asyncio.gather(
                *(asyncio.to_thread(self._remove_path, path) for path in paths)
            )
