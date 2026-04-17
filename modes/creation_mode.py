"""
Режим создания визуализации.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF, QMimeData, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.paths import (
    documents_directory,
    qfile_dialog_options_stable,
    qfile_dialog_parent_for_modal,
)
from ui.toast import show_toast
from app.project_assets import (
    is_image_file,
    is_milkdrop_file,
    is_video_file,
    normalize_image_elements_for_save,
    normalize_video_milkdrop_for_save,
    resolve_image_path_for_load,
)
from config.app_settings import settings
from elements import (
    BaseVisualizationElement,
    GroupContainerElement,
    ImageElement,
    LineElement,
    MilkdropElement,
    OscilloscopeElement,
    TextElement,
    TrackNameElement,
    VideoElement,
    WaveElement,
)
from ui.canvas_view import InteractiveCanvasView
from widgets import ElementButton, PropertiesPanel, ResolutionBackground

logger = logging.getLogger(__name__)

_CLIPBOARD_MIME = "application/x-audioviz-elements+json"

_ELEMENT_CLASS_MAP = {
    "ImageElement": ImageElement,
    "WaveElement": WaveElement,
    "OscilloscopeElement": OscilloscopeElement,
    "TextElement": TextElement,
    "TrackNameElement": TrackNameElement,
    "LineElement": LineElement,
    "VideoElement": VideoElement,
    "MilkdropElement": MilkdropElement,
}


def _regenerate_element_tree_ids(root: BaseVisualizationElement) -> None:
    """Новые element_id для корня и всех потомков группы (копия/вставка)."""
    import uuid

    root.element_id = uuid.uuid4().hex
    if isinstance(root, GroupContainerElement):
        for c in root.members():
            _regenerate_element_tree_ids(c)


def _element_from_project_item(elem_data: Dict[str, Any], pp: Path) -> Optional[BaseVisualizationElement]:
    elem_type = elem_data.get("type")
    if str(elem_type or "") == "GroupContainerElement":
        return GroupContainerElement.from_dict_with_resolver(
            elem_data, lambda d: _element_from_project_item(d, pp)
        )
    cls = _ELEMENT_CLASS_MAP.get(str(elem_type or ""))
    if cls is None:
        return None
    try:
        element = cls.from_dict(elem_data)
    except Exception:
        return None
    if elem_type == "ImageElement":
        stored = str(elem_data.get("image_path", "") or "").strip()
        if stored:
            abs_p = resolve_image_path_for_load(pp, stored)
            if abs_p and os.path.isfile(abs_p):
                element.load_image(abs_p)
                if not Path(stored).is_absolute():
                    element.image_path = stored.replace("\\", "/")
    elif elem_type == "VideoElement":
        stored = str(elem_data.get("video_path", "") or "").strip()
        if stored and isinstance(element, VideoElement):
            abs_p = resolve_image_path_for_load(pp, stored)
            if abs_p and os.path.isfile(abs_p):
                element.video_path = stored.replace("\\", "/") if not Path(stored).is_absolute() else stored
    elif elem_type == "MilkdropElement" and isinstance(element, MilkdropElement):
        for key in ("preset_path", "textures_dir"):
            val = str(elem_data.get(key, "") or "").strip()
            if val and not Path(val).is_absolute():
                setattr(element, key, val.replace("\\", "/"))
    return element


def _image_pick_start_directory() -> str:
    """Только «Документы»: не проверяем каталог проекта (is_dir/сеть/OneDrive может надолго блокировать UI до IFileDialog)."""
    return documents_directory()


def _ensure_project_save_path_json(path: str) -> str:
    """Путь сохранения проекта: всегда расширение .json (если ввели без расширения или другое — приводим к .json)."""
    p = (path or "").strip()
    if not p:
        return p
    pl = Path(p)
    if pl.suffix.lower() == ".json":
        return p
    if pl.suffix == "":
        return f"{p}.json"
    return str(pl.with_suffix(".json"))


def _top_base_element_at_view(view: QGraphicsView, view_pt: QPoint) -> Optional[BaseVisualizationElement]:
    """Верхний визуальный элемент под точкой в координатах viewport (надёжнее, чем scene.itemAt + transform).

    Дети группы не выбираются сами — иначе первым в списке оказывается дочерний item и клик ломает логику."""
    try:
        for it in view.items(view_pt):
            if not isinstance(it, BaseVisualizationElement):
                continue
            el: BaseVisualizationElement = it
            while isinstance(el, BaseVisualizationElement):
                try:
                    if el.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                        return el
                except Exception:
                    return el
                par = el.parentItem()
                if isinstance(par, GroupContainerElement):
                    return par
                if isinstance(par, BaseVisualizationElement):
                    el = par
                    continue
                break
    except Exception:
        return None
    return None


def _properties_panel_width(parent_w: int) -> int:
    """Ширина правой панели свойств: 20–50% окна, по умолчанию 30%."""
    w = int(parent_w * 0.30)
    min_w = int(parent_w * 0.20)
    max_w = int(parent_w * 0.50)
    # Страховка от слишком маленьких окон; нижняя граница ×2 — дольше не «схлопывается» при ресайзе.
    min_w = max(440, min_w)
    max_w = max(min_w, max_w)
    return max(min_w, min(max_w, w))


class CreationMode(QWidget):
    """Режим создания визуализации"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.parent_window = parent
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(20, 20, 20))
        self.elements: List[BaseVisualizationElement] = []
        self.current_line_element: Optional[LineElement] = None
        self.is_drawing_line = False
        self._fit_pending = False
        # Разрешение экрана по умолчанию 16:9
        self.resolution_width = 1920
        self.resolution_height = 1080
        self.resolution_background: Optional[ResolutionBackground] = None
        self._project_json_path: Optional[str] = None
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._run_autosave)
        self._viz_fullscreen_active = False
        self._drop_guide_items: List[QGraphicsLineItem] = []
        self._drop_guide_origin: Optional[QPointF] = None
        self.setup_ui()

        self._history_move_timer = QTimer(self)
        self._history_move_timer.setSingleShot(True)
        self._history_move_timer.timeout.connect(self._history_commit_if_changed)
        self._history: List[Dict[str, Any]] = []
        self._history_index = 0
        self._history_applying = False
        BaseVisualizationElement.set_geometry_commit_notifier(self._on_element_moved_for_history_debounce)
        BaseVisualizationElement.set_position_ui_notifier(self._on_element_position_for_properties_panel)
        self._history_reset()

    def _do_fit_canvas(self):
        self._fit_pending = False
        try:
            if self.resolution_background:
                rect = self.resolution_background.sceneBoundingRect()
                if rect.width() > 1 and rect.height() > 1:
                    if getattr(self, "_viz_fullscreen_active", False):
                        self.view.fitInView(rect, Qt.AspectRatioMode.IgnoreAspectRatio)
                    else:
                        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_viz_fullscreen_active", False):
            QTimer.singleShot(0, self._do_fit_canvas)
            return
        if self._fit_pending:
            return
        self._fit_pending = True
        QTimer.singleShot(150, self._do_fit_canvas)

    def schedule_autosave(self) -> None:
        if not self._project_json_path:
            return
        self._autosave_timer.start(1800)

    def _run_autosave(self) -> None:
        if not self._project_json_path:
            return
        base = Path(self._project_json_path).parent
        dest = str(base / "autosave.json")
        try:
            self._write_project_json(dest, show_success_dialog=False)
        except Exception:
            logger.debug("autosave failed", exc_info=True)

    def _on_scene_changed_for_autosave(self, *_args) -> None:
        self.schedule_autosave()

    def _collect_project_data(self) -> Dict[str, Any]:
        elements_to_save = [elem for elem in self.elements if isinstance(elem, BaseVisualizationElement)]
        scene_rect = self.scene.sceneRect()
        return {
            "format_version": 3,
            "elements": [elem.to_dict() for elem in elements_to_save],
            "scene_width": scene_rect.width(),
            "scene_height": scene_rect.height(),
            "resolution_width": self.resolution_width,
            "resolution_height": self.resolution_height,
        }

    def _project_parent_for_paths(self) -> Path:
        if self._project_json_path:
            return Path(self._project_json_path).resolve().parent
        return Path.cwd()

    def _project_files_start_dir(self) -> str:
        """Стартовая папка для JSON без resolve() и без is_dir() — сеть/OneDrive не должны блокировать UI."""
        if not self._project_json_path:
            return documents_directory()
        try:
            parent = Path(self._project_json_path).expanduser().parent
            s = str(parent)
            if s not in ("", ".", os.sep):
                return s
        except OSError:
            pass
        return documents_directory()

    @staticmethod
    def _snapshots_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        try:
            return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        except Exception:
            return a == b

    def _history_reset(self) -> None:
        self._history_applying = True
        try:
            self._history = [copy.deepcopy(self._collect_project_data())]
            self._history_index = 0
        finally:
            self._history_applying = False

    def _history_commit_if_changed(self) -> None:
        if self._history_applying or not self._history:
            return
        snap = copy.deepcopy(self._collect_project_data())
        if self._snapshots_equal(self._history[self._history_index], snap):
            return
        self._history = self._history[: self._history_index + 1]
        self._history.append(snap)
        self._history_index = len(self._history) - 1
        while len(self._history) > 51 and self._history_index > 0:
            self._history.pop(0)
            self._history_index -= 1

    def _on_element_moved_for_history_debounce(self, _element: BaseVisualizationElement) -> None:
        if self._history_applying or self.is_drawing_line:
            return
        self._history_move_timer.start(400)

    def _on_element_position_for_properties_panel(self, element: BaseVisualizationElement) -> None:
        try:
            ce = getattr(self.properties_panel, "current_element", None)
            multi = getattr(self.properties_panel, "_current_elements", None) or []
            if ce is element or (multi and element in multi):
                self.properties_panel.refresh_position_fields_from_element(element)
        except Exception:
            pass

    def _apply_project_dict(self, data: Dict[str, Any], *, project_parent: Optional[Path] = None) -> None:
        """Пересобрать сцену из данных проекта (для загрузки и undo/redo)."""
        self._history_applying = True
        try:
            pp = project_parent if project_parent is not None else self._project_parent_for_paths()

            for elem in self.elements:
                self._detach_videos_in_tree(elem)
                self.scene.removeItem(elem)
            self.elements.clear()

            if "resolution_width" in data and "resolution_height" in data:
                self.resolution_width = data["resolution_width"]
                self.resolution_height = data["resolution_height"]
                self.width_spin.setValue(self.resolution_width)
                self.height_spin.setValue(self.resolution_height)
                if self.resolution_background:
                    self.resolution_background.set_size(self.resolution_width, self.resolution_height)

            for elem_data in data.get("elements", []):
                try:
                    element = _element_from_project_item(elem_data, pp)
                    if element is not None:
                        self.scene.addItem(element)
                        self.elements.append(element)
                except Exception as e:
                    logger.warning("Ошибка загрузки элемента %s: %s", elem_data.get("type"), e)
                    continue

            QTimer.singleShot(0, self._reattach_all_project_videos)

            self.scene.clearSelection()
            self.properties_panel.clear_properties()
            self._do_fit_canvas()
        finally:
            self._history_applying = False
        if self._project_json_path:
            self.schedule_autosave()

    def editor_undo(self) -> None:
        if self.is_drawing_line or self._history_index <= 0 or not self._history:
            return
        self._history_index -= 1
        self._apply_project_dict(self._history[self._history_index])

    def editor_redo(self) -> None:
        if self.is_drawing_line or not self._history or self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._apply_project_dict(self._history[self._history_index])

    def editor_delete_selected(self) -> None:
        if self.is_drawing_line:
            return
        items = [i for i in self.scene.selectedItems() if isinstance(i, BaseVisualizationElement)]
        if not items:
            return
        for it in items:
            self._element_delete(it, commit_history=False)
        self._history_commit_if_changed()

    def _selected_base_elements(self) -> List[BaseVisualizationElement]:
        return [i for i in self.scene.selectedItems() if isinstance(i, BaseVisualizationElement)]

    def _refresh_properties_for_selection(self) -> None:
        sel = self._selected_base_elements()
        if len(sel) == 1:
            self.properties_panel.show_properties(sel[0])
        elif len(sel) > 1:
            self.properties_panel.show_properties_multi(sel)
        else:
            self.properties_panel.clear_properties()

    def _reattach_video_in_tree(self, root: BaseVisualizationElement) -> None:
        if isinstance(root, VideoElement):
            self._start_video_from_saved_path(root)
        elif isinstance(root, GroupContainerElement):
            for ch in root.members():
                self._reattach_video_in_tree(ch)

    def _start_video_from_saved_path(self, v: VideoElement) -> None:
        raw = (getattr(v, "video_path", "") or "").strip()
        if not raw:
            try:
                v.detach_media()
            except Exception:
                pass
            v.update()
            return
        pp = self._project_parent_for_paths()
        abs_p = resolve_image_path_for_load(pp, raw)
        if abs_p and os.path.isfile(abs_p):
            v.open_video(abs_p, self)
        else:
            try:
                v.detach_media()
            except Exception:
                pass
            v.update()

    def _detach_videos_in_tree(self, root: BaseVisualizationElement) -> None:
        if isinstance(root, VideoElement):
            try:
                root.detach_media()
            except Exception:
                pass
        elif isinstance(root, GroupContainerElement):
            for ch in root.members():
                self._detach_videos_in_tree(ch)

    def _reattach_all_project_videos(self) -> None:
        for e in list(self.elements):
            self._reattach_video_in_tree(e)

    def editor_group_selected(self) -> None:
        sel = self._selected_base_elements()
        if len(sel) < 2:
            return
        if any(isinstance(x, LineElement) for x in sel):
            show_toast(self, tr("msg.group_no_line"), "warn", 3200)
            return
        if any(isinstance(x, GroupContainerElement) for x in sel):
            show_toast(self, tr("msg.group_nested"), "warn", 3200)
            return
        br = sel[0].sceneBoundingRect()
        for it in sel[1:]:
            br = br.united(it.sceneBoundingRect())
        gx, gy = float(br.left()), float(br.top())
        gw, gh = max(1.0, float(br.width())), max(1.0, float(br.height()))
        zmax = max(it.zValue() for it in sel)
        grp = GroupContainerElement(gx, gy, gw, gh)
        grp.setZValue(zmax)
        self.scene.addItem(grp)
        for ch in list(sel):
            scene_p = QPointF(ch.scenePos())
            ch.setParentItem(grp)
            ch.setPos(grp.mapFromScene(scene_p))
            ch.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            ch.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            if ch in self.elements:
                self.elements.remove(ch)
            if ch not in grp._members:
                grp._members.append(ch)
        grp._sync_rect_from_children()
        grp._design_pos = QPointF(float(grp.x()), float(grp.y()))
        self.elements.append(grp)
        self.scene.clearSelection()
        grp.setSelected(True)
        self.scene.update()
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def editor_ungroup_selected(self) -> None:
        sel = self._selected_base_elements()
        if len(sel) != 1 or not isinstance(sel[0], GroupContainerElement):
            return
        g = sel[0]
        kids = list(g.members())
        for ch in kids:
            scene_origin = ch.mapToScene(QPointF(0, 0))
            ch.setParentItem(None)
            ch.setPos(scene_origin)
            ch.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            ch.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self.elements.append(ch)
        if g in self.elements:
            self.elements.remove(g)
        self.scene.removeItem(g)
        self.scene.clearSelection()
        self.scene.update()
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def _register_saved_project_path(self, path: str) -> None:
        try:
            settings.add_recent_project(path)
        except Exception:
            pass

    def editor_select_all(self) -> None:
        if self.is_drawing_line:
            return
        if not self.elements:
            return
        self.scene.clearSelection()
        for e in self.elements:
            if isinstance(e, BaseVisualizationElement):
                e.setSelected(True)
        self.scene.update()

    def editor_duplicate_all_selected(self) -> None:
        if self.is_drawing_line:
            return
        items = self._selected_base_elements()
        if not items:
            return
        pp = self._project_parent_for_paths()
        new_items: List[BaseVisualizationElement] = []
        for el in items:
            data = el.to_dict()
            sp = el.scenePos()
            data["x"] = float(sp.x()) + 24.0
            data["y"] = float(sp.y()) + 24.0
            ne = _element_from_project_item(data, pp)
            if ne is None:
                continue
            _regenerate_element_tree_ids(ne)
            ne.setZValue(el.zValue())
            self.scene.addItem(ne)
            self.elements.append(ne)
            new_items.append(ne)
        self.scene.clearSelection()
        for ne in new_items:
            ne.setSelected(True)
        for ne in new_items:
            QTimer.singleShot(0, lambda el=ne: self._reattach_video_in_tree(el))
        self.scene.update()
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def editor_nudge_selected(self, dx: float, dy: float) -> None:
        if self.is_drawing_line:
            return
        items = self._selected_base_elements()
        if not items:
            return
        BaseVisualizationElement.set_position_snap_suppressed(True)
        try:
            for el in items:
                el.setPos(el.x() + dx, el.y() + dy)
                el.update()
        finally:
            BaseVisualizationElement.set_position_snap_suppressed(False)
        self.scene.update()
        self._history_commit_if_changed()

    def editor_fit_view_to_selection(self) -> None:
        items = self._selected_base_elements()
        if not items:
            return
        br = items[0].sceneBoundingRect()
        for it in items[1:]:
            br = br.united(it.sceneBoundingRect())
        if br.width() < 2 or br.height() < 2:
            return
        m = 24.0
        br = br.adjusted(-m, -m, m, m)
        self.view.fitInView(br, Qt.AspectRatioMode.KeepAspectRatio)

    def editor_reset_canvas_zoom(self) -> None:
        self.view.resetTransform()
        self._do_fit_canvas()

    def editor_layer_selected(self, delta: int) -> None:
        if self.is_drawing_line or delta == 0:
            return
        items = self._selected_base_elements()
        if not items:
            return
        for el in items:
            z = el.zValue() + float(delta)
            if z <= -999.0:
                z = -998.0
            el.setZValue(z)
        self.scene.update()
        self._history_commit_if_changed()

    def editor_copy_selected(self) -> None:
        items = self._selected_base_elements()
        if not items:
            return
        blob = {"format": "aviz_clip_v1", "elements": [e.to_dict() for e in items]}
        try:
            raw = json.dumps(blob, ensure_ascii=False)
        except Exception:
            return
        md = QMimeData()
        md.setData(_CLIPBOARD_MIME, raw.encode("utf-8"))
        md.setText(raw)
        QApplication.clipboard().setMimeData(md)

    def editor_paste_from_clipboard(self) -> None:
        if self.is_drawing_line:
            return
        md = QApplication.clipboard().mimeData()
        raw = None
        if md.hasFormat(_CLIPBOARD_MIME):
            try:
                raw = bytes(md.data(_CLIPBOARD_MIME)).decode("utf-8")
            except Exception:
                raw = None
        if raw is None and md.hasText():
            raw = md.text()
        if not raw:
            return
        try:
            blob = json.loads(raw)
        except Exception:
            return
        if not isinstance(blob, dict) or blob.get("format") != "aviz_clip_v1":
            return
        elems = blob.get("elements")
        if not isinstance(elems, list) or not elems:
            return
        pp = self._project_parent_for_paths()
        new_items: List[BaseVisualizationElement] = []
        for elem_data in elems:
            if not isinstance(elem_data, dict):
                continue
            el = _element_from_project_item(elem_data, pp)
            if el is None:
                continue
            _regenerate_element_tree_ids(el)
            el.setPos(el.x() + 24, el.y() + 24)
            self.scene.addItem(el)
            self.elements.append(el)
            new_items.append(el)
        if not new_items:
            return
        self.scene.clearSelection()
        for el in new_items:
            el.setSelected(True)
        for el in new_items:
            QTimer.singleShot(0, lambda e=el: self._reattach_video_in_tree(e))
        self.scene.update()
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def _align_selected(self, mode: str) -> None:
        items = self._selected_base_elements()
        if len(items) < 2:
            return
        brs = [it.sceneBoundingRect() for it in items]
        union = brs[0]
        for r in brs[1:]:
            union = union.united(r)
        BaseVisualizationElement.set_position_snap_suppressed(True)
        try:
            for it in items:
                sr = it.sceneBoundingRect()
                pos = it.pos()
                dx = 0.0
                dy = 0.0
                if mode == "left":
                    dx = union.left() - sr.left()
                elif mode == "right":
                    dx = union.right() - sr.right()
                elif mode == "top":
                    dy = union.top() - sr.top()
                elif mode == "bottom":
                    dy = union.bottom() - sr.bottom()
                elif mode == "hcenter":
                    dx = union.center().x() - sr.center().x()
                elif mode == "vcenter":
                    dy = union.center().y() - sr.center().y()
                else:
                    continue
                it.setPos(pos.x() + dx, pos.y() + dy)
                it.update()
        finally:
            BaseVisualizationElement.set_position_snap_suppressed(False)
        self.scene.update()
        self._history_commit_if_changed()

    def save_project_quick(self) -> None:
        if not self._project_json_path:
            self.save_project_as_dialog()
            return
        path = self._project_json_path
        try:
            self._write_project_json(path, show_success_dialog=True)
            self._register_saved_project_path(path)
            self.schedule_autosave()
        except Exception as e:
            import traceback

            detail = f"{e}\n{traceback.format_exc()}"
            show_toast(self, tr("msg.save_fail_detail", detail=detail)[:900], "err", 7000)

    def save_project_smart(self) -> None:
        """Сохранить в текущий файл или первый раз — через диалог."""
        if self._project_json_path:
            self.save_project_quick()
        else:
            self.save_project_as_dialog()

    def save_project_as_dialog(self) -> None:
        dlg_parent = self.parent_window if getattr(self, "parent_window", None) else self.window() or self
        try:
            dlg_parent.raise_()
            dlg_parent.activateWindow()
        except Exception:
            pass
        path, _ = QFileDialog.getSaveFileName(
            qfile_dialog_parent_for_modal(dlg_parent),
            tr("dialog.save_project"),
            self._project_files_start_dir(),
            tr("dialog.filter.json"),
            "",
            qfile_dialog_options_stable(),
        )
        if path:
            path = _ensure_project_save_path_json(path)
            try:
                self._project_json_path = path
                self._write_project_json(path, show_success_dialog=True)
                self._register_saved_project_path(path)
                self.schedule_autosave()
            except Exception as e:
                import traceback

                detail = f"{e}\n{traceback.format_exc()}"
                show_toast(self, tr("msg.save_fail_detail", detail=detail)[:900], "err", 7000)

    def show_recent_projects_menu(self) -> None:
        menu = QMenu(self)
        paths = settings.recent_projects()
        if not paths:
            na = QAction(tr("editor.recent_empty"), self)
            na.setEnabled(False)
            menu.addAction(na)
        else:
            for p in paths:
                if not p or len(p) > 500:
                    continue
                act = QAction(p, self)
                act.setToolTip(p)

                def _open(path: str = p) -> None:
                    if os.path.isfile(path):
                        self.load_project_from_path(path, show_success_dialog=True)
                    else:
                        show_toast(self, tr("msg.recent_missing", path=path), "warn", 5000)

                act.triggered.connect(_open)
                menu.addAction(act)
            menu.addSeparator()
            clr = QAction(tr("editor.recent_clear"), self)

            def _clear() -> None:
                settings.clear_recent_projects()
                show_toast(self, tr("editor.recent_cleared"), "info", 2500)

            clr.triggered.connect(_clear)
            menu.addAction(clr)
        btn = getattr(self, "_recent_menu_btn", None)
        gp = btn.mapToGlobal(QPoint(0, btn.height())) if btn is not None else self.mapToGlobal(QPoint(0, 0))
        menu.exec(gp)

    def view_key_press(self, event) -> None:
        if self.is_drawing_line:
            QGraphicsView.keyPressEvent(self.view, event)
            return
        k = event.key()
        step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        if k == Qt.Key.Key_Left:
            self.editor_nudge_selected(-step, 0)
            event.accept()
            return
        if k == Qt.Key.Key_Right:
            self.editor_nudge_selected(step, 0)
            event.accept()
            return
        if k == Qt.Key.Key_Up:
            self.editor_nudge_selected(0, -step)
            event.accept()
            return
        if k == Qt.Key.Key_Down:
            self.editor_nudge_selected(0, step)
            event.accept()
            return
        if k == Qt.Key.Key_0 and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.editor_reset_canvas_zoom()
            event.accept()
            return
        if k == Qt.Key.Key_G and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.editor_ungroup_selected()
            else:
                self.editor_group_selected()
            event.accept()
            return
        QGraphicsView.keyPressEvent(self.view, event)

    def _write_project_json(self, path: str, *, show_success_dialog: bool) -> None:
        project_root = Path(path).resolve().parent
        elements_to_save = [elem for elem in self.elements if isinstance(elem, BaseVisualizationElement)]
        normalize_image_elements_for_save(project_root, elements_to_save)
        normalize_video_milkdrop_for_save(project_root, elements_to_save)
        data = self._collect_project_data()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if show_success_dialog:
            show_toast(self, tr("msg.project_saved"), "info", 3200)

    def setup_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Адаптивные ширины панелей под текущий размер окна.
        # Слева сетка 3×90px кнопок — не уже ~300px, иначе контент обрезается.
        parent_w = self.parent_window.width() if hasattr(self, "parent_window") and self.parent_window else 1600
        # Ширина левой панели: фиксированная “удобная” по умолчанию (без настройки в диалоге).
        left_menu_w = max(300, min(460, int(parent_w * 0.23)))
        properties_w = _properties_panel_width(parent_w)
        # С новой рамкой (border=2px) и плотными стилями оставляем небольшой запас,
        # чтобы кнопки сетки не «вылезали» за левую панель при узких размерах.
        _lm_margins = 24
        _btn_gaps = 14
        element_cell = max(46, (left_menu_w - _lm_margins - _btn_gaps - 12) // 3)
        
        # Левое меню элементов с прокруткой
        left_menu = QWidget()
        left_menu.setMinimumWidth(left_menu_w)
        left_menu.setStyleSheet("")
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        
        # Заголовок
        title = QLabel(tr("editor.elements_title"))
        title.setStyleSheet("")
        title.setFixedHeight(22)
        left_layout.addWidget(title)
        
        # Настройки разрешения
        resolution_group = QGroupBox(tr("editor.resolution"))
        resolution_group.setStyleSheet("")
        resolution_layout = QVBoxLayout()
        
        # Выбор пропорций
        aspect_combo = QComboBox()
        for ratio in ("16:9", "16:10", "4:3", "21:9", "1:1"):
            aspect_combo.addItem(ratio, ratio)
        aspect_combo.addItem(tr("editor.aspect.custom"), "custom")
        aspect_combo.setCurrentIndex(0)
        aspect_combo.setStyleSheet("")
        aspect_combo.currentIndexChanged.connect(self._on_aspect_changed)
        resolution_layout.addWidget(QLabel(tr("editor.aspect")))
        resolution_layout.addWidget(aspect_combo)
        self.aspect_combo = aspect_combo
        
        # Размеры
        width_spin = QSpinBox()
        width_spin.setRange(100, 7680)
        width_spin.setValue(1920)
        width_spin.setStyleSheet("")
        width_spin.valueChanged.connect(self.on_resolution_changed)
        self.width_spin = width_spin
        
        height_spin = QSpinBox()
        height_spin.setRange(100, 4320)
        height_spin.setValue(1080)
        height_spin.setStyleSheet("")
        height_spin.valueChanged.connect(self.on_resolution_changed)
        self.height_spin = height_spin
        
        wh_row = QHBoxLayout()
        wh_row.setSpacing(6)
        wh_row.addWidget(QLabel(tr("editor.width")), 0)
        wh_row.addWidget(width_spin, 1)
        wh_row.addWidget(QLabel(tr("editor.height")), 0)
        wh_row.addWidget(height_spin, 1)
        resolution_layout.addLayout(wh_row)
        
        resolution_group.setLayout(resolution_layout)
        left_layout.addWidget(resolution_group)
        
        left_layout.addSpacing(8)
        
        # Сетка элементов 2x3 (заголовок «Элементы» уже сверху — вторую подпись не дублируем)
        elements_grid = QWidget()
        elements_grid_layout = QVBoxLayout()
        elements_grid_layout.setContentsMargins(0, 0, 0, 0)
        elements_grid_layout.setSpacing(5)
        
        # Определяем элементы с иконками (чёрно-белые символы)
        elements_data = [
            ("IMG", tr("el.image"), "image"),
            ("~", tr("el.wave"), "wave"),
            ("|", tr("el.oscilloscope"), "oscilloscope"),
            ("T", tr("el.text"), "text"),
            ("♪", tr("el.track"), "track"),
            ("/", tr("el.line"), "line"),
            ("m", tr("el.milkdrop"), "milkdrop"),
            ("▶", tr("el.video"), "video"),
        ]

        for row_i in range(0, len(elements_data), 3):
            row = QHBoxLayout()
            row.setSpacing(5)
            row.setContentsMargins(0, 0, 0, 0)
            for icon, name, elem_type in elements_data[row_i : row_i + 3]:
                btn = ElementButton(name, icon, elem_type, self, cell_side=element_cell)
                btn.clicked.connect(lambda checked, t=elem_type: self.add_element_by_type(t))
                row.addWidget(btn)
            elements_grid_layout.addLayout(row)
        elements_grid.setLayout(elements_grid_layout)
        left_layout.addWidget(elements_grid)
        
        # Подсказка для инструмента линии.
        self.line_hint_label = QLabel("")
        self.line_hint_label.setWordWrap(True)
        self.line_hint_label.setVisible(False)
        self.line_hint_label.setStyleSheet("")
        left_layout.addWidget(self.line_hint_label)

        left_layout.addSpacing(20)
        
        # Кнопки управления проектом
        save_btn = QPushButton(tr("editor.save"))
        save_btn.clicked.connect(self.save_project_smart)
        # Оборачиваем проектные кнопки для guided tour.
        project_wrap = QWidget()
        project_wrap.setObjectName("projectButtonsWrap")
        project_l = QVBoxLayout(project_wrap)
        project_l.setContentsMargins(0, 0, 0, 0)
        project_l.setSpacing(8)
        project_l.addWidget(save_btn)

        load_btn = QPushButton(tr("editor.load"))
        load_btn.clicked.connect(self.load_project)
        project_l.addWidget(load_btn)

        self._recent_menu_btn = QPushButton(tr("editor.recent"))
        self._recent_menu_btn.clicked.connect(self.show_recent_projects_menu)
        project_l.addWidget(self._recent_menu_btn)

        grp_btn = QPushButton(tr("editor.group"))
        grp_btn.clicked.connect(self.editor_group_selected)
        project_l.addWidget(grp_btn)
        ugrp_btn = QPushButton(tr("editor.ungroup"))
        ugrp_btn.clicked.connect(self.editor_ungroup_selected)
        project_l.addWidget(ugrp_btn)
        gh = QLabel(tr("editor.group_select_hint"))
        gh.setWordWrap(True)
        gh.setStyleSheet("color: #808080; font-size: 10px;")
        project_l.addWidget(gh)

        play_btn = QPushButton(tr("editor.play"))
        play_btn.clicked.connect(self.start_playback)
        project_l.addWidget(play_btn)
        self._project_buttons_wrap = project_wrap
        left_layout.addWidget(project_wrap)
        
        left_menu.setLayout(left_layout)
        
        # Центральная область визуализации
        self.scene.setSceneRect(-500, -500, 3000, 3000)
        
        # Добавляем элемент разрешения экрана (на задний план) - ДО создания view
        self.resolution_background = ResolutionBackground(
            self.resolution_width, self.resolution_height, 100, 100
        )
        self.resolution_background.setZValue(-1000)  # Всегда на заднем плане
        self.scene.addItem(self.resolution_background)
        
        # Создаём ScrollArea для прокрутки ПОСЛЕ установки layout и создания resolution_background
        from PyQt6.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidget(left_menu)
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(left_menu_w)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Без max width — сплиттером можно расширить; при узком окне не обрезаем кнопки.
        scroll_area.setStyleSheet("")
        
        # Используем подкласс, чтобы не делать monkey-patching обработчиков.
        self.view = InteractiveCanvasView(self.scene, self)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setStyleSheet("border: none;")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemBoundingRect)
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        # Включаем масштабирование колесом мыши
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Включаем drag & drop на view
        self.view.setAcceptDrops(True)
        self.view.dragLeaveEvent = self.view_drag_leave
        
        # Для перемещения зажатым колесом
        self.middle_button_pressed = False
        self.last_pan_point = None
        
        # Для resize
        self.resizing_element = None
        self.resize_handle = None
        self.resize_start_pos = None
        self.resize_start_size = None
        self.resize_start_pos_item = None
        # Для rotate
        self.rotating_element: Optional[BaseVisualizationElement] = None
        self.rotate_start_angle = 0.0
        self.rotate_start_deg = 0.0
        self.rotate_last_angle = 0.0
        
        # Правая панель свойств
        self.properties_panel = PropertiesPanel()
        self.properties_panel.setMinimumWidth(properties_w)
        
        # Сплиттер: центр тянется, боковые — по минимуму, но без жёсткого max (нет обрезки форм).
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll_area)
        splitter.addWidget(self.view)
        splitter.addWidget(self.properties_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(2, 0)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        total_w = max(parent_w, 900)
        mid_w = max(320, total_w - left_menu_w - properties_w)
        splitter.setSizes([left_menu_w, mid_w, properties_w])
        layout.addWidget(splitter)
        self._main_splitter = splitter
        self._left_scroll = scroll_area
        
        self.setLayout(layout)
        
        # Подключение сигналов сцены
        self.scene.selectionChanged.connect(self.on_selection_changed)
        try:
            self.scene.changed.connect(self._on_scene_changed_for_autosave)
        except Exception:
            pass

        # Включаем drag & drop на view
        self.view.setAcceptDrops(True)
        self.view.dragEnterEvent = self.view_drag_enter
        self.view.dragMoveEvent = self.view_drag_move
        self.view.dropEvent = self.view_drop

        # Первый fit под текущее разрешение.
        self._do_fit_canvas()

        # Демо-сигнал для удобной настройки (волна/осциллограф и т.п.) в режиме редактора.
        # В playback приходит реальный звук, а в редакторе — “примерные” волны.
        self._demo_audio_phase = 0.0
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(1000)  # раз в секунду — новый «снимок» для превью виджетов
        self._demo_timer.timeout.connect(self._tick_demo_audio)
        self._demo_timer.start()

    def _iter_elements_for_editor_audio(self):
        """Топ-уровень + дети групп (в группе дети не в self.elements, но им нужен демо-FFT)."""
        for e in list(self.elements):
            if isinstance(e, GroupContainerElement):
                for c in e.members():
                    if isinstance(c, BaseVisualizationElement):
                        yield c
            elif isinstance(e, BaseVisualizationElement):
                yield e

    def _tick_demo_audio(self) -> None:
        try:
            if not getattr(self, "elements", None):
                return
            # Если приложение свернуто/не активно — не спамим обновления.
            try:
                if self.parent_window and self.parent_window.isMinimized():
                    return
            except Exception:
                pass

            sr = 44100.0
            n = 1024
            t0 = time.monotonic()
            self._demo_audio_phase = (self._demo_audio_phase + 0.35) % (2.0 * np.pi)

            tt = (np.arange(n, dtype=float) / sr) + t0
            # Умеренные уровни (~типичный микшер/плеер), без клиппинга и «вылетов» за разумные амплитуды.
            rng = np.random.default_rng(int(t0 * 1000) % 1_000_000)
            f1, f2, f3 = rng.uniform(55.0, 110.0), rng.uniform(160.0, 320.0), rng.uniform(700.0, 1600.0)
            a1, a2, a3 = rng.uniform(0.12, 0.22), rng.uniform(0.06, 0.14), rng.uniform(0.03, 0.08)
            x = (
                a1 * np.sin(2.0 * np.pi * f1 * tt + self._demo_audio_phase)
                + a2 * np.sin(2.0 * np.pi * f2 * tt + self._demo_audio_phase * 0.73)
                + a3 * np.sin(2.0 * np.pi * f3 * tt + self._demo_audio_phase * 1.17)
            )
            x += rng.normal(0.0, 0.012, size=n)
            # Мягкая огибающая, чтобы не было «кирпича» по амплитуде.
            denom = max(1, n - 1)
            env = 0.55 + 0.45 * np.sin(np.pi * np.arange(n, dtype=float) / float(denom))
            x = x * env
            peak = float(np.max(np.abs(x))) + 1e-9
            target_peak = 0.38
            if peak > target_peak:
                x = x * (target_peak / peak)
            x = np.clip(x, -0.45, 0.45)

            win = np.hanning(n)
            fft = np.abs(np.fft.rfft(x * win))
            freqs = np.fft.rfftfreq(n, d=1.0 / sr)

            for e in self._iter_elements_for_editor_audio():
                try:
                    e.update_audio_data(x, fft, freqs)
                except Exception:
                    continue
            try:
                self.scene.update()
            except Exception:
                pass
        except Exception:
            # Демо не должен ломать редактор
            return

    def apply_visual_settings_from_config(self) -> None:
        """Применить визуальные параметры после «ОК» в настройках."""
        if not getattr(self, "_main_splitter", None) or not getattr(self, "_left_scroll", None):
            return
        parent_w = self.parent_window.width() if self.parent_window else 900
        left_menu_w = max(300, min(460, int(parent_w * 0.23)))
        properties_w = _properties_panel_width(parent_w)
        total_w = max(parent_w, 900)
        mid_w = max(320, total_w - left_menu_w - properties_w)
        self._left_scroll.setMinimumWidth(left_menu_w)
        self.properties_panel.setMinimumWidth(properties_w)
        self._main_splitter.setSizes([left_menu_w, mid_w, properties_w])
    
    def view_wheel_event(self, event):
        """Обработка масштабирования и перемещения колесом мыши"""
        modifiers = event.modifiers()
        delta = event.angleDelta().y()
        
        # Ctrl + колесо = приближение/отдаление
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if delta > 0:
                self.view.scale(1.1, 1.1)
            else:
                self.view.scale(0.9, 0.9)
        # Alt + колесо = влево/вправо
        elif modifiers & Qt.KeyboardModifier.AltModifier:
            scroll_amount = delta / 10.0
            self.view.horizontalScrollBar().setValue(
                self.view.horizontalScrollBar().value() - int(scroll_amount)
            )
        # Просто колесо = вверх/вниз
        else:
            scroll_amount = delta / 10.0
            self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().value() - int(scroll_amount)
            )
    
    def add_element_by_type(self, element_type: str):
        """Добавить элемент по типу"""
        if element_type == "image":
            self.add_image()
        elif element_type == "wave":
            self.add_wave()
        elif element_type == "oscilloscope":
            self.add_oscilloscope()
        elif element_type == "text":
            self.add_text()
        elif element_type == "track":
            self.add_track_name()
        elif element_type == "line":
            self.add_line()
        elif element_type == "milkdrop":
            self.add_milkdrop()
        elif element_type == "video":
            self.add_video()

    def _on_aspect_changed(self, _index: int = 0) -> None:
        """Обработка изменения пропорций (данные в элементе списка)."""
        data = self.aspect_combo.currentData()
        if data == "custom":
            return
        ratios = {
            "16:9": (16, 9),
            "16:10": (16, 10),
            "4:3": (4, 3),
            "21:9": (21, 9),
            "1:1": (1, 1),
        }
        if data not in ratios:
            return
        w_ratio, h_ratio = ratios[data]
        current_width = self.width_spin.value()
        new_height = int(current_width * h_ratio / w_ratio)
        self.height_spin.blockSignals(True)
        self.height_spin.setValue(new_height)
        self.height_spin.blockSignals(False)
        self.on_resolution_changed()
    
    def on_resolution_changed(self):
        """Обработка изменения разрешения"""
        self.resolution_width = self.width_spin.value()
        self.resolution_height = self.height_spin.value()
        if self.resolution_background:
            self.resolution_background.set_size(self.resolution_width, self.resolution_height)
        self.schedule_autosave()
    
    def _show_element_context_menu(
        self, element: BaseVisualizationElement, global_pos
    ) -> None:
        menu = QMenu(self)
        a_flip_h = QAction(tr("ctx.flip_h"), self)
        a_flip_h.triggered.connect(lambda: self._element_toggle_flip_h(element))
        menu.addAction(a_flip_h)
        a_flip_v = QAction(tr("ctx.flip_v"), self)
        a_flip_v.triggered.connect(lambda: self._element_toggle_flip_v(element))
        menu.addAction(a_flip_v)
        menu.addSeparator()
        fit_act = QAction(tr("ctx.fit_resolution"), self)
        fit_act.triggered.connect(lambda: self._element_fit_resolution(element))
        if isinstance(element, LineElement):
            fit_act.setEnabled(False)
            fit_act.setToolTip(tr("ctx.fit_line_tip"))
        menu.addAction(fit_act)
        sel = self._selected_base_elements()
        if len(sel) >= 2:
            align_menu = QMenu(tr("ctx.align_menu"), self)
            align_menu.addAction(tr("ctx.align_left"), lambda: self._align_selected("left"))
            align_menu.addAction(tr("ctx.align_right"), lambda: self._align_selected("right"))
            align_menu.addAction(tr("ctx.align_top"), lambda: self._align_selected("top"))
            align_menu.addAction(tr("ctx.align_bottom"), lambda: self._align_selected("bottom"))
            align_menu.addAction(tr("ctx.align_hcenter"), lambda: self._align_selected("hcenter"))
            align_menu.addAction(tr("ctx.align_vcenter"), lambda: self._align_selected("vcenter"))
            menu.addMenu(align_menu)
            menu.addAction(tr("editor.group"), self.editor_group_selected)
        if len(sel) == 1 and isinstance(sel[0], GroupContainerElement):
            menu.addAction(tr("editor.ungroup"), self.editor_ungroup_selected)
        menu.addSeparator()
        menu.addAction(tr("ctx.duplicate"), lambda: self._element_duplicate(element))
        menu.addAction(tr("ctx.layer_up"), lambda: self._element_layer_up(element))
        menu.addAction(tr("ctx.layer_down"), lambda: self._element_layer_down(element))
        menu.addAction(tr("ctx.front"), lambda: self._element_bring_front(element))
        menu.addAction(tr("ctx.back"), lambda: self._element_send_back(element))
        menu.addSeparator()
        menu.addAction(tr("ctx.delete"), lambda: self._element_delete(element))
        menu.exec(global_pos)

    def _element_toggle_flip_h(self, element: BaseVisualizationElement) -> None:
        element.flip_h = not element.flip_h
        element._apply_flip_transform()
        element.update()
        if getattr(self.properties_panel, "current_element", None) is element:
            self.properties_panel.show_properties(element)
        self._history_commit_if_changed()

    def _element_toggle_flip_v(self, element: BaseVisualizationElement) -> None:
        element.flip_v = not element.flip_v
        element._apply_flip_transform()
        element.update()
        if getattr(self.properties_panel, "current_element", None) is element:
            self.properties_panel.show_properties(element)
        self._history_commit_if_changed()

    def _element_fit_resolution(self, element: BaseVisualizationElement) -> None:
        if not self.resolution_background or isinstance(element, LineElement):
            return
        if isinstance(element, GroupContainerElement):
            return
        bg = self.resolution_background
        element.setPos(bg.x(), bg.y())
        element.width = float(bg.width)
        element.height = float(bg.height)
        element._apply_flip_transform()
        element.update()
        self.scene.update()
        if getattr(self.properties_panel, "current_element", None) is element:
            self.properties_panel.show_properties(element)
        self._history_commit_if_changed()

    def _element_duplicate(self, element: BaseVisualizationElement) -> None:
        data = element.to_dict()
        sp = element.scenePos()
        data["x"] = float(sp.x()) + 24.0
        data["y"] = float(sp.y()) + 24.0
        new_el = _element_from_project_item(data, self._project_parent_for_paths())
        if new_el is None:
            logger.warning("Дублирование элемента: from_dict failed")
            return
        _regenerate_element_tree_ids(new_el)
        new_el.setZValue(element.zValue())
        self.scene.addItem(new_el)
        self.elements.append(new_el)
        self.scene.clearSelection()
        new_el.setSelected(True)
        QTimer.singleShot(0, lambda: self._reattach_video_in_tree(new_el))
        self.scene.update()
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def _element_layer_up(self, element: BaseVisualizationElement) -> None:
        element.setZValue(element.zValue() + 1.0)
        self.scene.update()
        self._history_commit_if_changed()

    def _element_layer_down(self, element: BaseVisualizationElement) -> None:
        z = element.zValue() - 1.0
        if z <= -999.0:
            z = -998.0
        element.setZValue(z)
        self.scene.update()
        self._history_commit_if_changed()

    def _element_bring_front(self, element: BaseVisualizationElement) -> None:
        zs = [
            e.zValue()
            for e in self.elements
            if isinstance(e, BaseVisualizationElement)
        ]
        element.setZValue(max(zs) + 1.0 if zs else 100.0)
        self.scene.update()
        self._history_commit_if_changed()

    def _element_send_back(self, element: BaseVisualizationElement) -> None:
        others = [
            e.zValue()
            for e in self.elements
            if isinstance(e, BaseVisualizationElement) and e is not element
        ]
        if others:
            element.setZValue(min(others) - 1.0)
        else:
            element.setZValue(0.0)
        if element.zValue() <= -999:
            element.setZValue(-998.0)
        self.scene.update()
        self._history_commit_if_changed()

    def _element_delete(self, element: BaseVisualizationElement, *, commit_history: bool = True) -> None:
        if isinstance(element, VideoElement):
            try:
                element.detach_media()
            except Exception:
                pass
        if isinstance(element, GroupContainerElement):
            for ch in list(element.members()):
                self._detach_videos_in_tree(ch)
                ch.setParentItem(None)
                try:
                    self.scene.removeItem(ch)
                except Exception:
                    pass
                if ch in self.elements:
                    self.elements.remove(ch)
            element._members.clear()
        try:
            self.scene.removeItem(element)
        except Exception:
            pass
        if element in self.elements:
            self.elements.remove(element)
        self.properties_panel.clear_properties()
        self.scene.update()
        if commit_history:
            self._history_commit_if_changed()

    def view_mouse_press(self, event):
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self.view.setFocus(Qt.FocusReason.MouseFocusReason)
        view_pt = event.position().toPoint()
        if event.button() == Qt.MouseButton.RightButton:
            scene_pos = self.view.mapToScene(view_pt)
            item = _top_base_element_at_view(self.view, view_pt)
            if item and isinstance(item, BaseVisualizationElement):
                if not item.isSelected():
                    self.scene.clearSelection()
                    item.setSelected(True)
                self._show_element_context_menu(item, event.globalPosition().toPoint())
                event.accept()
                return

        # Зажатое колесо мыши для перемещения
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middle_button_pressed = True
            self.last_pan_point = event.position().toPoint()
            self.view.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        
        # Если активен инструмент линии — он имеет приоритет над ресайзом.
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing_line:
            scene_pos = self.view.mapToScene(event.position().toPoint())
            self.current_line_element = LineElement(scene_pos.x(), scene_pos.y())
            # Первая точка всегда в начале координат элемента (0, 0)
            self.current_line_element.add_point(QPointF(0, 0))
            self.current_line_element.setZValue(100)  # Поверх подложки
            self.scene.addItem(self.current_line_element)
            self.elements.append(self.current_line_element)
            event.accept()
            return

        # Маркеры / множественное выделение (Shift — добавить, Ctrl — переключить) + рамка на пустом месте.
        if not self.is_drawing_line and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(view_pt)
            item = _top_base_element_at_view(self.view, view_pt)
            if item and isinstance(item, BaseVisualizationElement):
                from PyQt6.QtGui import QGuiApplication

                mods = QGuiApplication.keyboardModifiers()
                shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
                ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
                additive = shift or ctrl

                try:
                    if item.get_rotate_handle_at(scene_pos):
                        if not item.isSelected():
                            if not additive:
                                self.scene.clearSelection()
                            item.setSelected(True)
                        self.rotating_element = item
                        center = item.mapToScene(QPointF(item.width / 2, item.height / 2))
                        v = scene_pos - center
                        import math

                        ang = math.degrees(math.atan2(v.y(), v.x()))
                        self.rotate_start_angle = ang
                        self.rotate_last_angle = ang
                        self.rotate_start_deg = float(getattr(item, "rotation_deg", 0.0) or 0.0)
                        self.view.setCursor(Qt.CursorShape.SizeAllCursor)
                        event.accept()
                        return
                except Exception:
                    pass

                try:
                    handle = item.get_resize_handle_at(scene_pos)
                    if handle:
                        if not item.isSelected():
                            if not additive:
                                self.scene.clearSelection()
                            item.setSelected(True)
                        self.resizing_element = item
                        self.resize_handle = handle
                        self.resize_start_pos = scene_pos
                        self.resize_start_size = (item.width, item.height)
                        self.resize_start_pos_item = (item.x(), item.y())
                        event.accept()
                        return
                except Exception:
                    pass

                if ctrl:
                    item.setSelected(not item.isSelected())
                    if not item.isSelected():
                        event.accept()
                        return
                    super(type(self.view), self.view).mousePressEvent(event)
                    return
                if shift:
                    item.setSelected(True)
                    super(type(self.view), self.view).mousePressEvent(event)
                    return
                if not item.isSelected():
                    self.scene.clearSelection()
                    item.setSelected(True)

        # Явный super: unbound QGraphicsView.mousePressEvent(self.view, …) даёт сбои/рекурсию в части сборок PyQt6.
        super(type(self.view), self.view).mousePressEvent(event)
    
    def view_mouse_move(self, event):
        # Rotate элемента
        if self.rotating_element:
            scene_pos = self.view.mapToScene(event.position().toPoint())
            item = self.rotating_element
            try:
                center = item.mapToScene(QPointF(item.width / 2, item.height / 2))
                v = scene_pos - center
                import math

                ang = math.degrees(math.atan2(v.y(), v.x()))
                delta = ang - float(self.rotate_last_angle)
                # Нормализуем дельту, чтобы переход через -180/180 не давал “рывок”.
                while delta <= -180.0:
                    delta += 360.0
                while delta > 180.0:
                    delta -= 360.0

                new_deg = float((getattr(item, "rotation_deg", 0.0) or 0.0) + delta)
                self.rotate_last_angle = ang
                # Нормализация
                while new_deg <= -180.0:
                    new_deg += 360.0
                while new_deg > 180.0:
                    new_deg -= 360.0

                from PyQt6.QtGui import QGuiApplication

                # Снап к 90° при удержании Shift.
                if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
                    step = 90.0
                    nearest = round(new_deg / step) * step
                    if abs(new_deg - nearest) <= 7.0:
                        new_deg = nearest

                item.rotation_deg = new_deg
                item._apply_transform()
                item.update()
                event.accept()
                return
            except Exception:
                pass

        # Resize элемента
        if self.resizing_element and self.resize_handle:
            scene_pos = self.view.mapToScene(event.position().toPoint())
            delta = scene_pos - self.resize_start_pos
            
            new_width = self.resize_start_size[0]
            new_height = self.resize_start_size[1]
            new_x = self.resize_start_pos_item[0]
            new_y = self.resize_start_pos_item[1]
            
            if "right" in self.resize_handle:
                new_width = max(20, self.resize_start_size[0] + delta.x())
            if "left" in self.resize_handle:
                new_width = max(20, self.resize_start_size[0] - delta.x())
                new_x = self.resize_start_pos_item[0] + delta.x()
            if "bottom" in self.resize_handle:
                new_height = max(20, self.resize_start_size[1] + delta.y())
            if "top" in self.resize_handle:
                new_height = max(20, self.resize_start_size[1] - delta.y())
                new_y = self.resize_start_pos_item[1] + delta.y()

            from PyQt6.QtGui import QGuiApplication

            item_r = self.resizing_element
            mods = QGuiApplication.keyboardModifiers()
            if (
                mods & Qt.KeyboardModifier.ShiftModifier
                and item_r is not None
                and not isinstance(item_r, LineElement)
            ):
                rw = float(self.resize_start_size[0])
                rh = float(self.resize_start_size[1])
                sx, sy = float(self.resize_start_pos_item[0]), float(self.resize_start_pos_item[1])
                if rw >= 1e-6 and rh >= 1e-6:
                    ar = rw / rh
                    h = self.resize_handle or ""
                    corners = {"top-left", "top-right", "bottom-left", "bottom-right"}
                    if h in corners:
                        dw = float(new_width) - rw
                        dh = float(new_height) - rh
                        if abs(dw) >= abs(dh):
                            new_height = max(20.0, float(new_width) / ar)
                        else:
                            new_width = max(20.0, float(new_height) * ar)
                        if h == "bottom-right":
                            new_x, new_y = sx, sy
                        elif h == "bottom-left":
                            new_x = sx + rw - float(new_width)
                            new_y = sy
                        elif h == "top-right":
                            new_x = sx
                            new_y = sy + rh - float(new_height)
                        elif h == "top-left":
                            new_x = sx + rw - float(new_width)
                            new_y = sy + rh - float(new_height)
                    elif h in ("right", "left"):
                        new_height = max(20.0, float(new_width) / ar)
                        new_y = sy + (rh - float(new_height)) / 2.0
                        if h == "right":
                            new_x = sx
                        else:
                            new_x = sx + rw - float(new_width)
                    elif h in ("top", "bottom"):
                        new_width = max(20.0, float(new_height) * ar)
                        new_x = sx + (rw - float(new_width)) / 2.0
                        if h == "bottom":
                            new_y = sy
                        else:
                            new_y = sy + rh - float(new_height)

            if not (
                QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier
            ):
                from elements.snap_geometry import collect_snap_lines, snap_resize_rect

                lx, ly = collect_snap_lines(self.scene, self.resizing_element)
                new_x, new_y, new_width, new_height = snap_resize_rect(
                    self.resize_handle,
                    new_x,
                    new_y,
                    new_width,
                    new_height,
                    lx,
                    ly,
                )

            self.resizing_element.width = new_width
            self.resizing_element.height = new_height
            self.resizing_element.setPos(new_x, new_y)
            self.resizing_element._apply_transform()
            self.resizing_element.update()
            event.accept()
            return

        # Перемещение зажатым колесом (раньше ховера курсора — иначе крутилка перехватывает move)
        if self.middle_button_pressed and self.last_pan_point:
            delta = event.position().toPoint() - self.last_pan_point
            self.view.horizontalScrollBar().setValue(
                self.view.horizontalScrollBar().value() - delta.x()
            )
            self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().value() - delta.y()
            )
            self.last_pan_point = event.position().toPoint()
            event.accept()
            return
        
        # Курсор над маркерами размера (можно тянуть без предварительного клика по элементу)
        if not self.resizing_element:
            view_pt = event.position().toPoint()
            scene_pos = self.view.mapToScene(view_pt)
            item = _top_base_element_at_view(self.view, view_pt)
            if item and isinstance(item, BaseVisualizationElement):
                if item.get_rotate_handle_at(scene_pos):
                    self.view.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    handle = item.get_resize_handle_at(scene_pos)
                    if handle:
                        if "top-left" in handle or "bottom-right" in handle:
                            self.view.setCursor(Qt.CursorShape.SizeFDiagCursor)
                        elif "top-right" in handle or "bottom-left" in handle:
                            self.view.setCursor(Qt.CursorShape.SizeBDiagCursor)
                        elif "top" in handle or "bottom" in handle:
                            self.view.setCursor(Qt.CursorShape.SizeVerCursor)
                        elif "left" in handle or "right" in handle:
                            self.view.setCursor(Qt.CursorShape.SizeHorCursor)
                        else:
                            self.view.setCursor(Qt.CursorShape.ArrowCursor)
                    else:
                        self.view.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.view.setCursor(Qt.CursorShape.ArrowCursor)
        
        if self.is_drawing_line and self.current_line_element:
            scene_pos = self.view.mapToScene(event.position().toPoint())
            # Преобразуем координаты сцены в локальные координаты элемента
            local_pos = self.current_line_element.mapFromScene(scene_pos)
            self.current_line_element.add_point(local_pos)
            self.scene.update()
        else:
            self.view.graphics_view_mouse_move(event)
    
    def view_mouse_release(self, event):
        # Отпускание колеса мыши
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middle_button_pressed = False
            self.last_pan_point = None
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        
        # Завершение resize (только отпускание ЛКМ — иначе не сбрасываем незавершённый drag).
        if self.resizing_element and event.button() == Qt.MouseButton.LeftButton:
            self.resizing_element = None
            self.resize_handle = None
            self.resize_start_pos = None
            self.resize_start_size = None
            self.resize_start_pos_item = None
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            self._history_commit_if_changed()
            event.accept()
            return

        # Завершение rotate
        if self.rotating_element and event.button() == Qt.MouseButton.LeftButton:
            self.rotating_element = None
            self.rotate_start_angle = 0.0
            self.rotate_start_deg = 0.0
            self.rotate_last_angle = 0.0
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            self._history_commit_if_changed()
            event.accept()
            return
        
        if self.is_drawing_line and self.current_line_element:
            line_elem = self.current_line_element
            line_elem.finish_drawing()
            line_elem.setSelected(True)
            self.current_line_element = None
            self.is_drawing_line = False
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            if self.line_hint_label:
                self.line_hint_label.setVisible(False)
            self.scene.update()
            self._history_commit_if_changed()
        else:
            self.view.graphics_view_mouse_release(event)
    
    def on_selection_changed(self):
        # Не пересобирать панель свойств синхронно из цепочки mousePress сцены —
        # иначе возможен краш (удаление виджетов во время обработки события вида).
        app = QApplication.instance()
        if app is None:
            self._deferred_refresh_properties_after_selection()
            return
        QTimer.singleShot(0, self._deferred_refresh_properties_after_selection)

    def _deferred_refresh_properties_after_selection(self) -> None:
        try:
            self._refresh_properties_for_selection()
        except Exception:
            logger.exception("properties refresh after selection failed")
    
    def _prepare_import_image_path(self, path: str) -> Optional[str]:
        """Диалог удаления фона; None — отмена или ошибка чтения файла."""
        from ui.image_import_edit_dialog import run_image_import_edit_dialog

        return run_image_import_edit_dialog(path, self)

    def add_image(self):
        # Диалог открываем сразу в этом же обработчике клика: отложенный QTimer на части систем
        # откладывал появление QFileDialog до «вечности» (пользователь не видел окно выбора файла).
        try:
            if not self.resolution_background:
                parent_widget = self.parent_window if hasattr(self, "parent_window") and self.parent_window else self
                show_toast(parent_widget, tr("err.resolution_init"), "warn", 4000)
                return
            self._add_image_open_file_dialog()
        except Exception as e:
            logger.error(f"Error in add_image: {e}", exc_info=True)
            try:
                parent_widget = self.parent_window if hasattr(self, "parent_window") and self.parent_window else self
                show_toast(
                    parent_widget,
                    tr("err.add_image") + f"\n{e}",
                    "err",
                    5500,
                )
            except Exception:
                pass

    def _add_image_open_file_dialog(self) -> None:
        try:
            from PyQt6 import sip

            if sip.isdeleted(self):
                return
        except Exception:
            pass
        try:
            _ = self.scene
        except RuntimeError:
            return
        dlg_parent = self.parent_window if getattr(self, "parent_window", None) else self.window() or self
        try:
            dlg_parent.raise_()
            dlg_parent.activateWindow()
        except Exception:
            pass
        try:
            path, _ = QFileDialog.getOpenFileName(
                qfile_dialog_parent_for_modal(dlg_parent),
                tr("dialog.pick_image"),
                _image_pick_start_directory(),
                tr("dialog.filter.images"),
                "",
                qfile_dialog_options_stable(),
            )
        except Exception as e:
            logger.error(f"Error opening image file dialog: {e}", exc_info=True)
            try:
                pw = self.parent_window if getattr(self, "parent_window", None) else self
                show_toast(pw, tr("err.add_image") + f"\n{e}", "err", 5500)
            except Exception:
                pass
            return
        if not path:
            return
        QTimer.singleShot(0, lambda p=path: self._complete_add_image_after_pick(p))

    def _complete_add_image_after_pick(self, path: str) -> None:
        try:
            from PyQt6 import sip

            if sip.isdeleted(self):
                return
        except Exception:
            pass
        try:
            _ = self.scene
        except RuntimeError:
            return
        try:
            prepared = self._prepare_import_image_path(path)
            if not prepared:
                return
            # Ещё один тик после закрытия модальных окон — главное окно успевает отрисоваться до decode в ImageElement.
            QTimer.singleShot(0, lambda p=prepared: self._create_image_element(p))
        except Exception as e:
            logger.error(f"Error completing add_image: {e}", exc_info=True)
            try:
                parent_widget = self.parent_window if hasattr(self, "parent_window") and self.parent_window else self
                show_toast(
                    parent_widget,
                    tr("err.add_image") + f"\n{e}",
                    "err",
                    5500,
                )
            except Exception:
                pass

    def _create_image_element(self, path: str):
        """Создать элемент изображения после выбора файла."""
        if not self.resolution_background:
            show_toast(
                self.parent_window if hasattr(self, "parent_window") and self.parent_window else self,
                tr("err.resolution_init"),
                "warn",
                4000,
            )
            return

        try:
            # Создаём элемент в центре подложки.
            bg_x = self.resolution_background.x()
            bg_y = self.resolution_background.y()
            bg_w = self.resolution_background.width
            bg_h = self.resolution_background.height

            width, height = 200, 200
            x = bg_x + bg_w / 2 - width / 2
            y = bg_y + bg_h / 2 - height / 2

            element = ImageElement(x, y, width, height, path if path else "")
            element.setZValue(100)

            self.scene.addItem(element)
            self.elements.append(element)

            # Обновления нужны, чтобы элемент сразу появился.
            element.prepareGeometryChange()
            element.update()
            self.scene.update()
            self.view.update()
            self.schedule_autosave()
            QTimer.singleShot(0, self._history_commit_if_changed)
        except Exception as e:
            logger.error(f"Error in _create_image_element: {e}", exc_info=True)
            show_toast(
                self.parent_window if hasattr(self, "parent_window") and self.parent_window else self,
                tr("err.image_create") + f"\n{e}",
                "err",
                5500,
            )

    def _clear_drop_guide_lines(self) -> None:
        for it in self._drop_guide_items:
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._drop_guide_items.clear()

    def _update_drop_guide_lines(self, scene_end: QPointF) -> None:
        """Пунктир «связи» от точки входа курсора на холст до текущей позиции (ортогональный излом)."""
        self._clear_drop_guide_lines()
        if self._drop_guide_origin is None:
            return
        if (scene_end - self._drop_guide_origin).manhattanLength() < 6.0:
            return
        ox, oy = float(self._drop_guide_origin.x()), float(self._drop_guide_origin.y())
        tx, ty = float(scene_end.x()), float(scene_end.y())
        pen = QPen(QColor(130, 200, 255, 220))
        pen.setWidth(0)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        l1 = QGraphicsLineItem(ox, oy, tx, oy)
        l1.setPen(pen)
        l1.setZValue(1_000_000)
        l2 = QGraphicsLineItem(tx, oy, tx, ty)
        l2.setPen(pen)
        l2.setZValue(1_000_000)
        self.scene.addItem(l1)
        self.scene.addItem(l2)
        self._drop_guide_items.extend([l1, l2])

    def _create_image_element_at_scene(
        self,
        scene_pos: QPointF,
        path: str,
        *,
        skip_import_dialog: bool = False,
    ) -> None:
        """Создать ImageElement в точке сцены с размером по пропорциям файла (drop с диска / буфера)."""
        if not self.resolution_background:
            return
        p = (path or "").strip()
        if not p or not os.path.isfile(p):
            return
        if skip_import_dialog:
            prepared = p
        else:
            prepared = self._prepare_import_image_path(p)
        if not prepared:
            return
        reader = QImageReader(prepared)
        reader.setAutoTransform(True)
        sz = reader.size()
        if not sz.isValid() or sz.width() <= 0 or sz.height() <= 0:
            pm = QPixmap(prepared)
            if pm.isNull():
                return
            iw, ih = max(1, pm.width()), max(1, pm.height())
        else:
            iw, ih = max(1, sz.width()), max(1, sz.height())
        bg_w = float(self.resolution_background.width)
        bg_h = float(self.resolution_background.height)
        max_w = min(bg_w * 0.95, float(iw))
        max_h = min(bg_h * 0.95, float(ih))
        scale = min(max_w / float(iw), max_h / float(ih), 1.0)
        w = max(40.0, float(iw) * scale)
        h = max(40.0, float(ih) * scale)
        x = float(scene_pos.x()) - w / 2.0
        y = float(scene_pos.y()) - h / 2.0
        element = ImageElement(x, y, w, h, prepared)
        element.setZValue(100)
        self.scene.addItem(element)
        self.elements.append(element)
        element.prepareGeometryChange()
        element.update()
        self.scene.update()
        self.view.update()
        self.schedule_autosave()
        QTimer.singleShot(0, self._history_commit_if_changed)

    def _mime_drop_is_accepted(self, mime) -> bool:
        if mime.hasText():
            return True
        if mime.hasImage():
            return True
        if mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    lf = u.toLocalFile()
                    if lf and (
                        is_image_file(Path(lf))
                        or is_video_file(Path(lf))
                        or is_milkdrop_file(Path(lf))
                    ):
                        return True
        return False

    def add_wave(self):
        try:
            logger.debug("add_wave called")
            bg_x = self.resolution_background.x()
            bg_y = self.resolution_background.y()
            bg_w = self.resolution_background.width
            bg_h = self.resolution_background.height
            logger.debug(f"Background: x={bg_x}, y={bg_y}, w={bg_w}, h={bg_h}")
            width, height = 400, 200
            x = bg_x + bg_w/2 - width/2
            y = bg_y + bg_h/2 - height/2
            logger.debug(f"Creating WaveElement at ({x}, {y}) with size ({width}, {height})")
            element = WaveElement(x, y, width, height)
            element.setZValue(100)
            logger.debug(f"Element created, zValue={element.zValue()}")
            self.scene.addItem(element)
            logger.debug("Element added to scene")
            self.elements.append(element)
            logger.debug("Element added to elements list")
            element.update()  # Принудительное обновление
            self.scene.update()  # Обновление сцены
            logger.debug("Scene updated")
            self._history_commit_if_changed()
        except Exception as e:
            logger.error(f"Error in add_wave: {e}", exc_info=True)
            raise
    
    def add_oscilloscope(self):
        try:
            logger.debug("add_oscilloscope called")
            bg_x = self.resolution_background.x()
            bg_y = self.resolution_background.y()
            bg_w = self.resolution_background.width
            bg_h = self.resolution_background.height
            logger.debug(f"Background: x={bg_x}, y={bg_y}, w={bg_w}, h={bg_h}")
            width, height = 400, 200
            x = bg_x + bg_w/2 - width/2
            y = bg_y + bg_h/2 - height/2
            logger.debug(f"Creating OscilloscopeElement at ({x}, {y}) with size ({width}, {height})")
            element = OscilloscopeElement(x, y, width, height)
            element.setZValue(100)
            logger.debug(f"Element created, zValue={element.zValue()}")
            self.scene.addItem(element)
            logger.debug("Element added to scene")
            self.elements.append(element)
            logger.debug("Element added to elements list")
            element.update()  # Принудительное обновление
            self.scene.update()  # Обновление сцены
            logger.debug("Scene updated")
            self._history_commit_if_changed()
        except Exception as e:
            logger.error(f"Error in add_oscilloscope: {e}", exc_info=True)
            raise
    
    def add_text(self):
        bg_x = self.resolution_background.x()
        bg_y = self.resolution_background.y()
        bg_w = self.resolution_background.width
        bg_h = self.resolution_background.height
        width, height = 200, 50
        x = bg_x + bg_w/2 - width/2
        y = bg_y + bg_h/2 - height/2
        element = TextElement(x, y, width, height, tr("editor.new_text"))
        element.setZValue(100)
        self.scene.addItem(element)
        self.elements.append(element)
        self._history_commit_if_changed()
    
    def add_track_name(self):
        bg_x = self.resolution_background.x()
        bg_y = self.resolution_background.y()
        bg_w = self.resolution_background.width
        bg_h = self.resolution_background.height
        width, height = 400, 50
        x = bg_x + bg_w/2 - width/2
        y = bg_y + bg_h/2 - height/2
        element = TrackNameElement(x, y, width, height)
        element.setZValue(100)
        self.scene.addItem(element)
        self.elements.append(element)
        self._history_commit_if_changed()
    
    def add_line(self):
        # На случай “повторного выбора” инструмента — отменяем незавершённую линию.
        if self.current_line_element:
            try:
                self.scene.removeItem(self.current_line_element)
            except Exception:
                pass
            if self.current_line_element in self.elements:
                try:
                    self.elements.remove(self.current_line_element)
                except Exception:
                    pass
            self.current_line_element = None
            self._history_commit_if_changed()

        self.is_drawing_line = True
        self.view.setCursor(Qt.CursorShape.CrossCursor)
        if self.line_hint_label:
            self.line_hint_label.setText(tr("editor.line_hint"))
            self.line_hint_label.setVisible(True)
        # Линия будет создана при первом клике

    def add_milkdrop(self) -> None:
        if not self.resolution_background:
            show_toast(self, tr("err.resolution_init"), "warn", 4000)
            return
        from elements.milkdrop_element import default_projectm_preset_dir

        start = default_projectm_preset_dir() or documents_directory()
        path, _ = QFileDialog.getOpenFileName(
            qfile_dialog_parent_for_modal(self.window() or self),
            tr("dialog.pick_milk"),
            start,
            tr("dialog.filter.milk"),
            "",
            qfile_dialog_options_stable(),
        )
        if not path:
            return
        bg = self.resolution_background
        w, h = float(bg.width) * 0.85, float(bg.height) * 0.85
        x = float(bg.x()) + (float(bg.width) - w) / 2.0
        y = float(bg.y()) + (float(bg.height) - h) / 2.0
        el = MilkdropElement(x, y, w, h)
        el.preset_path = path
        el.setZValue(5)
        self.scene.addItem(el)
        self.elements.append(el)
        el.setSelected(True)
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def add_video(self) -> None:
        if not self.resolution_background:
            show_toast(self, tr("err.resolution_init"), "warn", 4000)
            return
        path, _ = QFileDialog.getOpenFileName(
            qfile_dialog_parent_for_modal(self.window() or self),
            tr("dialog.pick_video"),
            documents_directory(),
            tr("dialog.filter.video"),
            "",
            qfile_dialog_options_stable(),
        )
        if not path:
            return
        bg = self.resolution_background
        w, h = float(bg.width) * 0.55, float(bg.height) * 0.55
        x = float(bg.x()) + (float(bg.width) - w) / 2.0
        y = float(bg.y()) + (float(bg.height) - h) / 2.0
        el = VideoElement(x, y, w, h, path)
        el.setZValue(80)
        self.scene.addItem(el)
        self.elements.append(el)
        el.setSelected(True)
        QTimer.singleShot(0, lambda: self._reattach_video_in_tree(el))
        self._refresh_properties_for_selection()
        self._history_commit_if_changed()

    def cancel_line_drawing(self):
        """Отменить незавершённое рисование линии."""
        if self.current_line_element:
            try:
                self.scene.removeItem(self.current_line_element)
            except Exception:
                pass
            try:
                if self.current_line_element in self.elements:
                    self.elements.remove(self.current_line_element)
            except Exception:
                pass

        self.current_line_element = None
        self.is_drawing_line = False
        self.view.setCursor(Qt.CursorShape.ArrowCursor)

        if self.line_hint_label:
            self.line_hint_label.setVisible(False)

        self.scene.clearSelection()
        self.properties_panel.clear_properties()
        self.scene.update()
        self._history_commit_if_changed()

    def keyPressEvent(self, event):
        # Отмена режима рисования линии.
        if event.key() == Qt.Key.Key_Escape and self.is_drawing_line:
            self.cancel_line_drawing()
            event.accept()
            return
        super().keyPressEvent(event)
    
    def view_drag_enter(self, event):
        """Обработка входа drag & drop"""
        if self._mime_drop_is_accepted(event.mimeData()):
            event.acceptProposedAction()
            self.view.setStyleSheet("border: 2px dashed rgba(255, 255, 255, 0.9);")
            self._clear_drop_guide_lines()
            self._drop_guide_origin = self.view.mapToScene(event.position().toPoint())
            self._update_drop_guide_lines(self._drop_guide_origin)
        else:
            event.ignore()

    def view_drag_move(self, event):
        """Без accept на move внешний drag (Проводник) часто не доходит до drop."""
        if self._mime_drop_is_accepted(event.mimeData()):
            event.acceptProposedAction()
            scene_pos = self.view.mapToScene(event.position().toPoint())
            self._update_drop_guide_lines(scene_pos)
        else:
            event.ignore()

    def view_drag_leave(self, event):
        """Обработка выхода drag & drop"""
        self.view.setStyleSheet("border: none;")
        self._drop_guide_origin = None
        self._clear_drop_guide_lines()
    
    def view_drop(self, event):
        """Обработка drop элемента на сцену"""
        mime = event.mimeData()
        drop_pos = event.position().toPoint()
        scene_pos = self.view.mapToScene(drop_pos)
        self._drop_guide_origin = None
        self._clear_drop_guide_lines()

        if mime.hasUrls():
            for u in mime.urls():
                if not u.isLocalFile():
                    continue
                lf = u.toLocalFile()
                if lf and is_image_file(Path(lf)) and os.path.isfile(lf):
                    # Сразу из Проводника — без диалога импорта; фон можно править из свойств элемента.
                    self._create_image_element_at_scene(scene_pos, lf, skip_import_dialog=True)
                    event.acceptProposedAction()
                    self.view.setStyleSheet("border: none;")
                    return
                if lf and is_video_file(Path(lf)) and os.path.isfile(lf) and self.resolution_background:
                    w, h = 320.0, 180.0
                    el = VideoElement(
                        float(scene_pos.x()) - w / 2,
                        float(scene_pos.y()) - h / 2,
                        w,
                        h,
                        lf,
                    )
                    el.setZValue(80)
                    self.scene.addItem(el)
                    self.elements.append(el)
                    QTimer.singleShot(0, lambda e=el: self._reattach_video_in_tree(e))
                    event.acceptProposedAction()
                    self.view.setStyleSheet("border: none;")
                    self._history_commit_if_changed()
                    return
                if lf and is_milkdrop_file(Path(lf)) and os.path.isfile(lf) and self.resolution_background:
                    from elements.milkdrop_element import default_projectm_textures_dir

                    bg = self.resolution_background
                    w, h = float(bg.width) * 0.85, float(bg.height) * 0.85
                    el = MilkdropElement(
                        float(scene_pos.x()) - w / 2,
                        float(scene_pos.y()) - h / 2,
                        w,
                        h,
                    )
                    el.preset_path = lf
                    td = default_projectm_textures_dir()
                    if td:
                        el.textures_dir = td
                    el.setZValue(5)
                    self.scene.addItem(el)
                    self.elements.append(el)
                    event.acceptProposedAction()
                    self.view.setStyleSheet("border: none;")
                    self._history_commit_if_changed()
                    return

        if mime.hasImage():
            raw = mime.imageData()
            if isinstance(raw, QImage):
                img = raw
            elif isinstance(raw, QPixmap):
                img = raw.toImage()
            else:
                img = QImage(raw) if raw is not None else QImage()
            if not img.isNull():
                tdir = Path(tempfile.gettempdir()) / "AudioVizStudio_drops"
                tdir.mkdir(parents=True, exist_ok=True)
                dest = tdir / f"drop_{int(time.time() * 1000)}_{os.getpid()}.png"
                if img.save(str(dest), "PNG"):
                    self._create_image_element_at_scene(scene_pos, str(dest), skip_import_dialog=True)
                    event.acceptProposedAction()
                    self.view.setStyleSheet("border: none;")
                    return

        if mime.hasText():
            element_type = mime.text()
            # Центрируем элемент относительно курсора
            if element_type == "image":
                dlg_parent = self.parent_window if getattr(self, "parent_window", None) else self.window() or self
                try:
                    dlg_parent.raise_()
                    dlg_parent.activateWindow()
                except Exception:
                    pass
                path, _ = QFileDialog.getOpenFileName(
                    qfile_dialog_parent_for_modal(dlg_parent),
                    tr("dialog.pick_image"),
                    _image_pick_start_directory(),
                    tr("dialog.filter.images"),
                    "",
                    qfile_dialog_options_stable(),
                )
                if not path:
                    event.ignore()
                    self.view.setStyleSheet("border: none;")
                    return
                prepared = self._prepare_import_image_path(path)
                if not prepared:
                    self.view.setStyleSheet("border: none;")
                    return
                width, height = 200, 200
                # Создаём элемент в позиции курсора (центрируем)
                element = ImageElement(scene_pos.x() - width/2, scene_pos.y() - height/2, width, height, prepared)
                element.setZValue(100)
                self.scene.addItem(element)
                self.elements.append(element)
            elif element_type == "wave":
                width, height = 400, 200
                element = WaveElement(scene_pos.x() - width/2, scene_pos.y() - height/2, width, height)
                element.setZValue(100)
                self.scene.addItem(element)
                self.elements.append(element)
            elif element_type == "oscilloscope":
                width, height = 400, 200
                element = OscilloscopeElement(scene_pos.x() - width/2, scene_pos.y() - height/2, width, height)
                element.setZValue(100)
                self.scene.addItem(element)
                self.elements.append(element)
            elif element_type == "text":
                width, height = 200, 50
                element = TextElement(
                    scene_pos.x() - width / 2,
                    scene_pos.y() - height / 2,
                    width,
                    height,
                    tr("editor.new_text"),
                )
                element.setZValue(100)
                self.scene.addItem(element)
                self.elements.append(element)
            elif element_type == "track":
                width, height = 400, 50
                element = TrackNameElement(scene_pos.x() - width/2, scene_pos.y() - height/2, width, height)
                element.setZValue(100)
                self.scene.addItem(element)
                self.elements.append(element)
            elif element_type == "video":
                dlg_parent = self.parent_window if getattr(self, "parent_window", None) else self.window() or self
                path, _ = QFileDialog.getOpenFileName(
                    qfile_dialog_parent_for_modal(dlg_parent),
                    tr("dialog.pick_video"),
                    documents_directory(),
                    tr("dialog.filter.video"),
                    "",
                    qfile_dialog_options_stable(),
                )
                if path and self.resolution_background:
                    w, h = 320.0, 180.0
                    el = VideoElement(
                        float(scene_pos.x()) - w / 2,
                        float(scene_pos.y()) - h / 2,
                        w,
                        h,
                        path,
                    )
                    el.setZValue(80)
                    self.scene.addItem(el)
                    self.elements.append(el)
                    QTimer.singleShot(0, lambda e=el: self._reattach_video_in_tree(e))
            elif element_type == "milkdrop":
                dlg_parent = self.parent_window if getattr(self, "parent_window", None) else self.window() or self
                from elements.milkdrop_element import default_projectm_preset_dir, default_projectm_textures_dir

                start = default_projectm_preset_dir() or documents_directory()
                path, _ = QFileDialog.getOpenFileName(
                    qfile_dialog_parent_for_modal(dlg_parent),
                    tr("dialog.pick_milk"),
                    start,
                    tr("dialog.filter.milk"),
                    "",
                    qfile_dialog_options_stable(),
                )
                if path and self.resolution_background:
                    bg = self.resolution_background
                    w, h = float(bg.width) * 0.85, float(bg.height) * 0.85
                    el = MilkdropElement(
                        float(scene_pos.x()) - w / 2,
                        float(scene_pos.y()) - h / 2,
                        w,
                        h,
                    )
                    el.preset_path = path
                    td = default_projectm_textures_dir()
                    if td:
                        el.textures_dir = td
                    el.setZValue(5)
                    self.scene.addItem(el)
                    self.elements.append(el)
            elif element_type == "line":
                self.add_line()
                self.current_line_element = LineElement(scene_pos.x(), scene_pos.y())
                self.current_line_element.add_point(QPointF(0, 0))
                self.current_line_element.setZValue(100)
                self.scene.addItem(self.current_line_element)
                self.elements.append(self.current_line_element)
            
            event.acceptProposedAction()
            self._history_commit_if_changed()
            # Возвращаем обычный стиль
            self.view.setStyleSheet("border: none;")
        else:
            event.ignore()
    
    def load_project_from_path(self, path: str, *, show_success_dialog: bool = True) -> bool:
        """Загрузка JSON-проекта с диска. Возвращает True при успехе."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            project_parent = Path(path).resolve().parent
            self._apply_project_dict(data, project_parent=project_parent)

            if show_success_dialog:
                show_toast(self, tr("msg.project_loaded"), "info", 3200)
            self._project_json_path = path
            self._register_saved_project_path(path)
            self.schedule_autosave()
            self._history_reset()
            return True
        except Exception as e:
            show_toast(self, tr("msg.project_load_fail") + f" {e}", "err", 6000)
            return False

    def load_project(self):
        dlg_parent = self.parent_window if getattr(self, "parent_window", None) else self.window() or self
        try:
            dlg_parent.raise_()
            dlg_parent.activateWindow()
        except Exception:
            pass
        path, _ = QFileDialog.getOpenFileName(
            qfile_dialog_parent_for_modal(dlg_parent),
            tr("dialog.open_project"),
            self._project_files_start_dir(),
            tr("dialog.filter.json"),
            "",
            qfile_dialog_options_stable(),
        )
        if path:
            self.load_project_from_path(path, show_success_dialog=True)

    def set_viz_fullscreen_chrome_visible(self, visible: bool) -> None:
        """В полноэкранном режиме «только визуализация»: скрыть левую панель и свойства."""
        self._viz_fullscreen_active = not visible
        try:
            self._left_scroll.setVisible(visible)
            self.properties_panel.setVisible(visible)
        except Exception:
            pass
        # F11: без полос прокрутки у холста — только fit по области разрешения на весь экран.
        try:
            if visible:
                self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            else:
                self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        except Exception:
            pass
        try:
            sp = self._main_splitter
            if visible:
                if getattr(self, "_saved_splitter_handle_width", None) is not None:
                    sp.setHandleWidth(int(self._saved_splitter_handle_width))
                    self._saved_splitter_handle_width = None
            else:
                self._saved_splitter_handle_width = sp.handleWidth()
                sp.setHandleWidth(0)
        except Exception:
            pass
        if visible:
            QTimer.singleShot(150, self._do_fit_canvas)
        else:
            QTimer.singleShot(0, self._do_fit_canvas)
            QTimer.singleShot(150, self._do_fit_canvas)
    
    def start_playback(self):
        if not self.elements:
            show_toast(self, tr("warn.no_elements"), "warn", 4000)
            return
        self.parent_window.switch_to_playback_mode(self.elements, self._project_json_path)
    
    def get_elements(self):
        return self.elements.copy()


