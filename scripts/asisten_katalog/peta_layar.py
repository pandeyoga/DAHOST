"""Peta kode layar (frontend) → alamat API yang dipanggil, menu (module id) dan portal.

Dipakai `buat_katalog.py`. Murni membaca berkas; tidak menjalankan apa pun dari frontend.
"""
from __future__ import annotations

import collections
import os
import re

SHARED_LIMIT = 25
IMP_RX = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\(\s*|export\s[^'"]*?from\s*)['"]([^'"]+)['"]""")
CONST_RX = re.compile(r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(`[^`]*`|'[^'\n]*'|"[^"\n]*")""")
STR_RX = re.compile(r"""`([^`]*)`|'([^'\n]*)'|"([^"\n]*)\"""")
ENVISH = re.compile(r"process\.env|BACKEND|^API$|^API_URL$|^API_BASE$|^BASE_URL$|^apiBase$|^BACKEND_URL$")
PORTAL_NAMA = {"management": "Manajemen", "sysadmin": "Sistem", "production": "Produksi", "cutting": "Cutting",
               "procurement": "Pengadaan", "warehouse": "Gudang", "accessories": "Aksesoris", "finance": "Keuangan",
               "hr": "SDM", "rnd": "R&D", "self": "Portal Saya", "maklon": "Maklon", "toko": "Marketing",
               "collaboration": "Kolaborasi", "sales": "Penjualan", "assets": "Aset"}


def _baca(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def _segs(p):
    return [x for x in p.split("/") if x != ""]


def cocok(be_path: str, fe: str) -> bool:
    """be_path '/api/x/{id}/y' vs string layar (boleh tanpa /api, boleh diawali {} atau berisi {})."""
    b, f = _segs(be_path), _segs(fe)
    if not f:
        return False
    if f[0] not in ("api", "{}"):
        f = ["api"] + f
    lead = False
    while f and f[0] == "{}":
        f, lead = f[1:], True
    if not f:
        return False
    if lead:
        if len([x for x in f if "{}" not in x]) < 2 or len(f) > len(b):
            return False
        b = b[len(b) - len(f):]
    if len(b) != len(f):
        return False
    for x, y in zip(b, f):
        if x.startswith("{") or y == "{}":
            continue
        if "{}" in y:
            pre, _, post = y.partition("{}")
            if not (x.startswith(pre) and x.endswith(post)):
                return False
            continue
        if x != y:
            return False
    return True


class PetaLayar:
    def __init__(self, root: str):
        self.src = os.path.join(root, "frontend", "src")
        erp = os.path.join(self.src, "components", "erp")
        files = []
        for dp, _dn, fn in os.walk(self.src):
            if "__tests__" in dp or "node_modules" in dp or os.sep + "_archive" in dp:
                continue
            for f in fn:
                if f.endswith((".js", ".jsx")) and ".test." not in f:
                    files.append(os.path.normpath(os.path.join(dp, f)))
        self.files = files
        fset = set(files)

        def resolve(base, spec):
            if spec.startswith("@/"):
                cand = os.path.join(self.src, spec[2:])
            elif spec.startswith("."):
                cand = os.path.join(os.path.dirname(base), spec)
            else:
                return None
            cand = os.path.normpath(cand)
            for c in (cand, cand + ".js", cand + ".jsx", os.path.join(cand, "index.js"),
                      os.path.join(cand, "index.jsx")):
                if c in fset:
                    return c
            return None

        self.graph, self.paths = {}, {}
        for f in files:
            s = _baca(f)
            self.graph[f] = {r for r in (resolve(f, m) for m in IMP_RX.findall(s)) if r}
            consts = {n: lit[1:-1] for n, lit in CONST_RX.findall(s)}
            ps = set()
            for a, b, c in STR_RX.findall(s):
                t = a or b or c
                if "/" not in t or len(t) > 300 or " " in t.strip():
                    continue
                if a or "${" in t:
                    t = self._expand(t, consts)
                p = self._norm(t)
                if p and len(p) > 2:
                    ps.add(p)
            self.paths[f] = ps

        reg_f = os.path.join(erp, "moduleRegistry.js")
        reg = _baca(reg_f)
        comp = {}
        for name, spec in re.findall(r"const\s+(\w+)\s*=\s*(?:lazyRetry|lazy|lazyWithRetry)\(\s*\(\)\s*=>\s*import\("
                                     r"\s*['\"]([^'\"]+)['\"]", reg):
            r = resolve(reg_f, spec)
            if r:
                comp[name] = r
        for name, spec in re.findall(r"import\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]", reg):
            r = resolve(reg_f, spec)
            if r:
                comp.setdefault(name, r)
        self.mod_file, redir = {}, {}
        for mid, rhs in re.findall(r"^\s*'([a-z0-9][a-z0-9-]*)'\s*:\s*([^\n]+)", reg, re.M):
            m = re.match(r"makeRedirect\(\s*'([a-z0-9-]+)'", rhs)
            if m:
                redir[mid] = m.group(1)
                continue
            m = re.match(r"(?:withProps|makeModuleWithTab)\(\s*(\w+)", rhs) or re.match(r"(\w+)", rhs)
            if m and m.group(1) in comp:
                self.mod_file[mid] = comp[m.group(1)]
        nav = _baca(os.path.join(erp, "portal-shell", "portalNav.js"))
        self.mod_portal = collections.defaultdict(set)
        self.mod_label = {}
        portal = None
        for line in nav.splitlines():
            m = re.match(r"^  ([a-z_]+): \{", line)
            if m:
                portal = m.group(1)
                continue
            for mid, lab in re.findall(r"id:\s*'([a-z0-9-]+)',\s*label:\s*'([^']+)'", line):
                if portal:
                    self.mod_portal[mid].add(portal)
                    self.mod_label.setdefault(mid, lab)
        for a, b in redir.items():
            for p in self.mod_portal.get(a, ()):
                self.mod_portal[b].add(p)
            if a in self.mod_label:
                self.mod_label.setdefault(b, self.mod_label[a])
        self.file_mods = collections.defaultdict(set)
        for mid, f in self.mod_file.items():
            for g in self._reach(f):
                self.file_mods[g].add(mid)

    @staticmethod
    def _expand(t, consts, depth=0):
        def rep(m):
            e = m.group(1).strip()
            if e in consts and depth < 4:
                v = consts[e]
                return "" if "process.env" in v else PetaLayar._expand(v, consts, depth + 1)
            return "" if ENVISH.search(e) else "{}"
        return re.sub(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", rep, t)

    @staticmethod
    def _norm(p):
        p = p.split("?")[0].split("#")[0].strip()
        i = p.find("/api/")
        if i >= 0:
            p = p[i:]
        elif p.startswith("http"):
            return None
        if not p.startswith("/") and not p.startswith("{}"):
            return None
        return re.sub(r"/+", "/", p).rstrip("/") or None

    def _reach(self, start):
        seen, st = set(), [start]
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            st.extend(self.graph.get(x, ()))
        return seen

    def pemakai(self, be_path: str) -> dict:
        """{berkas: [...], menu: [(id, label)], portal: [nama]} — layar aktif yang memanggil alamat ini."""
        fe = [f for f, ps in self.paths.items() if any(cocok(be_path, x) for x in ps)]
        mods = set()
        for f in fe:
            ms = self.file_mods.get(f, set())
            if len(ms) <= SHARED_LIMIT:
                mods |= ms
        portals = set()
        for mid in mods:
            portals |= self.mod_portal.get(mid, set())
        menu = sorted(((m, self.mod_label.get(m, "")) for m in mods), key=lambda x: (not x[1], x[0]))
        return {"berkas": sorted(os.path.relpath(f, self.src).replace("\\", "/") for f in fe),
                "menu": menu, "portal": sorted(PORTAL_NAMA.get(p, p) for p in portals)}
