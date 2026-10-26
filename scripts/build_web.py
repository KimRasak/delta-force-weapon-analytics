#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build self-contained static web application (index.html + web_data.js)
for Delta Force (三角洲行动) Weapon & Attachment Analytics.
Works out-of-the-box on Cloudflare Pages, GitHub Pages, EdgeOne Pages, and local file://.
"""

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def inline_md(text: str) -> str:
    """Convert inline Markdown (code, bold, italic, links) to HTML safely."""
    # Escape HTML first
    text = html.escape(text)

    # Extract inline code spans to protect them from bold/italic replacement
    code_spans = []

    def save_code(m):
        idx = len(code_spans)
        code_spans.append(f'<code class="md-code">{m.group(1)}</code>')
        return f"@@CODE_{idx}@@"

    text = re.sub(r"`([^`]+)`", save_code, text)

    # Links [label](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener" class="md-link">\1</a>',
        text,
    )

    # Bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)

    # Restore code spans
    for idx, span in enumerate(code_spans):
        text = text.replace(f"@@CODE_{idx}@@", span)

    return text


def md_to_html_and_toc(md_text: str, prefix: str = "doc"):
    """Lightweight, dependency-free Markdown to HTML converter with table & TOC support."""
    lines = md_text.splitlines()
    out = []
    toc = []
    i = 0
    n = len(lines)
    heading_seq = 0

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Blank line
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", stripped) or re.match(r"^\*{3,}$", stripped):
            out.append('<hr class="md-hr" />')
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(html.escape(lines[i]))
                i += 1
            i += 1  # skip closing ```
            out.append(
                f'<pre class="md-pre"><code class="lang-{html.escape(lang)}">'
                + "\n".join(code_lines)
                + "</code></pre>"
            )
            continue

        # Heading
        m_head = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m_head:
            level = len(m_head.group(1))
            raw_title = m_head.group(2).strip()
            heading_seq += 1
            hid = f"{prefix}-h-{heading_seq}"
            clean_title = re.sub(r"[`*_]", "", raw_title)
            if level in (2, 3):
                toc.append({"id": hid, "level": level, "text": clean_title})
            out.append(
                f'<h{level} id="{hid}" class="md-h{level}">{inline_md(raw_title)}</h{level}>'
            )
            i += 1
            continue

        # Markdown Table (starts with | and next line is separator | :--- |)
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            align_cells = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            aligns = []
            for ac in align_cells:
                if ac.startswith(":") and ac.endswith(":"):
                    aligns.append("center")
                elif ac.endswith(":"):
                    aligns.append("right")
                else:
                    aligns.append("left")
            i += 2
            tbody_rows = []
            while i < n and lines[i].strip().startswith("|"):
                row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                tbody_rows.append(row_cells)
                i += 1

            th_html = "".join(
                f'<th style="text-align:{aligns[idx] if idx < len(aligns) else "left"}">{inline_md(hc)}</th>'
                for idx, hc in enumerate(header_cells)
            )
            tr_html_list = []
            for rcells in tbody_rows:
                tds = "".join(
                    f'<td style="text-align:{aligns[idx] if idx < len(aligns) else "left"}">{inline_md(rc)}</td>'
                    for idx, rc in enumerate(rcells)
                )
                tr_html_list.append(f"<tr>{tds}</tr>")
            out.append(
                '<div class="table-scroll"><table class="md-table">'
                f"<thead><tr>{th_html}</tr></thead>"
                f"<tbody>{''.join(tr_html_list)}</tbody>"
                "</table></div>"
            )
            continue

        # Blockquote
        if stripped.startswith(">"):
            bq_lines = []
            while i < n and lines[i].strip().startswith(">"):
                content = re.sub(r"^>\s?", "", lines[i].strip())
                bq_lines.append(inline_md(content))
                i += 1
            out.append(f'<blockquote class="md-blockquote">{"<br/>".join(bq_lines)}</blockquote>')
            continue

        # Unordered or Ordered List
        if re.match(r"^(\d+\.|[-*+])\s+", stripped):
            list_items = []
            is_ol = bool(re.match(r"^\d+\.\s+", stripped))
            tag = "ol" if is_ol else "ul"
            while i < n:
                cur = lines[i]
                cur_strip = cur.strip()
                if not cur_strip:
                    break
                m_li = re.match(r"^(\s*)(\d+\.|[-*+])\s+(.+)$", cur)
                if m_li:
                    indent = len(m_li.group(1))
                    content = inline_md(m_li.group(3))
                    cls = "md-li-sub" if indent >= 2 else "md-li"
                    list_items.append(f'<li class="{cls}">{content}</li>')
                    i += 1
                elif cur.startswith("  ") and list_items:
                    # Continuation or nested content (e.g., inline table inside list)
                    if cur_strip.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
                        break
                    list_items[-1] = list_items[-1][:-5] + f"<br/>{inline_md(cur_strip)}</li>"
                    i += 1
                else:
                    break
            out.append(f'<{tag} class="md-list">{"".join(list_items)}</{tag}>')
            continue

        # Paragraph
        p_lines = []
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith("#")
            and not lines[i].strip().startswith(">")
            and not lines[i].strip().startswith("```")
            and not (lines[i].strip().startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()))
            and not re.match(r"^(\d+\.|[-*+])\s+", lines[i].strip())
            and not re.match(r"^-{3,}$", lines[i].strip())
        ):
            p_lines.append(inline_md(lines[i].strip()))
            i += 1
        if p_lines:
            out.append(f'<p class="md-p">{" ".join(p_lines)}</p>')

    return "\n".join(out), toc


def main():
    weapons = load_json(DATA_DIR / "weapons_base_sol.json")
    variants = load_json(DATA_DIR / "weapon_mod_variants_sol.json")
    parts = load_json(DATA_DIR / "all_parts_catalog_sol.json")
    ammo = load_json(DATA_DIR / "ammo_catalog_and_prices.json")
    armors = load_json(DATA_DIR / "armors_and_helmets.json")

    custom_guide_md = (DOCS_DIR / "CUSTOM_LOADOUT_GUIDE.md").read_text(encoding="utf-8")
    insights_md = (DOCS_DIR / "INSIGHTS.md").read_text(encoding="utf-8")
    readme_md = (ROOT / "README.md").read_text(encoding="utf-8")

    cg_html, cg_toc = md_to_html_and_toc(custom_guide_md, "cg")
    in_html, in_toc = md_to_html_and_toc(insights_md, "in")
    rm_html, rm_toc = md_to_html_and_toc(readme_md, "rm")

    payload = {
        "updated_at": "2026-04 (S8 赛季最新解包+交易行实时物价)",
        "weapons": weapons,
        "variants": variants,
        "parts": parts,
        "ammo": ammo,
        "armors": armors,
        "docs": {
            "custom_guide": {
                "title": "🎯 绝密巴克什（外围+塔内）高容错定制配枪指南",
                "html": cg_html,
                "toc": cg_toc,
            },
            "insights": {
                "title": "🔬 全量武器与配件底层数据深度挖掘报告",
                "html": in_html,
                "toc": in_toc,
            },
            "readme": {
                "title": "📊 项目总览与 62 把武器全量基线天梯",
                "html": rm_html,
                "toc": rm_toc,
            },
        },
    }

    web_data_path = ROOT / "web_data.js"
    web_data_js = "window.DF_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    web_data_path.write_text(web_data_js, encoding="utf-8")
    print(f"Wrote {web_data_path} ({len(web_data_js) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
