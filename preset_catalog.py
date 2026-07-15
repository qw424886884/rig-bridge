"""Humanoid skeleton preset catalog and role aliases.

The catalog is intentionally data-first: presets are matching hints, not a
runtime dependency on commercial preset files. Exact preset hits are tried
before topology inference; topology still handles unnamed or renamed rigs.
"""

import re


CORE_PRESET_ROLES = (
    "hips",
    "spine_01",
    "head",
    "left_upper_arm",
    "left_lower_arm",
    "left_hand",
    "right_upper_arm",
    "right_lower_arm",
    "right_hand",
    "left_upper_leg",
    "left_lower_leg",
    "left_foot",
    "right_upper_leg",
    "right_lower_leg",
    "right_foot",
)

PRESET_MIN_CONFIDENCE = 0.32
PRESET_MIN_CORE_HITS = 4
PRESET_MIN_SIGNATURE_GAP = 0.08
PRESET_MIN_RAW_HITS_BY_PROFILE = {
    "unreal": 3,
}

PRESET_SOURCE_REFERENCES = {
    "observed_mixamo_fbx": {
        "label": "Observed Mixamo FBX",
        "url": "",
        "kind": "observed-sample",
        "note": "Common Mixamo FBX bone names observed in Blender imports.",
    },
    "observed_auto_rig_pro_scene": {
        "label": "Observed Auto-Rig Pro scene",
        "url": "",
        "kind": "observed-sample",
        "note": "Auto-Rig Pro control, FK/IK, and reference naming observed in the working test scene.",
    },
    "observed_mmd_fk_scene": {
        "label": "Observed MMD FK scene",
        "url": "",
        "kind": "observed-sample",
        "note": "MMD FK center, lower-body, torso, limb, toe, and finger naming verified in a production retarget scene.",
    },
    "epic_animation_retargeting": {
        "label": "Epic Animation Retargeting",
        "url": "https://dev.epicgames.com/documentation/unreal-engine/animation-retargeting-in-unreal-engine",
        "kind": "official-doc",
        "note": "Unreal Skeletons are bone names plus hierarchy data; retargeting depends on skeleton structure.",
    },
    "epic_ik_rig_retargeting": {
        "label": "Epic IK Rig retargeting",
        "url": "https://dev.epicgames.com/documentation/unreal-engine/retargeting-bipeds-with-ik-rig-in-unreal-engine",
        "kind": "official-doc",
        "note": "Unreal biped retarget root is typically pelvis or hips.",
    },
    "unity_human_body_bones": {
        "label": "Unity HumanBodyBones",
        "url": "https://docs.unity3d.com/2018.4/Documentation/ScriptReference/HumanBodyBones.html",
        "kind": "official-doc",
        "note": "Unity Humanoid standard body and finger labels.",
    },
    "vrm_1_0_humanoid": {
        "label": "VRM 1.0 humanoid",
        "url": "https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md",
        "kind": "spec",
        "note": "VRM humanoid parent-child relationships and required roles.",
    },
    "reallusion_bone_list": {
        "label": "Reallusion Bone List",
        "url": "https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/04-Introducing-the-User-Interface/Bone-List.htm",
        "kind": "official-doc",
        "note": "Character Creator / ActorCore bone names.",
    },
    "observed_rigify": {
        "label": "Observed Blender Rigify",
        "url": "",
        "kind": "observed-sample",
        "note": "Common Rigify generated DEF/ORG/MCH naming.",
    },
}


