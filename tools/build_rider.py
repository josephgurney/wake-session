"""Build the Thursday Yacht Club rider from the MakeHuman base body (CC0), with plain Python and numpy.

    git clone --depth 1 https://github.com/makehumancommunity/mpfb2 ../mpfb2
    python tools/build_rider.py --mpfb ../mpfb2          # writes assets/rider.glb and assets/rider.js

What it does, in order:
  1. loads the MakeHuman base mesh and morphs it with MPFB2's body targets (gender, age, muscle, weight, height,
     proportions) using the same weighting MPFB2 itself uses;
  2. fits MPFB2's 53-bone "game engine" skeleton to the morphed body and takes its skin weights;
  3. grows board shorts, an impact vest and boots out of the body surface (so they bend exactly like the skin),
     and deletes the skin they hide; adds a helmet and a pair of Lobster sunglasses on the head bone;
  4. writes a skinned glTF binary (GLB), plus rider.js: the same bytes as base64, so index.html can load the
     model straight from disk without a web server.

Everything the game needs to know about the model (bone names, rest lengths) comes from the GLB itself; the
foot measurements the pose code uses are stored in the root node's extras.
Body shape, outfit colours and clothing fit are the constants just below. Tweak, re-run, reload the game.
"""
import argparse
import base64
import collections
import gzip
import json
import pathlib
import struct

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---- body: MakeHuman macro sliders, 0..1 (0.5 is average) ----
BODY = {"gender": 1.0, "age": 0.5, "muscle": 0.78, "weight": 0.42, "height": 0.5, "proportions": 0.85,
        "cupsize": 0.5, "firmness": 0.5, "race": {"asian": 0.25, "caucasian": 0.5, "african": 0.25}}


def srgb(hex_):
    """sRGB hex -> linear RGB, since glTF vertex colours and factors are linear."""
    c = np.array([int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)])
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ---- outfit ----
SKIN = srgb("#c99272")
SHORTS, SHORTS_STRIPE, WAISTBAND = srgb("#16304f"), srgb("#00b298"), srgb("#0b1626")
VEST, VEST_SIDE, VEST_ZIP = srgb("#c81d25"), srgb("#1b1d22"), srgb("#e8e8e8")
BOOT, BOOT_TRIM, BOOT_SOLE = srgb("#26282e"), srgb("#00b298"), srgb("#111214")
HELMET, HELMET_TRIM = srgb("#eef0f2"), srgb("#1b1d22")
FRAME, LENS = srgb("#e6007e"), srgb("#ff7a1a")  # Lobster neon pink frame, orange mirror lens
EYE = srgb("#d8d4cf")

MATERIALS = {  # name: (roughness, metallic, double sided)
    "skin": (0.55, 0.0, False), "shorts": (0.82, 0.0, True), "vest": (0.72, 0.0, True),
    "boots": (0.6, 0.0, True), "helmet": (0.38, 0.0, True), "frame": (0.35, 0.0, True), "lens": (0.05, 0.85, True),
}


# ------------------------------------------------------------------ MakeHuman data
def load_obj(path):
    verts, faces, groups = [], [], []
    group = None
    for line in open(path):
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "):
            group = line.split(None, 1)[1].strip()
        elif line.startswith("f "):
            faces.append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
            groups.append(group)
    return np.array(verts), np.array(faces), np.array(groups)


def load_target(data, name):
    idx, off = [], []
    for line in gzip.open(data / "targets" / (name + ".target.gz")).read().decode().splitlines():
        p = line.split()
        if len(p) == 4 and not line.startswith("#"):
            idx.append(int(p[0]))
            off.append([float(x) for x in p[1:]])
    return np.array(idx, dtype=int), np.array(off)


