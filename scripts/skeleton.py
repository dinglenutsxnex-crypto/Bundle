import re

_NAME_RE = re.compile(r'"([^"]+)"')
_POS_RE = re.compile(r"G\.Pos:\(([^)]+)\)")
_ROT_RE = re.compile(r"G\.Rot \(quat\):\(([^)]+)\)")

BONE_MAP = {
    0: "pelvis", 1: "stomach", 2: "chest", 3: "neck", 4: "head", 5: "hair", 6: "hair1",
    7: "zero_joint_hand_l", 8: "clavicle_l", 9: "arm_l", 10: "forearm_l",
    11: "forearm_twist_l", 12: "hand_l", 13: "weapon_l", 14: "f_big1_l", 15: "f_big2_l", 16: "f_big3_l",
    17: "f_main1_l", 18: "f_main2_l", 19: "f_main3_l", 20: "f_pointer1_l", 21: "f_pointer2_l", 22: "f_pointer3_l",
    23: "scapular_l", 24: "chest_l", 25: "zero_joint_hand_r", 26: "clavicle_r", 27: "arm_r", 28: "forearm_r",
    29: "forearm_twist_r", 30: "hand_r", 31: "weapon_r", 32: "f_big1_r", 33: "f_big2_r", 34: "f_big3_r",
    35: "f_main1_r", 36: "f_main2_r", 37: "f_main3_r", 38: "f_pointer1_r", 39: "f_pointer2_r", 40: "f_pointer3_r",
    41: "scapular_r", 42: "chest_r", 43: "zero_joint_pelvis_l", 44: "thigh_l", 45: "calf_l", 46: "foot_l",
    47: "toe_l", 48: "back_l", 49: "chest_h_49", 50: "stomach_h_50",
    51: "zero_joint_pelvis_r", 52: "thigh_r", 53: "calf_r", 54: "foot_r", 55: "toe_r", 56: "back_r",
    57: "biceps_twist_l", 58: "biceps_twist_r", 59: "thigh_twist_l", 60: "thigh_twist_r",
    61: "foot_r_extra", 62: "toe_r_extra", 63: "weapon_r_extra", 64: "weapon_l_extra", 65: "root_extra",
}
NAME_TO_ID = {name: bone_id for bone_id, name in BONE_MAP.items()}


class BoneNode:
    def __init__(self, name, bone_id, parent_name, rest_local_pos, rest_local_rot):
        self.name = name
        self.bone_id = bone_id
        self.parent_name = parent_name
        self.rest_local_pos = rest_local_pos
        self.rest_local_rot = rest_local_rot
        self.children = []


def load_skeleton_definition(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_skeleton(skeleton_definition: str):
    lines = [line for line in skeleton_definition.split("\n") if line.strip()]

    raw_nodes = []
    for line in lines:
        stripped_len = len(line) - len(line.lstrip())
        depth = stripped_len // 2

        name_match = _NAME_RE.search(line)
        pos_match = _POS_RE.search(line)
        rot_match = _ROT_RE.search(line)
        if not name_match:
            continue

        name = name_match.group(1)
        pos = tuple(float(v) for v in pos_match.group(1).split(",")) if pos_match else (0.0, 0.0, 0.0)
        rot = tuple(float(v) for v in rot_match.group(1).split(",")) if rot_match else (0.0, 0.0, 0.0, 1.0)

        raw_nodes.append({"name": name, "level": depth, "global_pos": pos, "global_rot": rot})

    bones_by_name = {}
    root_name = None
    stack = []

    for node in raw_nodes:
        name = node["name"]
        bone_id = NAME_TO_ID.get(name)

        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()

        if stack:
            parent_name = stack[-1]["name"]
            parent_global_pos = stack[-1]["global_pos"]
            parent_global_rot = stack[-1]["global_rot"]
            local_pos, local_rot = _compute_local_from_global(
                parent_global_pos, parent_global_rot,
                node["global_pos"], node["global_rot"],
            )
        else:
            parent_name = None
            root_name = name
            local_pos = node["global_pos"]
            local_rot = node["global_rot"]

        bone = BoneNode(name, bone_id, parent_name, local_pos, local_rot)
        bones_by_name[name] = bone
        if parent_name is not None:
            bones_by_name[parent_name].children.append(bone)

        stack.append({"name": name, "level": node["level"],
                       "global_pos": node["global_pos"], "global_rot": node["global_rot"]})

    return bones_by_name, root_name


def _compute_local_from_global(parent_pos, parent_rot, child_pos, child_rot):
    from rotation_utils import quat_conjugate, quat_multiply, quat_rotate_vector

    parent_rot_inv = quat_conjugate(parent_rot)

    dpos = (
        child_pos[0] - parent_pos[0],
        child_pos[1] - parent_pos[1],
        child_pos[2] - parent_pos[2],
    )
    local_pos = quat_rotate_vector(parent_rot_inv, dpos)
    local_rot = quat_multiply(parent_rot_inv, child_rot)

    return local_pos, local_rot
