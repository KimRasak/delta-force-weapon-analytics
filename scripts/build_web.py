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


SLOT_BY_PREFIX = {
    "1302": ("barrel", "枪管(Barrel)"),
    "1313": ("muzzle", "枪口(Muzzle)"),
    "1339": ("gasBlock", "导气箍(GasBlock)"),
    "1356": ("gasBlock", "导气箍(GasBlock)"),
    "1342": ("bolt", "枪机/杠杆(Bolt/Lever)"),
    "1352": ("bolt", "枪机/杠杆(Bolt/Lever)"),
    "1325": ("trigger", "扳机/击锤(Trigger)"),
    "1338": ("trigger", "扳机/击锤(Trigger)"),
    "1343": ("chargingHandle", "拉机柄帽(ChargingHandle)"),
    "1305": ("handguard", "护木/枪身套件(Handguard)"),
    "1320": ("handguard", "护木/枪身套件(Handguard)"),
    "1322": ("handguard", "护木/枪身套件(Handguard)"),
    "1340": ("handguard", "护木/枪身套件(Handguard)"),
    "1341": ("handguard", "护木/枪身套件(Handguard)"),
    "1314": ("foregrip", "前握把/阻手器(Foregrip)"),
    "1317": ("bipod", "两脚架/平衡杆(Bipod)"),
    "1351": ("bipod", "两脚架/平衡杆(Bipod)"),
    "1312": ("magazine", "弹匣/弹鼓(Magazine)"),
    "1334": ("magAssist", "弹匣快拔套(MagAssist)"),
    "1303": ("rearGrip", "后握把(RearGrip)"),
    "1333": ("gripMount", "握把片/底座(GripPanel)"),
    "1354": ("gripMount", "握把片/底座(GripPanel)"),
    "1345": ("gripMount", "握把片/底座(GripPanel)"),
    "1304": ("stock", "枪托(Stock)"),
    "1324": ("stockAcc", "托腮板/托垫/子弹袋(StockAcc)"),
    "1329": ("stockAcc", "托腮板/托垫/子弹袋(StockAcc)"),
    "1353": ("stockAcc", "托腮板/托垫/子弹袋(StockAcc)"),
    "1311": ("optic", "瞄准镜(Optic)"),
    "1321": ("opticAcc", "增高架/遮光罩(OpticAcc)"),
    "1337": ("opticAcc", "增高架/遮光罩(OpticAcc)"),
    "1316": ("laser", "激光镭指/手电(Laser)"),
    "1332": ("patch", "护木贴片(RailPatch)"),
    "1344": ("bowPart", "复合弓配件(BowPart)"),
    "1347": ("bowPart", "复合弓配件(BowPart)"),
    "1350": ("bowPart", "复合弓配件(BowPart)"),
}