def macro_components(macro, name, value):
    out = []
    for part in macro[name]["parts"]:
        lo, hi = part["lowest"], part["highest"]
        if lo < value < hi:
            t = (value - lo) / (hi - lo)
            if part["low"]:
                out.append((part["low"], round(1 - t, 4)))
            if part["high"]:
                out.append((part["high"], round(t, 4)))
    return out


def macro_targets(data, info, cutoff=0.01):
    """MPFB2's TargetService.calculate_target_stack_from_macro_info_dict, minus the female-only breast targets."""
    macro = json.load(open(data / "targets" / "macrodetails" / "macro.json"))["macrotargets"]
    c = {k: macro_components(macro, k, info[k]) for k in ("gender", "age", "muscle", "weight", "proportions", "height")}
    out = []
    for race, rw in info["race"].items():
        for a, aw in c["age"]:
            for g, gw in c["gender"]:
                if rw * gw * aw > cutoff:
                    out.append((f"macrodetails/{race}-{g}-{a}", rw * gw * aw))
    for g, gw in c["gender"]:
        for a, aw in c["age"]:
            for m, mw in c["muscle"]:
                for w, ww in c["weight"]:
                    base = gw * aw * mw * ww
                    if base > cutoff:
                        out.append((f"macrodetails/universal-{g}-{a}-{m}-{w}", base))
                    for h, hw in c["height"]:
                        if base * hw > cutoff:
                            out.append((f"macrodetails/height/{g}-{a}-{m}-{w}-{h}", base * hw))
                    for p, pw in c["proportions"]:
                        if base * pw > cutoff and a != "baby":
                            out.append((f"macrodetails/proportions/{g}-{a}-{m}-{w}-{p}", base * pw))
    return out


# ------------------------------------------------------------------ geometry helpers
def vertex_normals(P, tris):
    n = np.zeros_like(P)
    fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def quads_to_tris(q):
    return np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])


def adjacency(quads, n):
    nb = [set() for _ in range(n)]
    for f in quads:
        for i in range(4):
            a, b = f[i], f[(i + 1) % 4]
            nb[a].add(b)
            nb[b].add(a)
    return nb


def ring_depth(mask, nb, maxd=6):
    """For vertices inside mask: how many edge rings in from the region's border (border = 0)."""
    depth = np.full(len(mask), -1)
    frontier = [v for v in np.nonzero(mask)[0] if any(not mask[u] for u in nb[v])]
    for v in frontier:
        depth[v] = 0
    d = 0
    while frontier and d < maxd:
        d += 1
        nxt = []
        for v in frontier:
            for u in nb[v]:
                if mask[u] and depth[u] < 0:
                    depth[u] = d
                    nxt.append(u)
        frontier = nxt
    depth[mask & (depth < 0)] = maxd
    return depth


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def paint(base, colour, w):
    """Blend colour into base by weight w (0..1 per vertex): soft edges instead of quad-shaped stair-steps."""
    return base * (1 - w[:, None]) + colour * w[:, None]


