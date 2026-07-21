def quat_multiply(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    result = (
        ax * bw + aw * bx + ay * bz - az * by,
        ay * bw + aw * by + az * bx - ax * bz,
        az * bw + aw * bz + ax * by - ay * bx,
        aw * bw - ax * bx - ay * by - az * bz,
    )
    return quat_normalize(result)


def quat_conjugate(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def quat_normalize(q):
    x, y, z, w = q
    n = (x * x + y * y + z * z + w * w) ** 0.5
    if n == 0:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / n, y / n, z / n, w / n)


def quat_rotate_vector(q, v):
    qx, qy, qz, qw = q
    vx, vy, vz = v

    ix = qw * vx + qy * vz - qz * vy
    iy = qw * vy + qz * vx - qx * vz
    iz = qw * vz + qx * vy - qy * vx
    iw = -qx * vx - qy * vy - qz * vz

    rx = ix * qw + iw * -qx + iy * -qz - iz * -qy
    ry = iy * qw + iw * -qy + iz * -qx - ix * -qz
    rz = iz * qw + iw * -qz + ix * -qy - iy * -qx

    return (rx, ry, rz)
