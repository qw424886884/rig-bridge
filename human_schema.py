MAX_NECK_COUNT = 3
MAX_SPINE_COUNT = 6


def _neck_role_defs():
    return [(f"neck_{index:02d}", f"颈{index}") for index in range(MAX_NECK_COUNT, 0, -1)]


def _spine_role_defs():
    return [(f"spine_{index:02d}", f"脊柱{index}") for index in range(MAX_SPINE_COUNT, 0, -1)]


HUMAN_ROLE_GROUPS = [
    {
        "id": "center",
        "label": "中轴",
        "roles": [
            ("head", "头"),
            *_neck_role_defs(),
            *_spine_role_defs(),
            ("hips", "髋"),
        ],
    },
    {
        "id": "left_arm",
        "label": "左臂",
        "roles": [
            ("left_shoulder", "左肩"),
            ("left_upper_arm", "左大臂"),
            ("left_lower_arm", "左小臂"),
            ("left_hand", "左手"),
            ("left_thumb", "左拇指"),
            ("left_index", "左食指"),
            ("left_middle", "左中指"),
            ("left_ring", "左无名指"),
            ("left_pinky", "左小指"),
        ],
    },
    {
        "id": "right_arm",
        "label": "右臂",
        "roles": [
            ("right_shoulder", "右肩"),
            ("right_upper_arm", "右大臂"),
            ("right_lower_arm", "右小臂"),
            ("right_hand", "右手"),
            ("right_thumb", "右拇指"),
            ("right_index", "右食指"),
            ("right_middle", "右中指"),
            ("right_ring", "右无名指"),
            ("right_pinky", "右小指"),
        ],
    },
    {
        "id": "left_leg",
        "label": "左腿",
        "roles": [
            ("left_upper_leg", "左大腿"),
            ("left_lower_leg", "左小腿"),
            ("left_foot", "左脚"),
            ("left_toe", "左脚趾"),
        ],
    },
    {
        "id": "right_leg",
        "label": "右腿",
        "roles": [
            ("right_upper_leg", "右大腿"),
            ("right_lower_leg", "右小腿"),
            ("right_foot", "右脚"),
            ("right_toe", "右脚趾"),
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
