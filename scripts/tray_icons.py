"""程序生成托盘图标（多尺寸 .ico），避免外部二进制资源依赖。"""
from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = ASSETS / "tray.ico"

# 主色（与网页管理台蓝色主题呼应）
BLUE = (79, 140, 255, 255)
BLUE_DARK = (40, 90, 200, 255)
WHITE = (255, 255, 255, 255)
GREEN = (53, 192, 122, 255)


def _draw_icon(size: int, running: bool = False):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    # 圆角底
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size // 5, fill=BLUE)
    # 中心闪电/齿轮简化：画一个白色闪电
    cx = size / 2
    bolt = [
        (cx + size * 0.06, size * 0.22),
        (cx - size * 0.14, size * 0.54),
        (cx - size * 0.01, size * 0.54),
        (cx - size * 0.08, size * 0.80),
        (cx + size * 0.16, size * 0.44),
        (cx + size * 0.02, size * 0.44),
    ]
    d.polygon(bolt, fill=WHITE)
    # 运行中：右下角绿点
    if running:
        r = max(2, size // 6)
        cxy = (size - r - pad, size - r - pad)
        d.ellipse([cxy[0] - r, cxy[1] - r, cxy[0] + r, cxy[1] + r], fill=GREEN, outline=WHITE)
    return img


def ensure_icon() -> Path:
    """确保 assets/tray.ico 存在，返回路径。"""
    if ICON_PATH.exists():
        return ICON_PATH
    try:
        ASSETS.mkdir(parents=True, exist_ok=True)
        base = _draw_icon(64)
        # PIL 保存多尺寸 ico
        base.save(ICON_PATH, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
    except Exception:
        # 兜底：无 PIL 时由 tray.py 用 tkinter PhotoImage
        pass
    return ICON_PATH


if __name__ == "__main__":
    p = ensure_icon()
    print("icon:", p, "exists=", p.exists())
