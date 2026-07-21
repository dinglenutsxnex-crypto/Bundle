from rotation_utils import quat_multiply, quat_rotate_vector, quat_normalize


def solve_frame_fk(bones_by_name, root_name, frame_local_overrides):
    world_pos = {}
    world_rot = {}

    def recurse(bone_name, parent_world_pos, parent_world_rot):
        bone = bones_by_name[bone_name]
        override = frame_local_overrides.get(bone.bone_id)

        if override is not None:
            local_pos = override["position"]
            local_rot = override["rotation"]
        else:
            local_pos = bone.rest_local_pos
            local_rot = bone.rest_local_rot

        if parent_world_rot is None:
            this_world_rot = quat_normalize(local_rot)
            this_world_pos = local_pos
        else:
            rotated_offset = quat_rotate_vector(parent_world_rot, local_pos)
            this_world_pos = (
                parent_world_pos[0] + rotated_offset[0],
                parent_world_pos[1] + rotated_offset[1],
                parent_world_pos[2] + rotated_offset[2],
            )
            this_world_rot = quat_multiply(parent_world_rot, local_rot)

        world_pos[bone_name] = this_world_pos
        world_rot[bone_name] = this_world_rot

        for child in bone.children:
            recurse(child.name, this_world_pos, this_world_rot)

    recurse(root_name, None, None)
    return world_pos, world_rot


def solve_animation_fk(bones_by_name, root_name, parsed_animation, anchor_to_origin=True):
    all_frames_world_pos = []

    origin_offset = None

    for frame in parsed_animation.frames:
        overrides = {b["boneId"]: b for b in frame["bones"]}
        world_pos, _world_rot = solve_frame_fk(bones_by_name, root_name, overrides)

        if anchor_to_origin and origin_offset is None:
            px, py, pz = world_pos[root_name]
            origin_offset = (px, py, pz)

        if anchor_to_origin:
            ox, oy, oz = origin_offset
            adjusted = {
                name: (pos[0] - ox, pos[1] - oy, pos[2] - oz)
                for name, pos in world_pos.items()
            }
            all_frames_world_pos.append(adjusted)
        else:
            all_frames_world_pos.append(world_pos)

    return all_frames_world_pos