# ------------------------------------------------------------------ build
def build(mpfb):
    data = pathlib.Path(mpfb) / "src" / "mpfb" / "data"
    V, quads, fgroup = load_obj(data / "3dobjs" / "base.obj")
    for name, w in macro_targets(data, BODY):
        idx, off = load_target(data, name)
        if len(idx):  # the all-average target is empty: it moves nothing
            V[idx] += w * off
    P = V * 0.1  # decimetres -> metres; base mesh is Y up, facing +Z, like glTF
    body_q = quads[fgroup == "body"]
    body_v = np.unique(body_q)
    P[:, 1] -= P[body_v, 1].min()  # soles on y = 0
    P[:, 0] -= P[body_v, 0].mean()

    # joints: centre of each helper cube, or the mean of listed vertices
    gverts = collections.defaultdict(set)
    for f, g in zip(quads, fgroup):
        gverts[g].update(f.tolist())

    def joint(spec):
        if spec["strategy"] == "CUBE":
            return P[sorted(gverts[spec["cube_name"]])].mean(0)
        if spec["strategy"] == "MEAN":
            return P[spec["vertex_indices"]].mean(0)
        return P[spec["vertex_index"]]

    rig = json.load(open(data / "rigs" / "standard" / "rig.game_engine.json"))
    order, seen = [], set()

    def visit(b):
        if b in seen:
            return
        if rig[b]["parent"]:
            visit(rig[b]["parent"])
        seen.add(b)
        order.append(b)

    for b in sorted(rig):
        visit(b)
    head = {b: joint(rig[b]["head"]) for b in order}
    bix = {b: i for i, b in enumerate(order)}

    # skin weights: per vertex, by bone
    wjson = json.load(open(data / "rigs" / "standard" / "weights.game_engine.json"))["weights"]
    W = np.zeros((len(P), len(order)), dtype=np.float32)
    for b, lst in wjson.items():
        for v, w in lst:
            W[v, bix[b]] += w
    s = W.sum(1)
    head_only = s < 1e-6
    W[head_only, bix["head"]] = 1.0  # eye helpers carry no weights: they ride on the head
    W /= W.sum(1, keepdims=True)

    def wsum(*names):
        return sum(W[:, bix[n]] for n in names)

    tris_all = quads_to_tris(body_q)
    N = vertex_normals(P, tris_all)
    nb = adjacency(body_q, len(P))

    y = P[:, 1]
    knee_y = head["calf_l"][1]
    ankle_y = head["foot_l"][1]
    waist_y = head["spine_01"][1] + 0.02
    neck_y = head["neck_01"][1]
    in_body = np.zeros(len(P), bool)
    in_body[body_v] = True

    # ---- regions, decided per vertex from bone weights and height ----
    hem_y = knee_y + 0.06
    shorts = in_body & (wsum("pelvis", "thigh_l", "thigh_r", "spine_01") > 0.5) & (y > hem_y) & (y < waist_y + 0.03)
    arm = wsum("upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r", "hand_l", "hand_r")
    torso = wsum("spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "pelvis")
    vest = in_body & (torso > 0.55) & (arm < 0.3) & (y > waist_y - 0.07) & (y < neck_y - 0.035) & (wsum("neck_01", "head") < 0.2)
    boots = in_body & (wsum("foot_l", "foot_r", "ball_l", "ball_r", "calf_l", "calf_r") > 0.5) & (y < ankle_y + 0.2)

    # skin hidden under clothing goes; keep a few rings inside each opening so no gap shows
    hidden = np.zeros(len(P), bool)
    for region, keep_rings in ((shorts, 3), (vest, 3), (boots, 2)):
        hidden |= region & (ring_depth(region, nb) >= keep_rings)
    skin_q = body_q[~hidden[body_q].all(1)]
    eye_q = quads[np.isin(fgroup, ["helper-l-eye", "helper-r-eye"])]

    parts = {}  # material -> (positions, normals, colours, weights, triangles)

    def add_part(mat, pos, nrm, col, w, tris):
        if mat in parts:
            p0, n0, c0, w0, t0 = parts[mat]
            parts[mat] = (np.vstack([p0, pos]), np.vstack([n0, nrm]), np.vstack([c0, col]), np.vstack([w0, w]),
                          np.vstack([t0, tris + len(p0)]))
        else:
            parts[mat] = (pos, nrm, col, w, tris)

    def submesh(quads_sel, pos=None, col=None):
        """Re-index a set of base-mesh quads into a compact mesh (positions/normals/weights from the base mesh)."""
        used = np.unique(quads_sel)
        remap = -np.ones(len(P), dtype=int)
        remap[used] = np.arange(len(used))
        tris = quads_to_tris(remap[quads_sel])
        pp = (P if pos is None else pos)[used]
        return used, pp, tris

    # body skin (and eyeballs behind the glasses)
    used, pp, tris = submesh(skin_q)
    add_part("skin", pp, N[used], np.tile(SKIN, (len(used), 1)), W[used], tris)
    used, pp, tris = submesh(eye_q)
    add_part("skin", pp, vertex_normals(pp, tris), np.tile(EYE, (len(used), 1)), W[used], tris)

    # ---- clothing shells: the body surface pushed out along its normals, smoothed, with a thick rim ----
    def shell(region, thickness, colour_fn, mat, smooth_iters):
        q = body_q[region[body_q].all(1)]
        used = np.unique(q)
        remap = -np.ones(len(P), dtype=int)
        remap[used] = np.arange(len(used))
        lq = remap[q]
        base, n0 = P[used], N[used]
        t = thickness(base, n0)
        pos = base + n0 * t[:, None]
        # edges: interior ones are shared by two quads, the opening's edge loops by one
        edges, directed = collections.Counter(), {}
        for f in lq:
            for i in range(4):
                a, b = f[i], f[(i + 1) % 4]
                edges[(min(a, b), max(a, b))] += 1
                directed[(min(a, b), max(a, b))] = (a, b)  # as the (only) face on an open edge winds it
        E = np.array(list(edges))
        loop = collections.defaultdict(list)
        for (a, b), c in edges.items():
            if c == 1:
                loop[a].append(b)
                loop[b].append(a)
        border = np.zeros(len(used), bool)
        border[list(loop)] = True
        # 1) iron each opening's edge loop into a smooth curve (selecting whole quads leaves stair-steps)
        for _ in range(30):
            new = pos.copy()
            for v, r in loop.items():
                if len(r) == 2:
                    new[v] = 0.5 * pos[v] + 0.25 * (pos[r[0]] + pos[r[1]])
            pos = new
        # 2) Taubin smoothing of the inside (shrink, then un-shrink) so fabric skims over muscle and toes
        both = np.vstack([E, E[:, ::-1]])
        deg = np.bincount(both[:, 0], minlength=len(used))[:, None]
        for _ in range(smooth_iters):
            for lam in (0.5, -0.53):
                avg = np.zeros_like(pos)
                np.add.at(avg, both[:, 0], pos[both[:, 1]])
                step = lam * (avg / np.maximum(deg, 1) - pos)
                step[border] = 0
                pos = pos + step
        # 3) nowhere closer to the skin than most of the requested thickness, so nothing pokes through
        d = ((pos - base) * n0).sum(1)
        pos += n0 * np.maximum(0, 0.85 * t - d)[:, None]
        tris = quads_to_tris(lq)
        nrm = vertex_normals(pos, tris)
        col = colour_fn(base, n0)
        # rim: fold each opening back toward the skin so the fabric shows its thickness. The rim gets its own
        # vertices facing out of the opening, so it shades as one smooth band
        rv = sorted(loop)
        nbr = collections.defaultdict(list)
        for a, b in E:
            nbr[a].append(b)
            nbr[b].append(a)
        out_dir = np.array([pos[v] - pos[[u for u in nbr[v] if not border[u]] or nbr[v]].mean(0) for v in rv])
        out_dir -= n0[rv] * (out_dir * n0[rv]).sum(1, keepdims=True)
        out_dir /= np.maximum(np.linalg.norm(out_dir, axis=1, keepdims=True), 1e-9)
        omap = {v: len(pos) + i for i, v in enumerate(rv)}
        imap = {v: len(pos) + len(rv) + i for i, v in enumerate(rv)}
        inner = pos[rv] - n0[rv] * (t[rv] * 0.8)[:, None]
        rim = []
        for key, c in edges.items():
            if c == 1:
                a, b = directed[key]  # walk the edge against its face's winding so the rim faces the same way
                rim += [[omap[b], omap[a], imap[a]], [omap[b], imap[a], imap[b]]]
        pos = np.vstack([pos, pos[rv], inner])
        nrm = np.vstack([nrm, out_dir, out_dir])
        col = np.vstack([col, col[rv] * 0.75, col[rv] * 0.6])
        if rim:
            tris = np.vstack([tris, np.array(rim, dtype=int)])
        add_part(mat, pos, nrm, col, np.vstack([W[used], W[used[rv]], W[used[rv]]]), tris)

    def shorts_thickness(p, n):
        flare = smoothstep(hem_y + 0.14, hem_y, p[:, 1])  # board shorts hang loose toward the hem
        return 0.011 + 0.028 * flare

    def shorts_colour(p, n):
        c = np.tile(SHORTS, (len(p), 1))
        side = smoothstep(0.72, 0.86, n[:, 0] * np.sign(p[:, 0])) * smoothstep(waist_y - 0.05, waist_y - 0.08, p[:, 1])
        c = paint(c, SHORTS_STRIPE, side)  # a panel down the outer thigh
        return paint(c, WAISTBAND, smoothstep(waist_y - 0.045, waist_y - 0.03, p[:, 1]))

    def vest_thickness(p, n):
        return np.full(len(p), 0.024)

    def vest_colour(p, n):
        c = paint(np.tile(VEST, (len(p), 1)), VEST_SIDE, smoothstep(0.62, 0.78, np.abs(n[:, 0])))
        band = smoothstep(waist_y + 0.09, waist_y + 0.10, p[:, 1]) * smoothstep(waist_y + 0.14, waist_y + 0.13, p[:, 1])
        c = paint(c, VEST_SIDE, band)  # a strap round the belly
        return paint(c, VEST_ZIP, smoothstep(0.011, 0.006, np.abs(p[:, 0])) * (p[:, 2] > 0))

    def boot_thickness(p, n):
        return 0.022 + 0.008 * (p[:, 1] < 0.03)

    def boot_colour(p, n):
        c = paint(np.tile(BOOT, (len(p), 1)), BOOT_TRIM, smoothstep(ankle_y + 0.15, ankle_y + 0.17, p[:, 1]))
        return paint(c, BOOT_SOLE, smoothstep(0.024, 0.014, p[:, 1]))

    shell(shorts, shorts_thickness, shorts_colour, "shorts", 6)
    shell(vest, vest_thickness, vest_colour, "vest", 10)
    shell(boots, boot_thickness, boot_colour, "boots", 25)

    # ---- helmet: the scalp pushed out and smoothed into a shell, rim above the brow, lower at the back ----
    leye = P[sorted(gverts["joint-l-eye"])].mean(0)
    reye = P[sorted(gverts["joint-r-eye"])].mean(0)
    eye_c = (leye + reye) / 2
    headw = W[:, bix["head"]]
    back = smoothstep(eye_c[2], eye_c[2] - 0.16, P[:, 2])  # 0 at the eyes, 1 at the back of the skull
    scalp = in_body & (headw > 0.9) & (y > eye_c[1] + 0.045 - 0.075 * back)
    shell(scalp, lambda p, n: np.full(len(p), 0.03), lambda p, n: paint(
        np.tile(HELMET, (len(p), 1)), HELMET_TRIM, smoothstep(0.018, 0.010, np.abs(p[:, 0]))), "helmet", 40)

    # ---- sunglasses, Lobster style: a slim mirrored wraparound lens with a notch over the nose, a pink brow bar
    #      along its top edge, and pink arms back to the ears. The lens wraps round to the temples but never closer to
    #      the face than LENS_GAP, and the arms trace the side of the head, so nothing ends up buried in the skin ----
    face = P[body_v][headw[body_v] > 0.5]

    def furthest(along, at, axis, lo, hi, sign=1):
        """Furthest skin point along an axis (z: out from the face, x: out from the side of the head), sampled in a
        thin slice through `at` on the other horizontal axis and between heights lo..hi. None if the slice is empty."""
        other = 0 if axis == 2 else 2
        sel = face[(np.abs(face[:, other] - at) < 0.006) & (face[:, 1] > lo) & (face[:, 1] < hi)]
        return None if len(sel) == 0 else (sign * sel[:, axis]).max() * sign

    LENS_GAP, ARM_GAP = 0.01, 0.003
    span = np.linalg.norm(leye - reye)
    half = span / 2 + 0.042
    lpos, ltris, fpos, ftris, cols = [], [], [], [], 17
    for i in range(cols):
        t = -1 + 2 * i / (cols - 1)
        x, z = t * half, eye_c[2] + 0.036 - 0.07 * t * t  # wraps back toward the temples
        skin = furthest(2, x, 2, eye_c[1] - 0.025, eye_c[1] + 0.02)
        if skin is not None:
            z = max(z, skin + LENS_GAP)
        top = eye_c[1] + 0.017 - 0.004 * t * t - 0.005 * np.exp(-(t / 0.1) ** 2)
        bot = eye_c[1] - 0.02 + 0.019 * np.exp(-(t / 0.13) ** 2) + 0.006 * t ** 4  # two lenses joined by a bridge
        lpos += [[x, bot, z], [x, top, z]]
        fpos += [[x, top - 0.003, z + 0.002], [x, top + 0.005, z + 0.002]]
    for i in range(cols - 1):
        a = 2 * i
        ltris += [[a, a + 2, a + 1], [a + 1, a + 2, a + 3]]
        ftris += [[a, a + 2, a + 1], [a + 1, a + 2, a + 3]]
    y0 = eye_c[1] + 0.011
    for side in (-1, 1):  # arms: a ribbon from the end of the lens back past the ear, just off the side of the head
        e = np.array(lpos[0 if side < 0 else 2 * cols - 2])
        k = len(fpos)
        x = e[0]
        for j, z in enumerate(np.linspace(e[2], e[2] - 0.1, 8)):
            skin = furthest(0, z, 0, y0 - 0.012, y0 + 0.02, side)
            if skin is not None:
                x = side * max(side * x, side * skin + ARM_GAP)  # only ever outward, so the arm stays straight-ish
            fpos += [[x, y0, z], [x, y0 + 0.008, z]]
            if j:
                a = k + 2 * (j - 1)
                ftris += [[a, a + 2, a + 1], [a + 1, a + 2, a + 3]]
    for name, pos, tris, colour in (("lens", lpos, ltris, LENS), ("frame", fpos, ftris, FRAME)):
        pos, tris = np.array(pos), np.array(tris)
        w = np.zeros((len(pos), len(order)), dtype=np.float32)
        w[:, bix["head"]] = 1
        add_part(name, pos, vertex_normals(pos, tris), np.tile(colour, (len(pos), 1)), w, tris)

    # numbers the game's pose code uses to put the soles on the board
    fl = in_body & (wsum("foot_l", "ball_l") > 0.5)
    fwd = P[fl, 2] - head["foot_l"][2]
    extras = {"ankleHeight": float(head["foot_l"][1]), "toeReach": float(fwd.max()), "heelReach": float(-fwd.min()),
              "height": float(P[body_v, 1].max()), "source": "MakeHuman base mesh (CC0) via MPFB2, built by tools/build_rider.py"}
    return order, rig, head, parts, extras


# ------------------------------------------------------------------ glTF writer
def write_glb(path, order, rig, head, parts, extras):
    buf = bytearray()
    views, accessors = [], []

    def add(arr, ctype, typ, target=None, norm=False, minmax=False):
        while len(buf) % 4:
            buf.append(0)
        off = len(buf)
        raw = arr.tobytes()
        buf.extend(raw)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
        if target:
            v["target"] = target
        views.append(v)
        a = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        if norm:
            a["normalized"] = True
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        accessors.append(a)
        return len(accessors) - 1

    nodes = [{"name": "Rider", "children": [], "extras": extras}]
    jnode = {}
    for b in order:
        parent = rig[b]["parent"]
        t = head[b] - (head[parent] if parent else 0)
        jnode[b] = len(nodes)
        nodes.append({"name": b, "translation": [float(x) for x in t]})
        if parent:
            nodes[jnode[parent]].setdefault("children", []).append(jnode[b])
        else:
            nodes[0]["children"].append(jnode[b])
    ibm = np.zeros((len(order), 16), dtype=np.float32)
    for i, b in enumerate(order):
        m = np.eye(4, dtype=np.float32)
        m[:3, 3] = -head[b]
        ibm[i] = m.T.reshape(-1)  # column-major
    skin = {"joints": [jnode[b] for b in order], "skeleton": jnode[order[0]],
            "inverseBindMatrices": add(ibm, 5126, "MAT4")}

    materials, meshes = [], []
    for mat, (pos, nrm, col, w, tris) in parts.items():
        rough, metal, double = MATERIALS[mat]
        materials.append({"name": mat, "doubleSided": double,
                          "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "roughnessFactor": rough, "metallicFactor": metal}})
        # four strongest bones per vertex, as bytes summing to exactly 255
        top = np.argsort(-w, axis=1)[:, :4]
        tw = np.take_along_axis(w, top, 1)
        tw = tw / tw.sum(1, keepdims=True)
        q = np.floor(tw * 255).astype(np.int32)
        q[:, 0] += 255 - q.sum(1)
        prim = {"attributes": {
            "POSITION": add(pos.astype(np.float32), 5126, "VEC3", 34962, minmax=True),
            "NORMAL": add(nrm.astype(np.float32), 5126, "VEC3", 34962),
            "COLOR_0": add(np.hstack([np.clip(np.round(col * 255), 0, 255), np.full((len(col), 1), 255)]).astype(np.uint8),
                           5121, "VEC4", 34962, norm=True),
            "JOINTS_0": add(top.astype(np.uint8), 5121, "VEC4", 34962),
            "WEIGHTS_0": add(q.astype(np.uint8), 5121, "VEC4", 34962, norm=True)},
            "indices": add(tris.astype(np.uint16).reshape(-1), 5123, "SCALAR", 34963),
            "material": len(materials) - 1}
        meshes.append({"name": mat, "primitives": [prim]})
        nodes.append({"name": mat, "mesh": len(meshes) - 1, "skin": 0})
        nodes[0]["children"].append(len(nodes) - 1)
    gltf = {"asset": {"version": "2.0", "generator": "wake-session tools/build_rider.py",
                      "copyright": "Body: MakeHuman base mesh and MPFB2 rig, CC0. Outfit: Thursday Yacht Club."},
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes, "meshes": meshes, "materials": materials,
            "skins": [skin], "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(buf) % 4:
        buf.append(0)
    glb = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf))
    glb += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    path.write_bytes(glb)
    return glb


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mpfb", required=True, help="path to a clone of github.com/makehumancommunity/mpfb2")
    ap.add_argument("--out", default=str(ROOT / "assets"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    order, rig, head, parts, extras = build(args.mpfb)
    glb = write_glb(out / "rider.glb", order, rig, head, parts, extras)
    (out / "rider.js").write_text("// Generated by tools/build_rider.py: the rider model (assets/rider.glb) as base64, so the game\n"
                                  "// can load it from disk without a web server. Body: MakeHuman base mesh and MPFB2 rig (CC0).\n"
                                  "window.WAKE_RIDER_GLB='" + base64.b64encode(glb).decode() + "';\n")
    tri = sum(len(p[4]) for p in parts.values())
    print(f"{len(order)} bones, {tri} triangles, {len(glb) / 1024:.0f} KB glb; height {extras['height']:.2f} m")
    for k, p in parts.items():
        print(f"  {k:<8} {len(p[0]):>6} verts {len(p[4]):>6} tris")
