from __future__ import annotations

from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from zypg.storage.files import homework_dir, relpath

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

_DUMMY = {"", "未标注", "未指定知识点", "none", "null"}


def _dummy_label(k: Any) -> bool:
    return str(k or "").strip().lower() in _DUMMY


def _wrap_label(text: str, width: int = 7) -> str:
    s = str(text or "").strip()
    if len(s) <= width:
        return s
    parts = [s[i : i + width] for i in range(0, min(len(s), width * 3), width)]
    return "\n".join(parts)


def figure_kp_radar(acc: dict[str, float]):
    items = [(str(k), float(v) * 100) for k, v in acc.items() if not _dummy_label(k) and v is not None]
    if len(items) < 3:
        return None
    labels = [_wrap_label(k) for k, _ in items]
    vals = [v for _, v in items]
    n = len(items)
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    vals_c = vals + vals[:1]
    ang_c = np.concatenate([ang, ang[:1]])
    fig, ax = plt.subplots(figsize=(7.2, 7.2), subplot_kw={"polar": True})
    ring = np.linspace(0, 2 * np.pi, 256)
    ax.plot(ring, np.full_like(ring, 60), color="#dc2626", linestyle="--", linewidth=2.2, label="六成线")
    ax.fill(ring, np.full_like(ring, 60), color="#fecaca", alpha=0.25)
    ax.plot(ang_c, vals_c, color="#4c1d95", linewidth=2)
    ax.fill(ang_c, vals_c, color="#7c3aed", alpha=0.22)
    colors = ["#dc2626" if v < 60 else "#16a34a" for v in vals]
    ax.scatter(ang, vals, c=colors, s=70, zorder=5, edgecolors="white", linewidths=1.2)
    ax.set_xticks(ang, labels, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "六成", "80", "100"])
    ax.set_title("知识点掌握（红点=低于六成，该先讲）", pad=16)
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), frameon=False)
    fig.tight_layout()
    return fig


def figure_kp_bars(acc: dict[str, float]):
    items = [(str(k), float(v) * 100) for k, v in acc.items() if not _dummy_label(k) and v is not None]
    if not items:
        return None
    items.sort(key=lambda x: x[1])
    labels = [k if len(k) <= 18 else k[:17] + "…" for k, _ in items]
    vals = [v for _, v in items]
    colors = ["#dc2626" if v < 60 else "#2563eb" for v in vals]
    fig, ax = plt.subplots(figsize=(8.2, max(3.6, 0.45 * len(items) + 1.6)))
    ax.barh(labels, vals, color=colors, height=0.62)
    ax.axvline(60, color="#dc2626", linestyle="--", linewidth=2.4, label="必讲线 60%")
    ax.set_xlim(0, 100)
    ax.set_xlabel("正确率 %")
    ax.set_title("本班各知识点正确率（按题次，已确认）")
    ax.legend(loc="lower right")
    for y, v in enumerate(vals):
        ax.text(min(v + 1.2, 88), y, f"{v:.0f}%", va="center", fontsize=9)
    fig.tight_layout()
    return fig


def render_charts(class_id: str, homework_id: str | None, pack: dict[str, Any]) -> dict[str, str]:
    """Only keep the radar PNG. Other charts are drawn in the 学情页, not as dumped images."""
    out = homework_dir(homework_id or class_id, "charts")
    paths: dict[str, str] = {}
    kps = {
        str(k): float(v)
        for k, v in (pack.get("knowledge_accuracy") or {}).items()
        if not _dummy_label(k) and v is not None
    }
    item_like = bool(kps) and all(str(k).startswith("第") and str(k).endswith("题") for k in kps)
    if kps and not item_like:
        fig = figure_kp_radar(kps)
        if fig is not None:
            p = out / "kp_radar.png"
            fig.savefig(p, dpi=140, bbox_inches="tight")
            plt.close(fig)
            paths["radar"] = relpath(p)
    return paths
