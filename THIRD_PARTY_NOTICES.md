# Source attribution

This merged plugin is based on and interoperates with the following projects:

- `DBJD-CR/astrbot_plugin_proactive_chat`, used as the project base. The included
  `LICENSE` file is its GNU Affero General Public License v3 notice.
- `Justice-ocr/astrbot_plugin_proactive_chat`, used for contextual scheduling,
  unanswered-limit handling and the AstrBot Pages management interface.
- `nuomicici/astrbot_plugin_splitter`, used as the behavioral reference for
  smart splitting, paired-symbol protection, media strategies, delays and
  per-segment TTS handling.
- `luosheng520qaq/astrbot_plugin_nobrowser_markdown_to_pic`, used as the
  reference implementation for local browser-free Markdown rendering.
- `pillowmd` (`Monody-S/CustomMarkdownImage`, MIT), used to render Markdown
  tables to PNG files without Chromium.
- `Whereis-Alice/astrbot_plugin_math_render`, used as the functional reference
  for MathJax rendering, bare-LaTeX normalization and math-focused image cards.
- `MathJax` (Apache-2.0) and `Microsoft Playwright` (Apache-2.0), used to render
  complex LaTeX formulas in a persistent Chromium page.

Upstream repositories:

- https://github.com/DBJD-CR/astrbot_plugin_proactive_chat
- https://github.com/Justice-ocr/astrbot_plugin_proactive_chat
- https://github.com/nuomicici/astrbot_plugin_splitter
- https://github.com/luosheng520qaq/astrbot_plugin_nobrowser_markdown_to_pic
- https://github.com/Monody-S/CustomMarkdownImage
- https://github.com/Whereis-Alice/astrbot_plugin_math_render
- https://github.com/mathjax/MathJax
- https://github.com/microsoft/playwright-python
