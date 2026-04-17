"""Копирование изображений в папку проекта и относительные пути в JSON."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Iterable

_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
}

_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
_MILK_SUFFIXES = {".milk"}


def is_image_file(path: str | Path) -> bool:
    p = Path(path)
    return p.suffix.lower() in _IMAGE_SUFFIXES


def is_video_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _VIDEO_SUFFIXES


def is_milkdrop_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in _MILK_SUFFIXES


def project_dir_from_json(json_path: str | Path) -> Path:
    return Path(json_path).resolve().parent


def assets_subdir() -> str:
    return "assets"


def assets_dir(project_root: Path | str) -> Path:
    return Path(project_root) / assets_subdir()


def _to_posix_rel(p: Path) -> str:
    return p.as_posix()


def resolve_image_path_for_load(project_root: Path | str, stored: str) -> str:
    """Абсолютный путь для загрузки pixmap (старые проекты с абсолютным путём — как есть)."""
    s = (stored or "").strip()
    if not s:
        return ""
    p = Path(s)
    if p.is_absolute():
        return str(p)
    root = Path(project_root)
    return str((root / s).resolve())


def ensure_binary_asset_in_project(
    project_root: Path | str,
    src_path: str,
    *,
    allowed_suffixes: set[str],
    dest_prefix: str,
    default_ext: str,
) -> str:
    """Скопировать файл в assets/ с префиксом имени; вернуть относительный путь."""
    src = Path(src_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(str(src))
    root = Path(project_root).resolve()
    ad = assets_dir(root)
    ad.mkdir(parents=True, exist_ok=True)

    try:
        rel_try = src.relative_to(root)
        if rel_try.parts and rel_try.parts[0] == assets_subdir():
            return _to_posix_rel(rel_try)
    except ValueError:
        pass

    ext = src.suffix.lower() if src.suffix else default_ext
    if ext not in allowed_suffixes:
        ext = default_ext
    st = src.stat()
    digest = hashlib.sha256(f"{src}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:12]
    base = f"{dest_prefix}{digest}{ext}"
    dest = ad / base
    n = 0
    while dest.exists():
        n += 1
        dest = ad / f"{dest_prefix}{digest}_{n}{ext}"
    shutil.copy2(src, dest)
    return _to_posix_rel(dest.relative_to(root))


def ensure_asset_in_project(project_root: Path | str, src_path: str) -> str:
    """Скопировать файл в assets/ при необходимости; вернуть относительный путь для JSON."""
    src = Path(src_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(str(src))
    root = Path(project_root).resolve()
    ad = assets_dir(root)
    ad.mkdir(parents=True, exist_ok=True)

    try:
        rel_try = src.relative_to(root)
        if rel_try.parts and rel_try.parts[0] == assets_subdir():
            return _to_posix_rel(rel_try)
    except ValueError:
        pass

    st = src.stat()
    digest = hashlib.sha256(f"{src}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:12]
    ext = src.suffix.lower() if src.suffix else ".bin"
    if ext not in _IMAGE_SUFFIXES:
        ext = ".png"
    base = f"img_{digest}{ext}"
    dest = ad / base
    n = 0
    while dest.exists():
        n += 1
        dest = ad / f"img_{digest}_{n}{ext}"
    shutil.copy2(src, dest)
    return _to_posix_rel(dest.relative_to(root))


def normalize_image_elements_for_save(project_root: Path | str, elements: Iterable) -> None:
    """Перед записью JSON: все ImageElement с путями вне проекта — в assets/, путь в модели — относительный."""
    from elements.group_container import GroupContainerElement
    from elements.image_element import ImageElement

    root = Path(project_root).resolve()

    def walk(it: object) -> Iterable:
        if isinstance(it, ImageElement):
            yield it
        elif isinstance(it, GroupContainerElement):
            for ch in it.members():
                yield from walk(ch)

    for elem in elements:
        for img in walk(elem):
            raw = (img.image_path or "").strip()
            if not raw:
                continue
            try:
                new_rel = ensure_asset_in_project(root, raw)
                if new_rel != raw.replace("\\", "/"):
                    img.image_path = new_rel
                    img.load_image(resolve_image_path_for_load(root, new_rel))
            except Exception:
                continue


def normalize_video_milkdrop_for_save(project_root: Path | str, elements: Iterable) -> None:
    """Перед записью JSON: видео и .milk вне проекта — копировать в assets/."""
    from elements.group_container import GroupContainerElement
    from elements.video_element import VideoElement
    from elements.milkdrop_element import MilkdropElement

    root = Path(project_root).resolve()

    def walk(it: object) -> Iterable:
        if isinstance(it, (VideoElement, MilkdropElement)):
            yield it
        elif isinstance(it, GroupContainerElement):
            for ch in it.members():
                yield from walk(ch)

    for elem in elements:
        for node in walk(elem):
            if isinstance(node, VideoElement):
                raw = (node.video_path or "").strip()
                if not raw:
                    continue
                try:
                    new_rel = ensure_binary_asset_in_project(
                        root,
                        raw,
                        allowed_suffixes=_VIDEO_SUFFIXES,
                        dest_prefix="vid_",
                        default_ext=".mp4",
                    )
                    if new_rel != raw.replace("\\", "/"):
                        node.video_path = new_rel
                except Exception:
                    continue
            elif isinstance(node, MilkdropElement):
                raw = (node.preset_path or "").strip()
                if not raw:
                    continue
                try:
                    new_rel = ensure_binary_asset_in_project(
                        root,
                        raw,
                        allowed_suffixes=_MILK_SUFFIXES,
                        dest_prefix="milk_",
                        default_ext=".milk",
                    )
                    if new_rel != raw.replace("\\", "/"):
                        node.preset_path = new_rel
                except Exception:
                    continue
