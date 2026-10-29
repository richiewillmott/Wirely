"""The circuit itself: parts placed on the sheet and the wires between them. No Qt here.

Connections are worked out from geometry, just like on paper: a wire end that touches a pin, another wire's
end, or lands anywhere along another wire is connected to it. Two wires that merely cross are not.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from ..i18n import tr
from . import parts as P

FILE_VERSION = 1
FILE_EXT = ".wirely"

Point = tuple  # (x, y) integers in sheet units


def _id() -> str:
    return uuid.uuid4().hex[:8]


def snap(v: float, grid: int = P.GRID) -> int:
    return int(round(v / grid)) * grid


def transform(x, y, rot: int, flip: bool):
    """Local part coordinates -> rotated/flipped (still relative to the part centre)."""
    if flip:
        x = -x
    for _ in range(rot % 4):
        x, y = -y, x          # 90° clockwise on screen (y points down)
    return x, y


@dataclass
class Component:
    kind: str
    x: int = 0
    y: int = 0
    rot: int = 0
    flip: bool = False
    ref: str = ""
    props: dict = field(default_factory=dict)
    id: str = field(default_factory=_id)

    @property
    def part(self) -> P.PartDef:
        return P.get(self.kind)

    def pin_positions(self) -> dict:
        out = {}
        for name, px, py in self.part.pins:
            dx, dy = transform(px, py, self.rot, self.flip)
            out[name] = (int(self.x + dx), int(self.y + dy))
        return out

    def value(self, key):
        if key in self.props:
            return self.props[key]
        p = self.part.prop(key)
        return p.default if p else None

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "ref": self.ref, "x": self.x, "y": self.y,
                "rot": self.rot, "flip": self.flip, "props": dict(self.props)}

    @classmethod
    def from_dict(cls, d):
        c = cls(kind=d["kind"], x=int(d.get("x", 0)), y=int(d.get("y", 0)), rot=int(d.get("rot", 0)) % 4,
                flip=bool(d.get("flip", False)), ref=d.get("ref", ""), props=dict(d.get("props", {})),
                id=d.get("id") or _id())
        # fill in values added to the part since the file was saved
        for k, v in c.part.defaults().items():
            c.props.setdefault(k, v)
        return c


@dataclass
class Wire:
    points: list
    id: str = field(default_factory=_id)

    def __post_init__(self):
        self.points = [(int(x), int(y)) for x, y in self.points]

    @property
    def ends(self):
        return self.points[0], self.points[-1]

    def segments(self):
        return list(zip(self.points[:-1], self.points[1:]))

    def to_dict(self):
        return {"id": self.id, "points": [list(p) for p in self.points]}

    @classmethod
    def from_dict(cls, d):
        return cls(points=[tuple(p) for p in d["points"]], id=d.get("id") or _id())


@dataclass
class Net:
    name: str
    pins: list                        # [(component id, pin name), …]
    points: set
    wires: list                       # wire ids


def on_segment(p, a, b) -> bool:
    """Is point p on the straight segment a–b (ends included)?"""
    (x, y), (x1, y1), (x2, y2) = p, a, b
    if (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) != 0:
        return False
    return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)


# ------------------------------------------------------------------------------------- wire shape helpers
def tidy(points: list) -> list:
    """Remove repeated points and points in the middle of a straight run."""
    pts = []
    for p in points:
        p = (int(p[0]), int(p[1]))
        if not pts or pts[-1] != p:
            pts.append(p)
    changed = True
    while changed and len(pts) > 2:
        changed = False
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]):
                # straight through (or doubling back): b is not needed
                del pts[i]
                changed = True
                break
    return pts


def route(a: Point, b: Point, horizontal_first: bool = True) -> list:
    """Right-angled path from a to b with at most one bend."""
    if a[0] == b[0] or a[1] == b[1]:
        return [a, b]
    corner = (b[0], a[1]) if horizontal_first else (a[0], b[1])
    return [a, corner, b]


def drag_end(points: list, end: int, new: Point) -> list:
    """Move one end of a wire (end = 0 or -1) to `new`, keeping every segment horizontal or vertical."""
    pts = list(points)
    if end != 0:
        pts.reverse()
    old = pts[0]
    if len(pts) == 2:
        far = pts[1]
        horiz = old[1] == far[1] and old[0] != far[0]
        path = route(far, new, horizontal_first=horiz)
        pts = list(reversed(path))
    else:
        nxt = pts[1]
        if old[1] == nxt[1] and old[0] != nxt[0]:     # first segment horizontal: neighbour follows in y
            pts[1] = (nxt[0], new[1])
        elif old[0] == nxt[0]:                         # vertical: neighbour follows in x
            pts[1] = (new[0], nxt[1])
        else:                                          # (diagonal - shouldn't happen) add a bend
            pts.insert(1, (new[0], nxt[1]))
        pts[0] = new
    pts = tidy(pts)
    if end != 0:
        pts.reverse()
    return pts


def move_segment(points: list, i: int, dx: int, dy: int) -> list:
    """Slide segment i sideways (perpendicular to itself); the wire's ends stay where they are."""
    pts = list(points)
    a, b = pts[i], pts[i + 1]
    if a[1] == b[1]:
        dx = 0
    elif a[0] == b[0]:
        dy = 0
    na, nb = (a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)
    new = pts[:i + 1] + pts[i + 1:]
    new[i], new[i + 1] = na, nb
    # keep the ends fixed by adding a short link back to them
    if i == 0:
        new.insert(0, a)
    if i + 1 == len(pts) - 1:
        new.append(b)
    return tidy(new)


