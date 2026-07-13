from .matcher import infer_side, name_tokens, score_name_for_role


MAX_NECK_COUNT = 3
MAX_SPINE_COUNT = 6


def _vec3(vector):
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def _distance(a, b):
    return sum((a[index] - b[index]) ** 2 for index in range(3)) ** 0.5


def _descendant_count(row, rows):
    count = 0
    stack = list(row["children"])
    while stack:
        name = stack.pop()
        child = rows.get(name)
        if not child:
            continue
        count += 1
        stack.extend(child["children"])
    return count


def _ancestor_names(row, rows):
    names = []
    parent = row["parent"]
    while parent:
        names.append(parent)
        parent = rows[parent]["parent"] if parent in rows else None
    return names


def _build_rows(armature):
    rows = {}
    matrix = armature.matrix_world
    for bone in armature.data.bones:
        head = _vec3(matrix @ bone.head_local)
        tail = _vec3(matrix @ bone.tail_local)
        rows[bone.name] = {
            "name": bone.name,
            "bone": bone,
            "parent": bone.parent.name if bone.parent else None,
            "children": [child.name for child in bone.children],
            "head": head,
            "tail": tail,
            "mid": _mid(head, tail),
            "length": _distance(head, tail),
        }
    for row in rows.values():
        row["descendants"] = _descendant_count(row, rows)
        row["ancestors"] = _ancestor_names(row, rows)
    return rows


def _axis_model(rows):
    points = []
    for row in rows.values():
        points.append(row["head"])
        points.append(row["tail"])
    mins = [min(point[index] for point in points) for index in range(3)]
    maxs = [max(point[index] for point in points) for index in range(3)]
    spans = [maxs[index] - mins[index] for index in range(3)]
    yz_vertical = 1 if spans[1] >= spans[2] else 2
    vertical = 0 if spans[0] > spans[yz_vertical] * 1.65 else yz_vertical
    remaining = [index for index in range(3) if index != vertical]
    lateral = max(remaining, key=lambda index: spans[index])
    depth = next(index for index in range(3) if index not in {vertical, lateral})
    return {
        "mins": mins,
        "maxs": maxs,
        "spans": [span if span > 1e-6 else 1.0 for span in spans],
        "vertical": vertical,
        "lateral": lateral,
        "depth": depth,
        "lateral_center": (mins[lateral] + maxs[lateral]) * 0.5,
    }


def _norm(row, axes, axis_name):
    axis = axes[axis_name]
    return (row["mid"][axis] - axes["mins"][axis]) / axes["spans"][axis]


def _axis_delta(row, axes, axis_name):
    axis = axes[axis_name]
    return row["mid"][axis] - axes[f"{axis_name}_center"] if f"{axis_name}_center" in axes else row["mid"][axis]


def _infer_left_sign(rows, axes):
    lateral = axes["lateral"]
    center = axes["lateral_center"]
    observed = []
    for row in rows.values():
        side = infer_side(name_tokens(row["name"]))
        if side in {"left", "right"}:
            observed.append((side, row["mid"][lateral] - center))
    left_values = [value for side, value in observed if side == "left"]
    right_values = [value for side, value in observed if side == "right"]
    if left_values and right_values:
        return 1 if sum(left_values) / len(left_values) > sum(right_values) / len(right_values) else -1
    if left_values:
        return 1 if sum(left_values) / len(left_values) > 0 else -1
    if right_values:
        return -1 if sum(right_values) / len(right_values) > 0 else 1
    # Blender, Mixamo, and the current Auto-Rig Pro target use positive lateral
    # coordinates for the character's left side. With fully anonymized bone
    # names this convention is the least surprising default.
    return 1


def _side(row, axes, left_sign):
    lateral = row["mid"][axes["lateral"]] - axes["lateral_center"]
    if abs(lateral) < axes["spans"][axes["lateral"]] * 0.04:
        return None
    return "left" if lateral * left_sign > 0 else "right"


def _add(result, role_id, row, score, reasons):
    if not row:
        return
    name_score, name_reasons = score_name_for_role(row["name"], role_id)
    final_score = max(score, score * 0.82 + name_score * 0.18)
    final_reasons = list(reasons)
    if name_reasons:
        final_reasons.append("name:" + "+".join(name_reasons))
    old = result.get(role_id)
    if old and old["score"] >= final_score:
        return
    result[role_id] = {
        "role_id": role_id,
        "bone_name": row["name"],
        "score": round(min(1.0, final_score), 4),
        "reasons": final_reasons,
    }


