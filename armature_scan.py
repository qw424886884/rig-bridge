from .matcher import infer_side, name_tokens, score_name_for_role


MAX_NECK_COUNT = 3
MAX_SPINE_COUNT = 6


def _vec3(vector):
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def _distance(a, b):
    return sum((a[index] - b[index]) ** 2 for index in range(3)) ** 0.5


def _subtract(a, b):
    return tuple(a[index] - b[index] for index in range(3))


def _dot(a, b):
    return sum(a[index] * b[index] for index in range(3))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(vector):
    return sum(value * value for value in vector) ** 0.5


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


def _bilateral_axis_evidence(rows, mins, spans, vertical, lateral, depth):
    """Score an axis by symmetric sibling branches rooted near the body center."""
    center = (mins[lateral] + mins[lateral] + spans[lateral]) * 0.5
    evidence = []
    vertical_span = max(spans[vertical], 1.0e-6)
    lateral_span = max(spans[lateral], 1.0e-6)
    depth_span = max(spans[depth], 1.0e-6)
    for parent in rows.values():
        children = [rows[name] for name in parent["children"] if name in rows]
        if len(children) < 2:
            continue
        parent_offset = abs(parent["mid"][lateral] - center) / lateral_span
        if parent_offset > 0.22:
            continue
        best = None
        for index, first in enumerate(children[:-1]):
            for second in children[index + 1:]:
                if min(first["descendants"], second["descendants"]) < 2:
                    continue
                lateral_separation = abs(first["head"][lateral] - second["head"][lateral]) / lateral_span
                if lateral_separation < 0.035:
                    continue
                vertical_error = abs(first["head"][vertical] - second["head"][vertical]) / vertical_span
                depth_error = abs(first["head"][depth] - second["head"][depth]) / depth_span
                length_error = abs(first["length"] - second["length"]) / max(first["length"], second["length"], 1.0e-6)
                descendant_error = abs(first["descendants"] - second["descendants"]) / max(
                    first["descendants"], second["descendants"], 1
                )
                branch_scale = min(
                    1.0,
                    max(first["length"], second["length"]) / vertical_span * 8.0,
                )
                symmetry = 1.0 - min(
                    1.0,
                    vertical_error * 2.4
                    + depth_error * 1.7
                    + length_error * 0.42
                    + descendant_error * 0.34,
                )
                score = lateral_separation * 2.1 + symmetry * 0.72 + branch_scale * 0.28 - parent_offset * 0.35
                pair_center = (first["head"][lateral] + second["head"][lateral]) * 0.5
                candidate = (score, pair_center)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best:
            evidence.append(best)
    evidence.sort(reverse=True, key=lambda item: item[0])
    strongest = evidence[:4]
    if not strongest:
        return 0.0, center
    total_weight = sum(max(0.05, score) for score, _ in strongest)
    inferred_center = sum(max(0.05, score) * value for score, value in strongest) / total_weight
    return sum(score for score, _ in strongest), inferred_center


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
    axis_evidence = []
    for lateral_candidate in remaining:
        depth_candidate = next(index for index in remaining if index != lateral_candidate)
        score, center = _bilateral_axis_evidence(
            rows,
            mins,
            spans,
            vertical,
            lateral_candidate,
            depth_candidate,
        )
        axis_evidence.append((score, spans[lateral_candidate], lateral_candidate, depth_candidate, center))
    axis_evidence.sort(reverse=True)
    _, _, lateral, depth, lateral_center = axis_evidence[0]
    return {
        "mins": mins,
        "maxs": maxs,
        "spans": [span if span > 1e-6 else 1.0 for span in spans],
        "vertical": vertical,
        "lateral": lateral,
        "depth": depth,
        "lateral_center": lateral_center,
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


def _named_side_evidence_count(rows):
    sides = [infer_side(name_tokens(row["name"])) for row in rows.values()]
    return min(sides.count("left"), sides.count("right"))


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
    chain = [hips]
    used = {hips["name"]}
    current = hips
    while len(chain) < max_len:
        child_rows = [rows[name] for name in current["children"] if name in rows and name not in used]
        if len(chain) >= 3 and len(child_rows) >= 2 and all(child["descendants"] <= 1 for child in child_rows):
            break
        if len(chain) >= 3 and len(child_rows) >= 3:
            substantial_branches = [
                child
                for child in child_rows
                if child["descendants"] >= 2
                and child["length"] >= axes["spans"][axes["vertical"]] * 0.025
            ]
            # The chest owns two substantial arm branches plus the continuing
            # neck. A head may own many face sockets, hair, or a prop, but it
            # does not own another symmetric pair of long limb subtrees.
            if len(substantial_branches) < 2:
                break
        choices = []
        for child_name in current["children"]:
            if child_name in used or child_name not in rows:
                continue
            child = rows[child_name]
            score = score_fn(child, current)
            if score >= 0.08:
                choices.append((score, child))
        if not choices:
            break
        # A head often owns several leaf sockets or effect bones. Once the
        # central chain reaches that fan, the anatomical trunk ends at the
        # current bone rather than at whichever accessory reaches highest.
        if len(choices) >= 2 and all(child["descendants"] == 0 for _, child in choices):
            break
        choices.sort(reverse=True, key=lambda item: item[0])
        current = choices[0][1]
        chain.append(current)
        used.add(current["name"])
    return chain[1:]


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


def _joint_gap(parent, child, axes):
    body_span = axes["spans"][axes["vertical"]]
    return _distance(parent["tail"], child["head"]) / max(body_span, 1.0e-6)


def _descending_limb_chain(rows, axes, side, left_sign, start, max_len=4):
    chain = [start]
    used = {start["name"]}
    current = start
    while len(chain) < max_len:
        direct_children = [rows[name] for name in current["children"] if name in rows and name not in used]
        if len(chain) >= 3 and len(direct_children) == 1 and direct_children[0]["descendants"] == 0:
            chain.append(direct_children[0])
            break
        choices = []
        for child_name in current["children"]:
            if child_name in used or child_name not in rows:
                continue
            child = rows[child_name]
            child_side = _side(child, axes, left_sign)
            if child_side not in {side, None}:
                continue
            down = _norm(current, axes, "vertical") - _norm(child, axes, "vertical")
            same_side = 1.0 if child_side == side else 0.25
            continuity = 1.0 - min(1.0, _joint_gap(current, child, axes) / 0.08)
            length = child["length"] / axes["spans"][axes["vertical"]]
            score = down * 1.15 + same_side * 0.24 + continuity * 0.28 + min(0.2, length)
            choices.append((score, child))
        if not choices:
            break
        choices.sort(reverse=True, key=lambda item: item[0])
        score, child = choices[0]
        if score < 0.12:
            break
        chain.append(child)
        used.add(child["name"])
        current = child
    return chain


def _leg_chain_candidates(rows, axes, side, left_sign):
    candidates = []
    vertical_span = axes["spans"][axes["vertical"]]
    for row in rows.values():
        if _side(row, axes, left_sign) != side:
            continue
        chain = _descending_limb_chain(rows, axes, side, left_sign, row, max_len=4)
        if len(chain) < 3:
            continue
        verticals = [_norm(item, axes, "vertical") for item in chain]
        first_down = verticals[0] - verticals[1]
        second_down = verticals[1] - verticals[2]
        descent = verticals[0] - min(verticals)
        end_height = min(verticals)
        root_height = verticals[0]
        if first_down < 0.055 or second_down < 0.045:
            continue
        if descent < 0.20 or end_height > 0.42 or root_height < 0.28:
            continue
        lateral = abs(row["mid"][axes["lateral"]] - axes["lateral_center"]) / axes["spans"][axes["lateral"]]
        if lateral > 0.34:
            continue
        connected = sum(1.0 - min(1.0, _joint_gap(first, second, axes) / 0.08) for first, second in zip(chain, chain[1:]))
        total_length = sum(item["length"] for item in chain) / max(vertical_span, 1.0e-6)
        toe_bonus = 0.12 if len(chain) >= 4 else 0.0
        score = (
            descent * 1.9
            + first_down * 0.55
            + second_down * 0.55
            + connected * 0.18
            + min(0.55, total_length) * 0.42
            + toe_bonus
            - lateral * 0.22
        )
        candidates.append((score, chain))
    candidates.sort(reverse=True, key=lambda item: item[0])
    return candidates


def _chain_mirror_error(left_chain, right_chain, axes):
    count = min(len(left_chain), len(right_chain))
    if count < 3:
        return 1.0
    lateral = axes["lateral"]
    depth = axes["depth"]
    vertical = axes["vertical"]
    center = axes["lateral_center"]
    errors = []
    for left, right in zip(left_chain[:count], right_chain[:count]):
        lateral_error = abs(abs(left["mid"][lateral] - center) - abs(right["mid"][lateral] - center)) / axes["spans"][lateral]
        depth_error = abs(left["mid"][depth] - right["mid"][depth]) / axes["spans"][depth]
        vertical_error = abs(left["mid"][vertical] - right["mid"][vertical]) / axes["spans"][vertical]
        length_error = abs(left["length"] - right["length"]) / max(left["length"], right["length"], 1.0e-6)
        errors.append(lateral_error + depth_error + vertical_error + length_error * 0.35)
    return sum(errors) / len(errors)


def _paired_leg_chains(rows, axes, left_sign):
    left_candidates = _leg_chain_candidates(rows, axes, "left", left_sign)
    right_candidates = _leg_chain_candidates(rows, axes, "right", left_sign)
    best = None
    best_score = -1.0
    for left_score, left_chain in left_candidates[:12]:
        for right_score, right_chain in right_candidates[:12]:
            length_penalty = abs(len(left_chain) - len(right_chain)) * 0.22
            mirror_error = _chain_mirror_error(left_chain, right_chain, axes)
            if mirror_error > 0.34:
                continue
            score = (left_score + right_score) * 0.5 - mirror_error * 1.65 - length_penalty
            if score > best_score:
                best = {"left": left_chain, "right": right_chain}
                best_score = score
    return best or {}


def _central_bilateral_branch_pairs(rows, axes, left_sign):
    pairs = []
    lateral = axes["lateral"]
    depth = axes["depth"]
    vertical = axes["vertical"]
    lateral_span = axes["spans"][lateral]
    depth_span = axes["spans"][depth]
    vertical_span = axes["spans"][vertical]
    center = axes["lateral_center"]
    for parent in rows.values():
        if abs(parent["mid"][lateral] - center) / lateral_span > 0.22:
            continue
        children = [rows[name] for name in parent["children"] if name in rows]
        for index, first in enumerate(children[:-1]):
            for second in children[index + 1:]:
                first_side = _side(first, axes, left_sign)
                second_side = _side(second, axes, left_sign)
                if {first_side, second_side} != {"left", "right"}:
                    continue
                if min(first["descendants"], second["descendants"]) < 2:
                    continue
                lateral_separation = abs(first["head"][lateral] - second["head"][lateral]) / lateral_span
                vertical_error = abs(first["head"][vertical] - second["head"][vertical]) / vertical_span
                depth_error = abs(first["head"][depth] - second["head"][depth]) / depth_span
                length_error = abs(first["length"] - second["length"]) / max(first["length"], second["length"], 1.0e-6)
                descendant_error = abs(first["descendants"] - second["descendants"]) / max(
                    first["descendants"], second["descendants"], 1
                )
                if vertical_error > 0.12 or depth_error > 0.18 or length_error > 0.7:
                    continue
                symmetry = 1.0 - min(
                    1.0,
                    vertical_error * 2.2
                    + depth_error * 1.7
                    + length_error * 0.45
                    + descendant_error * 0.3,
                )
                side_rows = {first_side: first, second_side: second}
                score = lateral_separation * 1.8 + symmetry * 0.9 + min(
                    0.35,
                    min(first["descendants"], second["descendants"]) * 0.035,
                )
                pairs.append({
                    "parent": parent,
                    "left": side_rows["left"],
                    "right": side_rows["right"],
                    "score": score,
                    "height": (first["head"][vertical] + second["head"][vertical]) * 0.5,
                })
    pairs.sort(reverse=True, key=lambda item: item["score"])
    return pairs


def _outward_chain_from_root(rows, axes, side, left_sign, start, max_len=4):
    chain = [start]
    current = start
    while len(chain) < max_len:
        children = [rows[name] for name in current["children"] if name in rows]
        if len(chain) >= 2 and len(children) >= 3:
            break
        choices = []
        for child in children:
            child_side = _side(child, axes, left_sign)
            if child_side not in {side, None}:
                continue
            parent_offset = abs(current["mid"][axes["lateral"]] - axes["lateral_center"])
            child_offset = abs(child["mid"][axes["lateral"]] - axes["lateral_center"])
            outward = (child_offset - parent_offset) / axes["spans"][axes["lateral"]]
            continuity = 1.0 - min(1.0, _joint_gap(current, child, axes) / 0.08)
            score = outward * 0.8 + continuity * 0.42 + min(0.3, child["descendants"] * 0.02)
            choices.append((score, child))
        if not choices:
            break
        choices.sort(reverse=True, key=lambda item: item[0])
        chain.append(choices[0][1])
        current = choices[0][1]
    return chain


def _bilateral_limb_landmarks(rows, axes, left_sign):
    pairs = _central_bilateral_branch_pairs(rows, axes, left_sign)
    best = None
    best_score = -1.0
    vertical_span = axes["spans"][axes["vertical"]]
    for lower in pairs:
        lower_name = lower["parent"]["name"]
        for upper in pairs:
            if lower is upper or lower_name not in upper["parent"]["ancestors"]:
                continue
            height_gap = (upper["height"] - lower["height"]) / vertical_span
            if height_gap < 0.08:
                continue
            ancestor_distance = upper["parent"]["ancestors"].index(lower_name) + 1
            if ancestor_distance > MAX_SPINE_COUNT + 2:
                continue
            score = lower["score"] + upper["score"] + min(0.45, height_gap) - ancestor_distance * 0.025
            if score > best_score:
                best = (lower, upper)
                best_score = score
    if not best:
        return {}
    lower, upper = best
    legs = {
        side: _descending_limb_chain(rows, axes, side, left_sign, lower[side], max_len=4)
        for side in ("left", "right")
    }
    arms = {
        side: _outward_chain_from_root(rows, axes, side, left_sign, upper[side], max_len=4)
        for side in ("left", "right")
    }
    if any(len(chain) < 3 for chain in (*legs.values(), *arms.values())):
        return {}
    return {
        "hips": lower["parent"],
        "chest": upper["parent"],
        "legs": legs,
        "arms": arms,
    }


def _landmark_left_sign(landmarks, axes):
    if not landmarks:
        return None
    up = _subtract(landmarks["chest"]["mid"], landmarks["hips"]["mid"])
    if _length(up) <= 1.0e-8:
        return None
    forward_samples = []
    for chain in landmarks["legs"].values():
        if len(chain) >= 4:
            forward_samples.append(_subtract(chain[3]["mid"], chain[2]["mid"]))
        elif len(chain) >= 3:
            forward_samples.append(_subtract(chain[2]["tail"], chain[2]["head"]))
    if len(forward_samples) < 2:
        return None
    forward = tuple(sum(sample[index] for sample in forward_samples) for index in range(3))
    up_length_sq = max(_dot(up, up), 1.0e-8)
    forward = tuple(
        forward[index] - up[index] * _dot(forward, up) / up_length_sq
        for index in range(3)
    )
    if _length(forward) <= 1.0e-8:
        return None
    left = _cross(forward, up)
    lateral_value = left[axes["lateral"]]
    if abs(lateral_value) <= _length(left) * 0.2:
        return None
    return 1 if lateral_value > 0.0 else -1


def _lateral_center_from_leg_pair(paired_legs, axes):
    left = paired_legs.get("left")
    right = paired_legs.get("right")
    if not left or not right:
        return None
    lateral = axes["lateral"]
    # Bone tails can be display-oriented or fixed length in imported game
    # rigs. The two upper-leg heads are the stable anatomical hip joints.
    return (left[0]["head"][lateral] + right[0]["head"][lateral]) * 0.5


def _nearest_common_ancestor_row(first, second, rows):
    first_names = {first["name"], *first["ancestors"]}
    current = second
    while current:
        if current["name"] in first_names:
            return current
        parent_name = current["parent"]
        current = rows.get(parent_name) if parent_name else None
    return None


def _has_central_upward_child(row, rows, axes, left_sign, ignored_name=""):
    row_height = _norm(row, axes, "vertical")
    for child_name in row["children"]:
        if child_name == ignored_name or child_name not in rows:
            continue
        child = rows[child_name]
        if _side(child, axes, left_sign) is not None:
            continue
        if _norm(child, axes, "vertical") > row_height + 0.025:
            return True
    return False


def _hips_from_leg_pair(paired_legs, rows, axes, left_sign):
    left = paired_legs.get("left")
    right = paired_legs.get("right")
    if not left or not right:
        return None
    pelvis = _nearest_common_ancestor_row(left[0], right[0], rows)
    if not pelvis:
        return None
    if _has_central_upward_child(pelvis, rows, axes, left_sign):
        return pelvis
    parent = rows.get(pelvis["parent"]) if pelvis["parent"] else None
    if parent and _has_central_upward_child(parent, rows, axes, left_sign, ignored_name=pelvis["name"]):
        return parent
    return pelvis


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
        continuation = min(0.2, child["descendants"] * 0.012)
        return outward * 0.42 + same_side * 0.34 + name_score * 0.22 + child["length"] * 0.02 + continuation

    def build_chain(start):
        chain = [start]
        used = set(trunk_names)
        used.add(start["name"])
        current = start
        while len(chain) < 4:
            extending_children = sum(
                rows[name]["descendants"] > 0
                for name in current["children"]
                if name in rows
            )
            if len(chain) >= 2 and extending_children >= 3:
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

    best_chain = []
    best_score = -1.0e9
    lateral = axes["lateral"]
    center = axes["lateral_center"]
    lateral_span = axes["spans"][lateral]
    for root_score, start in candidates[:20]:
        chain = build_chain(start)
        outward_gain = (
            abs(chain[-1]["mid"][lateral] - center)
            - abs(chain[0]["mid"][lateral] - center)
        ) / lateral_span
        finger_fan = min(1.0, len(chain[-1]["children"]) / 3.0)
        structural_score = (
            root_score * 0.28
            + len(chain) * 0.78
            + max(0.0, outward_gain) * 1.4
            + finger_fan * 0.55
            + min(1.0, start["descendants"] / 20.0) * 0.15
        )
        if len(chain) < 3:
            structural_score -= 1.2
        if structural_score > best_score:
            best_chain = chain
            best_score = structural_score
    return best_chain


def _finger_branch_chain(rows, root, max_len=5):
    chain = [root]
    current = root
    while len(chain) < max_len:
        children = [rows[name] for name in current["children"] if name in rows]
        if not children:
            break
        children.sort(
            key=lambda row: (row["descendants"], row["length"]),
            reverse=True,
        )
        current = children[0]
        chain.append(current)
    return chain


def _finger_roots(rows, hand, arm_names):
    direct_roots = [rows[name] for name in hand["children"] if name in rows and name not in arm_names]
    if len(direct_roots) < 3:
        grandchildren = []
        for child in direct_roots:
            grandchildren.extend(rows[name] for name in child["children"] if name in rows and name not in arm_names)
        direct_roots.extend(grandchildren)
    branches = []
    for root in direct_roots:
        chain = _finger_branch_chain(rows, root)
        direction = _subtract(chain[-1]["tail"], chain[0]["head"])
        if _length(direction) <= 1.0e-8:
            continue
        branches.append({
            "root": chain[0],
            "chain": chain,
            "direction": direction,
            "endpoint": chain[-1]["tail"],
            "chain_length": len(chain),
        })
    if len(branches) < 5:
        return [branch["root"] for branch in branches]
    if len(branches) > 5:
        branches.sort(
            key=lambda branch: (branch["chain_length"], branch["root"]["descendants"]),
            reverse=True,
        )
        branches = branches[:5]

    def direction_similarity(first, second):
        return _dot(first, second) / max(_length(first) * _length(second), 1.0e-8)

    thumb = min(
        branches,
        key=lambda branch: sum(
            direction_similarity(branch["direction"], other["direction"])
            for other in branches
            if other is not branch
        ),
    )
    fingers = [branch for branch in branches if branch is not thumb]

    def average_pairwise_spread(points):
        distances = [
            _distance(first, second)
            for index, first in enumerate(points[:-1])
            for second in points[index + 1:]
        ]
        return sum(distances) / len(distances) if distances else 0.0

    strip_palm_helper = False
    if fingers and all(len(branch["chain"]) >= 4 for branch in fingers):
        root_spread = average_pairwise_spread([branch["chain"][0]["head"] for branch in fingers])
        next_spread = average_pairwise_spread([branch["chain"][1]["head"] for branch in fingers])
        strip_palm_helper = bool(
            root_spread > 1.0e-8
            and next_spread > root_spread * 1.35
        )
    if strip_palm_helper:
        for branch in fingers:
            branch["root"] = branch["chain"][1]
            branch["direction"] = _subtract(branch["endpoint"], branch["root"]["head"])

    average_root = tuple(
        sum(branch["root"]["head"][index] for branch in fingers) / len(fingers)
        for index in range(3)
    )
    common_direction = tuple(
        sum(branch["direction"][index] for branch in fingers)
        for index in range(3)
    )
    width = _subtract(thumb["endpoint"], average_root)
    direction_length_sq = max(_dot(common_direction, common_direction), 1.0e-8)
    width = tuple(
        width[index] - common_direction[index] * _dot(width, common_direction) / direction_length_sq
        for index in range(3)
    )
    if _length(width) <= 1.0e-8:
        width = _subtract(thumb["root"]["head"], average_root)
    fingers.sort(
        key=lambda branch: _dot(_subtract(branch["root"]["head"], average_root), width),
        reverse=True,
    )
    return [thumb["root"], *(branch["root"] for branch in fingers)]


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


def _trim_trunk_to_structural_head(trunk, rows, landmarks, axes):
    if not trunk or not landmarks:
        return trunk
    hips = landmarks.get("hips")
    chest = landmarks.get("chest")
    if not hips or not chest:
        return trunk
    vertical = axes["vertical"]
    torso_height = chest["mid"][vertical] - hips["mid"][vertical]
    if torso_height <= 1.0e-8:
        return trunk
    try:
        chest_index = next(index for index, row in enumerate(trunk) if row["name"] == chest["name"])
    except StopIteration:
        return trunk
    for index in range(chest_index + 1, len(trunk)):
        child_rows = [rows[name] for name in trunk[index]["children"] if name in rows]
        if len(child_rows) >= 2:
            return trunk[:index + 1]
    for index in range(chest_index + 1, len(trunk)):
        head_height = (trunk[index]["mid"][vertical] - chest["mid"][vertical]) / torso_height
        if head_height >= 0.42:
            return trunk[:index + 1]
    return trunk


def analyze_humanoid_roles(armature):
    """Return role candidates using topology first, names only as supporting evidence."""
    if armature is None or getattr(armature, "type", None) != "ARMATURE" or not armature.data.bones:
        return {}

    rows = _build_rows(armature)
    axes = _axis_model(rows)
    left_sign = _infer_left_sign(rows, axes)
    result = {}

    landmarks = _bilateral_limb_landmarks(rows, axes, left_sign)
    if _named_side_evidence_count(rows) < 2:
        structural_left_sign = _landmark_left_sign(landmarks, axes)
        if structural_left_sign is not None and structural_left_sign != left_sign:
            left_sign = structural_left_sign
            landmarks = _bilateral_limb_landmarks(rows, axes, left_sign)
    paired_legs = landmarks.get("legs") or _paired_leg_chains(rows, axes, left_sign)
    paired_arms = landmarks.get("arms") or {}
    paired_center = _lateral_center_from_leg_pair(paired_legs, axes)
    if paired_center is not None:
        axes["lateral_center"] = paired_center
    hips = landmarks.get("hips") or _hips_from_leg_pair(paired_legs, rows, axes, left_sign)
    if hips:
        hips_score = 0.86
    else:
        hips, hips_score = _choose_hips(rows, axes)
    if not hips:
        return result
    hips_reason = "topology:paired-leg-root" if paired_legs else "topology:branch-root"
    _add(result, "hips", hips, hips_score, [hips_reason])

    trunk = _trim_trunk_to_structural_head(_trunk_chain(rows, hips, axes), rows, landmarks, axes)
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
        leg = paired_legs.get(side) or _leg_chain(rows, axes, side, left_sign, trunk_names, hips)
        side_prefix = f"{side}_"
        for role_base, row in zip(("upper_leg", "lower_leg", "foot", "toe"), leg):
            score = 0.79 if paired_legs.get(side) and role_base != "toe" else 0.62 if role_base == "toe" else 0.7
            reason = "topology:paired-leg-chain" if paired_legs.get(side) else "topology:leg-chain"
            _add(result, side_prefix + role_base, row, score, [reason])
            assigned_chain_names.add(row["name"])

    for side in ("left", "right"):
        arm = paired_arms.get(side) or _arm_chain(
            rows, axes, side, left_sign, trunk_names | assigned_chain_names, hips
        )
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
            for role_base, row in zip(("thumb", "index", "middle", "ring", "pinky"), finger_candidates[:5]):
                _add(result, side_prefix + role_base, row, 0.48, ["topology:finger-fan"])

    return result
