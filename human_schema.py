MAX_NECK_COUNT = 3
MAX_SPINE_COUNT = 6


def _neck_role_defs():
    return [(f"neck_{index:02d}", f"Neck{index}") for index in range(MAX_NECK_COUNT, 0, -1)]


def _spine_role_defs():
    return [(f"spine_{index:02d}", f"Spine{index}") for index in range(MAX_SPINE_COUNT, 0, -1)]


HUMAN_ROLE_GROUPS = [
    {
        "id": "center",
        "label": "Center",
        "roles": [
            ("head", "Head"),
            *_neck_role_defs(),
            *_spine_role_defs(),
            ("hips", "Hips"),
        ],
    },
    {
        "id": "left_arm",
        "label": "Left Arm",
        "roles": [
            ("left_shoulder", "Left Shoulder"),
            ("left_upper_arm", "Left Upper Arm"),
            ("left_lower_arm", "Left Forearm"),
            ("left_hand", "Left Hand"),
            ("left_thumb", "Left Thumb"),
            ("left_index", "Left Index"),
            ("left_middle", "Left Middle"),
            ("left_ring", "Left Ring"),
            ("left_pinky", "Left Pinky"),
        ],
    },
    {
        "id": "right_arm",
        "label": "Right Arm",
        "roles": [
            ("right_shoulder", "Right Shoulder"),
            ("right_upper_arm", "Right Upper Arm"),
            ("right_lower_arm", "Right Forearm"),
            ("right_hand", "Right Hand"),
            ("right_thumb", "Right Thumb"),
            ("right_index", "Right Index"),
            ("right_middle", "Right Middle"),
            ("right_ring", "Right Ring"),
            ("right_pinky", "Right Pinky"),
        ],
    },
    {
        "id": "left_leg",
        "label": "Left Leg",
        "roles": [
            ("left_upper_leg", "Left Thigh"),
            ("left_lower_leg", "Left Shin"),
            ("left_foot", "Left Foot"),
            ("left_toe", "Left Toes"),
        ],
    },
    {
        "id": "right_leg",
        "label": "Right Leg",
        "roles": [
            ("right_upper_leg", "Right Thigh"),
            ("right_lower_leg", "Right Shin"),
            ("right_foot", "Right Foot"),
            ("right_toe", "Right Toes"),
        ],
    },
]


HUMAN_ROLES = [
    {"id": role_id, "label": label, "group": group["id"]}
    for group in HUMAN_ROLE_GROUPS
    for role_id, label in group["roles"]
]


HUMAN_ROLE_BY_ID = {role["id"]: role for role in HUMAN_ROLES}


FINGER_ROLE_IDS = {
    "left_thumb",
    "left_index",
    "left_middle",
    "left_ring",
    "left_pinky",
    "right_thumb",
    "right_index",
    "right_middle",
    "right_ring",
    "right_pinky",
}


def neck_roles(count):
    count = max(1, min(MAX_NECK_COUNT, int(count)))
    return [f"neck_{index:02d}" for index in range(count, 0, -1)]


def spine_roles(count):
    count = max(1, min(MAX_SPINE_COUNT, int(count)))
    return [f"spine_{index:02d}" for index in range(count, 0, -1)]


def visible_role_ids(neck_count=1, spine_count=3, show_fingers=True):
    roles = [
        "head",
        *neck_roles(neck_count),
        "left_shoulder",
        *spine_roles(spine_count),
        "right_shoulder",
        "left_upper_arm",
        "right_upper_arm",
        "left_lower_arm",
        "right_lower_arm",
        "left_hand",
        "hips",
        "right_hand",
        "left_upper_leg",
        "right_upper_leg",
        "left_lower_leg",
        "right_lower_leg",
        "left_foot",
        "right_foot",
        "left_toe",
        "right_toe",
    ]
    if show_fingers:
        roles.extend(
            [
                "left_thumb",
                "left_index",
                "left_middle",
                "left_ring",
                "left_pinky",
                "right_thumb",
                "right_index",
                "right_middle",
                "right_ring",
                "right_pinky",
            ]
        )
    return roles
