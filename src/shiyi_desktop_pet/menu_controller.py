"""One declarative command hierarchy shared by pet and tray menus."""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from .constants import DEFAULT_PET_ACTIONS
from .models import ActionId, ActionKey
from .settings import AppSettings


_LOGGER = logging.getLogger(__name__)
ErrorReporter = Callable[[str, str], None] | logging.Logger


@dataclass(frozen=True)
class MenuCommand:
    """A controller intent emitted by a menu item."""

    kind: str
    value: object | None = None
    target: str | None = None


@dataclass(frozen=True)
class MenuItem:
    label: str
    command: MenuCommand | None = None
    children: tuple["MenuItem", ...] = ()
    checked_from: str | None = None
    checked_value: object | None = None
    radio_group: str | None = None
    description: str = ""


@dataclass(frozen=True)
class _ActionBinding:
    action: QAction
    item: MenuItem


_DEFAULT_ACTION_ITEMS = tuple(
    (definition.label, definition.action_id) for definition in DEFAULT_PET_ACTIONS
)


def _direction_label(degrees: float) -> str:
    number = f"{degrees:05.1f}" if not degrees.is_integer() else f"{int(degrees):03d}"
    return f"观察 {number}°"


class _DetailMenu(QMenu):
    """Native menu with a painted, circular help target on every row."""

    _EXTRA_WIDTH = 34
    _MIN_DIAMETER = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail_help_enabled = False
        # QToolTip normally waits for the platform wake-up delay (about 700 ms
        # on Windows 11). Mouse tracking lets the help filter show the detailed
        # explanation as soon as the pointer enters the circular question mark.
        self.setMouseTracking(True)

    def set_detail_help_enabled(self, enabled: bool) -> None:
        self._detail_help_enabled = bool(enabled)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        if self._detail_help_enabled:
            size.setWidth(size.width() + self._EXTRA_WIDTH)
        return size

    def detail_help_rect(self, action: QAction) -> QRect:
        geometry = self.actionGeometry(action)
        diameter = max(
            self._MIN_DIAMETER,
            min(20, self.fontMetrics().height() - 4),
        )
        right = self.width() - 8
        return QRect(
            right - diameter + 1,
            geometry.center().y() - diameter // 2,
            diameter,
            diameter,
        )

    def detail_help_hit_rect(self, action: QAction) -> QRect:
        return self.detail_help_rect(action).adjusted(-4, -4, 4, 4)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._detail_help_enabled:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for action in self.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            selected = action is self.activeAction()
            color_role = (
                self.palette().ColorRole.HighlightedText
                if selected
                else self.palette().ColorRole.WindowText
            )
            color = self.palette().color(color_role)
            circle = self.detail_help_rect(action)
            painter.setPen(QPen(color, 1.25))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle.adjusted(1, 1, -1, -1))
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(max(9, circle.height() - 6))
            painter.setFont(font)
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "?")
        painter.end()