def _choose_hips(rows, axes):
    best = None
    best_score = -1.0
    max_desc = max((row["descendants"] for row in rows.values()), default=1) or 1
    for row in rows.values():
        vertical = _norm(row, axes, "vertical")
        lateral_center = 1.0 - min(1.0, abs(row["mid"][axes["lateral"]] - axes["lateral_center"]) / (axes["spans"][axes["lateral"]] * 0.5))
        branch = min(1.0, len(row["children"]) / 3.0)
        desc = row["descendants"] / max_desc
        lower_mid = 1.0 - min(1.0, abs(vertical - 0.38) / 0.38)
        score = lateral_center * 0.34 + branch * 0.24 + desc * 0.24 + lower_mid * 0.18
        if row["parent"] is None and row["descendants"] > 5:
            score += 0.05
        name_score, _ = score_name_for_role(row["name"], "hips")
        score += name_score * 0.12
        if score > best_score:
            best = row
            best_score = score
    return best, min(0.9, max(0.42, best_score))


def _next_by_score(rows, current, used, score_fn, min_score=0.0):
    best = None
    best_score = min_score
    for child_name in current["children"]:
        if child_name in used or child_name not in rows:
            continue
        child = rows[child_name]
        score = score_fn(child, current)
        if score > best_score:
            best = child
            best_score = score
    return best, best_score


def _follow_chain(rows, start, used, score_fn, max_len, min_score=0.05):
    chain = []
    current = start
    local_used = set(used)
    while current and len(chain) < max_len:
        chain.append(current)
        local_used.add(current["name"])
        current, score = _next_by_score(rows, current, local_used, score_fn, min_score=min_score)
        if not current:
            break
    return chain


def _trunk_chain(rows, hips, axes):
    def score_fn(child, parent):
        up = _norm(child, axes, "vertical") - _norm(parent, axes, "vertical")
        center_offset = abs(child["mid"][axes["lateral"]] - axes["lateral_center"]) / axes["spans"][axes["lateral"]]
        if center_offset > 0.14:
            return -1.0
        center = 1.0 - min(1.0, center_offset / 0.14)
        return up * 0.82 + center * 0.18

    max_len = MAX_SPINE_COUNT + MAX_NECK_COUNT + 2
    return _follow_chain(rows, hips, {hips["name"]}, score_fn, max_len=max_len, min_score=0.08)[1:]


def _candidate_branch_roots(rows, axes, side, left_sign, trunk_names, hips):
    roots = []
    hips_v = _norm(hips, axes, "vertical")
    for row in rows.values():
        if row["name"] in trunk_names:
            continue
        row_side = _side(row, axes, left_sign)
        if row_side != side:
            continue
        parent = row["parent"]
        ancestors = set(row["ancestors"])
        from_trunk = parent in trunk_names or bool(ancestors & trunk_names)
        if not from_trunk:
            continue
        if parent in trunk_names:
            trunk_distance = 0
        else:
            trunk_distance = next(
                (index + 1 for index, name in enumerate(row["ancestors"]) if name in trunk_names),
                99,
            )
        vertical = _norm(row, axes, "vertical")
        lateral_abs = abs(row["mid"][axes["lateral"]] - axes["lateral_center"]) / axes["spans"][axes["lateral"]]
        roots.append((row, vertical, lateral_abs, vertical - hips_v, trunk_distance))
    return roots


def _leg_chain(rows, axes, side, left_sign, trunk_names, hips):
    candidates = []
    for row, vertical, lateral_abs, above_hips, trunk_distance in _candidate_branch_roots(rows, axes, side, left_sign, trunk_names, hips):
        if above_hips > 0.16 or above_hips < -0.18:
            continue
        start_height = 1.0 - min(1.0, abs(above_hips + 0.06) / 0.22)
        candidates.append((
            -trunk_distance * 0.75 + start_height * 0.45 + lateral_abs * 0.22 + row["descendants"] * 0.015,
            row,
        ))
    if not candidates:
        return []
    candidates.sort(reverse=True, key=lambda item: item[0])
    start = candidates[0][1]

    def score_fn(child, parent):
        down = _norm(parent, axes, "vertical") - _norm(child, axes, "vertical")
        same_side = 1.0 if _side(child, axes, left_sign) == side else 0.2
        return down * 0.72 + same_side * 0.22 + child["length"] * 0.02

    return _follow_chain(rows, start, trunk_names, score_fn, max_len=4, min_score=0.02)