# ------------------------------------------------------------------------------------- the circuit
class Circuit:
    def __init__(self):
        self.components: dict[str, Component] = {}
        self.wires: dict[str, Wire] = {}
        self.title = ""

    # ---- editing
    def next_ref(self, prefix: str) -> str:
        used = set()
        for c in self.components.values():
            m = re.fullmatch(re.escape(prefix) + r"(\d+)", c.ref)
            if m:
                used.add(int(m.group(1)))
        n = 1
        while n in used:
            n += 1
        return f"{prefix}{n}"

    def add(self, kind: str, x=0, y=0, rot=0, flip=False, props=None, ref=None) -> Component:
        part = P.get(kind)
        values = part.defaults()
        values.update(props or {})
        c = Component(kind, snap(x), snap(y), rot % 4, flip, ref or self.next_ref(part.prefix), values)
        self.components[c.id] = c
        return c

    def add_wire(self, points) -> Wire | None:
        pts = tidy(points)
        if len(pts) < 2:
            return None
        w = Wire(pts)
        self.wires[w.id] = w
        return w

    def remove(self, item_id: str):
        self.components.pop(item_id, None)
        self.wires.pop(item_id, None)

    def clear(self):
        self.components.clear()
        self.wires.clear()

    def is_empty(self):
        return not self.components and not self.wires

    # ---- connectivity
    def _all_pins(self):
        for c in self.components.values():
            for name, pos in c.pin_positions().items():
                yield c, name, pos

    def nets(self) -> list[Net]:
        """Groups of pins that are joined together by wires (or by touching)."""
        parent = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        wires = list(self.wires.values())
        for w in wires:
            for a, b in w.segments():
                union(a, b)
        # every pin and every wire end joins any wire it lands on
        specials = [pos for _c, _n, pos in self._all_pins()] + [e for w in wires for e in w.ends]
        for s in specials:
            find(s)
            for w in wires:
                for a, b in w.segments():
                    if on_segment(s, a, b):
                        union(s, a)
                        break
        groups: dict = {}
        for c, name, pos in self._all_pins():
            groups.setdefault(find(pos), Net("", [], set(), []))
            groups[find(pos)].pins.append((c.id, name))
        for w in wires:
            r = find(w.points[0])
            groups.setdefault(r, Net("", [], set(), []))
            groups[r].wires.append(w.id)
        for pt in list(parent):
            r = find(pt)
            if r in groups:
                groups[r].points.add(pt)
        nets = list(groups.values())
        # stable, readable names: nets touching a 0 V symbol are "0"
        gnd = {c.id for c in self.components.values() if c.kind == "ground"}
        n = 1
        for net in sorted(nets, key=lambda nt: min(nt.points) if nt.points else (0, 0)):
            if any(cid in gnd for cid, _ in net.pins):
                net.name = "0"
            else:
                net.name = f"N{n}"
                n += 1
        return nets

    def net_of_pin(self, comp_id: str, pin: str) -> Net | None:
        for net in self.nets():
            if (comp_id, pin) in net.pins:
                return net
        return None

    def junctions(self) -> list[Point]:
        """Points where three or more connections meet (drawn as a dot)."""
        count: dict = {}
        wires = list(self.wires.values())
        for w in wires:
            for e in w.ends:
                count[e] = count.get(e, 0) + 1
        for _c, _n, pos in self._all_pins():
            count[pos] = count.get(pos, 0) + 1
        out = []
        for pt, n in count.items():
            # a wire passing straight through (or bending at) this point adds two connections
            for w in wires:
                pts = w.points
                if pt in pts[1:-1]:
                    n += 2
                elif pt not in (pts[0], pts[-1]) and any(on_segment(pt, a, b) for a, b in w.segments()):
                    n += 2
            if n >= 3 and any(pt in w.points or any(on_segment(pt, a, b) for a, b in w.segments())
                              for w in wires):
                out.append(pt)
        return sorted(out)

    def unconnected_pins(self) -> list:
        """(component id, pin name, position) for every pin nothing is attached to."""
        ends = {}
        for w in self.wires.values():
            for e in w.ends:
                ends[e] = ends.get(e, 0) + 1
        pins = list(self._all_pins())
        pin_count = {}
        for _c, _n, pos in pins:
            pin_count[pos] = pin_count.get(pos, 0) + 1
        out = []
        for c, name, pos in pins:
            if pin_count[pos] > 1 or ends.get(pos):
                continue
            if any(on_segment(pos, a, b) for w in self.wires.values() for a, b in w.segments()):
                continue
            out.append((c.id, name, pos))
        return out

    def wires_at(self, pos) -> list:
        """(wire, end index) for wire ends sitting exactly on pos."""
        out = []
        for w in self.wires.values():
            if w.points[0] == pos:
                out.append((w, 0))
            if w.points[-1] == pos and len(w.points) > 1:
                out.append((w, -1))
        return out

    # ---- bill of materials
    def bill_of_materials(self) -> list[dict]:
        from .units import fmt
        rows: dict = {}
        for c in sorted(self.components.values(), key=lambda c: _ref_key(c.ref)):
            if c.kind in ("ground", "note"):
                continue
            part = c.part
            desc = [part.tr_name]
            for p in part.props:
                if p.on_label:
                    v = c.value(p.key)
                    desc.append(fmt(v, p.unit) if p.kind == "number" else tr(str(v)))
            key = tuple(desc)
            rows.setdefault(key, {"description": " ".join(desc), "refs": [], "qty": 0})
            rows[key]["refs"].append(c.ref)
            rows[key]["qty"] += 1
        return list(rows.values())

    # ---- saving
    def to_dict(self) -> dict:
        return {"app": "Wirely", "version": FILE_VERSION, "title": self.title,
                "components": [c.to_dict() for c in self.components.values()],
                "wires": [w.to_dict() for w in self.wires.values()]}

    def load_dict(self, d: dict):
        self.clear()
        self.title = d.get("title", "")
        for cd in d.get("components", []):
            c = Component.from_dict(cd)
            self.components[c.id] = c
        for wd in d.get("wires", []):
            w = Wire.from_dict(wd)
            if len(w.points) >= 2:
                self.wires[w.id] = w
        return self

    @classmethod
    def from_dict(cls, d: dict) -> "Circuit":
        return cls().load_dict(d)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "Circuit":
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("app") not in ("Wirely", "Sparkbench"):        # Sparkbench was Wirely's working name
            raise ValueError(tr("This isn't a Wirely circuit file."))
        if int(d.get("version", 1)) > FILE_VERSION:
            raise ValueError(tr("This file was saved by a newer version of Wirely — please update."))
        return cls.from_dict(d)

    def bounds(self):
        """x0, y0, x1, y1 around everything (in sheet units), or None if empty."""
        xs, ys = [], []
        for c in self.components.values():
            bx, by, bw, bh = c.part.box
            for cx, cy in ((bx, by), (bx + bw, by + bh)):
                dx, dy = transform(cx, cy, c.rot, c.flip)
                xs.append(c.x + dx)
                ys.append(c.y + dy)
        for w in self.wires.values():
            for x, y in w.points:
                xs.append(x)
                ys.append(y)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


def _ref_key(ref: str):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", ref or "")
    return (m.group(1), int(m.group(2))) if m else (ref, 0)