class _MenuDetailHelpFilter(QObject):
    """Show an action's explanation only over its circular help target."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._visible_action: QAction | None = None

    @staticmethod
    def _action_at(watched: _DetailMenu, position) -> QAction | None:
        return next(
            (
                candidate
                for candidate in watched.actions()
                if candidate.isVisible()
                and not candidate.isSeparator()
                and watched.actionGeometry(candidate).top()
                <= position.y()
                <= watched.actionGeometry(candidate).bottom()
            ),
            None,
        )

    def _hide(self) -> None:
        if self._visible_action is not None:
            QToolTip.hideText()
            self._visible_action = None

    def _show_at(self, watched: _DetailMenu, position) -> None:
        action = self._action_at(watched, position)
        if action is None or not action.toolTip():
            self._hide()
            return
        question_area = watched.detail_help_hit_rect(action)
        if not question_area.contains(position):
            self._hide()
            return
        if self._visible_action is action and QToolTip.isVisible():
            return
        QToolTip.showText(
            watched.mapToGlobal(position),
            action.toolTip(),
            watched,
            question_area,
        )
        self._visible_action = action

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isinstance(watched, _DetailMenu):
            return False

        if event.type() == QEvent.Type.MouseMove:
            self._show_at(watched, event.position().toPoint())
            return False

        if event.type() in {QEvent.Type.Leave, QEvent.Type.Hide}:
            self._hide()
            return False

        if event.type() != QEvent.Type.ToolTip:
            return False

        action = self._action_at(watched, event.pos())
        if action is None or not action.toolTip():
            self._hide()
            return True
        question_area = watched.detail_help_hit_rect(action)
        if not question_area.contains(event.pos()):
            self._hide()
            return True
        self._show_at(watched, event.pos())
        return True


def _toggle(label: str, setting_name: str, description: str) -> MenuItem:
    return MenuItem(
        label,
        MenuCommand("toggle", target=setting_name),
        checked_from=setting_name,
        description=description,
    )


def _choice(
    label: str,
    kind: str,
    value: object,
    setting_name: str,
    radio_group: str,
    description: str,
) -> MenuItem:
    return MenuItem(
        label,
        MenuCommand(kind, value),
        checked_from=setting_name,
        checked_value=value,
        radio_group=radio_group,
        description=description,
    )


def _menu_items(
    pet_choices: tuple[tuple[str, str], ...],
    action_items: tuple[tuple[str, ActionKey], ...],
    look_degrees: tuple[float, ...] = tuple(index * 22.5 for index in range(16)),
    action_details: Mapping[ActionKey, str] | None = None,
    gaze_frame_count: int = 16,
    shortcut_labels: tuple[tuple[int, str], ...] = (),
) -> tuple[MenuItem, ...]:
    action_details = action_details or {}
    gaze_step = 360.0 / gaze_frame_count if gaze_frame_count else 0.0
    shortcut_text = "、".join(
        f"{digit}={label}" for digit, label in shortcut_labels
    )
    look_item = (
        (
            MenuItem(
                "观察方向",
                children=tuple(
                    MenuItem(
                        _direction_label(degrees),
                        MenuCommand("look", degrees),
                        description=(
                            f"立即固定显示 {degrees:g}° 的注视帧：0°正上、90°正右、"
                            "180°正下、270°正左，其他角度按顺时针计算。这个选择只用于逐帧"
                            "检查素材，不会移动宠物，也不会修改“看向鼠标”及其注视方式。"
                        ),
                    )
                    for degrees in look_degrees
                ),
                description=(
                    f"这里列出 {len(look_degrees)} 个固定测试角度，相邻间隔通常为 22.5°。"
                    f"当前宠物自动看鼠标实际可使用 {gaze_frame_count} 帧，角度间隔"
                    f" {gaze_step:g}°；因此南宫婉等高密度宠物的自动注视会比这个测试菜单更细。"
                ),
            ),
        )
        if look_degrees
        else ()
    )
    gaze_controls = (
        (
            _toggle(
                "看向鼠标",
                "gaze_enabled",
                f"当前宠物有 {gaze_frame_count} 个注视方向，每档约 {gaze_step:g}°。程序每"
                " 50 毫秒读取一次鼠标，以约 110 毫秒响应时间平滑转向，最大转向速度"
                " 360°/秒；鼠标进入宠物中心约 24 像素×当前大小的死区时保持当前方向。"
                "拖动、手动动作和移动动作优先，结束后才恢复注视。",
            ),
            MenuItem(
                "注视方式",
                children=(
                    _choice(
                        "鼠标活动时（推荐）",
                        "gaze_mode",
                        "active",
                        "gaze_mode",
                        "gaze_mode",
                        "鼠标移动时立即注视；连续 8 秒没有检测到鼠标位置变化后释放注视。"
                        "若已开自动闲逛，就按所选强度开始移动；若未开闲逛但开了自主小动作，"
                        "第一次可在静止满 8 秒时触发，之后每次动作间隔 15–35 秒；两项都关闭"
                        "则回到待机。鼠标再次移动会立刻中断闲逛并恢复注视。",
                    ),
                    _choice(
                        "始终看向鼠标",
                        "gaze_mode",
                        "always",
                        "gaze_mode",
                        "gaze_mode",
                        "只要“看向鼠标”开启，就不使用 8 秒静止释放规则：鼠标停多久都保持"
                        "当前注视方向。自动闲逛计时器和 15–35 秒自主小动作都会暂停；"
                        "右键手动动作、单击、双击、数字快捷键和拖动仍可临时覆盖注视。",
                    ),
                ),
                description=(
                    "这个选项只在“看向鼠标”已勾选且当前宠物含注视素材时生效。"
                    "“鼠标活动时”采用 8 秒静止门槛并把控制权交回闲逛/自主动作；"
                    "“始终看向鼠标”没有超时，会持续占用基础行为。"
                ),
            ),
        )
        if look_degrees
        else ()
    )
    return (
        MenuItem(
            "动作",
            children=(
                *(
                    MenuItem(
                        label,
                        MenuCommand("action", action),
                        description=action_details.get(
                            action,
                            f"立即播放当前宠物的“{label}”动作。手动动作会暂时打断闲逛或注视；"
                            "该宠物包没有提供可显示的帧数、时长、权重和冷却详情。",
                        ),
                    )
                    for label, action in action_items
                ),
                MenuItem(
                    "随机动作",
                    MenuCommand("action", ActionId.RANDOM),
                    description=(
                        "只从当前宠物 JSON 中 role=interaction 且 autoplayWeight>0 的动作"
                        "里抽取；移动、遁光、待机和注视都不参加。抽取前先排除仍在 cooldownMs"
                        "冷却中的动作，再尽量避免和上次相同的动作或 autoplayGroup 特效组；"
                        "概率按剩余动作的权重重新计算。若全部仍在冷却，则回到待机。"
                    ),
                ),
                MenuItem(
                    "动作展示",
                    MenuCommand("showcase"),
                    description=(
                        "按 pet.json 的定义顺序，连续播放菜单可见或允许自主触发的"
                        " role=interaction 动作，包括 showInMenu=false 但权重大于 0 的隐藏自主"
                        "动作；既不显示菜单、权重也为 0 的休眠/彩蛋动作不会播放。待机、普通"
                        "移动、遁光和注视帧同样不在展示范围内；需要持续 30–90 秒的常驻状态"
                        "入口也会跳过，以免整套展示长时间停在同一场景。"
                        "每项严格使用自己的 frameDurations、repeatCount 和 holdMs，当前动画速度"
                        "仍会按慢速×1.25、正常×1、快速×0.75换算时长。单击、双击、拖动或"
                        "选择其他动作可立即中断。"
                    ),
                ),
                *look_item,
            ),
            description=(
                "这里的单个动作说明直接读取当前宠物 pet.json，会列出帧数、单帧毫秒数、"
                "正常速度总时长、循环/停留、自动权重、名义概率和冷却秒数。切换宠物后"
                "名称与数值会一起重建；“随机动作”和“动作展示”的候选范围不同。"
            ),
        ),
        _toggle(
            "自动闲逛",
            "wander_enabled",
            "开启后，只在宠物当前所在显示器的可用区域内选目标；可用区域会扣除任务栏。"
            "等待时间由“闲逛强度”决定，普通移动速度由“移动速度”决定（100%大小分别为"
            " 75/120/180 像素/秒）。每次到达目标后有 35% 概率接一个随机原地动作，"
            "其余情况重新等待。活动注视会抢占闲逛，鼠标静止 8 秒后再恢复。",
        ),
        MenuItem(
            "闲逛强度",
            children=tuple(
                _choice(
                    label,
                    "wander_intensity",
                    intensity,
                    "wander_intensity",
                    "wander_intensity",
                    description,
                )
                for label, intensity, description in (
                    (
                        "安静",
                        "quiet",
                        "每次完成移动或回到闲逛状态后，随机等待 8–18 秒。普通目标与当前位置"
                        "的水平距离最多为屏幕可移动宽度的 25%；宠物 JSON 若定义了稀有遁光，"
                        "它仍可按自身距离比例触发。窗口不会越过可用区域或进入任务栏。",
                    ),
                    (
                        "标准",
                        "standard",
                        "每次完成移动或回到闲逛状态后，随机等待 2–6 秒。普通目标可位于"
                        "当前显示器整个可用区域；到达后仍有 35% 概率接一个随机原地动作。"
                        "这是旧版本设置升级后的默认档。",
                    ),
                    (
                        "活跃",
                        "active",
                        "每次完成移动或回到闲逛状态后，只随机等待 1–3 秒。目标范围与“标准”"
                        "相同，均覆盖当前显示器整个可用区域；区别只有等待更短，所以移动和"
                        "到达后的随机动作明显更频繁。",
                    ),
                )
            ),
            description=(
                "三个档位分别是：安静 8–18 秒且普通目标≤可移动宽度25%；标准 2–6 秒"
                "且全可用区域；活跃 1–3 秒且全可用区域。它不改变动画帧时长，也不改变"
                " 75/120/180 像素/秒的移动速度；稀有遁光仍遵守宠物 JSON 的独立权重和冷却。"
            ),
        ),
        *gaze_controls,
        _toggle(
            "自主小动作",
            "autonomous_actions_enabled",
            "关闭自动闲逛时才会工作。若不看鼠标或宠物不支持注视，首次及每次动作后随机"
            "等待 15–35 秒；若使用“鼠标活动时”注视，鼠标静止满 8 秒可触发第一次，"
            "之后仍按 15–35 秒。候选仅限 role=interaction 且权重>0，排除移动、遁光、"
            "待机和注视，并遵守每项冷却及同动作/同特效组不连续规则。",
        ),
        _toggle(
            "悬停数字快捷键",
            "hover_digits_enabled",
            "只有鼠标命中当前宠物图像的不透明像素时，主键盘或数字小键盘 0–9 才会被"
            "宠物接收；透明区域和其他位置的数字会原样交给当前应用，程序不记录输入。"
            + (f"当前映射：{shortcut_text}。" if shortcut_text else "固定语义槽为1待机、2右移、3左移、4–9互动、0随机。")
            + "关闭后会停用这组全局悬停监听。",
        ),
        _toggle(
            "始终置顶",
            "always_on_top",
            "对应 Windows 的 WindowStaysOnTopHint：开启后，宠物在浏览器、资源管理器、"
            "聊天窗口等普通顶层窗口之上；关闭后，任意普通窗口都可以盖住它。它不会把宠物"
            "固定到屏幕坐标或任务栏，也不会影响开机启动。独占全屏、锁屏、UAC安全桌面和"
            "部分系统界面仍可位于宠物之上。",
        ),
        MenuItem(
            "开机启动",
            MenuCommand("toggle", target="startup_enabled"),
            checked_from="startup_enabled",
            description=(
                "开启时写入当前用户注册表 HKCU\\Software\\Microsoft\\Windows\\"
                "CurrentVersion\\Run 下的 DesktopCompanion 值，内容为带引号的安装版 exe"
                "绝对路径加 --startup；关闭时删除该值。它在登录 Windows 账户后启动，"
                "不需要管理员权限，不是系统服务，也与“始终置顶”无关。"
            ),
        ),
        MenuItem(
            "切换宠物",
            children=tuple(
                _choice(
                    display_name,
                    "pet",
                    pet_id,
                    "pet_id",
                    "pet",
                    f"立即切换为“{display_name}”，中断当前动作和闲逛，并重新载入它的图集、"
                    "动作名称、帧参数、注视方向及托盘图标。当前屏幕位置、75%–150%大小、"
                    "动画/移动速度、闲逛、注视和详情开关保持不变；宠物 ID 会立即写入设置。",
                )
                for pet_id, display_name in pet_choices
            ),
            description=(
                f"当前共列出 {len(pet_choices)} 只通过校验的宠物。切换时会中断当前动作，"
                "替换图集、动作菜单、数字映射、注视密度和托盘图标，但保留位置、大小、速度"
                "及全部通用开关；所选宠物会立即保存，不必等到退出。"
            ),
        ),
        MenuItem(
            "重新扫描宠物",
            MenuCommand("refresh_pets"),
            description=(
                "立即重新读取内置资源和 %APPDATA%\\DesktopCompanion\\pets 下的每个子目录。"
                "程序校验 pet.json、宠物ID、192×208单元格、图集尺寸/透明通道、帧坐标、"
                "动作角色、帧时长、权重和冷却；有效修改马上生效，无效或重复包会被忽略，"
                "托盘通知会显示发现数量和忽略数量。"
            ),
        ),
        MenuItem(
            "打开宠物目录",
            MenuCommand("open_pets_directory"),
            description=(
                "打开 %APPDATA%\\DesktopCompanion\\pets；目录不存在时自动创建。每只宠物"
                "必须独占一个以安全宠物ID命名的子文件夹，至少包含 pet.json 和"
                " spritesheet.webp。复制完成后要点“重新扫描宠物”；覆盖安装会保留此目录，"
                "但卸载会清理，重要自制素材应另行备份。"
            ),
        ),
        MenuItem(
            "大小",
            children=tuple(
                _choice(
                    f"{scale}%",
                    "scale",
                    scale,
                    "scale_percent",
                    "scale",
                    f"把 192×208 像素的基础单元格显示为 {192 * scale // 100}×"
                    f"{208 * scale // 100} 像素（{scale}%）。窗口、点击区域、注视中心死区、"
                    "手动移动步长和自动移动速度会同比缩放；原始 WebP 图集不会被改写。",
                )
                for scale in (75, 100, 125, 150)
            ),
            description=(
                "四档对应实际窗口尺寸：75%=144×156、100%=192×208、125%=240×260、"
                "150%=288×312 像素。缩放会同比影响点击区域、24像素注视死区、手动每帧"
                "12像素步长和自动移动像素/秒；动作的时间长度不变。"
            ),
        ),
        MenuItem(
            "动画速度",
            children=tuple(
                _choice(
                    label,
                    "animation_speed",
                    speed,
                    "animation_speed",
                    "animation_speed",
                    description,
                )
                for label, speed, description in (
                    ("慢速", "slow", "把 pet.json 中每个 frameMs/frameDurations 乘 1.25；例如100毫秒变125毫秒。播放速率为正常的0.8倍，动作总时长增加25%；不改变窗口移动速度。"),
                    ("正常", "normal", "严格使用 pet.json 的原始 frameMs、frameDurations、repeatCount 和 holdMs，倍率为1.0；动作菜单里的总时长都按这一档计算。"),
                    ("快速", "fast", "把 pet.json 中每个帧时长和停留时间乘0.75；例如100毫秒变75毫秒。播放速率约为正常的1.33倍，动作总时长减少25%；不改变窗口移动速度。"),
                )
            ),
            description=(
                "时间倍率分别为慢速×1.25、正常×1.0、快速×0.75，作用于帧时长、重复轮次"
                "和末帧停留，所以动作总时长同比变化。它不修改普通闲逛的75/120/180像素/秒；"
                "但遁光位移与动画进度绑定，因此会随动画档位更早或更晚完成。"
            ),
        ),
        MenuItem(
            "移动速度",
            children=tuple(
                _choice(
                    label,
                    "movement_speed",
                    speed,
                    "movement_speed",
                    "movement_speed",
                    description,
                )
                for label, speed, description in (
                    ("慢速", "slow", "100%大小时按75像素/秒移动；75%/125%/150%大小时分别约56.25/93.75/112.5像素/秒。只影响普通自动闲逛，不改变帧时长和遁光比例位移。"),
                    ("正常", "normal", "100%大小时按120像素/秒移动；75%/125%/150%大小时分别为90/150/180像素/秒。只影响普通自动闲逛，不改变动作播放节奏。"),
                    ("快速", "fast", "100%大小时按180像素/秒移动；75%/125%/150%大小时分别为135/225/270像素/秒。只影响普通自动闲逛，不改变帧时长和遁光比例位移。"),
                )
            ),
            description=(
                "100%大小的三档为75/120/180像素/秒，实际速度再乘当前大小比例。只控制"
                "普通自动闲逛的窗口位移；手动移动动作仍是每换帧12像素×大小，遁光仍按"
                "图集中 travelDistanceRatio 和动作进度计算，动画帧时长也不受此项影响。"
            ),
        ),
        MenuItem(
            "回到屏幕中央",
            MenuCommand("center"),
            description=(
                "先读取鼠标所在显示器，再取扣除任务栏后的 availableGeometry，把宠物窗口"
                "的中心精确放到该可用区域中心，并再次限制在屏幕边界内。它会中断当前闲逛，"
                "但不改变宠物、大小、速度、开关或开机启动设置；退出时会保存新位置。"
            ),
        ),
        _toggle(
            "显示详情",
            "menu_details_enabled",
            "开启后，宠物右键菜单和托盘右键菜单的每一行右侧都会绘制一个圆形 ?。"
            "只有鼠标进入圆圈及其周围4像素的命中区才显示说明，停在文字、勾选框或子菜单"
            "箭头上都不会弹出；说明会随当前宠物和 JSON 参数动态更新。再次点击可关闭，"
            "选择保存在 %APPDATA%\\DesktopCompanion\\settings.ini。",
        ),
        MenuItem(
            "关于桌面灵伴",
            MenuCommand("about"),
            description=(
                "打开信息窗口，显示当前安装版本、这次扫描后通过校验的宠物总数，以及全部"
                "可切换宠物名称。这里只读，不修改设置；若刚复制宠物但数量没变化，请先使用"
                "“重新扫描宠物”。"
            ),
        ),
        MenuItem(
            "退出",
            MenuCommand("quit"),
            description=(
                "停止16毫秒动画计时器、50毫秒注视计时器、闲逛/自主动作计时器和数字键钩子，"
                "保存宠物、位置、大小、速度及开关到 %APPDATA%\\DesktopCompanion\\settings.ini，"
                "然后关闭宠物和托盘图标。这不会卸载或删除宠物包；若“开机启动”仍勾选，"
                "下次登录Windows时还会重新启动。"
            ),
        ),
    )


class MenuController:
    """Materialize the shared command model as refreshable Qt menus."""

    def __init__(
        self,
        settings_supplier: Callable[[], AppSettings],
        startup_supplier: Callable[[], bool],
        dispatch: Callable[[MenuCommand], None],
        error_reporter: ErrorReporter | None = None,
        pet_choices_supplier: Callable[[], tuple[tuple[str, str], ...]] | None = None,
        action_items_supplier: Callable[[], tuple[tuple[str, ActionKey], ...]] | None = None,
        look_degrees_supplier: Callable[[], tuple[float, ...]] | None = None,
        action_details_supplier: Callable[[], Mapping[ActionKey, str]] | None = None,
        gaze_frame_count_supplier: Callable[[], int] | None = None,
        shortcut_labels_supplier: Callable[[], tuple[tuple[int, str], ...]] | None = None,
    ) -> None:
        self._settings_supplier = settings_supplier
        self._startup_supplier = startup_supplier
        self._dispatch = dispatch
        self._error_reporter = error_reporter if error_reporter is not None else _LOGGER
        self._pet_choices_supplier = pet_choices_supplier or (lambda: ())
        self._action_items_supplier = action_items_supplier or (
            lambda: _DEFAULT_ACTION_ITEMS
        )
        self._look_degrees_supplier = look_degrees_supplier or (
            lambda: tuple(index * 22.5 for index in range(16))
        )
        self._action_details_supplier = action_details_supplier or (lambda: {})
        self._gaze_frame_count_supplier = gaze_frame_count_supplier or (lambda: 16)
        self._shortcut_labels_supplier = shortcut_labels_supplier or (lambda: ())
        self._menus: list[QMenu] = []

    @property
    def items(self) -> tuple[MenuItem, ...]:
        return _menu_items(
            self._pet_choices(),
            self._action_items(),
            self._look_degrees(),
            self._action_details(),
            self._gaze_frame_count(),
            self._shortcut_labels(),
        )

    def flattened_labels(self) -> tuple[str, ...]:
        def flatten(items: tuple[MenuItem, ...]):
            for item in items:
                yield item.label
                yield from flatten(item.children)

        return tuple(flatten(self.items))

    def create_menu(self, parent: QWidget | None = None) -> QMenu:
        menu = _DetailMenu(parent)
        self._rebuild(menu)
        menu.aboutToShow.connect(lambda current=menu: self.refresh(current))
        self._menus.append(menu)
        return menu

    def _rebuild(self, menu: QMenu, details_enabled: bool = False) -> None:
        previous_filter = getattr(menu, "_shiyi_detail_help_filter", None)
        if previous_filter is not None:
            menu.removeEventFilter(previous_filter)
            previous_filter.deleteLater()
            menu._shiyi_detail_help_filter = None
        menu.clear()
        bindings: list[_ActionBinding] = []
        groups: dict[str, QActionGroup] = {}
        retained: list[object] = []
        self._populate(
            menu, self.items, bindings, groups, retained, details_enabled
        )
        menu._shiyi_bindings = bindings
        menu._shiyi_retained = retained

    def refresh(self, menu: QMenu) -> None:
        try:
            settings = self._settings_supplier()
            if not isinstance(settings, AppSettings):
                raise TypeError("settings supplier returned an invalid value")
        except Exception as error:
            settings = AppSettings()
            self._report_supplier_error("settings supplier", error)

        try:
            startup_enabled = bool(self._startup_supplier())
        except Exception as error:
            startup_enabled = False
            self._report_supplier_error("startup supplier", error)

        self._rebuild(menu, settings.menu_details_enabled)

        bindings = menu._shiyi_bindings
        for binding in bindings:
            source = binding.item.checked_from
            if source is None:
                continue
            actual = (
                startup_enabled
                if source == "startup_enabled"
                else getattr(settings, source)
            )
            expected = binding.item.checked_value
            binding.action.setChecked(bool(actual) if expected is None else actual == expected)

    def refresh_all(self) -> None:
        for menu in tuple(self._menus):
            self.refresh(menu)

    def _pet_choices(self) -> tuple[tuple[str, str], ...]:
        try:
            choices = tuple(self._pet_choices_supplier())
            if any(
                not isinstance(pet_id, str)
                or not isinstance(display_name, str)
                or not pet_id
                or not display_name
                for pet_id, display_name in choices
            ):
                raise TypeError("pet choices supplier returned invalid values")
            return choices
        except Exception as error:
            self._report_supplier_error("pet choices supplier", error)
            return ()

    def _action_items(self) -> tuple[tuple[str, ActionKey], ...]:
        try:
            items = tuple(self._action_items_supplier())
            if (
                not items
                or len({action for _, action in items}) != len(items)
                or any(
                    not isinstance(label, str)
                    or not label
                    or not isinstance(action, str)
                    or not action
                    for label, action in items
                )
            ):
                raise TypeError("action items supplier returned invalid values")
            return items
        except Exception as error:
            self._report_supplier_error("action items supplier", error)
            return _DEFAULT_ACTION_ITEMS

    def _look_degrees(self) -> tuple[float, ...]:
        try:
            values = tuple(self._look_degrees_supplier())
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0.0 <= float(value) < 360.0
                for value in values
            ):
                raise TypeError("look degrees supplier returned invalid values")
            return tuple(float(value) for value in values)
        except Exception as error:
            self._report_supplier_error("look degrees supplier", error)
            return ()

    def _action_details(self) -> dict[ActionKey, str]:
        try:
            details = dict(self._action_details_supplier())
            if any(
                not isinstance(action, str)
                or not action
                or not isinstance(description, str)
                or not description.strip()
                for action, description in details.items()
            ):
                raise TypeError("action details supplier returned invalid values")
            return details
        except Exception as error:
            self._report_supplier_error("action details supplier", error)
            return {}

    def _gaze_frame_count(self) -> int:
        try:
            count = self._gaze_frame_count_supplier()
            if not isinstance(count, int) or isinstance(count, bool) or count not in {0, 16, 32, 64}:
                raise TypeError("gaze frame count supplier returned an invalid value")
            return count
        except Exception as error:
            self._report_supplier_error("gaze frame count supplier", error)
            return 0

    def _shortcut_labels(self) -> tuple[tuple[int, str], ...]:
        try:
            labels = tuple(self._shortcut_labels_supplier())
            if any(
                not isinstance(digit, int)
                or isinstance(digit, bool)
                or digit not in range(10)
                or not isinstance(label, str)
                or not label
                for digit, label in labels
            ):
                raise TypeError("shortcut labels supplier returned invalid values")
            return labels
        except Exception as error:
            self._report_supplier_error("shortcut labels supplier", error)
            return ()

    def _report_supplier_error(self, context: str, error: Exception) -> None:
        error_type = type(error).__name__
        try:
            warning = getattr(self._error_reporter, "warning", None)
            if callable(warning):
                warning("%s failed (%s)", context, error_type)
            else:
                self._error_reporter(context, error_type)
        except Exception:
            _LOGGER.warning("menu error reporter failed for %s (%s)", context, error_type)

    def _populate(
        self,
        menu: QMenu,
        items: tuple[MenuItem, ...],
        bindings: list[_ActionBinding],
        groups: dict[str, QActionGroup],
        retained: list[object],
        details_enabled: bool,
    ) -> None:
        menu.setToolTipsVisible(False)
        if isinstance(menu, _DetailMenu):
            menu.set_detail_help_enabled(details_enabled)
        if details_enabled:
            help_filter = _MenuDetailHelpFilter(menu)
            menu.installEventFilter(help_filter)
            menu._shiyi_detail_help_filter = help_filter
            retained.append(help_filter)
        for item in items:
            tooltip = self._wrap_description(item.description) if details_enabled else ""
            if item.children:
                submenu = _DetailMenu(menu)
                submenu.setTitle(item.label)
                menu.addMenu(submenu)
                submenu.menuAction().setText(item.label)
                submenu.menuAction().setToolTip(tooltip)
                submenu.menuAction().setProperty("_shiyi_label", item.label)
                retained.append(submenu)
                self._populate(
                    submenu,
                    item.children,
                    bindings,
                    groups,
                    retained,
                    details_enabled,
                )
                continue

            action = menu.addAction(item.label)
            action.setToolTip(tooltip)
            action.setProperty("_shiyi_label", item.label)
            retained.append(action)
            if item.checked_from is not None:
                action.setCheckable(True)
            if item.radio_group is not None:
                group = groups.get(item.radio_group)
                if group is None:
                    group = QActionGroup(menu)
                    group.setExclusive(True)
                    groups[item.radio_group] = group
                    retained.append(group)
                group.addAction(action)
            if item.command is not None:
                action.triggered.connect(
                    lambda checked=False, current=item: self._trigger(current, checked)
                )
            bindings.append(_ActionBinding(action, item))

    @staticmethod
    def _wrap_description(description: str) -> str:
        return "\n".join(
            textwrap.wrap(
                description,
                width=34,
                break_long_words=True,
                break_on_hyphens=False,
            )
        )

    def _trigger(self, item: MenuItem, checked: bool) -> None:
        command = item.command
        if command is None:
            return
        if command.kind == "toggle":
            command = replace(command, value=bool(checked))
        self._dispatch(command)
