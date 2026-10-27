#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Delta Force (三角洲行动) Non-Sniper Weapons, Per-Gun Parts (零件数据), Combat Variants & Ammo/Armor Dataset Builder
Data Version: 2026-10-15 (S10/S11 Official SDK Runtime Pack) / Market Prices: 2026-10-23
"""

import csv
import glob
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PER_GUN_DIR = DATA_DIR / "per_weapon_parts"
DATA_DIR.mkdir(exist_ok=True)
PER_GUN_DIR.mkdir(exist_ok=True)

for old_f in ["practical_gunsmith_builds.json", "practical_gunsmith_builds.csv", "muzzle_and_tune_modifiers.json", "muzzle_and_tune_modifiers.csv"]:
    p = DATA_DIR / old_f
    if p.exists():
        p.unlink()

RAW_CACHE_DIR = ROOT / "data" / "raw_cache"
RESEARCH_DIR = RAW_CACHE_DIR
V3_DIR = RESEARCH_DIR / "dfttk_v3"
CANY_FILE = RAW_CACHE_DIR / "cany_data.json"
ORZICE_FILE = RAW_CACHE_DIR / "orzice_archive_price.json"
ORZICE_LIVE_AMMO_FILE = RAW_CACHE_DIR / "orzice_live_ammo.json"
AGENT_ATT_FILE = RAW_CACHE_DIR / "agent_attachments.json"


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_open(path, **kwargs):
    Path(path).unlink(missing_ok=True)
    return open(path, "w", **kwargs)


def calc_chest_btk_ttk(
    flesh_dmg,
    armor_dmg,
    chest_mult,
    rof_rpm,
    trigger_delay_ms,
    velocity_mps,
    falloff_segments,
    distance_m,
    armor_durability,
    ammo_flesh_mult,
    ammo_armor_mult,
    pen_rate,
    armor_dur_rate,
    fire_mode="Auto",
    burst_count=None,
    burst_internal_rof=None,
    burst_interval_s=None,
    rof_stages=None,
):
    decay = 1.0
    for seg in falloff_segments:
        if distance_m >= seg["fromM"] and distance_m < seg["toM"]:
            decay = seg["rate"]
            break
        elif distance_m >= seg["toM"]:
            decay = seg["rate"]

    raw_flesh = flesh_dmg * ammo_flesh_mult * chest_mult * decay
    raw_armor = armor_dmg * ammo_armor_mult * armor_dur_rate * decay

    hp = 100.0
    arm = float(armor_durability)
    shots = 0
    while hp > 1e-6 and shots < 100:
        shots += 1
        if arm > 0:
            if arm >= raw_armor and raw_armor > 0:
                dmg_to_hp = raw_flesh * pen_rate
                arm -= raw_armor
            elif raw_armor <= 0:
                dmg_to_hp = raw_flesh * pen_rate
            else:
                ratio_armored = arm / raw_armor
                dmg_to_hp = raw_flesh * (ratio_armored * pen_rate + (1.0 - ratio_armored) * 1.0)
                arm = 0.0
        else:
            dmg_to_hp = raw_flesh
        hp -= dmg_to_hp

    if shots <= 1:
        shoot_time_ms = 0.0
    else:
        if fire_mode in ("Burst", "burst") and burst_count and burst_internal_rof and burst_interval_s:
            internal_interval_ms = 60000.0 / burst_internal_rof
            gap_ms = burst_interval_s * 1000.0
            shoot_time_ms = 0.0
            for s_idx in range(1, shots):
                if s_idx % burst_count == 0:
                    shoot_time_ms += gap_ms
                else:
                    shoot_time_ms += internal_interval_ms
        elif rof_stages:
            shoot_time_ms = 0.0
            for s_idx in range(1, shots):
                cur_rof = rof_rpm
                for st in rof_stages:
                    if "untilShot" in st and s_idx <= st["untilShot"]:
                        cur_rof = rof_rpm + st.get("rofAdd", 0)
                        break
                shoot_time_ms += 60000.0 / cur_rof
        else:
            shoot_time_ms = (shots - 1) * (60000.0 / rof_rpm)

    flight_ms = (distance_m / velocity_mps) * 1000.0 if velocity_mps > 0 else 0.0
    total_ttk_ms = shoot_time_ms + (trigger_delay_ms or 0.0) + flight_ms
    return shots, round(total_ttk_ms, 1), round(shoot_time_ms, 1)


def calc_limb_btk_ttk(
    flesh_dmg,
    limb_mult,
    rof_rpm,
    trigger_delay_ms,
    velocity_mps,
    falloff_segments,
    distance_m,
    ammo_flesh_mult,
    fire_mode="Auto",
    burst_count=None,
    burst_internal_rof=None,
    burst_interval_s=None,
):
    decay = 1.0
    for seg in falloff_segments:
        if distance_m >= seg["fromM"] and distance_m < seg["toM"]:
            decay = seg["rate"]
            break
        elif distance_m >= seg["toM"]:
            decay = seg["rate"]
    dmg_per_shot = flesh_dmg * ammo_flesh_mult * limb_mult * decay
    if dmg_per_shot <= 0:
        return 99, 99999.0
    shots = math.ceil(100.0 / dmg_per_shot - 1e-9)
    if shots <= 1:
        shoot_time_ms = 0.0
    elif fire_mode in ("Burst", "burst") and burst_count and burst_internal_rof and burst_interval_s:
        internal_interval_ms = 60000.0 / burst_internal_rof
        gap_ms = burst_interval_s * 1000.0
        shoot_time_ms = 0.0
        for s_idx in range(1, shots):
            if s_idx % burst_count == 0:
                shoot_time_ms += gap_ms
            else:
                shoot_time_ms += internal_interval_ms
    else:
        shoot_time_ms = (shots - 1) * (60000.0 / rof_rpm)
    flight_ms = (distance_m / velocity_mps) * 1000.0 if velocity_mps > 0 else 0.0
    return shots, round(shoot_time_ms + (trigger_delay_ms or 0.0) + flight_ms, 1)


def format_falloff(segments):
    parts = []
    for s in segments:
        to_str = f"{s['toM']:g}m" if s["toM"] < 500 else "∞"
        parts.append(f"{s['fromM']:g}-{to_str}:{s['rate']:g}x")
    return " | ".join(parts)


PART_CAT_CN = {
    "barrel": "枪管(Barrel)",
    "muzzle": "枪口(Muzzle)",
    "foregrip": "前握把(Foregrip)",
    "rearGrip": "后握把(RearGrip)",
    "stock": "枪托(Stock)",
    "stockPad": "枪托垫(StockPad)",
    "cheekRest": "托腮板(CheekRest)",
    "secondaryStock": "副枪托(SubStock)",
    "handguard": "护木(Handguard)",
    "handguardKit": "枪身套件(ReceiverKit)",
    "magazine": "弹匣/弹鼓(Magazine)",
    "secondaryMagazine": "副弹匣(SubMag)",
    "scope": "瞄准镜/镜座(Scope)",
    "optic": "组合瞄具(Optic)",
    "functional": "功能配件(Functional:导气/枪机/扳机/镭指/脚架/贴片)",
}

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


def extract_part_attributes(p_obj, tune_str="", agent_meta=None):
    res = {
        "range_velocity_pct": 0.0,
        "only_range_pct": 0.0,
        "only_speed_pct": 0.0,
        "recoil_control": 0,
        "hipfire_accuracy": 0,
        "handling": 0,
        "stability": 0,
        "laser_active_hipfire_bonus": 0,
        "laser_active_handling_bonus": 0,
        "net_panel_points": 0,
        "rof_interval_pct": 0.0,
        "fire_interval_mult_c": 1.0,
        "fire_interval_add_s": 0.0,
        "fire_mode_override": "",
        "trigger_delay_override_ms": None,
        "head_mult_override": None,
        "projectile_count_override": None,
        "mag_capacity_set": None,
        "mag_capacity_add": 0,
        "reload_time_pct": 0.0,
        "reload_time_set_s": None,
        "empty_reload_set_s": None,
        "hidden_recoil_v_pct": 0.0,
        "hidden_recoil_h_pct": 0.0,
        "hidden_recoil_v_single_pct": 0.0,
        "hidden_recoil_h_single_pct": 0.0,
        "hidden_v_shake_mult": 1.0,
        "hidden_h_shake_mult": 1.0,
        "hidden_gunkick_v_mult": 1.0,
        "hidden_gunkick_h_mult": 1.0,
        "hidden_gunkick_rand_mult": 1.0,
        "hidden_gunkick_spring_mult": 1.0,
        "hidden_ads_time_pct": 0.0,
        "hidden_ads_move_speed_add": 0.0,
        "hidden_ads_spread_pct": 0.0,
        "hidden_hit_camera_sway_pct": 0.0,
        "hidden_hit_gun_sway_pct": 0.0,
        "hidden_hold_breath_mult": 1.0,
        "hidden_shot_sound_mult": 1.0,
        "replaces_recoil_profile": False,
        "replaces_hip_spread_profile": False,
        "replaces_ads_spread_profile": False,
        "replaces_movement_profile": False,
        "custom_damage_str": "",
        "custom_bullet_str": "",
        "special_override_str": "",
        "hidden_mechanics_summary": "",
    }

    if not p_obj.get("effects"):
        return res

    d = p_obj["effects"][0].get("data", {})
    ops = d.get("operations", [])

    attr4_vals = []
    attr5_vals = []

    for op in ops:
        t = op.get("target")
        m = op.get("modifier")
        v = op.get("value")
        if v == 0 and m != "Initial":
            continue

        if t == "WeaponMainAttribute.MainAttrValues.2" and m == "Mult_A":
            res["range_velocity_pct"] = round(v * 100, 1)
        elif t == "GBullet_OnlyRange" and m == "Mult_A":
            res["only_range_pct"] = round(v * 100, 1)
        elif t == "GRange_OnlySpeed" and m == "Mult_A":
            res["only_speed_pct"] = round(v * 100, 1)
        elif t == "WeaponMainAttribute.MainAttrValues.3" and m == "Addend":
            res["recoil_control"] += int(v)
        elif t == "WeaponMainAttribute.MainAttrValues.4" and m == "Addend":
            attr4_vals.append(int(v))
        elif t == "WeaponMainAttribute.MainAttrValues.5" and m == "Addend":
            attr5_vals.append(int(v))
        elif t == "WeaponMainAttribute.MainAttrValues.6" and m == "Addend":
            res["stability"] += int(v)
        elif t == "GRateOfFire" and m == "Mult_A":
            res["rof_interval_pct"] = round(v * 100, 2)
        elif t == "FireInterval" and m == "Mult_A":
            res["rof_interval_pct"] = round(v * 100, 2)
        elif t == "FireInterval" and m == "Mult_C":
            res["fire_interval_mult_c"] = v
        elif t == "FireInterval" and m == "Addend":
            res["fire_interval_add_s"] = v
        elif t == "FireRateMode" and m == "Initial":
            res["fire_mode_override"] = "全自动(Auto)" if v == 0 else f"半自动/连发(Mode={v})"
        elif t == "FireDelayTime" and m == "Initial":
            res["trigger_delay_override_ms"] = int(v * 1000)
        elif t == "DamagePointId.HeadDamageRate" and m == "Initial":
            res["head_mult_override"] = v
        elif t == "ProjectileNumPerShot" and m == "Initial":
            res["projectile_count_override"] = int(v)
        elif t == "GMagCapacity":
            if m == "Initial":
                res["mag_capacity_set"] = int(v)
            elif m == "Addend":
                res["mag_capacity_add"] += int(v)
        elif t in ("ChangeClipTime", "GReload_Time") and m == "Mult_A":
            res["reload_time_pct"] = round(v * 100, 1)
        elif t == "ChangeClipTime" and m == "Initial":
            res["reload_time_set_s"] = v
        elif t == "ChangeClipTimewhenEmpty" and m == "Initial":
            res["empty_reload_set_s"] = v
        elif t == "GRecoil_V":
            if m == "Mult_A":
                res["hidden_recoil_v_pct"] = round(v * 100, 1)
            elif m == "Mult_C":
                res["hidden_recoil_v_pct"] = round((v - 1.0) * 100, 1)
        elif t == "GRecoil_H":
            if m == "Mult_A":
                res["hidden_recoil_h_pct"] = round(v * 100, 1)
            elif m == "Mult_C":
                res["hidden_recoil_h_pct"] = round((v - 1.0) * 100, 1)
        elif t == "GRecoil_V_singleorburst" and m == "Mult_A":
            res["hidden_recoil_v_single_pct"] = round(v * 100, 1)
        elif t == "GRecoil_H_singleorburst" and m == "Mult_A":
            res["hidden_recoil_h_single_pct"] = round(v * 100, 1)
        elif t == "GRecoil_VShake" and m == "Mult_C":
            res["hidden_v_shake_mult"] = v
        elif t == "GRecoil_HShake" and m == "Mult_C":
            res["hidden_h_shake_mult"] = v
        elif t == "GGunkickV" and m == "Mult_C":
            res["hidden_gunkick_v_mult"] = v
        elif t == "GGunkickH" and m == "Mult_C":
            res["hidden_gunkick_h_mult"] = v
        elif t == "GGunkickRandom" and m == "Mult_C":
            res["hidden_gunkick_rand_mult"] = v
        elif t == "GGunkickSpring" and m == "Mult_C":
            res["hidden_gunkick_spring_mult"] = v
        elif t == "GAiming_ADSTime" and m == "Mult_A":
            res["hidden_ads_time_pct"] = round(v * 100, 1)
        elif t == "GMovement_ADSSpeed" and m == "Addend":
            res["hidden_ads_move_speed_add"] = v
        elif t == "GSpread_ADS" and m == "Mult_A":
            res["hidden_ads_spread_pct"] = round(v * 100, 1)
        elif t == "CameraSwayBeHitScale" and m == "Mult_A":
            res["hidden_hit_camera_sway_pct"] = round(v * 100, 1)
        elif t == "GunSwayBeHitscale" and m == "Mult_A":
            res["hidden_hit_gun_sway_pct"] = round(v * 100, 1)
        elif t == "WeaponAppearanceTable.HoldBreathId.StandBreathFactor" and m == "Mult_C":
            res["hidden_hold_breath_mult"] = v
        elif t == "ShotDistance" and m == "Mult_C":
            res["hidden_shot_sound_mult"] = v
        elif t in ("AimingId.RecoilId", "WaistShootRecoilId"):
            res["replaces_recoil_profile"] = True
        elif t == "WaistShootSpreadId":
            res["replaces_hip_spread_profile"] = True
        elif t == "AimingId.SpreadId":
            res["replaces_ads_spread_profile"] = True
        elif t == "MovementSpeedId":
            res["replaces_movement_profile"] = True

    if len(attr4_vals) == 1:
        res["hipfire_accuracy"] = attr4_vals[0]
    elif len(attr4_vals) >= 2:
        res["hipfire_accuracy"] = min(attr4_vals)
        res["laser_active_hipfire_bonus"] = max(attr4_vals)

    if len(attr5_vals) == 1:
        res["handling"] = attr5_vals[0]
    elif len(attr5_vals) >= 2:
        res["handling"] = min(attr5_vals)
        res["laser_active_handling_bonus"] = max(attr5_vals)

    res["net_panel_points"] = (
        res["recoil_control"] + res["hipfire_accuracy"] + res["handling"] + res["stability"]
    )

    dp = d.get("damageProfile")
    if dp:
        hb = dp.get("hitboxMultipliers", {})
        res["custom_damage_str"] = (
            f"肉伤={dp.get('baseDamage')}/甲伤={dp.get('baseArmorDamage')} "
            f"(头{hb.get('head')}x/胸{hb.get('upperChest')}x/腹{hb.get('lowerChest')}x/四肢{hb.get('upperArm')}x)"
        )

    bp = d.get("bulletProfile")
    if bp:
        vel = bp.get("initialSpeedCmPerSecond", 0) / 100.0
        v_dist = bp.get("validDistanceCm", 0) / 100.0
        att_d = [x / 100.0 for x in bp.get("attenuationDistancesCm", []) if x < 50000]
        att_r = bp.get("attenuationRates", [])
        res["custom_bullet_str"] = f"初速={vel:g}m/s, 一段射程={v_dist:g}m, 衰减节点={att_d}, 衰减率={att_r}"

    ov = d.get("override")
    if ov:
        ov_parts = []
        if ov.get("supportedModes"):
            ov_parts.append(f"开火模式={ov['supportedModes']}")
        if ov.get("fireScheduleRules"):
            ov_parts.append(f"射速序列={ov['fireScheduleRules']}")
        res["special_override_str"] = "; ".join(ov_parts)

    hm = []
    if res["only_range_pct"]:
        hm.append(f"纯射程{res['only_range_pct']:+g}%")
    if res["hidden_recoil_v_pct"]:
        hm.append(f"独立垂直后坐{res['hidden_recoil_v_pct']:+g}%")
    if res["hidden_recoil_h_pct"]:
        hm.append(f"独立水平后坐{res['hidden_recoil_h_pct']:+g}%")
    if res["hidden_recoil_v_single_pct"]:
        hm.append(f"单点/连发垂直后坐{res['hidden_recoil_v_single_pct']:+g}%")
    if res["hidden_recoil_h_single_pct"]:
        hm.append(f"单点/连发水平后坐{res['hidden_recoil_h_single_pct']:+g}%")
    if res["hidden_v_shake_mult"] != 1.0:
        hm.append(f"垂直晃动×{res['hidden_v_shake_mult']:g}")
    if res["hidden_h_shake_mult"] != 1.0:
        hm.append(f"水平晃动×{res['hidden_h_shake_mult']:g}")
    if res["hidden_gunkick_v_mult"] != 1.0:
        hm.append(f"枪身垂直跳动×{res['hidden_gunkick_v_mult']:g}")
    if res["hidden_gunkick_h_mult"] != 1.0:
        hm.append(f"枪身水平跳动×{res['hidden_gunkick_h_mult']:g}")
    if res["hidden_gunkick_rand_mult"] != 1.0:
        hm.append(f"随机枪跳×{res['hidden_gunkick_rand_mult']:g}")
    if res["hidden_gunkick_spring_mult"] != 1.0:
        hm.append(f"回弹抖动×{res['hidden_gunkick_spring_mult']:g}")
    if res["hidden_ads_time_pct"]:
        hm.append(f"独立开镜时间{res['hidden_ads_time_pct']:+g}%")
    if res["hidden_ads_move_speed_add"]:
        hm.append(f"开镜移速{res['hidden_ads_move_speed_add']:+g}")
    if res["hidden_ads_spread_pct"]:
        hm.append(f"开镜散布{res['hidden_ads_spread_pct']:+g}%")
    if res["hidden_hit_camera_sway_pct"]:
        hm.append(f"受击镜头晃动{res['hidden_hit_camera_sway_pct']:+g}%")
    if res["hidden_hit_gun_sway_pct"]:
        hm.append(f"受击枪口晃动{res['hidden_hit_gun_sway_pct']:+g}%")
    if res["hidden_hold_breath_mult"] != 1.0 and p_obj.get("category") not in ("scope", "optic"):
        hm.append(f"屏息晃动×{res['hidden_hold_breath_mult']:g}")
    if res["hidden_shot_sound_mult"] != 1.0:
        hm.append(f"枪声距离×{res['hidden_shot_sound_mult']:g}")
    if res["replaces_recoil_profile"]:
        hm.append("专属后坐力曲线覆写")
    if res["replaces_hip_spread_profile"]:
        hm.append("专属腰射散布覆写")
    if res["replaces_ads_spread_profile"]:
        hm.append("专属开镜散布覆写")
    if res["replaces_movement_profile"]:
        hm.append("专属移速曲线覆写")
    if res["laser_active_handling_bonus"]:
        hm.append(f"开启镭指时:腰射+{res['laser_active_hipfire_bonus']}/操控+{res['laser_active_handling_bonus']}")
    res["hidden_mechanics_summary"] = " | ".join(hm)

    return res


def main():
    cat_weapons = load_json(V3_DIR / "catalog_weapons.json")["objects"]
    cat_ammo = load_json(V3_DIR / "catalog_ammo.json")["ammo"]
    ammo_inter = load_json(V3_DIR / "combat_defense_ammo-interactions.json")["profiles"]
    armors_doc = load_json(V3_DIR / "combat_defense_armors.json")["profiles"]
    helmets_doc = load_json(V3_DIR / "combat_defense_helmets.json")["profiles"]
    econ_doc = load_json(V3_DIR / "economy_market-prices.json")
    econ_prices = econ_doc["prices"]
    econ_avail = econ_doc.get("availability", {})
    items_loc = load_json(V3_DIR / "locales_zh-CN_items.json")["items"]
    tune_loc = load_json(V3_DIR / "locales_zh-CN_tune.json")["tune"]
    lib_sol = load_json(V3_DIR / "library_sol.json")
    lib_weapons = lib_sol["weapons"]
    lib_parts = lib_sol["parts"]

    # Normalize unlocalized placeholders, abbreviated translations, and casing mismatches
    # against official attachment names in agent_attachments.json / orzice_archive_price.json
    part_name_overrides = {
        "13120000380": "QJB201专属75发弹盒",
        "13120000256": "AUG60发弹鼓",
        "13110000099": "1p33 2/4倍瞄准镜",
        "13020000531": "QCQ171新式狡兔短枪管组合",
        "13020000532": "QCQ171新式红缨战术长枪管",
        "13110000091": "灵眼3/7弹道计算狙击镜",
        "13110000092": "灵眼6/12弹道计算狙击镜",
        "13020000402": "SVD实用长枪管",
        "13020000423": "SMG45实用重枪管",
        "13020000569": "ASh-12战斧重型枪管",
        "13030000124": "SVD聚合物一体枪托",
        "13050000249": "SVD聚合物护木",
        "13110000061": "OKP-7反射瞄准镜",
    }
    for pid, canonical_name in part_name_overrides.items():
        items_loc[pid] = canonical_name
        if pid in lib_parts:
            lib_parts[pid]["name"] = canonical_name
    cany_data = load_json(CANY_FILE)
    orzice_list = load_json(ORZICE_FILE)
    agent_nodes = load_json(AGENT_ATT_FILE)["nodes"]

    agent_by_name = {}
    for n in agent_nodes:
        if "Attachment" in n.get("labels", []):
            pr = n.get("props", {})
            nm = pr.get("name", "").strip()
            if nm:
                agent_by_name[nm] = pr
                agent_by_name[nm.replace(" ", "").upper()] = pr

    part_tunes = {}
    for path in sorted(glob.glob(str(V3_DIR / "combat_weapons" / "*.json"))):
        pack = load_json(path)
        tunes = pack.get("tunes", {})
        curves = pack.get("curves", {})
        for pid, pinfo in pack.get("parts", {}).items():
            tids = pinfo.get("tuneIds") or []
            if tids and pid not in part_tunes:
                t_list = []
                for tid in tids:
                    tobj = tunes.get(tid, {})
                    lbl = tobj.get("labels", {}).get("mainLocId", "")
                    lbl_cn = tune_loc.get(lbl, lbl.replace("authoring:", ""))
                    funcs = []
                    for fn in tobj.get("functions", []):
                        cid = fn.get("curveId")
                        pts = curves.get(cid, {}).get("points", [])
                        min_v = pts[0]["outputValue"] if pts else None
                        max_v = pts[-1]["outputValue"] if pts else None
                        funcs.append(f"{fn.get('target')}({min_v}..{max_v})")
                    t_list.append(f"{lbl_cn}[{'/'.join(funcs)}]" if funcs else lbl_cn)
                part_tunes[pid] = "; ".join(t_list)

    orzice_by_name = {}
    for item in orzice_list:
        nm = item.get("name", "").strip()
        if nm and item.get("price"):
            orzice_by_name[nm] = item["price"]
            orzice_by_name[nm.replace(" ", "").upper()] = item["price"]

    orzice_live_ammo_map = {}
    if ORZICE_LIVE_AMMO_FILE.exists():
        live_doc = load_json(ORZICE_LIVE_AMMO_FILE)
        for item in live_doc.get("items", []):
            nm = item.get("name", "").replace("&#43;", "+").strip()
            pr = item.get("price")
            if nm and pr:
                orzice_live_ammo_map[nm] = pr
                orzice_live_ammo_map[nm.replace(" ", "").upper()] = pr

    cany_ammo_map = {}
    for b in cany_data["bullets"]:
        cal = b["caliber"].replace(" ", "").replace("*", "x").upper()
        nm = b["name"].replace(" ", "").replace("-", "").upper()
        cany_ammo_map[(cal, b["level"], nm)] = b["price"]
        cany_ammo_map[(b["level"], nm)] = b["price"]

    ammo_type_to_cal = {}
    for aid, a in cat_ammo.items():
        if a.get("ammoTypeId") and a.get("caliber"):
            ammo_type_to_cal[a["ammoTypeId"]] = a["caliber"].replace("*", "x")

    # Build Ammo Catalog & Prices
    ammo_rows = []
    rep_ammo_by_type_level = {}
    rip_ammo_by_type = {}

    for aid, a in sorted(cat_ammo.items(), key=lambda x: (str(x[1].get("ammoTypeId", "")), x[1].get("penetrationLevel", 0), x[0])):
        at_id = a.get("ammoTypeId")
        cal = a.get("caliber") or ammo_type_to_cal.get(at_id) or "Special"
        cal_clean = cal.replace("*", "x")
        name = a.get("name", "")
        level = a.get("penetrationLevel", 0)
        rarity = a.get("rarity") or ""

        if cal_clean == "Special":
            if "7.62x51" in name:
                cal_clean = "7.62x51mm"
            elif "5.8x42" in name:
                cal_clean = "5.8x42mm"
            elif "9x39" in name:
                cal_clean = "9x39mm"
            elif ".45 ACP" in name:
                cal_clean = ".45ACP"
            elif "9x19" in name:
                cal_clean = "9x19mm"
            elif "12 Gauge" in name:
                cal_clean = "12Gauge"
            elif "箭" in name:
                cal_clean = "Arrow"

        # Check live orzice SSR ammo table first, then dfttk_v3 economy/market-prices.json
        price = None
        price_source = ""
        cand_keys = [
            f"{cal_clean} {name}".replace(" ", "").upper(),
            name.replace(" ", "").upper(),
            f".300BLK_{level}" if "300BLK" in cal_clean.upper() else "",
        ]
        for ck in cand_keys:
            if ck and ck in orzice_live_ammo_map:
                price = orzice_live_ammo_map[ck]
                price_source = "orzice_live_ssr"
                break
        if price is None and econ_prices.get(aid) is not None:
            price = econ_prices.get(aid)
            price_source = "dfttk_live_20261023"
        if price is None and aid in econ_avail and econ_avail[aid].get("lastKnownPrice"):
            price = econ_avail[aid]["lastKnownPrice"]
            price_source = "dfttk_last_known"
        if price is None:
            cal_key = cal_clean.replace(" ", "").upper()
            nm_key = name.replace(" ", "").replace("-", "").replace("“", "").replace("”", "").replace("蛋", "弹").upper()
            for pref in ["7.62X51MM", "5.8X42MM", "9X39MM", ".45ACP", "9X19MM", "12GAUGE"]:
                if nm_key.startswith(pref):
                    nm_key = nm_key[len(pref):]
            price = cany_ammo_map.get((cal_key, level, nm_key)) or cany_ammo_map.get((level, nm_key))
            if price is not None:
                price_source = "cany_orzice_20261019"
        if price is None:
            for cand_k, cand_p in orzice_by_name.items():
                if name.replace(" ", "").upper() in cand_k and cal_clean.split("x")[0].upper() in cand_k:
                    price = cand_p
                    price_source = "orzice_archive"
                    break

        market_status = "交易行可售"
        if price is None:
            if level >= 6:
                market_status = "红弹(交易行禁售/仅特勤处制造或局内产出)"
            else:
                market_status = "历史赛季/活动限定或仅工作台制造"

        inter = ammo_inter.get(aid, {}).get("armorCorrection", {})
        row = {
            "ammo_id": aid,
            "ammo_type_id": at_id or "",
            "caliber": cal_clean,
            "name": name,
            "penetration_level": level,
            "rarity": rarity,
            "is_season_limited": bool(a.get("isSeasonLimited", False)),
            "market_price": price,
            "market_status": market_status,
            "price_source": price_source,
            "flesh_damage_mult": a.get("fleshDamageMultiplier", 1.0),
            "armor_damage_mult": a.get("armorDamageMultiplier", 1.0),
        }
        for lv in range(1, 7):
            c = inter.get(str(lv), {})
            row[f"pen_rate_lv{lv}"] = c.get("bodyHealthRate", 0.0)
            row[f"armor_dur_rate_lv{lv}"] = c.get("bodyDurabilityRate", 1.0)
        ammo_rows.append(row)

        if at_id and not a.get("isSeasonLimited", False):
            key = (str(at_id), level)
            if key not in rep_ammo_by_type_level:
                rep_ammo_by_type_level[key] = row
            else:
                old = rep_ammo_by_type_level[key]
                if old["market_price"] is None and price is not None:
                    rep_ammo_by_type_level[key] = row
                elif level >= 3 and old["flesh_damage_mult"] != 1.0 and row["flesh_damage_mult"] == 1.0 and price is not None:
                    rep_ammo_by_type_level[key] = row

        if at_id and price is not None and (level == 0 or row["flesh_damage_mult"] >= 1.2):
            if str(at_id) not in rip_ammo_by_type or row["flesh_damage_mult"] > rip_ammo_by_type[str(at_id)]["flesh_damage_mult"]:
                rip_ammo_by_type[str(at_id)] = row

    with write_open(DATA_DIR / "ammo_catalog_and_prices.json", encoding="utf-8") as f:
        json.dump(ammo_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "ammo_catalog_and_prices.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(ammo_rows[0].keys()))
        writer.writeheader()
        writer.writerows(ammo_rows)

    # Build Armors & Helmets table
    cany_armors = {x["name"]: x["price"] for x in cany_data.get("armors", [])}
    defense_rows = []
    for aid, a in sorted(armors_doc.items(), key=lambda x: (x[1]["level"], x[1]["maxDurability"])):
        nm = a["name"]
        p = econ_prices.get(aid) or cany_armors.get(nm) or orzice_by_name.get(nm)
        defense_rows.append({
            "item_id": aid,
            "type": "防弹衣(Armor)",
            "name": nm,
            "level": a["level"],
            "max_durability": a["maxDurability"],
            "covered_areas": "+".join(a["coveredHitAreas"]),
            "covers_abdomen": "lowerChest" in a["coveredHitAreas"],
            "covers_upper_arm": "upperArm" in a["coveredHitAreas"],
            "market_price": p,
        })
    for hid, h in sorted(helmets_doc.items(), key=lambda x: (x[1]["level"], x[1]["maxDurability"])):
        nm = h["name"]
        p = econ_prices.get(hid) or cany_armors.get(nm) or orzice_by_name.get(nm)
        defense_rows.append({
            "item_id": hid,
            "type": "头盔(Helmet)",
            "name": nm,
            "level": h["level"],
            "max_durability": h["maxDurability"],
            "covered_areas": "+".join(h["coveredHitAreas"]),
            "covers_abdomen": False,
            "covers_upper_arm": False,
            "market_price": p,
        })
    with write_open(DATA_DIR / "armors_and_helmets.json", encoding="utf-8") as f:
        json.dump(defense_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "armors_and_helmets.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(defense_rows[0].keys()))
        writer.writeheader()
        writer.writerows(defense_rows)

    # Build All 577 Parts Master Catalog
    non_sniper_wids = {
        wid for wid, obj in cat_weapons.items()
        if obj.get("categoryId") not in ("sniperRifle", "specialWeapon")
    }

    all_parts_rows = []
    for pid, p_obj in sorted(lib_parts.items(), key=lambda x: (x[1].get("category", ""), x[0])):
        pname = p_obj.get("name", pid)
        raw_cat_en = p_obj.get("category", "unknown")
        slot_en, slot_cn = SLOT_BY_PREFIX.get(pid[:4], (raw_cat_en, PART_CAT_CN.get(raw_cat_en, raw_cat_en)))
        pcat_en = slot_en
        pcat_cn = slot_cn
        rarity = p_obj.get("rarity", "")
        p_price = (
            econ_prices.get(pid)
            or econ_avail.get(pid, {}).get("lastKnownPrice")
            or orzice_by_name.get(pname)
            or orzice_by_name.get(pname.replace(" ", "").upper())
        )
        t_str = part_tunes.get(pid, "")
        ag = agent_by_name.get(pname) or agent_by_name.get(pname.replace(" ", "").upper()) or {}
        weight_kg = ag.get("weight")
        grid_size = f"{ag.get('width', '')}x{ag.get('length', '')}" if ag.get("width") and ag.get("length") else ""
        adv_list = ag.get("effects", {}).get("advantage", []) if isinstance(ag.get("effects"), dict) else []
        dis_list = ag.get("effects", {}).get("disadvantage", []) if isinstance(ag.get("effects"), dict) else []

        wids_all = p_obj.get("weaponIds", [])
        wids_non_sniper = [w for w in wids_all if w in non_sniper_wids]
        wnames_non_sniper = [items_loc.get(w, w) for w in wids_non_sniper]

        attrs = extract_part_attributes(p_obj, t_str, ag)
        net_pts = attrs["net_panel_points"]
        price_per_pt = round(p_price / net_pts) if (p_price and net_pts > 0) else None

        part_row = {
            "part_id": pid,
            "name": pname,
            "category_cn": pcat_cn,
            "category_en": pcat_en,
            "rarity": rarity,
            "market_price": p_price,
            "weight_kg": weight_kg,
            "grid_size": grid_size,
            "compatible_non_sniper_count": len(wids_non_sniper),
            "compatible_all_weapons_count": len(wids_all),
            "compatible_weapons": " / ".join(wnames_non_sniper),
            "range_velocity_pct": attrs["range_velocity_pct"],
            "only_range_pct": attrs["only_range_pct"],
            "recoil_control": attrs["recoil_control"],
            "hipfire_accuracy": attrs["hipfire_accuracy"],
            "handling": attrs["handling"],
            "stability": attrs["stability"],
            "laser_active_hipfire_bonus": attrs["laser_active_hipfire_bonus"],
            "laser_active_handling_bonus": attrs["laser_active_handling_bonus"],
            "net_panel_points": net_pts,
            "price_per_positive_point": price_per_pt,
            "rof_interval_pct": attrs["rof_interval_pct"],
            "fire_mode_override": attrs["fire_mode_override"],
            "trigger_delay_override_ms": attrs["trigger_delay_override_ms"],
            "head_mult_override": attrs["head_mult_override"],
            "mag_capacity_set": attrs["mag_capacity_set"],
            "mag_capacity_add": attrs["mag_capacity_add"],
            "reload_time_pct": attrs["reload_time_pct"],
            "reload_time_set_s": attrs["reload_time_set_s"],
            "empty_reload_set_s": attrs["empty_reload_set_s"],
            "hidden_recoil_v_pct": attrs["hidden_recoil_v_pct"],
            "hidden_recoil_h_pct": attrs["hidden_recoil_h_pct"],
            "hidden_recoil_v_single_pct": attrs["hidden_recoil_v_single_pct"],
            "hidden_recoil_h_single_pct": attrs["hidden_recoil_h_single_pct"],
            "hidden_v_shake_mult": attrs["hidden_v_shake_mult"],
            "hidden_h_shake_mult": attrs["hidden_h_shake_mult"],
            "hidden_gunkick_v_mult": attrs["hidden_gunkick_v_mult"],
            "hidden_gunkick_h_mult": attrs["hidden_gunkick_h_mult"],
            "hidden_gunkick_rand_mult": attrs["hidden_gunkick_rand_mult"],
            "hidden_gunkick_spring_mult": attrs["hidden_gunkick_spring_mult"],
            "hidden_ads_time_pct": attrs["hidden_ads_time_pct"],
            "hidden_ads_move_speed_add": attrs["hidden_ads_move_speed_add"],
            "hidden_ads_spread_pct": attrs["hidden_ads_spread_pct"],
            "hidden_hit_camera_sway_pct": attrs["hidden_hit_camera_sway_pct"],
            "hidden_hit_gun_sway_pct": attrs["hidden_hit_gun_sway_pct"],
            "hidden_hold_breath_mult": attrs["hidden_hold_breath_mult"],
            "hidden_shot_sound_mult": attrs["hidden_shot_sound_mult"],
            "custom_damage_profile": attrs["custom_damage_str"],
            "custom_bullet_profile": attrs["custom_bullet_str"],
            "special_override": attrs["special_override_str"],
            "hidden_mechanics_summary": attrs["hidden_mechanics_summary"],
            "is_combat_tunable": bool(t_str),
            "tune_details": t_str,
            "tooltip_advantages": "；".join(adv_list),
            "tooltip_disadvantages": "；".join(dis_list),
        }
        all_parts_rows.append(part_row)

    with write_open(DATA_DIR / "all_parts_catalog_sol.json", encoding="utf-8") as f:
        json.dump(all_parts_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "all_parts_catalog_sol.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_parts_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_parts_rows)

    part_row_by_id = {r["part_id"]: r for r in all_parts_rows}

    cat_cn_map = {
        "assaultRifle": "突击步枪",
        "submachineGun": "冲锋枪",
        "lightMachineGun": "轻/通用机枪",
        "marksmanRifle": "精确射手步枪",
        "shotgun": "霰弹枪",
        "pistol": "手枪",
    }

    base_sol_rows = []
    base_mp_rows = []
    mod_variant_rows = []
    weapon_part_relation_rows = []

    for wid, wobj in sorted(cat_weapons.items()):
        cat_en = wobj.get("categoryId", "unknown")
        if cat_en in ("sniperRifle", "specialWeapon"):
            continue
        if wid.startswith("1803"):
            cat_en = "shotgun"
        cat_cn = cat_cn_map.get(cat_en, cat_en)
        wname = items_loc.get(wid, wid)
        at_id = str(wobj.get("ammoTypeId", ""))
        caliber = ammo_type_to_cal.get(at_id, at_id)
        bare_price = econ_prices.get(wid) or orzice_by_name.get(wname)

        sol = wobj["combatSummaryByMode"]["sol"]
        mp = wobj["combatSummaryByMode"]["mp"]
        lib_w = lib_weapons.get(wid, {})
        pack = load_json(V3_DIR / "combat_weapons" / f"{wid}.json")

        ammo_lv3 = rep_ammo_by_type_level.get((at_id, 3))
        ammo_lv4 = rep_ammo_by_type_level.get((at_id, 4))
        ammo_lv5 = rep_ammo_by_type_level.get((at_id, 5))
        ammo_rip = rip_ammo_by_type.get(at_id)

        p_lv3 = ammo_lv3["market_price"] if ammo_lv3 else None
        p_lv4 = ammo_lv4["market_price"] if ammo_lv4 else None
        p_lv5 = ammo_lv5["market_price"] if ammo_lv5 else None
        p_rip = ammo_rip["market_price"] if ammo_rip else None

        hb = sol["hitboxMultipliers"]
        segs = sol["damageFalloffSegments"]
        rof = round(sol["fireRateRpm"], 1)
        flesh = sol["baseFleshDamage"]
        armor = sol["baseArmorDamage"]
        vel = sol["muzzleVelocityMps"]
        delay = sol["triggerDelayMs"]
        fmode = sol["selectedFireMode"]

        base_burst_count = None
        base_burst_irof = None
        base_burst_int = None
        if fmode in ("Burst", "burst") or wid in ("18010000014", "18020000012", "18070000006"):
            if wid == "18020000012":
                base_burst_count = 3
                base_burst_irof = 1200
                base_burst_int = 0.127
                fmode = "Burst"
            elif wid == "18010000014":
                base_burst_count = 3
                base_burst_irof = 858
                base_burst_int = 0.21
                fmode = "Burst"
            elif wid == "18070000006":
                base_burst_count = 3
                base_burst_irof = 1100
                base_burst_int = 0.24
                fmode = "Burst"

        main_attrs = pack.get("weapon", {}).get("attributes", {}).get("mainAttrValues", {})
        base_attr_range = main_attrs.get("2")
        base_attr_recoil = main_attrs.get("3")
        base_attr_hip = main_attrs.get("4")
        base_attr_handling = main_attrs.get("5")
        base_attr_stability = main_attrs.get("6")

        compat_pids = [pid for pid, p in lib_parts.items() if wid in p.get("weaponIds", [])]

        r1 = segs[0]["toM"] if len(segs) >= 1 else 1000
        r2 = segs[1]["toM"] if len(segs) >= 2 else 1000
        d1 = segs[1]["rate"] if len(segs) >= 2 else 1.0
        d2 = segs[2]["rate"] if len(segs) >= 3 else d1
        d_min = segs[-1]["rate"] if segs else 1.0

        base_sol_row = {
            "weapon_id": wid,
            "name": wname,
            "category_cn": cat_cn,
            "category_en": cat_en,
            "caliber": caliber,
            "bare_gun_price": bare_price,
            "compatible_parts_count": len(compat_pids),
            "fire_mode": fmode,
            "supported_fire_modes": "/".join(sol.get("supportedFireModes", [])),
            "rof_rpm": rof,
            "shot_interval_ms": round(60000.0 / rof, 2) if rof > 0 else None,
            "trigger_delay_ms": delay,
            "muzzle_velocity_mps": vel,
            "projectile_count": sol.get("projectileCount", 1),
            "base_flesh_damage": flesh,
            "base_armor_damage": armor,
            "flesh_dps": round(flesh * rof / 60.0, 1),
            "armor_dps": round(armor * rof / 60.0, 1),
            "head_mult": hb["head"],
            "chest_mult": hb["upperChest"],
            "abdomen_mult": hb["lowerChest"],
            "upper_arm_mult": hb["upperArm"],
            "lower_arm_mult": hb["lowerArm"],
            "thigh_mult": hb["thigh"],
            "calf_mult": hb["lowerLeg"],
            "headshot_damage_0m": round(flesh * hb["head"], 1),
            "chest_damage_0m": round(flesh * hb["upperChest"], 1),
            "abdomen_damage_0m": round(flesh * hb["lowerChest"], 1),
            "limb_damage_0m": round(flesh * hb["upperArm"], 1),
            "falloff_segments": format_falloff(segs),
            "range_step1_m": r1,
            "range_step2_m": r2 if r2 < 500 else None,
            "decay_step1": d1,
            "decay_step2": d2,
            "min_far_decay": d_min,
            "panel_range_stat": base_attr_range,
            "panel_recoil_stat": base_attr_recoil,
            "panel_hipfire_stat": base_attr_hip,
            "panel_handling_stat": base_attr_handling,
            "panel_stability_stat": base_attr_stability,
            "mag_capacity": lib_w.get("capacity"),
            "reload_s": lib_w.get("reload"),
            "empty_reload_s": lib_w.get("emptyReload"),
            "ads_ms": lib_w.get("ads"),
            "sprint_to_fire_ms": lib_w.get("sprintToFire"),
            "ammo_lv3_name": ammo_lv3["name"] if ammo_lv3 else "",
            "ammo_lv3_price": p_lv3,
            "ammo_lv4_name": ammo_lv4["name"] if ammo_lv4 else "",
            "ammo_lv4_price": p_lv4,
            "ammo_lv5_name": ammo_lv5["name"] if ammo_lv5 else "",
            "ammo_lv5_price": p_lv5,
            "ammo_rip_name": ammo_rip["name"] if ammo_rip else "",
            "ammo_rip_price": p_rip,
            "burn_cost_per_sec_lv4": round(p_lv4 * rof / 60.0) if p_lv4 else None,
            "burn_cost_per_sec_lv5": round(p_lv5 * rof / 60.0) if p_lv5 else None,
            "mag30_cost_lv4": p_lv4 * 30 if p_lv4 else None,
            "mag30_cost_lv5": p_lv5 * 30 if p_lv5 else None,
        }
        base_sol_rows.append(base_sol_row)

        mp_hb = mp["hitboxMultipliers"]
        mp_segs = mp["damageFalloffSegments"]
        base_mp_rows.append({
            "weapon_id": wid,
            "name": wname,
            "category_cn": cat_cn,
            "caliber": caliber,
            "fire_mode": mp["selectedFireMode"],
            "rof_rpm": round(mp["fireRateRpm"], 1),
            "trigger_delay_ms": mp["triggerDelayMs"],
            "muzzle_velocity_mps": mp["muzzleVelocityMps"],
            "base_flesh_damage": mp["baseFleshDamage"],
            "flesh_dps": round(mp["baseFleshDamage"] * mp["fireRateRpm"] / 60.0, 1),
            "head_mult": mp_hb["head"],
            "chest_mult": mp_hb["upperChest"],
            "abdomen_mult": mp_hb["lowerChest"],
            "limb_mult": mp_hb["upperArm"],
            "falloff_segments": format_falloff(mp_segs),
        })

        combat = pack.get("combat", {})
        dmg_profiles = combat.get("damageProfiles", {})
        bul_profiles = combat.get("bulletProfiles", {})

        def apply_parts_to_weapon(part_id_list):
            v_rof = rof
            v_fmode = fmode
            v_delay = delay
            v_flesh = flesh
            v_armor = armor
            v_hb = dict(hb)
            v_vel = vel
            v_segs = [dict(s) for s in segs]
            v_b_count = base_burst_count
            v_b_irof = base_burst_irof
            v_b_int = base_burst_int
            v_stages = None

            range_mult_add = 0.0
            rof_interval_mult_a = 0.0
            rof_interval_mult_c = 1.0
            rof_interval_add = 0.0
            notes = []

            for pid in part_id_list:
                sol_effs = pack.get("effectsByItemId", {}).get(pid, {}).get("sol") or []
                for e in sol_effs:
                    tgt = e.get("target")
                    mod = e.get("modifier")
                    val = e.get("value")
                    if tgt == "WeaponMainAttribute.MainAttrValues.2" and mod == "Mult_A" and val != 0:
                        range_mult_add += val
                        notes.append(f"射程/初速{val*100:+.0f}%")
                    elif tgt == "AttackerValueId.DefaultDamageId" and mod == "Initial":
                        dp = dmg_profiles.get(val)
                        if dp:
                            v_flesh = dp.get("baseDamage", v_flesh)
                            v_armor = dp.get("baseArmorDamage", v_armor)
                            if "hitboxMultipliers" in dp:
                                v_hb = dict(dp["hitboxMultipliers"])
                            notes.append(f"伤害模型变更({v_flesh}肉/{v_armor}甲)")
                    elif tgt == "BulletFlyingId" and mod == "Initial":
                        bp = bul_profiles.get(val)
                        if bp:
                            if bp.get("initialSpeedCmPerSecond"):
                                v_vel = bp["initialSpeedCmPerSecond"] / 100.0
                            valid_m = bp.get("validDistanceCm", 4000) / 100.0
                            att_dists = [d / 100.0 for d in bp.get("attenuationDistancesCm", [])]
                            att_rates = bp.get("attenuationRates", [])
                            new_segs = [{"fromM": 0.0, "toM": valid_m, "rate": 1.0}]
                            prev_m = valid_m
                            for idx_a, r_a in enumerate(att_rates):
                                to_m = att_dists[idx_a] if idx_a < len(att_dists) else 1000.0
                                new_segs.append({"fromM": prev_m, "toM": to_m, "rate": r_a})
                                prev_m = to_m
                            v_segs = new_segs
                            notes.append(f"弹道模型变更(初速{v_vel:g}m/s)")
                    elif tgt == "DamagePointId.HeadDamageRate" and mod == "Initial":
                        v_hb["head"] = val
                        notes.append(f"爆头倍率->{val}x")
                    elif tgt == "GRateOfFire" and mod == "Mult_A" and val != 0:
                        rof_interval_mult_a += val
                        notes.append(f"射击间隔{val*100:+.1f}%")
                    elif tgt in ("FireInterval", "FireCD") and mod == "Mult_A" and val != 0:
                        if tgt == "FireInterval":
                            rof_interval_mult_a += val
                    elif tgt in ("FireInterval", "FireCD") and mod == "Mult_C" and val != 0:
                        if tgt == "FireInterval":
                            rof_interval_mult_c *= val
                    elif tgt in ("FireInterval", "FireCD") and mod == "Addend" and val != 0:
                        if tgt == "FireInterval":
                            rof_interval_add += val
                    elif tgt == "FireDelayTime" and mod == "Initial":
                        v_delay = int(val * 1000)
                        notes.append(f"扳机延迟->{v_delay}ms")
                    elif tgt == "FireRateMode" and mod == "Initial":
                        if val == 0:
                            v_fmode = "Auto"
                            v_b_count = None
                            v_b_irof = None
                            v_b_int = None
                            notes.append("解锁全自动模式")
                        elif val == 1:
                            v_fmode = "Burst/Semi"
                            notes.append("切换半自动/点射模式")

            if "13020000561" in part_id_list:
                v_rof = 679.9
                v_fmode = "Burst"
                v_b_count = 4
                v_b_irof = 845
                v_b_int = 0.14
            elif "13020000564" in part_id_list:
                v_rof = 872.1
                v_fmode = "Auto"
            elif "13050000427" in part_id_list:
                v_rof = 671.7
                v_fmode = "Auto"
            else:
                base_int_s = 60.0 / rof
                new_int_s = (base_int_s + rof_interval_add) * (1.0 + rof_interval_mult_a) * rof_interval_mult_c
                if new_int_s > 0:
                    v_rof = 60.0 / new_int_s

            if range_mult_add != 0.0:
                scale = 1.0 + range_mult_add
                v_vel = v_vel * scale
                scaled_segs = []
                for s in v_segs:
                    scaled_segs.append({
                        "fromM": round(s["fromM"] * scale, 2) if s["fromM"] < 500 else s["fromM"],
                        "toM": round(s["toM"] * scale, 2) if s["toM"] < 500 else round(s["toM"] * scale, 2),
                        "rate": s["rate"],
                    })
                v_segs = scaled_segs

            pnames = [items_loc.get(p, lib_parts.get(p, {}).get("name", p)) for p in part_id_list]
            return (
                v_rof,
                v_fmode,
                v_delay,
                v_flesh,
                v_armor,
                v_hb,
                v_vel,
                v_segs,
                v_b_count,
                v_b_irof,
                v_b_int,
                v_stages,
                pnames,
                "；".join(notes),
            )

        per_gun_rows = []
        for pid in sorted(compat_pids, key=lambda x: (lib_parts[x].get("category", ""), -(part_row_by_id[x]["market_price"] or 0))):
            pr_master = part_row_by_id[pid]
            res_single = apply_parts_to_weapon([pid])
            v_segs_single = res_single[7]
            if pr_master["only_range_pct"] != 0:
                sc = 1.0 + pr_master["only_range_pct"] / 100.0
                v_segs_single = [
                    {
                        "fromM": round(s["fromM"] * sc, 2) if s["fromM"] < 500 else s["fromM"],
                        "toM": round(s["toM"] * sc, 2) if s["toM"] < 500 else round(s["toM"] * sc, 2),
                        "rate": s["rate"],
                    }
                    for s in v_segs_single
                ]

            rel_row = {
                "weapon_id": wid,
                "weapon_name": wname,
                "weapon_category": cat_cn,
                "caliber": caliber,
                "part_id": pid,
                "part_name": pr_master["name"],
                "part_category_cn": pr_master["category_cn"],
                "part_category_en": pr_master["category_en"],
                "rarity": pr_master["rarity"],
                "is_weapon_exclusive": pr_master["compatible_all_weapons_count"] == 1,
                "compatible_weapons_count": pr_master["compatible_all_weapons_count"],
                "part_market_price": pr_master["market_price"],
                "range_velocity_pct": pr_master["range_velocity_pct"],
                "only_range_pct": pr_master["only_range_pct"],
                "recoil_control": pr_master["recoil_control"],
                "hipfire_accuracy": pr_master["hipfire_accuracy"],
                "handling": pr_master["handling"],
                "stability": pr_master["stability"],
                "net_panel_points": pr_master["net_panel_points"],
                "rof_interval_pct": pr_master["rof_interval_pct"],
                "mag_capacity_set": pr_master["mag_capacity_set"],
                "reload_time_pct": pr_master["reload_time_pct"],
                "hidden_recoil_v_pct": pr_master["hidden_recoil_v_pct"],
                "hidden_recoil_h_pct": pr_master["hidden_recoil_h_pct"],
                "hidden_v_shake_mult": pr_master["hidden_v_shake_mult"],
                "hidden_h_shake_mult": pr_master["hidden_h_shake_mult"],
                "hidden_gunkick_rand_mult": pr_master["hidden_gunkick_rand_mult"],
                "hidden_gunkick_spring_mult": pr_master["hidden_gunkick_spring_mult"],
                "hidden_ads_time_pct": pr_master["hidden_ads_time_pct"],
                "hidden_ads_move_speed_add": pr_master["hidden_ads_move_speed_add"],
                "hidden_mechanics_summary": pr_master["hidden_mechanics_summary"],
                "is_combat_tunable": pr_master["is_combat_tunable"],
                "tune_details": pr_master["tune_details"],
                "resulting_fire_mode": res_single[1],
                "resulting_rof_rpm": round(res_single[0], 1),
                "resulting_trigger_delay_ms": res_single[2],
                "resulting_flesh_dmg": res_single[3],
                "resulting_armor_dmg": res_single[4],
                "resulting_head_mult": res_single[5]["head"],
                "resulting_chest_mult": res_single[5]["upperChest"],
                "resulting_abdomen_mult": res_single[5]["lowerChest"],
                "resulting_limb_mult": res_single[5]["upperArm"],
                "resulting_velocity_mps": round(res_single[6], 1),
                "resulting_falloff": format_falloff(v_segs_single),
                "combat_change_note": res_single[13],
            }
            per_gun_rows.append(rel_row)
            weapon_part_relation_rows.append(rel_row)

        safe_wname = wname.replace(" ", "_").replace("/", "_")
        if per_gun_rows:
            with write_open(PER_GUN_DIR / f"{wid}_{safe_wname}_parts.csv", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(per_gun_rows[0].keys()))
                writer.writeheader()
                writer.writerows(per_gun_rows)

        def make_variant_row(
            variant_name,
            variant_type,
            part_ids,
            part_names,
            v_rof,
            v_fmode,
            v_delay,
            v_flesh,
            v_armor,
            v_hb,
            v_vel,
            v_segs,
            burst_count=None,
            burst_internal_rof=None,
            burst_interval_s=None,
            rof_stages=None,
            note="",
        ):
            parts_price = 0
            for pid in part_ids:
                pp = econ_prices.get(pid)
                if pp is None and pid in econ_avail and econ_avail[pid].get("lastKnownPrice"):
                    pp = econ_avail[pid]["lastKnownPrice"]
                if pp is None:
                    pnm = items_loc.get(pid, "")
                    pp = orzice_by_name.get(pnm)
                if pp is not None:
                    parts_price += pp

            total_base_mod_price = (bare_price or 0) + parts_price if bare_price is not None else None

            def run_sim(ammo_row, arm_lv, arm_dur, dist):
                if not ammo_row:
                    return None, None
                pellets = sol.get("projectileCount", 1)
                return calc_chest_btk_ttk(
                    flesh_dmg=v_flesh * pellets,
                    armor_dmg=v_armor * pellets,
                    chest_mult=v_hb["upperChest"],
                    rof_rpm=v_rof,
                    trigger_delay_ms=v_delay,
                    velocity_mps=v_vel,
                    falloff_segments=v_segs,
                    distance_m=dist,
                    armor_durability=arm_dur,
                    ammo_flesh_mult=ammo_row["flesh_damage_mult"],
                    ammo_armor_mult=ammo_row["armor_damage_mult"],
                    pen_rate=ammo_row[f"pen_rate_lv{arm_lv}"],
                    armor_dur_rate=ammo_row[f"armor_dur_rate_lv{arm_lv}"],
                    fire_mode=v_fmode,
                    burst_count=burst_count,
                    burst_internal_rof=burst_internal_rof,
                    burst_interval_s=burst_interval_s,
                    rof_stages=rof_stages,
                )[:2]

            eff_lv4 = ammo_lv4 or ammo_lv3 or ammo_lv5
            eff_lv5 = ammo_lv5 or ammo_lv4 or ammo_lv3

            btk_4v4_0m, ttk_4v4_0m = run_sim(eff_lv4, 4, 110, 0)
            btk_4v4_25m, ttk_4v4_25m = run_sim(eff_lv4, 4, 110, 25)
            btk_4v4_45m, ttk_4v4_45m = run_sim(eff_lv4, 4, 110, 45)
            btk_4v4_70m, ttk_4v4_70m = run_sim(eff_lv4, 4, 110, 70)

            btk_5v5_0m, ttk_5v5_0m = run_sim(eff_lv5, 5, 125, 0)
            btk_5v5_25m, ttk_5v5_25m = run_sim(eff_lv5, 5, 125, 25)
            btk_5v5_45m, ttk_5v5_45m = run_sim(eff_lv5, 5, 125, 45)
            btk_5v5_70m, ttk_5v5_70m = run_sim(eff_lv5, 5, 125, 70)

            btk_4v5_0m, ttk_4v5_0m = run_sim(eff_lv4, 5, 125, 0)
            btk_5v6_0m, ttk_5v6_0m = run_sim(eff_lv5, 6, 150, 0)

            limb_ammo = ammo_rip or eff_lv4
            btk_limb_0m, ttk_limb_0m = (None, None)
            if limb_ammo:
                pellets = sol.get("projectileCount", 1)
                btk_limb_0m, ttk_limb_0m = calc_limb_btk_ttk(
                    flesh_dmg=v_flesh * pellets,
                    limb_mult=v_hb["upperArm"],
                    rof_rpm=v_rof,
                    trigger_delay_ms=v_delay,
                    velocity_mps=v_vel,
                    falloff_segments=v_segs,
                    distance_m=0,
                    ammo_flesh_mult=limb_ammo["flesh_damage_mult"],
                    fire_mode=v_fmode,
                    burst_count=burst_count,
                    burst_internal_rof=burst_internal_rof,
                    burst_interval_s=burst_interval_s,
                )

            p4 = eff_lv4["market_price"] if eff_lv4 else None
            p5 = eff_lv5["market_price"] if eff_lv5 else None

            vr1 = v_segs[0]["toM"] if len(v_segs) >= 1 else 1000
            vr2 = v_segs[1]["toM"] if len(v_segs) >= 2 else 1000
            vd1 = v_segs[1]["rate"] if len(v_segs) >= 2 else 1.0
            vd2 = v_segs[2]["rate"] if len(v_segs) >= 3 else vd1
            vd_min = v_segs[-1]["rate"] if v_segs else 1.0

            return {
                "weapon_id": wid,
                "weapon_name": wname,
                "variant_name": variant_name,
                "variant_type": variant_type,
                "category_cn": cat_cn,
                "caliber": caliber,
                "mod_parts": " + ".join(part_names) if part_names else "原厂裸枪",
                "bare_gun_price": bare_price,
                "mod_parts_price": parts_price if part_ids else 0,
                "base_plus_mod_price": total_base_mod_price,
                "fire_mode": v_fmode,
                "rof_rpm": round(v_rof, 1),
                "shot_interval_ms": round(60000.0 / v_rof, 2) if v_rof > 0 else None,
                "trigger_delay_ms": v_delay,
                "muzzle_velocity_mps": round(v_vel, 1),
                "flesh_damage": v_flesh,
                "armor_damage": v_armor,
                "flesh_dps": round(v_flesh * sol.get("projectileCount", 1) * v_rof / 60.0, 1),
                "armor_dps": round(v_armor * sol.get("projectileCount", 1) * v_rof / 60.0, 1),
                "head_mult": v_hb["head"],
                "chest_mult": v_hb["upperChest"],
                "abdomen_mult": v_hb["lowerChest"],
                "upper_arm_mult": v_hb["upperArm"],
                "lower_arm_mult": v_hb["lowerArm"],
                "thigh_mult": v_hb["thigh"],
                "calf_mult": v_hb["lowerLeg"],
                "headshot_damage_0m": round(v_flesh * v_hb["head"], 1),
                "chest_damage_0m": round(v_flesh * v_hb["upperChest"], 1),
                "abdomen_damage_0m": round(v_flesh * v_hb["lowerChest"], 1),
                "limb_damage_0m": round(v_flesh * v_hb["upperArm"], 1),
                "falloff_segments": format_falloff(v_segs),
                "range_step1_m": round(vr1, 1),
                "range_step2_m": round(vr2, 1) if vr2 < 500 else None,
                "decay_step1": vd1,
                "decay_step2": vd2,
                "min_far_decay": vd_min,
                "eval_ammo_lv4": f"{eff_lv4['name']}(Lv{eff_lv4['penetration_level']})" if eff_lv4 else "",
                "eval_ammo_lv4_price": p4,
                "eval_ammo_lv5": f"{eff_lv5['name']}(Lv{eff_lv5['penetration_level']})" if eff_lv5 else "",
                "eval_ammo_lv5_price": p5,
                "eval_ammo_limb": f"{limb_ammo['name']}(Lv{limb_ammo['penetration_level']}, {limb_ammo['flesh_damage_mult']}x肉伤)" if limb_ammo else "",
                "eval_ammo_limb_price": limb_ammo["market_price"] if limb_ammo else None,
                "burn_cost_per_sec_lv4": round(p4 * v_rof / 60.0) if p4 else None,
                "burn_cost_per_sec_lv5": round(p5 * v_rof / 60.0) if p5 else None,
                "btk_4v4_0m": btk_4v4_0m,
                "ttk_4v4_0m_ms": ttk_4v4_0m,
                "btk_4v4_25m": btk_4v4_25m,
                "ttk_4v4_25m_ms": ttk_4v4_25m,
                "btk_4v4_45m": btk_4v4_45m,
                "ttk_4v4_45m_ms": ttk_4v4_45m,
                "btk_4v4_70m": btk_4v4_70m,
                "ttk_4v4_70m_ms": ttk_4v4_70m,
                "btk_5v5_0m": btk_5v5_0m,
                "ttk_5v5_0m_ms": ttk_5v5_0m,
                "btk_5v5_25m": btk_5v5_25m,
                "ttk_5v5_25m_ms": ttk_5v5_25m,
                "btk_5v5_45m": btk_5v5_45m,
                "ttk_5v5_45m_ms": ttk_5v5_45m,
                "btk_5v5_70m": btk_5v5_70m,
                "ttk_5v5_70m_ms": ttk_5v5_70m,
                "btk_4v5_0m": btk_4v5_0m,
                "ttk_4v5_0m_ms": ttk_4v5_0m,
                "btk_5v6_0m": btk_5v6_0m,
                "ttk_5v6_0m_ms": ttk_5v6_0m,
                "btk_limb_0m": btk_limb_0m,
                "ttk_limb_0m_ms": ttk_limb_0m,
                "kill_ammo_cost_4v4_0m": (btk_4v4_0m * 2 * p4) if (btk_4v4_0m and p4) else None,
                "kill_ammo_cost_5v5_0m": (btk_5v5_0m * 2 * p5) if (btk_5v5_0m and p5) else None,
                "note": note,
            }

        mod_variant_rows.append(
            make_variant_row(
                variant_name=f"{wname} (原厂裸枪)",
                variant_type="原厂基础",
                part_ids=[],
                part_names=[],
                v_rof=rof,
                v_fmode=fmode,
                v_delay=delay,
                v_flesh=flesh,
                v_armor=armor,
                v_hb=dict(hb),
                v_vel=vel,
                v_segs=[dict(s) for s in segs],
                burst_count=base_burst_count,
                burst_internal_rof=base_burst_irof,
                burst_interval_s=base_burst_int,
                note="原厂无改装基础形态",
            )
        )

        barrels = []
        special_parts = []
        for pid, eff_by_mode in pack.get("effectsByItemId", {}).items():
            sol_effs = eff_by_mode.get("sol") or []
            non_zero = [
                e for e in sol_effs
                if e.get("target") not in ("GMagCapacity", "ChangeClipTime", "ChangeClipTimewhenEmpty", "GReload_Time", "DisplayAttrValues.2")
                and (e.get("value") != 0 or e.get("modifier") == "Initial")
            ]
            if not non_zero or pid == wid:
                continue
            pcat = lib_parts.get(pid, {}).get("category", "unknown")
            pname = items_loc.get(pid, lib_parts.get(pid, {}).get("name", pid))
            if pcat == "muzzle":
                continue
            elif pcat == "barrel" or "枪管" in pname or ("套件" in pname and pcat != "handguard"):
                barrels.append((pid, pname))
            else:
                special_parts.append((pid, pname, pcat))

        for b_id, b_name in barrels:
            res = apply_parts_to_weapon([b_id])
            mod_variant_rows.append(
                make_variant_row(
                    variant_name=f"{wname} ({b_name})",
                    variant_type="枪管零件改装",
                    part_ids=[b_id],
                    part_names=res[12],
                    v_rof=res[0],
                    v_fmode=res[1],
                    v_delay=res[2],
                    v_flesh=res[3],
                    v_armor=res[4],
                    v_hb=res[5],
                    v_vel=res[6],
                    v_segs=res[7],
                    burst_count=res[8],
                    burst_internal_rof=res[9],
                    burst_interval_s=res[10],
                    rof_stages=res[11],
                    note=res[13] or "枪管零件改装形态",
                )
            )

        for sp_id, sp_name, sp_cat in special_parts:
            if "内部配件" in sp_name or sp_id == "13120000380":
                continue
            res = apply_parts_to_weapon([sp_id])
            mod_variant_rows.append(
                make_variant_row(
                    variant_name=f"{wname} ({sp_name})",
                    variant_type="核心机件改装",
                    part_ids=[sp_id],
                    part_names=res[12],
                    v_rof=res[0],
                    v_fmode=res[1],
                    v_delay=res[2],
                    v_flesh=res[3],
                    v_armor=res[4],
                    v_hb=res[5],
                    v_vel=res[6],
                    v_segs=res[7],
                    burst_count=res[8],
                    burst_internal_rof=res[9],
                    burst_interval_s=res[10],
                    rof_stages=res[11],
                    note=res[13] or "机件零件改装形态",
                )
            )
            if sp_id == "13050000427":
                continue
            for b_id, b_name in barrels:
                if wid == "18010000044" and "猎手" in b_name:
                    continue
                res_combo = apply_parts_to_weapon([b_id, sp_id])
                mod_variant_rows.append(
                    make_variant_row(
                        variant_name=f"{wname} ({b_name} + {sp_name})",
                        variant_type="枪管+机件组合",
                        part_ids=[b_id, sp_id],
                        part_names=res_combo[12],
                        v_rof=res_combo[0],
                        v_fmode=res_combo[1],
                        v_delay=res_combo[2],
                        v_flesh=res_combo[3],
                        v_armor=res_combo[4],
                        v_hb=res_combo[5],
                        v_vel=res_combo[6],
                        v_segs=res_combo[7],
                        burst_count=res_combo[8],
                        burst_internal_rof=res_combo[9],
                        burst_interval_s=res_combo[10],
                        rof_stages=res_combo[11],
                        note=res_combo[13],
                    )
                )

        if wid == "18070000033":
            res_m1911 = apply_parts_to_weapon(["13020000519", "13250000006", "13380000002"])
            mod_variant_rows.append(
                make_variant_row(
                    variant_name="M1911 (夜鹰战术枪管 + 夜鹰战术扳机 + 夜鹰战术击锤)",
                    variant_type="枪管+机件组合",
                    part_ids=["13020000519", "13250000006", "13380000002"],
                    part_names=res_m1911[12],
                    v_rof=res_m1911[0],
                    v_fmode=res_m1911[1],
                    v_delay=res_m1911[2],
                    v_flesh=res_m1911[3],
                    v_armor=res_m1911[4],
                    v_hb=res_m1911[5],
                    v_vel=res_m1911[6],
                    v_segs=res_m1911[7],
                    note=res_m1911[13],
                )
            )

        if wid == "18050000033":
            res_svch = apply_parts_to_weapon(["13020000599"])
            mod_variant_rows.append(
                make_variant_row(
                    variant_name="SVCH (SVCH长枪管 + SVCH爆发枪机)",
                    variant_type="枪管+机件组合",
                    part_ids=["13020000599", "13420000005"],
                    part_names=["SVCH长枪管", "SVCH爆发枪机"],
                    v_rof=600.0,
                    v_fmode="Auto",
                    v_delay=0,
                    v_flesh=res_svch[3],
                    v_armor=res_svch[4],
                    v_hb=res_svch[5],
                    v_vel=res_svch[6],
                    v_segs=res_svch[7],
                    rof_stages=[{"untilShot": 3, "rofAdd": 100}, {"rofAdd": 0}],
                    note="解锁全自动；射程/初速+30%；前3发爆发射速700RPM，后续600RPM",
                )
            )

    with write_open(DATA_DIR / "weapons_base_sol.json", encoding="utf-8") as f:
        json.dump(base_sol_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "weapons_base_sol.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(base_sol_rows[0].keys()))
        writer.writeheader()
        writer.writerows(base_sol_rows)

    with write_open(DATA_DIR / "weapons_base_mp.json", encoding="utf-8") as f:
        json.dump(base_mp_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "weapons_base_mp.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(base_mp_rows[0].keys()))
        writer.writeheader()
        writer.writerows(base_mp_rows)

    with write_open(DATA_DIR / "weapon_mod_variants_sol.json", encoding="utf-8") as f:
        json.dump(mod_variant_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "weapon_mod_variants_sol.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(mod_variant_rows[0].keys()))
        writer.writeheader()
        writer.writerows(mod_variant_rows)

    with write_open(DATA_DIR / "weapon_part_relations_sol.json", encoding="utf-8") as f:
        json.dump(weapon_part_relation_rows, f, ensure_ascii=False, indent=2)
    with write_open(DATA_DIR / "weapon_part_relations_sol.csv", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(weapon_part_relation_rows[0].keys()))
        writer.writeheader()
        writer.writerows(weapon_part_relation_rows)

    print(
        f"Successfully built:\n"
        f"  - {len(base_sol_rows)} non-sniper base weapons (SOL & MP)\n"
        f"  - {len(all_parts_rows)} individual weapon parts (all_parts_catalog_sol)\n"
        f"  - {len(weapon_part_relation_rows)} (weapon, part) compatibility & stat rows across 62 per-weapon CSVs\n"
        f"  - {len(mod_variant_rows)} combat-stat-changing weapon+part variants\n"
        f"  - {len(ammo_rows)} ammo entries & {len(defense_rows)} armor/helmet entries."
    )


if __name__ == "__main__":
    main()