def _arm_chain(rows, axes, side, left_sign, trunk_names, hips):
    candidates = []
    for row, vertical, lateral_abs, above_hips, trunk_distance in _candidate_branch_roots(rows, axes, side, left_sign, trunk_names, hips):
        if above_hips < 0.12:
            continue
        parent_bonus = 0.25 if row["parent"] in trunk_names else 0.0
        near_trunk = 1.0 - min(1.0, lateral_abs / 0.5)
        score = -trunk_distance * 0.72 + parent_bonus + near_trunk * 0.35 + vertical * 0.18 + row["descendants"] * 0.02
        candidates.append((score, row))
    if not candidates:
        return []
    candidates.sort(reverse=True, key=lambda item: item[0])
    start = candidates[0][1]

    def score_child(child, parent, chain_len):
        parent_abs = abs(parent["mid"][axes["lateral"]] - axes["lateral_center"])
        child_abs = abs(child["mid"][axes["lateral"]] - axes["lateral_center"])
        outward = (child_abs - parent_abs) / axes["spans"][axes["lateral"]]
        child_side = _side(child, axes, left_sign)
        same_side = 1.0 if child_side == side else 0.45 if child_side is None else -0.25
        if chain_len <= 1:
            expected = f"{side}_upper_arm"
        elif chain_len == 2:
            expected = f"{side}_lower_arm"
        else:
            expected = f"{side}_hand"
        name_score, _ = score_name_for_role(child["name"], expected)
        return outward * 0.42 + same_side * 0.34 + name_score * 0.22 + child["length"] * 0.02

    chain = [start]
    used = set(trunk_names)
    used.add(start["name"])
    current = start
    while len(chain) < 5:
        if len(chain) >= 4:
            break
        if len(chain) >= 3 and len(current["children"]) >= 3:
            break
        choices = []
        for child_name in current["children"]:
            if child_name in used or child_name not in rows:
                continue
            child = rows[child_name]
            score = score_child(child, current, len(chain))
            choices.append((score, child))
        if not choices:
            break
        choices.sort(reverse=True, key=lambda item: item[0])
        score, child = choices[0]
        if score < -0.16:
            break
        chain.append(child)
        used.add(child["name"])
        current = child
    return chain


def _finger_roots(rows, hand, arm_names):
    roots = [rows[name] for name in hand["children"] if name in rows and name not in arm_names]
    if len(roots) >= 3:
        return roots
    grandchildren = []
    for child in roots:
        grandchildren.extend(rows[name] for name in child["children"] if name in rows and name not in arm_names)
    return roots + grandchildren


def _sample_chain(chain, limit):
    if len(chain) <= limit:
        return list(chain)
    if limit <= 1:
        return [chain[-1]]
    last = len(chain) - 1
    indexes = [round(index * last / (limit - 1)) for index in range(limit)]
    return [chain[index] for index in indexes]


def _has_lateral_child(row, rows, axes, left_sign, chain_names):
    for child_name in row["children"]:
        if child_name in chain_names or child_name not in rows:
            continue
        if _side(rows[child_name], axes, left_sign) in {"left", "right"}:
            return True
    return False


def _split_trunk_chain(trunk, rows, axes, left_sign):
    if len(trunk) < 3:
        return [], [], trunk[-1] if trunk else None

    head = trunk[-1]
    body_chain = list(trunk[:-1])
    chain_names = {row["name"] for row in trunk}

    neck_chain = [body_chain.pop()]
    while body_chain and len(neck_chain) < MAX_NECK_COUNT:
        row = body_chain[-1]
        neck_name_score, _ = score_name_for_role(row["name"], f"neck_{len(neck_chain) + 1:02d}")
        lower_lengths = [item["length"] for item in body_chain[:-1]]
        average_lower = sum(lower_lengths) / len(lower_lengths) if lower_lengths else row["length"]
        looks_like_extra_neck = (
            neck_name_score >= 0.35
            or (row["length"] <= average_lower * 0.72 and not _has_lateral_child(row, rows, axes, left_sign, chain_names))
        )
        if not looks_like_extra_neck:
            break
        neck_chain.append(body_chain.pop())

    return body_chain, list(reversed(neck_chain)), head


