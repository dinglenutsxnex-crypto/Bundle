import struct

EXPECTED_HEADER = 457546134634734
_SCALE = 1.0 / 32767.0
_MAX_VALUE = 1.4142135
_SHIFT = 0.70710677


def half_to_float(h):
    s = (h & 0x8000) >> 15
    e = (h & 0x7C00) >> 10
    f = h & 0x03FF
    if e == 0:
        return (-1 if s else 1) * (2.0 ** -14) * (f / 1024.0)
    if e == 0x1F:
        return float("nan") if f else (-1 if s else 1) * float("inf")
    return (-1 if s else 1) * (2.0 ** (e - 15)) * (1 + f / 1024.0)


def parse_compressed_quaternion(v0, v1, v2):
    missing = (v0 >> 13) & 3
    sign_bit = (v0 >> 15) & 1

    a = ((v1 >> 14) + 4 * (v0 & 0x1FFF)) * _SCALE * _MAX_VALUE - _SHIFT
    b = ((v2 >> 15) + 2 * (v1 & 0x3FFF)) * _SCALE * _MAX_VALUE - _SHIFT
    c = (v2 & 0x7FFF) * _SCALE * _MAX_VALUE - _SHIFT

    d_squared = 1.0 - (a * a + b * b + c * c)
    d = d_squared ** 0.5 if d_squared > 0 else 0.0
    if sign_bit == 1:
        d = -d

    if missing == 0:
        return (d, a, b, c)
    if missing == 1:
        return (a, d, b, c)
    if missing == 2:
        return (a, b, d, c)
    if missing == 3:
        return (a, b, c, d)
    return (0.0, 0.0, 0.0, 1.0)


class ParsedAnimation:
    def __init__(self, frames, frames_count, bones_count, bone_ids):
        self.frames = frames
        self.frames_count = frames_count
        self.bones_count = bones_count
        self.bone_ids = bone_ids


def parse_animation_bin(data: bytes) -> ParsedAnimation:
    header_start = -1
    target = struct.pack("<Q", EXPECTED_HEADER)
    for i in range(len(data) - 8):
        if data[i:i + 8] == target:
            header_start = i
            break
    if header_start == -1:
        raise ValueError("Invalid file signature — EXPECTED_HEADER not found")

    offset = header_start + 8

    array_count = struct.unpack_from("<h", data, offset)[0]
    offset += 2
    garbage_size = array_count * 8
    offset += garbage_size

    frames_count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    bones_count = struct.unpack_from("<i", data, offset)[0]
    offset += 4

    frame_size = bones_count * 12

    bone_ids = []
    for _ in range(bones_count):
        bone_ids.append(struct.unpack_from("<h", data, offset)[0])
        offset += 2

    frames = []
    for _frame_index in range(frames_count):
        frame_bones = []
        for bone_index in range(bones_count):
            px, py, pz, v0, v1, v2 = struct.unpack_from("<6H", data, offset)
            offset += 12
            frame_bones.append({
                "boneId": bone_ids[bone_index],
                "position": (half_to_float(px), half_to_float(py), half_to_float(pz)),
                "rotation": parse_compressed_quaternion(v0, v1, v2),
            })
        frames.append({"bones": frame_bones})

    return ParsedAnimation(frames, frames_count, bones_count, bone_ids)
