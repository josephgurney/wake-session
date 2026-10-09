"""Build the Thursday Yacht Club rider from the MakeHuman base body (CC0), with plain Python and numpy.

    git clone --depth 1 https://github.com/makehumancommunity/mpfb2 ../mpfb2
    python tools/build_rider.py --mpfb ../mpfb2          # writes assets/rider.glb and assets/rider.js

What it does, in order:
  1. loads the MakeHuman base mesh and morphs it with MPFB2's body targets (gender, age, muscle, weight, height,
     proportions) using the same weighting MPFB2 itself uses;
  2. fits MPFB2's 53-bone "game engine" skeleton to the morphed body and takes its skin weights;
  3. grows board shorts, a gilet-style impact vest and boots out of the body surface (so they bend exactly like the
     skin), and deletes the skin they hide; grows a helmet out of the scalp, lays a chin strap on the skin, and adds
     a pair of Lobster sunglasses on the head bone;
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
VEST, VEST_SIDE, VEST_SEAM, VEST_TRIM = srgb("#c81d25"), srgb("#1b1d22"), srgb("#6e0e14"), srgb("#141518")
BOOT, BOOT_MESH, BOOT_TRIM, BOOT_SOLE = srgb("#151619"), srgb("#4a4e55"), srgb("#8fe31a"), srgb("#0e0f11")  # neon green, as the board
HELMET = srgb("#f6f6f4")
STRAP, BUCKLE = srgb("#141518"), srgb("#26282d")
FRAME, LENS = srgb("#e6007e"), srgb("#ff7a1a")  # Lobster neon pink frame, orange mirror lens
EYE = srgb("#d8d4cf")
# the vest's cut, in metres: the neckline (how far below the base of the neck at the back, how much lower at the front,
# the opening's half width and how far forward it reaches) and each armhole (centre this far below the shoulder joint,
# starting this far out from the middle, reaching up, down and fore-and-aft by these much)
VEST_FIT = {"neck_back": 0.012, "neck_drop": 0.05, "neck_w": 0.078, "neck_front": 0.11,
            "arm_drop": 0.075, "arm_x": 0.125, "arm_up": 0.125, "arm_down": 0.095, "arm_z": 0.08}

MATERIALS = {  # name: (roughness, metallic, double sided)
    "skin": (0.55, 0.0, False), "shorts": (0.82, 0.0, True), "vest": (0.72, 0.0, True),
    "boots": (0.6, 0.0, True), "helmet": (0.38, 0.0, True), "strap": (0.7, 0.0, True), "frame": (0.35, 0.0, True),
    "lens": (0.05, 0.85, True),
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


def subdivide(q, pos, nrm, w):
    """Split every quad into four at its edge midpoints and centre, averaging positions, normals and weights, so a
    garment has the resolution for seams and a smooth edge where the body mesh is coarse."""
    n, edges = len(pos), {}
    for f in q:
        for i in range(4):
            edges.setdefault((min(f[i], f[(i + 1) % 4]), max(f[i], f[(i + 1) % 4])), n + len(edges))
    E = np.array(list(edges), dtype=int).reshape(-1, 2)
    mid = lambda a, b: edges[(min(a, b), max(a, b))]
    out = []
    for i, (a, b, c, d) in enumerate(q):
        ab, bc, cd, da, ce = mid(a, b), mid(b, c), mid(c, d), mid(d, a), n + len(E) + i
        out += [[a, ab, ce, da], [ab, b, bc, ce], [ce, bc, c, cd], [da, ce, cd, d]]
    grow = lambda x: np.vstack([x, x[E].mean(1), x[q].mean(1)])
    nn = grow(nrm)
    return np.array(out), grow(pos), nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12), grow(w)


def largest_component(mask, quads):
    """Keep the biggest connected patch of the quads that lie wholly inside mask (drops stray islands)."""
    q = quads[mask[quads].all(1)]
    parent = {v: v for v in np.unique(q)}

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for f in q:
        for v in f[1:]:
            parent[find(v)] = find(f[0])
    roots = np.array([find(v) for v in parent])
    keep = np.array(list(parent))[roots == collections.Counter(roots.tolist()).most_common(1)[0][0]]
    out = np.zeros_like(mask)
    out[keep] = True
    return out


def box(centre, ax, ay, half):
    """A flat-shaded box centred on centre, its edges along the unit vectors ax, ay and their cross product, with the
    given half sizes along each."""
    A = [ax, ay, np.cross(ax, ay)]
    pos, nrm, tris = [], [], []
    for i in range(3):
        du, dv = A[(i + 1) % 3] * half[(i + 1) % 3], A[(i + 2) % 3] * half[(i + 2) % 3]
        for s in (1, -1):
            c, k = centre + A[i] * s * half[i], len(pos)
            pos += [c - du - dv, c + du - dv, c + du + dv, c - du + dv]
            nrm += [A[i] * s] * 4
            tris += [[k, k + 1, k + 2], [k, k + 2, k + 3]] if s > 0 else [[k, k + 2, k + 1], [k, k + 3, k + 2]]
    return np.array(pos), np.array(nrm), np.array(tris)


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
    # the impact vest is a gilet: broad straps over the shoulders, a round neck that dips at the front, a deep armhole
    # each side, and the hem over the top of the shorts. The neck opening is an ellipse round the neck, cut above a
    # neckline that drops toward the front; each armhole is an oval on the side of the chest round the arm's root
    nck = head["neck_01"]
    dz = P[:, 2] - nck[2]
    neck_line = nck[1] - VEST_FIT["neck_back"] - VEST_FIT["neck_drop"] * smoothstep(-0.02, 0.07, dz)
    in_neck = ((P[:, 0] / VEST_FIT["neck_w"]) ** 2 + (dz / np.where(dz > 0, VEST_FIT["neck_front"], 0.075)) ** 2 < 1) & (y > neck_line)
    sh = head["upperarm_l"]
    ay = y - (sh[1] - VEST_FIT["arm_drop"])
    in_arm = (np.abs(P[:, 0]) > VEST_FIT["arm_x"]) & (
        (ay / np.where(ay > 0, VEST_FIT["arm_up"], VEST_FIT["arm_down"])) ** 2 + ((P[:, 2] - sh[2]) / VEST_FIT["arm_z"]) ** 2 < 1)
    vest = largest_component(in_body & (y > waist_y - 0.07) & ~in_neck & ~in_arm & (arm < 0.45)
                             & (wsum("neck_01", "head") < 0.6) & (wsum("thigh_l", "thigh_r") < 0.3), body_q)
    boots = in_body & (wsum("foot_l", "foot_r", "ball_l", "ball_r", "calf_l", "calf_r") > 0.5) & (y < ankle_y + 0.2)

    # skin hidden under clothing goes; keep a few rings inside each opening so no gap shows
    hidden = np.zeros(len(P), bool)
    for region, keep_rings in ((shorts, 3), (vest, 3), (boots, 2)):
        hidden |= region & (ring_depth(region, nb) >= keep_rings)
    skin_q = body_q[~hidden[body_q].all(1)]
    eye_q = quads[np.isin(fgroup, ["helper-l-eye", "helper-r-eye"])]

    parts = {}  # material -> [positions, normals, colours, weights, triangles, shell offsets or None]

    def add_part(mat, pos, nrm, col, w, tris, off=None):
        if mat in parts:
            p0, n0, c0, w0, t0, o0 = parts[mat]
            if o0 is not None or off is not None:
                o0 = np.vstack([np.zeros_like(p0) if o0 is None else o0, np.zeros_like(pos) if off is None else off])
            parts[mat] = [np.vstack([p0, pos]), np.vstack([n0, nrm]), np.vstack([c0, col]), np.vstack([w0, w]),
                          np.vstack([t0, tris + len(p0)]), o0]
        else:
            parts[mat] = [pos, nrm, col, w, tris, off]

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
    def shell(region, thickness, colour_fn, mat, smooth_iters, subdiv=0, detail=None, rim_colour=None, stiff=0, last=0):
        """colour_fn(skin position, skin normal, garment position) colours each vertex. subdiv splits each quad that
        many times first. last builds the shell over a copy of the body smoothed that many times, like a boot over its
        last, so the toes soften into a toe box. stiff shrink-wraps it that many times (plain smoothing, held off the
        skin), so it bridges the hollows like stiff foam instead of showing the muscles under it. detail(base, normal)
        gives how far to press each vertex back in after smoothing (seams, quilting). rim_colour, if given, colours the
        folded edge of every opening."""
        q = body_q[region[body_q].all(1)]
        used = np.unique(q)
        remap = -np.ones(len(P), dtype=int)
        remap[used] = np.arange(len(used))
        lq = remap[q]
        base, n0, wts = P[used], N[used], W[used]
        for _ in range(subdiv):
            lq, base, n0, wts = subdivide(lq, base, n0, wts)
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
        border = np.zeros(len(base), bool)
        border[list(loop)] = True
        both = np.vstack([E, E[:, ::-1]])
        deg = np.bincount(both[:, 0], minlength=len(base))[:, None]
        for _ in range(last):
            avg = np.zeros_like(base)
            np.add.at(avg, both[:, 0], base[both[:, 1]])
            step = 0.5 * (avg / np.maximum(deg, 1) - base)
            step[border] = 0
            base = base + step
        if last:
            n0 = vertex_normals(base, quads_to_tris(lq))
        t = thickness(base, n0)
        pos = base + n0 * t[:, None]
        # 1) iron each opening's edge loop into a smooth curve (selecting whole quads leaves stair-steps)
        for _ in range(30 * 4 ** subdiv):
            new = pos.copy()
            for v, r in loop.items():
                if len(r) == 2:
                    new[v] = 0.5 * pos[v] + 0.25 * (pos[r[0]] + pos[r[1]])
            pos = new
        # 2) Taubin smoothing of the inside (shrink, then un-shrink) so fabric skims over muscle and toes
        for _ in range(smooth_iters):
            for lam in (0.5, -0.53):
                avg = np.zeros_like(pos)
                np.add.at(avg, both[:, 0], pos[both[:, 1]])
                step = lam * (avg / np.maximum(deg, 1) - pos)
                step[border] = 0
                pos = pos + step
        # 3) shrink-wrap: smooth without un-shrinking, but never closer to the skin than the thickness
        for _ in range(stiff):
            avg = np.zeros_like(pos)
            np.add.at(avg, both[:, 0], pos[both[:, 1]])
            step = 0.5 * (avg / np.maximum(deg, 1) - pos)
            step[border] = 0
            pos = pos + step
            pos += n0 * np.maximum(0, t - ((pos - base) * n0).sum(1))[:, None]
        # 4) nowhere closer to the skin than most of the requested thickness, so nothing pokes through
        d = ((pos - base) * n0).sum(1)
        pos += n0 * np.maximum(0, 0.85 * t - d)[:, None]
        if detail is not None:  # seams pressed in after the smoothing, so they stay crisp
            pos -= n0 * detail(base, n0)[:, None]
        tris = quads_to_tris(lq)
        nrm = vertex_normals(pos, tris)
        col = colour_fn(base, n0, pos)
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
        at = {v: i for i, v in enumerate(rv)}
        for _ in range(4 * 2 ** subdiv):  # even them out along the edge, so the band doesn't shade in streaks
            out_dir = np.array([0.5 * out_dir[i] + 0.25 * out_dir[[at[u] for u in loop[v]]].sum(0) * 2 / max(len(loop[v]), 1)
                                for i, v in enumerate(rv)])
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
        rc = (col[rv] * 0.75, col[rv] * 0.6) if rim_colour is None else (np.tile(rim_colour, (len(rv), 1)),) * 2
        col = np.vstack([col, *rc])
        if rim:
            tris = np.vstack([tris, np.array(rim, dtype=int)])
        # how far out from the skin each vertex stands, along the skin's normal, goes along as an extra attribute so
        # the crew can thin a garment down (only the outward part: the sideways moves that smoothed the edges stay)
        nn = np.vstack([n0, n0[rv], n0[rv]])
        out = nn * ((pos - np.vstack([base, base[rv], base[rv]])) * nn).sum(1, keepdims=True)
        add_part(mat, pos, nrm, col, np.vstack([wts, wts[rv], wts[rv]]), tris, out)

    def shorts_thickness(p, n):
        flare = smoothstep(hem_y + 0.14, hem_y, p[:, 1])  # board shorts hang loose toward the hem
        return 0.011 + 0.028 * flare

    def shorts_colour(p, n, q):
        c = np.tile(SHORTS, (len(p), 1))
        side = smoothstep(0.72, 0.86, n[:, 0] * np.sign(p[:, 0])) * smoothstep(waist_y - 0.05, waist_y - 0.08, p[:, 1])
        c = paint(c, SHORTS_STRIPE, side)  # a panel down the outer thigh
        return paint(c, WAISTBAND, smoothstep(waist_y - 0.045, waist_y - 0.03, p[:, 1]))

    # the vest: closed-cell foam panels in neoprene, thickest front and back, thinner down the sides and over the
    # shoulders. A smooth yoke over the chest and shoulders, then three quilted rows to the hem, side panels in a darker
    # colour, a zip up the front and dark binding round every edge
    chest_y, hem_v = head["spine_03"][1] + 0.11, waist_y - 0.07
    rows = chest_y - (chest_y - hem_v) * np.arange(3) / 3  # the seam above each row

    def vest_thickness(p, n):
        return 0.026 - 0.009 * smoothstep(0.55, 0.85, np.abs(n[:, 0])) - 0.01 * smoothstep(0.45, 0.85, n[:, 1])

    def vest_seams(p, n):
        """0..1 per vertex: how much each is on a stitched seam (the rows, the side panels' edges, the zip)."""
        row = np.max([np.exp(-((p[:, 1] - r) / 0.007) ** 2) for r in rows], axis=0) * (p[:, 1] < chest_y + 0.01)
        side = np.exp(-((np.abs(n[:, 0]) - 0.7) / 0.05) ** 2) * (p[:, 1] < chest_y + 0.06)
        zip_ = np.exp(-(p[:, 0] / 0.007) ** 2) * (n[:, 2] > 0.3)
        return np.max([row, side, 0.6 * zip_], axis=0)

    def vest_colour(p, n, q):
        c = paint(np.tile(VEST, (len(p), 1)), VEST_SIDE, smoothstep(0.66, 0.74, np.abs(n[:, 0])))
        c = paint(c, VEST_SEAM, 0.75 * vest_seams(p, n) * smoothstep(0.75, 0.6, np.abs(n[:, 0])))
        return paint(c, VEST_TRIM, smoothstep(0.012, 0.006, np.abs(p[:, 0])) * (n[:, 2] > 0.3))  # zip tape

    def boot_thickness(p, n):  # a thicker sole, and a roomier toe box
        return 0.022 + 0.008 * (p[:, 1] < 0.03) + 0.008 * smoothstep(0.05, 0.12, p[:, 2] - head["foot_l"][2])

    def boot_colour(p, n, q):
        """Black wake boots after the reference, laid out on the finished boot so the edges run clean: a grey mesh
        panel each side of the ankle, a grey tongue under black lace bars, a neon green liner showing round the cuff
        and a neon green edge round the sole."""
        ft = head["foot_l"]
        lx, fz, y_ = np.abs(q[:, 0]) - ft[0], q[:, 2] - ft[2], q[:, 1]  # out from the middle of the foot, forward of the ankle
        band = lambda v, a, b, e=0.005: smoothstep(a - e, a + e, v) * smoothstep(b + e, b - e, v)
        c = np.tile(BOOT, (len(p), 1))
        c = paint(c, BOOT_MESH, smoothstep(0.03, 0.04, np.abs(lx)) * band(y_, 0.035, ankle_y + 0.06) * band(fz, -0.03, 0.08))
        tongue = band(lx, -0.028, 0.028) * band(y_, ankle_y - 0.02, ankle_y + 0.14) * smoothstep(0.02, 0.04, fz)
        bars = smoothstep(0.55, 0.8, np.abs(np.sin((y_ - ankle_y) / 0.028 * np.pi)))
        c = paint(c, BOOT_MESH, tongue * (1 - bars))
        c = paint(c, BOOT_TRIM, smoothstep(ankle_y + 0.15, ankle_y + 0.16, y_))
        return paint(c, BOOT_TRIM, band(y_, -0.024, -0.008, 0.004))

    shell(shorts, shorts_thickness, shorts_colour, "shorts", 6)
    shell(vest, vest_thickness, vest_colour, "vest", 4, subdiv=1, stiff=60, detail=lambda p, n: 0.009 * vest_seams(p, n),
          rim_colour=VEST_TRIM)
    shell(boots, boot_thickness, boot_colour, "boots", 25, last=12, rim_colour=BOOT_TRIM)

    # ---- helmet: the scalp pushed out and smoothed into a shell, rim above the brow, lower at the back. Solid white ----
    leye = P[sorted(gverts["joint-l-eye"])].mean(0)
    reye = P[sorted(gverts["joint-r-eye"])].mean(0)
    eye_c = (leye + reye) / 2
    headw = W[:, bix["head"]]
    rim_y = lambda z: eye_c[1] + 0.045 - 0.075 * smoothstep(eye_c[2], eye_c[2] - 0.16, z)  # lower toward the back
    scalp = in_body & (headw > 0.9) & (y > rim_y(P[:, 2]))
    shell(scalp, lambda p, n: np.full(len(p), 0.03), lambda p, n, q: np.tile(HELMET, (len(p), 1)), "helmet", 40,
          rim_colour=HELMET * 0.86)

    # ---- chin strap: black webbing in a Y round each ear (one strap in front of it, one behind) meeting at a slider
    #      under the lobe, then down along the jaw to a side-release buckle under the chin. The straps start up under
    #      the shell, so they come out of the helmet's rim. Every point is laid on the skin and takes the skin's own
    #      weights there, so the strap moves with the jaw and neck instead of cutting through them ----
    near = in_body & (wsum("head", "neck_01") > 0.5) & (y > neck_y - 0.06)
    band = near & (headw > 0.5) & (y > eye_c[1] - 0.07) & (y < eye_c[1] + 0.02) & (P[:, 0] > 0)
    ear = P[band & (P[:, 0] > P[band, 0].max() - 0.012)].mean(0)  # the left ear: the widest point of the head there
    on_ear = (np.abs(P[:, 0]) > ear[0] - 0.022) & (np.abs(P[:, 1] - ear[1] + 0.003) < 0.038) & (np.abs(P[:, 2] - ear[2] + 0.008) < 0.04)
    hidx = np.nonzero(near & ~on_ear & (headw > 0.35))[0]  # the straps go round the ears, so they never settle onto one
    hp, hn = P[hidx], N[hidx]
    mid = hp[(np.abs(hp[:, 0]) < 0.006) & (hp[:, 2] > eye_c[2] - 0.04) & (headw[hidx] > 0.5)]
    chin = mid[mid[:, 1].argmin()]  # the underside of the chin
    STRAP_W, STRAP_T, STRAP_GAP = 0.017, 0.0022, 0.0025

    def spline(ctrl, n):
        """Catmull-Rom through the control points, n samples per span."""
        c = np.array(ctrl, float)
        c = np.vstack([2 * c[0] - c[1], c, 2 * c[-1] - c[-2]])
        out = []
        for i in range(1, len(c) - 2):
            p0, p1, p2, p3 = c[i - 1:i + 3]
            for t in np.linspace(0, 1, n, endpoint=False):
                out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
        return np.array(out + [c[-2]])

    def lay(pts):
        """Settle a strap's centre line onto the skin: any point under the local surface (fitted to its nearest skin
        vertices) comes up onto it, points above it stay where they are (a taut strap bridges the hollows), with a
        little smoothing between passes. Returns positions, surface normals and skin weights."""
        for it in range(10):
            out, nrm, wts = [], [], []
            for c in pts:
                d2 = ((hp - c) ** 2).sum(1)
                k = np.argsort(d2)[:14]
                wk = 1 / (np.sqrt(d2[k]) + 0.003)
                m = (hp[k] * wk[:, None]).sum(0) / wk.sum()
                nn = (hn[k] * wk[:, None]).sum(0)
                nn /= np.linalg.norm(nn)
                out.append(c + nn * max(0, STRAP_GAP - (c - m) @ nn))
                nrm.append(nn)
                wts.append((W[hidx[k]] * wk[:, None]).sum(0) / wk.sum())
            pts = np.array(out)
            if it < 9:
                pts[1:-1] = 0.5 * pts[1:-1] + 0.25 * (pts[:-2] + pts[2:])
        return pts, np.array(nrm), np.array(wts)

    def ribbon(pts, nrm, wts):
        """A flat strap along pts: STRAP_W wide across the skin, STRAP_T thick, each face shaded flat across."""
        tan = np.gradient(pts, axis=0)
        tan /= np.linalg.norm(tan, axis=1, keepdims=True)
        side = np.cross(nrm, tan)
        side /= np.linalg.norm(side, axis=1, keepdims=True)
        corner = lambda s, o: pts + side * (s * STRAP_W / 2) + nrm * (o * STRAP_T)
        pos, nr, tr, n = [], [], [], len(pts)
        for (a, b, fn) in (((-1, 1), (1, 1), nrm), ((1, 0), (-1, 0), -nrm), ((1, 1), (1, 0), side), ((-1, 0), (-1, 1), -side)):
            k = len(pos) * n
            pos.append(np.vstack([corner(*a), corner(*b)]))
            nr.append(np.vstack([fn, fn]))
            for i in range(n - 1):
                t1, t2 = [k + i, k + n + i, k + n + i + 1], [k + i, k + n + i + 1, k + i + 1]
                p = pos[-1]
                face = np.cross(p[n + i] - p[i], p[n + i + 1] - p[i])
                tr += [t1, t2] if face @ fn[i] > 0 else [t1[::-1], t2[::-1]]
        pos = np.vstack(pos)
        add_part("strap", pos, np.vstack(nr), np.tile(STRAP, (len(pos), 1)), np.vstack([wts] * 8), np.array(tr))

    def fitting(centre, along, out, half, wts):
        p, n_, t = box(centre, along, out, half)
        add_part("strap", p, n_, np.tile(BUCKLE, (len(p), 1)), np.tile(wts, (len(p), 1)), t)

    for s in (1, -1):
        m = np.array([s, 1, 1])
        J = np.array([ear[0] - 0.004, ear[1] - 0.05, ear[2] + 0.004]) * m  # the slider, just under the lobe
        zf, zr = ear[2] + 0.048, ear[2] - 0.045
        front = lay(spline([np.array([ear[0], rim_y(zf) + 0.016, zf]) * m, np.array([ear[0], ear[1] + 0.005, zf - 0.006]) * m, J], 8))
        rear = lay(spline([np.array([ear[0], rim_y(zr) + 0.016, zr]) * m, np.array([ear[0], ear[1] - 0.01, zr + 0.01]) * m, J], 8))
        jaw = lay(spline([J, np.array([0.035 * s, chin[1] + 0.004, chin[2] - 0.035]), np.array([0, chin[1], chin[2] - 0.03])], 10))
        for strap in (front, rear, jaw):
            ribbon(*strap)
        tj = jaw[0][2] - jaw[0][0]
        tj /= np.linalg.norm(tj)
        fitting(jaw[0][0] + jaw[1][0] * 0.003, tj, jaw[1][0], np.array([0.009, 0.0035, 0.011]), jaw[2][0])
        if s > 0:  # the buckle sits under the chin where the two jaw straps meet
            tb = jaw[0][-1] - jaw[0][-3]
            tb /= np.linalg.norm(tb)
            fitting(jaw[0][-1] + jaw[1][-1] * 0.004 - tb * 0.006, tb, jaw[1][-1], np.array([0.019, 0.005, 0.012]), jaw[2][-1])

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
              "soleDepth": float(-parts["boots"][0][:, 1].min()),  # how far the boots' soles stand below the feet
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
    for mat, (pos, nrm, col, w, tris, off) in parts.items():
        rough, metal, double = MATERIALS[mat]
        materials.append({"name": mat, "doubleSided": double,
                          "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "roughnessFactor": rough, "metallicFactor": metal}})
        # four strongest bones per vertex, as bytes summing to exactly 255
        top = np.argsort(-w, axis=1, kind="stable")[:, :4]
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
        if off is not None:  # a garment's offset from the skin (three.js reads it as the attribute _shell)
            prim["attributes"]["_SHELL"] = add(off.astype(np.float32), 5126, "VEC3", 34962)
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