def normalize_preset_name(name):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name or ""))
    text = text.lower()
    text = text.replace("mixamorig:", "")
    text = re.sub(r"[\s\-:]+", "_", text)
    text = text.replace(".", "_")
    text = re.sub(r"[^a-z0-9_\u3040-\u30ff\u4e00-\u9fff\uff10-\uff19]+", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def compact_preset_name(name):
    return normalize_preset_name(name).replace("_", "")


def profile(
    profile_id,
    label,
    role_bones,
    raw_markers=(),
    object_markers=(),
    description="",
    sources=(),
    family="",
    status="seed",
    aliases=(),
):
    return {
        "id": profile_id,
        "label": label,
        "family": family or label,
        "status": status,
        "aliases": tuple(aliases),
        "role_bones": {role_id: tuple(names) for role_id, names in role_bones.items()},
        "raw_markers": tuple(marker.lower() for marker in raw_markers),
        "object_markers": tuple(marker.lower() for marker in object_markers),
        "description": description,
        "sources": tuple(sources),
    }


HUMANOID_PRESET_PROFILES = (
    profile(
        "mixamo",
        "Mixamo",
        {
            "hips": ("mixamorig:Hips", "Hips"),
            "spine_01": ("mixamorig:Spine", "Spine"),
            "spine_02": ("mixamorig:Spine1", "Spine1"),
            "spine_03": ("mixamorig:Spine2", "Spine2"),
            "neck_01": ("mixamorig:Neck", "Neck"),
            "head": ("mixamorig:Head", "Head"),
            "left_shoulder": ("mixamorig:LeftShoulder", "LeftShoulder"),
            "right_shoulder": ("mixamorig:RightShoulder", "RightShoulder"),
            "left_upper_arm": ("mixamorig:LeftArm", "LeftArm"),
            "right_upper_arm": ("mixamorig:RightArm", "RightArm"),
            "left_lower_arm": ("mixamorig:LeftForeArm", "LeftForeArm"),
            "right_lower_arm": ("mixamorig:RightForeArm", "RightForeArm"),
            "left_hand": ("mixamorig:LeftHand", "LeftHand"),
            "right_hand": ("mixamorig:RightHand", "RightHand"),
            "left_upper_leg": ("mixamorig:LeftUpLeg", "LeftUpLeg"),
            "right_upper_leg": ("mixamorig:RightUpLeg", "RightUpLeg"),
            "left_lower_leg": ("mixamorig:LeftLeg", "LeftLeg"),
            "right_lower_leg": ("mixamorig:RightLeg", "RightLeg"),
            "left_foot": ("mixamorig:LeftFoot", "LeftFoot"),
            "right_foot": ("mixamorig:RightFoot", "RightFoot"),
            "left_toe": ("mixamorig:LeftToeBase", "LeftToeBase"),
            "right_toe": ("mixamorig:RightToeBase", "RightToeBase"),
            "left_thumb": ("mixamorig:LeftHandThumb1", "LeftHandThumb1"),
            "right_thumb": ("mixamorig:RightHandThumb1", "RightHandThumb1"),
            "left_index": ("mixamorig:LeftHandIndex1", "LeftHandIndex1"),
            "right_index": ("mixamorig:RightHandIndex1", "RightHandIndex1"),
            "left_middle": ("mixamorig:LeftHandMiddle1", "LeftHandMiddle1"),
            "right_middle": ("mixamorig:RightHandMiddle1", "RightHandMiddle1"),
            "left_ring": ("mixamorig:LeftHandRing1", "LeftHandRing1"),
            "right_ring": ("mixamorig:RightHandRing1", "RightHandRing1"),
            "left_pinky": ("mixamorig:LeftHandPinky1", "LeftHandPinky1"),
            "right_pinky": ("mixamorig:RightHandPinky1", "RightHandPinky1"),
        },
        raw_markers=("mixamorig:",),
        object_markers=("mixamo",),
        description="Mixamo FBX humanoid skeleton.",
        sources=("observed_mixamo_fbx",),
        family="animation-platform",
        status="validated-seed",
        aliases=("Adobe Mixamo",),
    ),
    profile(
        "auto_rig_pro",
        "Auto-Rig Pro",
        {
            "hips": ("c_root_master.x", "c_root.x", "root.x"),
            "spine_01": ("c_spine_01.x", "spine_01_ref.x"),
            "spine_02": ("c_spine_02.x", "spine_02_ref.x"),
            "spine_03": ("c_spine_03.x", "spine_03_ref.x"),
            "spine_04": ("c_spine_04.x", "spine_04_ref.x"),
            "spine_05": ("c_spine_05.x", "spine_05_ref.x"),
            "spine_06": ("c_spine_06.x", "spine_06_ref.x"),
            "neck_01": ("c_neck.x", "neck_ref.x"),
            "head": ("c_head.x", "head_ref.x"),
            "left_shoulder": ("c_shoulder.l", "shoulder_ref.l"),
            "right_shoulder": ("c_shoulder.r", "shoulder_ref.r"),
            "left_upper_arm": ("c_arm_fk.l", "c_arm_ik.l", "arm_ref.l"),
            "right_upper_arm": ("c_arm_fk.r", "c_arm_ik.r", "arm_ref.r"),
            "left_lower_arm": ("c_forearm_fk.l", "c_forearm_ik.l", "forearm_ref.l"),
            "right_lower_arm": ("c_forearm_fk.r", "c_forearm_ik.r", "forearm_ref.r"),
            "left_hand": ("c_hand_fk.l", "c_hand_ik.l", "hand_ref.l"),
            "right_hand": ("c_hand_fk.r", "c_hand_ik.r", "hand_ref.r"),
            "left_upper_leg": ("c_thigh_fk.l", "c_thigh_ik.l", "thigh_ref.l"),
            "right_upper_leg": ("c_thigh_fk.r", "c_thigh_ik.r", "thigh_ref.r"),
            "left_lower_leg": ("c_leg_fk.l", "c_leg_ik.l", "leg_ref.l"),
            "right_lower_leg": ("c_leg_fk.r", "c_leg_ik.r", "leg_ref.r"),
            "left_foot": ("c_foot_fk.l", "c_foot_ik.l", "foot_ref.l"),
            "right_foot": ("c_foot_fk.r", "c_foot_ik.r", "foot_ref.r"),
            "left_toe": ("c_toes_fk.l", "c_toes_ik.l", "toes_ref.l"),
            "right_toe": ("c_toes_fk.r", "c_toes_ik.r", "toes_ref.r"),
        },
        raw_markers=("c_", "_ref.", "_fk.", "_ik."),
        object_markers=("auto_rig", "arp", "human_rig"),
        description="Auto-Rig Pro control/reference naming.",
        sources=("observed_auto_rig_pro_scene",),
        family="rigging-addon",
        status="validated-seed",
        aliases=("ARP", "AutoRigPro"),
    ),
    profile(
        "mmd_fk",
        "MMD FK",
        {
            "hips": ("センター", "グルーブ"),
            "pelvis": ("下半身",),
            "spine_01": ("上半身",),
            "spine_02": ("上半身1",),
            "spine_03": ("上半身2",),
            "neck_01": ("首",),
            "head": ("頭",),
            "left_shoulder": ("肩.L", "左肩"),
            "right_shoulder": ("肩.R", "右肩"),
            "left_upper_arm": ("腕.L", "左腕"),
            "right_upper_arm": ("腕.R", "右腕"),
            "left_lower_arm": ("ひじ.L", "左ひじ"),
            "right_lower_arm": ("ひじ.R", "右ひじ"),
            "left_hand": ("手首.L", "左手首"),
            "right_hand": ("手首.R", "右手首"),
            "left_upper_leg": ("足.L", "左足"),
            "right_upper_leg": ("足.R", "右足"),
            "left_lower_leg": ("ひざ.L", "左ひざ"),
            "right_lower_leg": ("ひざ.R", "右ひざ"),
            "left_foot": ("足首.L", "左足首"),
            "right_foot": ("足首.R", "右足首"),
            "left_toe": ("足先EX.L", "つま先.L", "左つま先"),
            "right_toe": ("足先EX.R", "つま先.R", "右つま先"),
            "left_thumb": ("親指０.L", "親指0.L"),
            "right_thumb": ("親指０.R", "親指0.R"),
            "left_index": ("人指１.L", "人指1.L"),
            "right_index": ("人指１.R", "人指1.R"),
            "left_middle": ("中指１.L", "中指1.L"),
            "right_middle": ("中指１.R", "中指1.R"),
            "left_ring": ("薬指１.L", "薬指1.L"),
            "right_ring": ("薬指１.R", "薬指1.R"),
            "left_pinky": ("小指１.L", "小指1.L"),
            "right_pinky": ("小指１.R", "小指1.R"),
        },
        raw_markers=("センター", "下半身", "ひざ."),
        object_markers=("mmd", "miku", "mikumikudance"),
        description="MikuMikuDance FK skeleton with separate motion-center and lower-body pelvis bones.",
        sources=("observed_mmd_fk_scene",),
        family="animation-format",
        status="validated-production-sample",
        aliases=("MMD", "MikuMikuDance"),
    ),
    profile(
        "unreal",
        "Unreal/MetaHuman",
        {
            "hips": ("pelvis",),
            "spine_01": ("spine_01",),
            "spine_02": ("spine_02",),
            "spine_03": ("spine_03",),
            "neck_01": ("neck_01",),
            "head": ("head",),
            "left_shoulder": ("clavicle_l",),
            "right_shoulder": ("clavicle_r",),
            "left_upper_arm": ("upperarm_l",),
            "right_upper_arm": ("upperarm_r",),
            "left_lower_arm": ("lowerarm_l",),
            "right_lower_arm": ("lowerarm_r",),
            "left_hand": ("hand_l",),
            "right_hand": ("hand_r",),
            "left_upper_leg": ("thigh_l",),
            "right_upper_leg": ("thigh_r",),
            "left_lower_leg": ("calf_l", "lowerleg_l"),
            "right_lower_leg": ("calf_r", "lowerleg_r"),
            "left_foot": ("foot_l",),
            "right_foot": ("foot_r",),
            "left_toe": ("ball_l",),
            "right_toe": ("ball_r",),
        },
        raw_markers=("spine_01", "upperarm_l", "thigh_l", "clavicle_l"),
        object_markers=("ue", "unreal", "metahuman", "mannequin", "manny", "quinn"),
        description="Unreal Mannequin and MetaHuman-compatible core names.",
        sources=("epic_animation_retargeting", "epic_ik_rig_retargeting"),
        family="game-engine",
        status="needs-real-sample",
        aliases=("UE", "Unreal Engine", "MetaHuman", "Manny", "Quinn"),
    ),
    profile(
        "unity_humanoid",
        "Unity Humanoid",
        {
            "hips": ("Hips",),
            "spine_01": ("Spine",),
            "spine_02": ("Chest",),
            "spine_03": ("UpperChest",),
            "neck_01": ("Neck",),
            "head": ("Head",),
            "left_shoulder": ("LeftShoulder",),
            "right_shoulder": ("RightShoulder",),
            "left_upper_arm": ("LeftUpperArm",),
            "right_upper_arm": ("RightUpperArm",),
            "left_lower_arm": ("LeftLowerArm",),
            "right_lower_arm": ("RightLowerArm",),
            "left_hand": ("LeftHand",),
            "right_hand": ("RightHand",),
            "left_upper_leg": ("LeftUpperLeg",),
            "right_upper_leg": ("RightUpperLeg",),
            "left_lower_leg": ("LeftLowerLeg",),
            "right_lower_leg": ("RightLowerLeg",),
            "left_foot": ("LeftFoot",),
            "right_foot": ("RightFoot",),
            "left_toe": ("LeftToes",),
            "right_toe": ("RightToes",),
        },
        raw_markers=("LeftUpperArm", "RightUpperArm", "UpperChest"),
        object_markers=("unity",),
        description="Unity Humanoid avatar bone labels.",
        sources=("unity_human_body_bones",),
        family="game-engine",
        status="official-spec-seed",
        aliases=("Unity", "Unity Mecanim"),
    ),
    profile(
        "vrm_vroid",
        "VRM/VRoid",
        {
            "hips": ("J_Bip_C_Hips", "hips"),
            "spine_01": ("J_Bip_C_Spine", "spine"),
            "spine_02": ("J_Bip_C_Chest", "chest"),
            "spine_03": ("J_Bip_C_UpperChest", "upperChest"),
            "neck_01": ("J_Bip_C_Neck", "neck"),
            "head": ("J_Bip_C_Head", "head"),
            "left_shoulder": ("J_Bip_L_Shoulder", "leftShoulder"),
            "right_shoulder": ("J_Bip_R_Shoulder", "rightShoulder"),
            "left_upper_arm": ("J_Bip_L_UpperArm", "leftUpperArm"),
            "right_upper_arm": ("J_Bip_R_UpperArm", "rightUpperArm"),
            "left_lower_arm": ("J_Bip_L_LowerArm", "leftLowerArm"),
            "right_lower_arm": ("J_Bip_R_LowerArm", "rightLowerArm"),
            "left_hand": ("J_Bip_L_Hand", "leftHand"),
            "right_hand": ("J_Bip_R_Hand", "rightHand"),
            "left_upper_leg": ("J_Bip_L_UpperLeg", "leftUpperLeg"),
            "right_upper_leg": ("J_Bip_R_UpperLeg", "rightUpperLeg"),
            "left_lower_leg": ("J_Bip_L_LowerLeg", "leftLowerLeg"),
            "right_lower_leg": ("J_Bip_R_LowerLeg", "rightLowerLeg"),
            "left_foot": ("J_Bip_L_Foot", "leftFoot"),
            "right_foot": ("J_Bip_R_Foot", "rightFoot"),
            "left_toe": ("J_Bip_L_ToeBase", "leftToes"),
            "right_toe": ("J_Bip_R_ToeBase", "rightToes"),
        },
        raw_markers=("j_bip_", "leftUpperArm", "rightUpperArm"),
        object_markers=("vrm", "vroid"),
        description="VRM humanoid and common VRoid naming.",
        sources=("vrm_1_0_humanoid",),
        family="avatar-format",
        status="official-spec-seed",
        aliases=("VRM", "VRoid"),
    ),
    profile(
        "reallusion_cc",
        "Reallusion/ActorCore",
        {
            "hips": ("CC_Base_Hip", "CC_Base_Pelvis", "RL_BoneRoot"),
            "spine_01": ("CC_Base_Waist", "CC_Base_Spine01"),
            "spine_02": ("CC_Base_Spine01", "CC_Base_Spine02"),
            "spine_03": ("CC_Base_Spine02",),
            "neck_01": ("CC_Base_NeckTwist01", "CC_Base_Neck"),
            "head": ("CC_Base_Head",),
            "left_shoulder": ("CC_Base_L_Clavicle",),
            "right_shoulder": ("CC_Base_R_Clavicle",),
            "left_upper_arm": ("CC_Base_L_Upperarm", "CC_Base_L_UpperArm"),
            "right_upper_arm": ("CC_Base_R_Upperarm", "CC_Base_R_UpperArm"),
            "left_lower_arm": ("CC_Base_L_Forearm",),
            "right_lower_arm": ("CC_Base_R_Forearm",),
            "left_hand": ("CC_Base_L_Hand",),
            "right_hand": ("CC_Base_R_Hand",),
            "left_upper_leg": ("CC_Base_L_Thigh",),
            "right_upper_leg": ("CC_Base_R_Thigh",),
            "left_lower_leg": ("CC_Base_L_Calf",),
            "right_lower_leg": ("CC_Base_R_Calf",),
            "left_foot": ("CC_Base_L_Foot",),
            "right_foot": ("CC_Base_R_Foot",),
            "left_toe": ("CC_Base_L_ToeBase",),
            "right_toe": ("CC_Base_R_ToeBase",),
        },
        raw_markers=("cc_base_", "rl_boneroot", "actorcore"),
        object_markers=("cc_base", "reallusion", "actorcore", "character_creator"),
        description="Reallusion Character Creator / ActorCore style names.",
        sources=("reallusion_bone_list",),
        family="character-platform",
        status="needs-real-sample",
        aliases=("Character Creator", "ActorCore", "CC"),
    ),
    profile(
        "rigify",
        "Rigify",
        {
            "hips": ("DEF-spine", "ORG-spine"),
            "spine_01": ("DEF-spine.001", "ORG-spine.001"),
            "spine_02": ("DEF-spine.002", "ORG-spine.002"),
            "spine_03": ("DEF-spine.003", "ORG-spine.003"),
            "neck_01": ("DEF-spine.004", "DEF-neck"),
            "head": ("DEF-spine.006", "DEF-head"),
            "left_shoulder": ("DEF-shoulder.L",),
            "right_shoulder": ("DEF-shoulder.R",),
            "left_upper_arm": ("DEF-upper_arm.L",),
            "right_upper_arm": ("DEF-upper_arm.R",),
            "left_lower_arm": ("DEF-forearm.L",),
            "right_lower_arm": ("DEF-forearm.R",),
            "left_hand": ("DEF-hand.L",),
            "right_hand": ("DEF-hand.R",),
            "left_upper_leg": ("DEF-thigh.L",),
            "right_upper_leg": ("DEF-thigh.R",),
            "left_lower_leg": ("DEF-shin.L",),
            "right_lower_leg": ("DEF-shin.R",),
            "left_foot": ("DEF-foot.L",),
            "right_foot": ("DEF-foot.R",),
            "left_toe": ("DEF-toe.L",),
            "right_toe": ("DEF-toe.R",),
        },
        raw_markers=("def-", "org-", "mch-"),
        object_markers=("rigify",),
        description="Blender Rigify generated deformation bone names.",
        sources=("observed_rigify",),
        family="blender-rig",
        status="needs-real-sample",
        aliases=("Blender Rigify",),
    ),
)


def preset_profile(profile_id):
    for item in HUMANOID_PRESET_PROFILES:
        if item["id"] == profile_id:
            return item
    return None


def public_preset_profiles():
    profiles = []
    for item in HUMANOID_PRESET_PROFILES:
        profiles.append(
            {
                "id": item["id"],
                "label": item["label"],
                "family": item.get("family", ""),
                "status": item.get("status", ""),
                "aliases": list(item.get("aliases", ())),
                "sources": list(item.get("sources", ())),
                "description": item.get("description", ""),
                "roleCount": len(item.get("role_bones", {})),
                "coreRoleCount": len(
                    [role_id for role_id in CORE_PRESET_ROLES if role_id in item.get("role_bones", {})]
                ),
            }
        )
    return profiles


def _sample_set(sample_id, label, expected_profile, bone_names, object_name="", source="catalog-seed"):
    return {
        "id": sample_id,
        "label": label,
        "expected_profile": expected_profile,
        "object_name": object_name,
        "source": source,
        "bone_names": tuple(bone_names),
    }


def _sample_from_profile(sample_id, profile_id, label=None, object_name="", source="catalog-seed"):
    item = preset_profile(profile_id)
    if not item:
        raise ValueError(f"Unknown preset profile: {profile_id}")
    bone_names = [names[0] for names in item["role_bones"].values() if names]
    return _sample_set(
        sample_id,
        label or item["label"],
        profile_id,
        bone_names,
        object_name=object_name,
        source=source,
    )


HUMANOID_PRESET_SAMPLE_SETS = (
    _sample_from_profile(
        "mixamo_prefixed_core",
        "mixamo",
        object_name="Armature.001",
        source="observed_mixamo_fbx",
    ),
    _sample_set(
        "mixamo_unprefixed_core",
        "Ambiguous humanoid names without Mixamo signature",
        None,
        (
            "Hips",
            "Spine",
            "Spine1",
            "Spine2",
            "Neck",
            "Head",
            "LeftShoulder",
            "LeftArm",
            "LeftForeArm",
            "LeftHand",
            "RightShoulder",
            "RightArm",
            "RightForeArm",
            "RightHand",
            "LeftUpLeg",
            "LeftLeg",
            "LeftFoot",
            "RightUpLeg",
            "RightLeg",
            "RightFoot",
        ),
        object_name="ImportedArmature",
        source="observed_mixamo_fbx",
    ),
    _sample_from_profile(
        "auto_rig_pro_fk_core",
        "auto_rig_pro",
        object_name="Human_rig",
        source="observed_auto_rig_pro_scene",
    ),
    _sample_from_profile(
        "mmd_fk_production_core",
        "mmd_fk",
        object_name="MMD_Action_Source",
        source="observed_mmd_fk_scene",
    ),
    _sample_from_profile(
        "unreal_mannequin_core",
        "unreal",
        object_name="SKM_Manny",
        source="epic_animation_retargeting",
    ),
    _sample_set(
        "blender_vrm_export_not_unreal",
        "Blender-style VRM export without Unreal center-chain signature",
        None,
        (
            "root",
            "hips",
            "spine",
            "chest",
            "neck",
            "head",
            "shoulder.L",
            "upper_arm.L",
            "lower_arm.L",
            "hand.L",
            "shoulder.R",
            "upper_arm.R",
            "lower_arm.R",
            "hand.R",
            "upper_leg.L",
            "lower_leg.L",
            "foot.L",
            "upper_leg.R",
            "lower_leg.R",
            "foot.R",
        ),
        object_name="Armature",
        source="observed-local-vrm-export",
    ),
    _sample_from_profile(
        "unity_humanoid_core",
        "unity_humanoid",
        object_name="UnityHumanoid",
        source="unity_human_body_bones",
    ),
    _sample_from_profile(
        "vrm_vroid_j_bip_core",
        "vrm_vroid",
        object_name="VRoid_Avatar",
        source="vrm_1_0_humanoid",
    ),
    _sample_set(
        "vrm_spec_camel_case_core",
        "VRM humanoid camelCase roles",
        "vrm_vroid",
        (
            "hips",
            "spine",
            "chest",
            "upperChest",
            "neck",
            "head",
            "leftShoulder",
            "leftUpperArm",
            "leftLowerArm",
            "leftHand",
            "rightShoulder",
            "rightUpperArm",
            "rightLowerArm",
            "rightHand",
            "leftUpperLeg",
            "leftLowerLeg",
            "leftFoot",
            "rightUpperLeg",
            "rightLowerLeg",
            "rightFoot",
        ),
        object_name="VRM_Humanoid",
        source="vrm_1_0_humanoid",
    ),
    _sample_from_profile(
        "reallusion_cc_base_core",
        "reallusion_cc",
        object_name="CC_Base_Body",
        source="reallusion_bone_list",
    ),
    _sample_from_profile(
        "rigify_def_core",
        "rigify",
        object_name="rigify_human",
        source="observed_rigify",
    ),
)


COMMON_ROLE_ALIASES = {
    "hips": {
        "Hips",
        "Hip",
        "Pelvis",
        "pelvis",
        "root",
        "root.x",
        "root_ref.x",
        "c_root_master.x",
    },
    "spine_01": {"Spine", "Spine1", "spine_01", "spine01", "c_spine_01.x", "spine_01_ref.x"},
    "spine_02": {"Spine1", "Spine2", "spine_02", "spine02", "c_spine_02.x", "spine_02_ref.x"},
    "spine_03": {"Chest", "UpperChest", "Spine2", "Spine3", "spine_03", "spine03", "c_spine_03.x", "spine_03_ref.x"},
    "spine_04": {"Chest", "UpperChest", "Spine3", "Spine4", "spine_04", "spine04", "c_spine_04.x", "spine_04_ref.x"},
    "spine_05": {"Chest", "UpperChest", "Spine4", "Spine5", "spine_05", "spine05", "c_spine_05.x", "spine_05_ref.x"},
    "spine_06": {"Chest", "UpperChest", "Spine5", "Spine6", "spine_06", "spine06", "c_spine_06.x", "spine_06_ref.x"},
    "neck_01": {"Neck", "neck", "neck_01", "c_neck.x", "neck_ref.x"},
    "neck_02": {"Neck1", "neck_02", "neck02"},
    "neck_03": {"Neck2", "neck_03", "neck03"},
    "head": {"Head", "head", "c_head.x", "head_ref.x"},
    "left_shoulder": {"LeftShoulder", "LeftCollar", "clavicle_l", "c_shoulder.l", "shoulder_ref.l"},
    "right_shoulder": {"RightShoulder", "RightCollar", "clavicle_r", "c_shoulder.r", "shoulder_ref.r"},
    "left_upper_arm": {"LeftArm", "LeftUpperArm", "upperarm_l", "c_arm_fk.l", "c_arm_ik.l", "arm_ref.l"},
    "right_upper_arm": {"RightArm", "RightUpperArm", "upperarm_r", "c_arm_fk.r", "c_arm_ik.r", "arm_ref.r"},
    "left_lower_arm": {"LeftForeArm", "LeftLowerArm", "lowerarm_l", "c_forearm_fk.l", "c_forearm_ik.l", "forearm_ref.l"},
    "right_lower_arm": {"RightForeArm", "RightLowerArm", "lowerarm_r", "c_forearm_fk.r", "c_forearm_ik.r", "forearm_ref.r"},
    "left_hand": {"LeftHand", "hand_l", "c_hand_fk.l", "c_hand_ik.l", "hand_ref.l"},
    "right_hand": {"RightHand", "hand_r", "c_hand_fk.r", "c_hand_ik.r", "hand_ref.r"},
    "left_upper_leg": {"LeftUpLeg", "LeftUpperLeg", "thigh_l", "c_thigh_fk.l", "c_thigh_ik.l", "thigh_ref.l"},
    "right_upper_leg": {"RightUpLeg", "RightUpperLeg", "thigh_r", "c_thigh_fk.r", "c_thigh_ik.r", "thigh_ref.r"},
    "left_lower_leg": {"LeftLeg", "LeftLowerLeg", "calf_l", "shin_l", "c_leg_fk.l", "c_leg_ik.l", "leg_ref.l"},
    "right_lower_leg": {"RightLeg", "RightLowerLeg", "calf_r", "shin_r", "c_leg_fk.r", "c_leg_ik.r", "leg_ref.r"},
    "left_foot": {"LeftFoot", "foot_l", "c_foot_fk.l", "c_foot_ik.l", "foot_ref.l", "foot_bank_01_ref.l"},
    "right_foot": {"RightFoot", "foot_r", "c_foot_fk.r", "c_foot_ik.r", "foot_ref.r", "foot_bank_01_ref.r"},
    "left_toe": {"LeftToeBase", "LeftToe", "ball_l", "toe_l", "c_toes_fk.l", "c_toes_ik.l", "toes_ref.l"},
    "right_toe": {"RightToeBase", "RightToe", "ball_r", "toe_r", "c_toes_fk.r", "c_toes_ik.r", "toes_ref.r"},
    "left_thumb": {"LeftHandThumb1", "thumb_01_l", "thumb1_ref.l", "c_thumb1.l"},
    "right_thumb": {"RightHandThumb1", "thumb_01_r", "thumb1_ref.r", "c_thumb1.r"},
    "left_index": {"LeftHandIndex1", "index_01_l", "index1_ref.l", "c_index1.l"},
    "right_index": {"RightHandIndex1", "index_01_r", "index1_ref.r", "c_index1.r"},
    "left_middle": {"LeftHandMiddle1", "middle_01_l", "middle1_ref.l", "c_middle1.l"},
    "right_middle": {"RightHandMiddle1", "middle_01_r", "middle1_ref.r", "c_middle1.r"},
    "left_ring": {"LeftHandRing1", "ring_01_l", "ring1_ref.l", "c_ring1.l"},
    "right_ring": {"RightHandRing1", "ring_01_r", "ring1_ref.r", "c_ring1.r"},
    "left_pinky": {"LeftHandPinky1", "pinky_01_l", "pinky1_ref.l", "c_pinky1.l"},
    "right_pinky": {"RightHandPinky1", "pinky_01_r", "pinky1_ref.r", "c_pinky1.r"},
}


for preset in HUMANOID_PRESET_PROFILES:
    for role_id, names in preset["role_bones"].items():
        COMMON_ROLE_ALIASES.setdefault(role_id, set()).update(names)


def aliases_for_role(role_id):
    return COMMON_ROLE_ALIASES.get(role_id, set())


def normalized_bone_lookup(bone_names):
    lookup = {}
    for bone_name in bone_names:
        variants = {
            normalize_preset_name(bone_name),
            compact_preset_name(bone_name),
        }
        for variant in variants:
            if variant and variant not in lookup:
                lookup[variant] = bone_name
    return lookup


def preset_role_matches_from_names(bone_names, preset, role_ids=None):
    role_filter = set(role_ids) if role_ids else None
    lookup = normalized_bone_lookup(bone_names)
    matches = {}
    for role_id, aliases in preset["role_bones"].items():
        if role_filter is not None and role_id not in role_filter:
            continue
        for alias in aliases:
            for key in {normalize_preset_name(alias), compact_preset_name(alias)}:
                bone_name = lookup.get(key)
                if bone_name:
                    matches[role_id] = {
                        "role_id": role_id,
                        "bone_name": bone_name,
                        "score": 0.96,
                        "reasons": [f"preset:{preset['id']}"],
                    }
                    break
            if role_id in matches:
                break
    return matches


def score_preset_from_names(bone_names, preset, object_name=""):
    raw_names = [str(name) for name in bone_names]
    lowered = [name.lower() for name in raw_names]
    normalized = {normalize_preset_name(name) for name in raw_names}
    compact = {name.replace("_", "") for name in normalized}
    object_lower = str(object_name or "").lower()

    matches = preset_role_matches_from_names(raw_names, preset)
    core_hits = len([role_id for role_id in CORE_PRESET_ROLES if role_id in matches])
    all_hits = len(matches)
    core_total = len(CORE_PRESET_ROLES)
    all_total = max(1, len(preset["role_bones"]))
    raw_hits = 0
    for marker in preset["raw_markers"]:
        marker_norm = normalize_preset_name(marker)
        if (
            any(marker in name for name in lowered)
            or marker_norm in normalized
            or marker_norm.replace("_", "") in compact
        ):
            raw_hits += 1
    object_hit = any(marker and marker in object_lower for marker in preset["object_markers"])

    core_ratio = core_hits / core_total
    all_ratio = all_hits / all_total
    raw_ratio = min(1.0, raw_hits / max(1, len(preset["raw_markers"])))
    confidence = core_ratio * 0.68 + all_ratio * 0.20 + raw_ratio * 0.10
    if object_hit:
        confidence += 0.05
    confidence = min(1.0, confidence)
    return {
        "id": preset["id"],
        "label": preset["label"],
        "family": preset.get("family", ""),
        "status": preset.get("status", ""),
        "aliases": list(preset.get("aliases", ())),
        "sources": list(preset.get("sources", ())),
        "description": preset.get("description", ""),
        "confidence": round(confidence, 4),
        "coreHits": core_hits,
        "allHits": all_hits,
        "rawHits": raw_hits,
        "objectHit": bool(object_hit),
        "matches": matches,
    }


def best_matching_preset(bone_names, object_name=""):
    if not bone_names:
        return None
    return accepted_preset_match(score_all_presets(bone_names, object_name=object_name))


def score_all_presets(bone_names, object_name=""):
    scored = [
        score_preset_from_names(bone_names, preset, object_name=object_name)
        for preset in HUMANOID_PRESET_PROFILES
    ]
    scored.sort(key=lambda item: (item["confidence"], item["coreHits"], item["rawHits"]), reverse=True)
    return scored


def accepted_preset_match(scored):
    best = scored[0] if scored else None
    if not best:
        return None
    if best["confidence"] < PRESET_MIN_CONFIDENCE or best["coreHits"] < PRESET_MIN_CORE_HITS:
        return None
    minimum_raw_hits = PRESET_MIN_RAW_HITS_BY_PROFILE.get(best["id"], 1)
    if not best["objectHit"] and best["rawHits"] < minimum_raw_hits:
        return None
    has_signature = bool(best["rawHits"] or best["objectHit"])
    if not has_signature:
        return None
    runner_confidence = scored[1]["confidence"] if len(scored) > 1 else 0.0
    confidence_gap = best["confidence"] - runner_confidence
    if confidence_gap < PRESET_MIN_SIGNATURE_GAP and not best["objectHit"]:
        return None
    return best


def classify_bone_names(bone_names, object_name="", include_scores=False):
    scored = score_all_presets(bone_names, object_name=object_name)
    best = scored[0] if scored else None
    accepted = accepted_preset_match(scored)
    ambiguous = bool(
        best
        and best["confidence"] >= PRESET_MIN_CONFIDENCE
        and best["coreHits"] >= PRESET_MIN_CORE_HITS
        and not accepted
    )
    runner_confidence = scored[1]["confidence"] if len(scored) > 1 else 0.0
    return {
        "profile": accepted,
        "status": "preset-hit" if accepted else "ambiguous-preset" if ambiguous else "no-preset-hit",
        "topConfidenceGap": round((best["confidence"] if best else 0.0) - runner_confidence, 4),
        "scores": scored if include_scores else [],
    }


def preset_role_matches(armature, role_ids=None):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return {}
    bone_names = [bone.name for bone in armature.data.bones]
    best = best_matching_preset(bone_names, object_name=getattr(armature, "name", ""))
    if not best:
        return {}
    role_filter = set(role_ids) if role_ids else None
    matches = {}
    for role_id, match in best["matches"].items():
        if role_filter is not None and role_id not in role_filter:
            continue
        matches[role_id] = {
            **match,
            "score": min(1.0, max(match["score"], 0.86 + best["confidence"] * 0.1)),
            "reasons": [*match["reasons"], f"profile:{best['label']}"],
        }
    return matches


def audit_preset_sample_sets(samples=None, min_core_hits=12):
    sample_items = tuple(samples or HUMANOID_PRESET_SAMPLE_SETS)
    results = []
    passed = 0
    for sample in sample_items:
        classification = classify_bone_names(
            sample.get("bone_names", ()),
            object_name=sample.get("object_name", ""),
            include_scores=True,
        )
        profile = classification["profile"]
        expected = sample.get("expected_profile")
        matched = profile["id"] if profile else None
        core_hits = profile["coreHits"] if profile else 0
        ok = matched is None if expected is None else matched == expected and core_hits >= min_core_hits
        if ok:
            passed += 1
        results.append(
            {
                "id": sample.get("id"),
                "label": sample.get("label"),
                "source": sample.get("source"),
                "objectName": sample.get("object_name", ""),
                "expectedProfile": expected,
                "matchedProfile": matched,
                "matchedLabel": profile["label"] if profile else None,
                "confidence": profile["confidence"] if profile else 0.0,
                "coreHits": core_hits,
                "allHits": profile["allHits"] if profile else 0,
                "status": "pass" if ok else "fail",
                "topScores": [
                    {
                        "id": item["id"],
                        "label": item["label"],
                        "confidence": item["confidence"],
                        "coreHits": item["coreHits"],
                    }
                    for item in classification["scores"][:3]
                ],
            }
        )
    return {
        "schema": "humanoid-remap-studio.preset-audit.v1",
        "profileCount": len(HUMANOID_PRESET_PROFILES),
        "sourceCount": len(PRESET_SOURCE_REFERENCES),
        "sampleCount": len(sample_items),
        "passed": passed,
        "failed": len(sample_items) - passed,
        "ok": passed == len(sample_items),
        "profiles": public_preset_profiles(),
        "sources": PRESET_SOURCE_REFERENCES,
        "results": results,
    }