def analyze_humanoid_roles(armature):
    """Return role candidates using topology first, names only as supporting evidence."""
    if armature is None or getattr(armature, "type", None) != "ARMATURE" or not armature.data.bones:
        return {}

    rows = _build_rows(armature)
    axes = _axis_model(rows)
    left_sign = _infer_left_sign(rows, axes)
    result = {}

    hips, hips_score = _choose_hips(rows, axes)
    if not hips:
        return result
    _add(result, "hips", hips, hips_score, ["topology:branch-root"])

    trunk = _trunk_chain(rows, hips, axes)
    trunk_names = {hips["name"], *(row["name"] for row in trunk)}
    if trunk:
        lower_trunk, upper_neck, head = _split_trunk_chain(trunk, rows, axes, left_sign)
        for index, row in enumerate(_sample_chain(lower_trunk, MAX_SPINE_COUNT), start=1):
            score = 0.74 if index == min(len(lower_trunk), MAX_SPINE_COUNT) else 0.72
            reason = "topology:upper-trunk" if index == min(len(lower_trunk), MAX_SPINE_COUNT) else "topology:trunk-chain"
            _add(result, f"spine_{index:02d}", row, score, [reason])
        for index, row in enumerate(upper_neck[:MAX_NECK_COUNT], start=1):
            _add(result, f"neck_{index:02d}", row, 0.68, ["topology:neck-chain"])
        if len(trunk) >= 3:
            if not any(role_id.startswith("spine_") for role_id in result):
                _add(result, "spine_01", trunk[-3], 0.74, ["topology:upper-trunk"])
            if "neck_01" not in result:
                _add(result, "neck_01", trunk[-2], 0.68, ["topology:upper-trunk"])
            _add(result, "head", head, 0.76, ["topology:top-trunk"])
        elif len(trunk) == 2:
            _add(result, "spine_01", trunk[0], 0.58, ["topology:short-trunk"])
            _add(result, "head", trunk[1], 0.62, ["topology:short-trunk"])
        elif len(trunk) == 1:
            _add(result, "head", trunk[0], 0.46, ["topology:minimal-trunk"])

    assigned_chain_names = set(trunk_names)
    for side in ("left", "right"):
        leg = _leg_chain(rows, axes, side, left_sign, trunk_names, hips)
        side_prefix = f"{side}_"
        for role_base, row in zip(("upper_leg", "lower_leg", "foot", "toe"), leg):
            _add(result, side_prefix + role_base, row, 0.7 if role_base != "toe" else 0.55, ["topology:leg-chain"])
            assigned_chain_names.add(row["name"])

    for side in ("left", "right"):
        arm = _arm_chain(rows, axes, side, left_sign, trunk_names | assigned_chain_names, hips)
        side_prefix = f"{side}_"
        has_shoulder = False
        if len(arm) >= 4 and arm[0]["parent"] in trunk_names:
            lateral_offset = abs(arm[0]["mid"][axes["lateral"]] - axes["lateral_center"]) / axes["spans"][axes["lateral"]]
            is_short_stub = arm[0]["length"] <= arm[1]["length"] * 0.85
            shoulder_name_score, _ = score_name_for_role(arm[0]["name"], side_prefix + "shoulder")
            hand_has_finger_fan = len([name for name in arm[3]["children"] if name in rows]) >= 3
            has_shoulder = (
                shoulder_name_score >= 0.35
                or (lateral_offset < 0.22 and is_short_stub)
                or (hand_has_finger_fan and lateral_offset < 0.36)
            )
        if has_shoulder and len(arm) >= 4:
            roles = ("shoulder", "upper_arm", "lower_arm", "hand")
            hand = arm[3]
        elif len(arm) >= 3:
            roles = ("upper_arm", "lower_arm", "hand")
            hand = arm[2]
        elif len(arm) == 2:
            roles = ("upper_arm", "hand")
            hand = arm[1]
        elif len(arm) == 1:
            roles = ("hand",)
            hand = arm[0]
        else:
            roles = ()
            hand = None

        for role_base, row in zip(roles, arm):
            _add(result, side_prefix + role_base, row, 0.68 if role_base != "hand" else 0.62, ["topology:arm-chain"])
            assigned_chain_names.add(row["name"])

        if hand:
            finger_candidates = _finger_roots(rows, hand, {row["name"] for row in arm})
            finger_candidates.sort(key=lambda row: row["mid"][axes["depth"]])
            for role_base, row in zip(("thumb", "index", "middle", "ring", "pinky"), finger_candidates[:5]):
                _add(result, side_prefix + role_base, row, 0.48, ["topology:finger-fan"])

    return result