def main():
    weapons = load_json(DATA_DIR / "weapons_base_sol.json")
    weapons_mp = load_json(DATA_DIR / "weapons_base_mp.json")
    variants = load_json(DATA_DIR / "weapon_mod_variants_sol.json")
    parts = load_json(DATA_DIR / "all_parts_catalog_sol.json")
    ammo = load_json(DATA_DIR / "ammo_catalog_and_prices.json")
    armors = load_json(DATA_DIR / "armors_and_helmets.json")
    relations = load_json(DATA_DIR / "weapon_part_relations_sol.json")

    lib_sol_path = DATA_DIR / "raw_cache" / "dfttk_v3" / "library_sol.json"
    lib_parts = load_json(lib_sol_path).get("parts", {}) if lib_sol_path.exists() else {}

    for p in parts:
        pid = p["part_id"]
        if pid[:4] in SLOT_BY_PREFIX:
            p["category_en"], p["category_cn"] = SLOT_BY_PREFIX[pid[:4]]
        p["laser_active_hipfire_bonus"] = 0
        p["laser_active_handling_bonus"] = 0
        p["empty_reload_set_s"] = None
        p_obj = lib_parts.get(pid)
        if p_obj and p_obj.get("effects"):
            ops = p_obj["effects"][0].get("data", {}).get("operations", [])
            passive_hip = 0
            active_hip = 0
            passive_hnd = 0
            active_hnd = 0
            has_tactical = False
            for op in ops:
                tgt = op.get("target")
                mod = op.get("modifier")
                val = op.get("value", 0)
                scp = op.get("scope", "NONE")
                if tgt == "WeaponMainAttribute.MainAttrValues.4" and mod == "Addend":
                    if scp == "TacticalEffective":
                        active_hip += int(val)
                        has_tactical = True
                    else:
                        passive_hip += int(val)
                elif tgt == "WeaponMainAttribute.MainAttrValues.5" and mod == "Addend":
                    if scp == "TacticalEffective":
                        active_hnd += int(val)
                        has_tactical = True
                    else:
                        passive_hnd += int(val)
                elif tgt == "ChangeClipTimewhenEmpty" and mod == "Initial":
                    p["empty_reload_set_s"] = val
            if has_tactical:
                p["hipfire_accuracy"] = passive_hip
                p["handling"] = passive_hnd
                p["laser_active_hipfire_bonus"] = active_hip
                p["laser_active_handling_bonus"] = active_hnd
                p["net_panel_points"] = p["recoil_control"] + passive_hip + passive_hnd + p["stability"]
                if p.get("hidden_mechanics_summary"):
                    p["hidden_mechanics_summary"] = re.sub(
                        r"开启镭指时:腰射\+\d+/操控\+\d+",
                        f"开启镭指时:腰射+{active_hip}/操控+{active_hnd}",
                        p["hidden_mechanics_summary"],
                    )

    # Pre-resolve mod_part_ids on each variant so clicking a variant in Tab 3 pre-equips its parts
    for v in variants:
        wname = v.get("weapon_name", "")
        mod_str = v.get("mod_parts", "")
        if not mod_str or mod_str == "无改装 (基线)":
            v["mod_part_ids"] = []
        else:
            names = [s.strip() for s in mod_str.split("+") if s.strip()]
            pids = []
            for nm in names:
                for p in parts:
                    cws = [x.strip() for x in (p.get("compatible_weapons") or "").split("/")]
                    if p["name"] == nm and wname in cws:
                        pids.append(p["part_id"])
                        break
            v["mod_part_ids"] = pids

    weapon_part_effects = {}
    for r in relations:
        if r.get("combat_change_note"):
            key = f"{r['weapon_id']}:{r['part_id']}"
            weapon_part_effects[key] = {
                "fire_mode": r["resulting_fire_mode"],
                "rof_rpm": r["resulting_rof_rpm"],
                "trigger_delay_ms": r["resulting_trigger_delay_ms"],
                "flesh_dmg": r["resulting_flesh_dmg"],
                "armor_dmg": r["resulting_armor_dmg"],
                "head_mult": r["resulting_head_mult"],
                "chest_mult": r["resulting_chest_mult"],
                "abdomen_mult": r["resulting_abdomen_mult"],
                "limb_mult": r["resulting_limb_mult"],
                "velocity_mps": r["resulting_velocity_mps"],
                "falloff": r["resulting_falloff"],
                "note": r["combat_change_note"],
            }

    build_codes = []
    cany_path = DATA_DIR / "raw_cache" / "cany_data.json"
    if cany_path.exists():
        cany = load_json(cany_path)
        for w in cany.get("prices", []):
            wname = w.get("weaponName", "")
            for cfg in w.get("configs", []):
                if cfg.get("buildCode"):
                    hr = cfg.get("hitRate") or []
                    build_codes.append({
                        "weapon_name": wname,
                        "price": cfg.get("price"),
                        "barrel": cfg.get("barrel") or "原厂",
                        "muzzle": cfg.get("muzzle") or "无",
                        "build_code": cfg["buildCode"],
                        "aim_speed_ms": cfg.get("aimSpeed"),
                        "recoil_v": cfg.get("recoilVerticalAuto"),
                        "recoil_h": cfg.get("recoilHorizontalAuto"),
                        "stability_mult": cfg.get("stabilityMultiplier"),
                        "hit_30m": round(hr[0] * 100, 1) if len(hr) > 0 else None,
                        "hit_50m": round(hr[1] * 100, 1) if len(hr) > 1 else None,
                        "hit_100m": round(hr[2] * 100, 1) if len(hr) > 2 else None,
                    })

    custom_guide_md = (DOCS_DIR / "CUSTOM_LOADOUT_GUIDE.md").read_text(encoding="utf-8")
    insights_md = (DOCS_DIR / "INSIGHTS.md").read_text(encoding="utf-8")
    readme_md = (ROOT / "README.md").read_text(encoding="utf-8")

    cg_html, cg_toc = md_to_html_and_toc(custom_guide_md, "cg")
    in_html, in_toc = md_to_html_and_toc(insights_md, "in")
    rm_html, rm_toc = md_to_html_and_toc(readme_md, "rm")

    payload = {
        "updated_at": "2026-10 (最新SDK底层解包 + 交易行实时物价校准)",
        "weapons": weapons,
        "weapons_mp": weapons_mp,
        "variants": variants,
        "parts": parts,
        "ammo": ammo,
        "armors": armors,
        "weapon_part_effects": weapon_part_effects,
        "build_codes": build_codes,
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
    web_data_path.unlink(missing_ok=True)
    web_data_path.write_text(web_data_js, encoding="utf-8")
    print(f"Wrote {web_data_path} ({len(web_data_js) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
