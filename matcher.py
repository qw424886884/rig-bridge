import re

from .preset_catalog import aliases_for_role


SIDE_ALIASES = {
    "left": {"left", "l", "lf", "左"},
    "right": {"right", "r", "rt", "右"},
}


ROLE_ALIASES = {
    "head": {"head", "skull", "头"},
    "neck": {"neck", "颈"},
    "spine": {
        "spine",
        "torso",
        "body",
        "脊柱",
    },
    "chest": {"chest", "spine2", "spine_02", "spine3", "spine_03", "upperchest", "胸"},
    "hips": {"hips", "hip", "pelvis", "rootx", "root.x", "root", "髋", "骨盆"},
    "shoulder": {"shoulder", "clavicle", "collar", "肩"},
    "upper_arm": {"upperarm", "uparm", "armstretch", "arm_stretch", "大臂"},
    "lower_arm": {"lowerarm", "forearm", "elbow", "forearmstretch", "forearm_stretch", "小臂", "前臂"},
    "hand": {"hand", "wrist", "手", "手腕"},
    "thumb": {"thumb", "拇指"},
    "index": {"index", "forefinger", "pointer", "食指"},
    "middle": {"middle", "中指"},
    "ring": {"ring", "无名指"},
    "pinky": {"pinky", "little", "小指"},
    "upper_leg": {"upperleg", "upleg", "thigh", "thighstretch", "thigh_stretch", "大腿"},
    "lower_leg": {"lowerleg", "leg", "calf", "shin", "legstretch", "leg_stretch", "小腿"},
    "foot": {"foot", "ankle", "脚"},
    "toe": {"toe", "toes", "toebase", "脚趾"},
}

FINGER_BASES = ("thumb", "index", "middle", "ring", "pinky")


def normalize_name(name):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    text = text.lower()
    text = text.replace("mixamorig:", "")
    text = re.sub(r"[\s\-:]+", "_", text)
    text = text.replace(".", "_")
    text = re.sub(r"[^a-z0-9_\u3040-\u30ff\u4e00-\u9fff\uff10-\uff19]+", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def name_tokens(name):
    normalized = normalize_name(name)
    tokens = set(filter(None, normalized.split("_")))
    tokens.add(normalized)
    compact = normalized.replace("_", "")
    if compact:
        tokens.add(compact)
    return tokens


def infer_side(tokens):
    for side, aliases in SIDE_ALIASES.items():
        if tokens & aliases:
            return side
    for token in tokens:
        if token.endswith("l") or token.endswith("left"):
            return "left"
        if token.endswith("r") or token.endswith("right"):
            return "right"
    return None


def role_side(role_id):
    if role_id.startswith("left_"):
        return "left"
    if role_id.startswith("right_"):
        return "right"
    return None


def role_base(role_id):
    if role_id.startswith("left_"):
        return role_id[len("left_"):]
    if role_id.startswith("right_"):
        return role_id[len("right_"):]
    return role_id


def semantic_base(role_id):
    base = role_base(role_id)
    if re.match(r"neck_\d+$", base):
        return "neck"
    if re.match(r"spine_\d+$", base):
        return "spine"
    return base


def normalized_aliases_for_role(role_id):
    base = semantic_base(role_id)
    aliases = set(ROLE_ALIASES.get(base, {base}))
    aliases.update(aliases_for_role(role_id))
    if re.match(r"spine_\d+$", role_id) and int(role_id[-2:]) >= 3:
        aliases.update(ROLE_ALIASES["chest"])
    return {normalize_name(alias) for alias in aliases if alias}


def score_name_for_role(bone_name, role_id):
    tokens = name_tokens(bone_name)
    base = semantic_base(role_id)
    side = role_side(role_id)
    detected_side = infer_side(tokens)

    aliases = normalized_aliases_for_role(role_id)
    alias_hit = bool(tokens & aliases)
    compact = normalize_name(bone_name).replace("_", "")
    if base == "hand" and any(finger_base in compact for finger_base in FINGER_BASES):
        return 0.0, ["finger-not-hand"]
    compact_hit = any(alias.replace("_", "") in compact for alias in aliases)
    normalized_role = normalize_name(role_id)
    exact_role_hit = normalized_role in tokens or normalized_role.replace("_", "") == compact

    score = 0.0
    reasons = []
    if alias_hit:
        score += 0.65
        reasons.append("alias")
    elif compact_hit:
        score += 0.45
        reasons.append("compact-alias")
    if exact_role_hit:
        score += 0.25
        reasons.append("exact-role")

    if side:
        if detected_side == side:
            score += 0.25
            reasons.append("side")
        elif detected_side and detected_side != side:
            score -= 0.35
            reasons.append("opposite-side")
    else:
        if detected_side:
            score -= 0.1
            reasons.append("unexpected-side")
        else:
            score += 0.1
            reasons.append("center")

    return max(0.0, min(1.0, score)), reasons


def best_role_for_bone(bone_name, role_ids):
    scored = []
    for role_id in role_ids:
        score, reasons = score_name_for_role(bone_name, role_id)
        if score > 0:
            scored.append((score, role_id, reasons))
    if not scored:
        return None
    scored.sort(reverse=True, key=lambda row: row[0])
    score, role_id, reasons = scored[0]
    return {"role_id": role_id, "score": score, "reasons": reasons}
