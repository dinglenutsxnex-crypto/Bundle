import argparse
import csv
import sys

from bin_parser import parse_animation_bin
from skeleton import load_skeleton_definition, build_skeleton
from fk_solver import solve_animation_fk


def main():
    parser = argparse.ArgumentParser(
        description="Parse an SF3 animation .bin, run forward kinematics against the "
                     "SKELETON_DEFINITION rest pose, and write per-frame global bone "
                     "positions (pelvis-anchored) to CSV."
    )
    parser.add_argument("bin_path", help="path to the animation .bin file")
    parser.add_argument("-o", "--output", help="output CSV path (default: <input>.csv)")
    parser.add_argument(
        "--skeleton",
        default="skeleton_definition.txt",
        help="path to the extracted SKELETON_DEFINITION text (default: skeleton_definition.txt)",
    )
    parser.add_argument(
        "--no-anchor",
        action="store_true",
        help="emit true world coordinates without anchoring frame 0's pelvis to the origin",
    )
    args = parser.parse_args()

    output_path = args.output or (args.bin_path.rsplit(".", 1)[0] + ".csv")

    with open(args.bin_path, "rb") as f:
        data = f.read()

    try:
        anim = parse_animation_bin(data)
    except ValueError as e:
        sys.exit(f"ERROR parsing {args.bin_path}: {e}")

    skel_def = load_skeleton_definition(args.skeleton)
    bones_by_name, root_name = build_skeleton(skel_def)

    known_ids = {bone.bone_id for bone in bones_by_name.values()}
    referenced_ids = set(anim.bone_ids)
    unresolved_ids = sorted(referenced_ids - known_ids)

    if unresolved_ids:
        print(
            f"NOTE: {len(unresolved_ids)} bone id(s) in this file are not part of the "
            f"body skeleton and were skipped (weapon/attachment bones, not FK'd): "
            f"{unresolved_ids}",
            file=sys.stderr,
        )

    all_frames_world_pos = solve_animation_fk(
        bones_by_name, root_name, anim, anchor_to_origin=not args.no_anchor
    )

    bone_names_in_order = sorted(bones_by_name.keys(), key=lambda n: bones_by_name[n].bone_id)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "bone_id", "bone_name", "x", "y", "z"])
        for frame_index, world_pos in enumerate(all_frames_world_pos):
            for name in bone_names_in_order:
                bone_id = bones_by_name[name].bone_id
                x, y, z = world_pos[name]
                writer.writerow([frame_index, bone_id, name, f"{x:.6f}", f"{y:.6f}", f"{z:.6f}"])

    print(f"Wrote {anim.frames_count} frames x {len(bone_names_in_order)} bones to {output_path}")
    print(f"  Bones resolved via FK : {len(bone_names_in_order)}")
    print(f"  Bones skipped (unresolved id): {len(unresolved_ids)}")


if __name__ == "__main__":
    main()
