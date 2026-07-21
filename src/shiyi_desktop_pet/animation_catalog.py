from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .constants import (
    ACTION_SPECS,
    CELL_HEIGHT,
    CELL_WIDTH,
    DEFAULT_PET_ACTIONS,
    KEY_TO_ACTION,
    LOOK_DEGREES,
)
from .models import (
    ActionId,
    ActionKey,
    ActionRole,
    AnimationSpec,
    FrameAsset,
    PetActionDefinition,
    PetStateDefinition,
)
from .pet_registry import PetDefinition, PetRegistry
from .resource_locator import resource_root


def _has_visible_pixel(image: QImage) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


def _seconds(milliseconds: int) -> str:
    value = milliseconds / 1000.0
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _action_timing_text(spec: AnimationSpec) -> str:
    durations = spec.durations
    if len(set(durations)) == 1:
        frame_text = (
            f"{spec.frame_count} 帧，每帧 {durations[0]} 毫秒"
            f"（约 {1000 / durations[0]:.1f} 帧/秒）"
        )
    else:
        average = spec.cycle_ms / spec.frame_count
        frame_text = (
            f"{spec.frame_count} 帧，单帧 {min(durations)}–{max(durations)} 毫秒"
            f"（平均 {average:.0f} 毫秒/帧，约 {1000 / average:.1f} 帧/秒）"
        )
    if spec.loops is None:
        playback = f"单轮 {_seconds(spec.cycle_ms)} 秒并持续循环"
    else:
        total_ms = spec.cycle_ms * spec.loops + spec.hold_ms
        playback = f"播放 {spec.loops} 轮，总时长约 {_seconds(total_ms)} 秒"
        if spec.hold_ms:
            playback += f"（其中末帧停留 {_seconds(spec.hold_ms)} 秒）"
    return f"{frame_text}；{playback}"


def _nominal_weight_text(weight: int, total: int, pool_name: str) -> str:
    if weight <= 0:
        return f"不会进入{pool_name}的自动候选池"
    percentage = weight / max(1, total) * 100
    return (
        f"{pool_name}基础权重为 {weight}/{max(1, total)}"
        f"（全部候选均可用时约 {percentage:.1f}%）"
    )


class AnimationCatalog:
    """Validated atlas and semantic action catalog for v2 and dynamic v3 pets."""

    def __init__(
        self,
        atlas: QImage,
        *,
        pet_id: str = "custom",
        display_name: str = "",
        icon_frame: tuple[int, int] = (0, 0),
        actions: tuple[PetActionDefinition, ...] = DEFAULT_PET_ACTIONS,
        states: tuple[PetStateDefinition, ...] = (),
        sprite_version: int = 2,
    ):
        if atlas.isNull():
            raise ValueError("spritesheet could not be decoded")
        if not atlas.hasAlphaChannel():
            raise ValueError("spritesheet must have alpha")
        if sprite_version == 2:
            if (atlas.width(), atlas.height()) != (1536, 2288):
                raise ValueError("spritesheet must be 1536x2288")
        elif sprite_version == 3:
            if (
                atlas.width() % CELL_WIDTH
                or atlas.height() % CELL_HEIGHT
                or atlas.width() <= 0
                or atlas.height() <= 0
            ):
                raise ValueError("v3 spritesheet dimensions must be cell-size multiples")
            cell_total = (atlas.width() // CELL_WIDTH) * (
                atlas.height() // CELL_HEIGHT
            )
            if cell_total > 2_048 or atlas.width() * atlas.height() > 50_000_000:
                raise ValueError("v3 spritesheet grid is too large")
        else:
            raise ValueError("unsupported sprite version")

        self.pet_id = pet_id
        self.display_name = display_name
        self.sprite_version = sprite_version
        self._atlas = atlas.convertToFormat(QImage.Format.Format_RGBA8888)
        self.columns = self._atlas.width() // CELL_WIDTH
        self.rows = self._atlas.height() // CELL_HEIGHT
        if (
            not isinstance(icon_frame, tuple)
            or len(icon_frame) != 2
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in icon_frame
            )
            or not 0 <= icon_frame[0] < self.rows
            or not 0 <= icon_frame[1] < self.columns
        ):
            raise ValueError("iconFrame is outside the atlas")
        self.icon_frame = icon_frame

        action_map = {definition.action_id: definition for definition in actions}
        if len(action_map) != len(actions):
            raise ValueError("action ids must be unique")
        if sprite_version == 2 and set(action_map) != set(ACTION_SPECS):
            raise ValueError("actions must define every v2 atlas action exactly once")
        if sprite_version == 3:
            if not any(item.role is ActionRole.IDLE for item in actions):
                raise ValueError("v3 actions must define idle")
            if any(item.spec is None for item in actions):
                raise ValueError("v3 actions must define animation timing")

        self._action_definitions = tuple(actions)
        self._action_map = action_map
        self._state_definitions = tuple(states)
        self._state_map = {state.key: state for state in states}
        self._state_by_enter_action = {
            state.enter_action: state for state in states
        }
        if len(self._state_map) != len(states) or len(
            self._state_by_enter_action
        ) != len(states):
            raise ValueError("state ids and enter actions must be unique")
        if any(
            action_id not in action_map
            for state in states
            for action_id in (
                state.enter_action,
                *(choice.action_id for choice in state.resident_actions),
                state.exit_action,
            )
        ):
            raise ValueError("state references an unknown action")
        self._specs: dict[ActionKey, AnimationSpec] = {}
        self._actions: dict[ActionKey, tuple[FrameAsset, ...]] = {}

        if sprite_version == 2:
            used_counts = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
            for row, used in enumerate(used_counts):
                for column in range(8):
                    visible = _has_visible_pixel(self._cell(row, column))
                    if visible is not (column < used):
                        raise ValueError(
                            f"unexpected occupancy at row {row} column {column}"
                        )

        for definition in actions:
            spec = definition.spec
            if spec is None:
                spec = ACTION_SPECS[definition.action_id]
            self._specs[definition.action_id] = spec
            coordinates = self._frame_coordinates(spec)
            frames: list[FrameAsset] = []
            for row, column in coordinates:
                image = self._cell(row, column)
                variant = ""
                if definition.mirror_of is not None:
                    image = image.flipped(Qt.Orientation.Horizontal)
                    variant = f"mirror:{definition.action_id}"
                if not _has_visible_pixel(image):
                    raise ValueError(
                        f"action {definition.key} uses empty cell at row {row} column {column}"
                    )
                frames.append(FrameAsset(image, row, column, variant))
            self._actions[definition.action_id] = tuple(frames)

        self._idle_action = next(
            definition.action_id
            for definition in actions
            if definition.role is ActionRole.IDLE
        )
        gaze = next(
            (item for item in actions if item.role is ActionRole.GAZE), None
        )
        if sprite_version == 2:
            self.look_degrees = LOOK_DEGREES
            self._look_frames = tuple(
                FrameAsset(self._cell(9 + index // 8, index % 8), 9 + index // 8, index % 8)
                for index in range(16)
            )
        elif gaze is not None:
            self._look_frames = self._actions[gaze.action_id]
            step = 360.0 / len(self._look_frames)
            self.look_degrees = tuple(
                index * step for index in range(len(self._look_frames))
            )
        else:
            self.look_degrees = ()
            self._look_frames = ()
        menu_stride = max(1, len(self.look_degrees) // 16)
        self.manual_look_degrees = self.look_degrees[::menu_stride]

        self._icon_image = self._cell(*self.icon_frame)
        if not _has_visible_pixel(self._icon_image):
            raise ValueError("iconFrame must select a visible atlas cell")

    @classmethod
    def load_default(cls) -> "AnimationCatalog":
        return cls.load_pet("shiyi")

    @classmethod
    def load_pet(cls, pet_id: str) -> "AnimationCatalog":
        snapshot = PetRegistry(resource_root() / "pets", None).refresh()
        definition = snapshot.by_id(pet_id)
        if definition is None:
            raise ValueError(f"unknown pet: {pet_id}")
        return cls.load_definition(definition)

    @classmethod
    def load_definition(cls, definition: PetDefinition) -> "AnimationCatalog":
        return cls(
            QImage(str(definition.spritesheet_path)),
            pet_id=definition.pet_id,
            display_name=definition.display_name,
            icon_frame=definition.icon_frame,
            actions=definition.actions,
            states=definition.states,
            sprite_version=definition.sprite_version,
        )

    @property
    def idle_action(self) -> ActionKey:
        return self._idle_action

    @property
    def supports_gaze(self) -> bool:
        return bool(self._look_frames)

    @property
    def action_ids(self) -> tuple[ActionKey, ...]:
        return tuple(self._actions)

    @property
    def atlas_size(self) -> tuple[int, int]:
        return self._atlas.width(), self._atlas.height()

    def _cell(self, row: int, column: int) -> QImage:
        return self._atlas.copy(
            column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT
        )

    def _frame_coordinates(self, spec: AnimationSpec) -> tuple[tuple[int, int], ...]:
        start = spec.row * self.columns + spec.start_column
        coordinates = tuple(
            divmod(start + offset, self.columns)
            for offset in range(spec.frame_count)
        )
        if not coordinates or coordinates[-1][0] >= self.rows:
            raise ValueError("action frames extend outside the spritesheet")
        return coordinates

    def frames(self, action: ActionKey) -> tuple[FrameAsset, ...]:
        return self._actions[action]

    def spec(self, action: ActionKey) -> AnimationSpec:
        return self._specs[action]

    def definition(self, action: ActionKey) -> PetActionDefinition:
        return self._action_map[action]

    @property
    def states(self) -> tuple[PetStateDefinition, ...]:
        return self._state_definitions

    def state_for_enter_action(
        self, action: ActionKey
    ) -> PetStateDefinition | None:
        return self._state_by_enter_action.get(action)

    def state_definition(self, key: str) -> PetStateDefinition:
        return self._state_map[key]

    def icon_image(self) -> QImage:
        return self._icon_image.copy()

    def action_menu_items(self) -> tuple[tuple[str, ActionKey], ...]:
        return tuple(
            (definition.label, definition.action_id)
            for definition in self._action_definitions
            if definition.show_in_menu and definition.role is not ActionRole.GAZE
        )

    def action_menu_details(self) -> dict[ActionKey, str]:
        """Build precise, pet-specific help text from validated action metadata."""
        interaction_total = sum(
            definition.autoplay_weight
            for definition in self._action_definitions
            if definition.role is ActionRole.INTERACTION
            and definition.autoplay_weight > 0
        )
        movement_totals = {
            direction: sum(
                definition.autoplay_weight
                for definition in self._action_definitions
                if definition.role in {ActionRole.MOVE, ActionRole.BURST_MOVE}
                and definition.direction == direction
                and definition.autoplay_weight > 0
            )
            for direction in (-1, 1)
        }
        details: dict[ActionKey, str] = {}
        for definition in self._action_definitions:
            if not definition.show_in_menu or definition.role is ActionRole.GAZE:
                continue
            spec = self.spec(definition.action_id)
            timing = _action_timing_text(spec)
            speed_note = (
                "以上时长按“正常”动画速度计算；慢速时长乘 1.25，快速时长乘 0.75。"
            )
            if definition.role is ActionRole.IDLE:
                behavior = (
                    "这是没有手动动作、闲逛或注视任务时使用的基础待机；"
                    "从菜单选择它会立即结束当前手动动作并回到待机。"
                )
            elif definition.role is ActionRole.MOVE:
                direction = "右" if definition.direction > 0 else "左"
                weight = _nominal_weight_text(
                    definition.autoplay_weight,
                    movement_totals[definition.direction],
                    "同方向闲逛动作",
                )
                behavior = (
                    f"这是普通向{direction}移动。自动闲逛时，窗口按慢速 75、正常 120、"
                    "快速 180 像素/秒移动；手动选择时，100% 大小每切换一帧横移 12 像素，"
                    f"大小设置会同比缩放该距离。{weight}。"
                )
            elif definition.role is ActionRole.BURST_MOVE:
                direction = "右" if definition.direction > 0 else "左"
                start_frame = (definition.travel_start_frame or 0) + 1
                end_frame = (
                    definition.travel_end_frame
                    if definition.travel_end_frame is not None
                    else spec.frame_count - 1
                ) + 1
                ratio = definition.travel_distance_ratio or 0.0
                vertical = definition.max_vertical_ratio or 0.0
                weight = _nominal_weight_text(
                    definition.autoplay_weight,
                    movement_totals[definition.direction],
                    "同方向闲逛动作",
                )
                behavior = (
                    f"这是向{direction}遁光，位移集中在第 {start_frame}–{end_frame} 帧。"
                    f"目标横向距离为屏幕可移动宽度的 {ratio * 100:.0f}%；自动闲逛只有距离至少"
                    f" {definition.min_distance} 像素且边缘空间足够时才允许触发，垂直偏移最多为"
                    f"可移动高度的 {vertical * 100:.0f}%。{weight}；单次触发后冷却"
                    f" {_seconds(definition.cooldown_ms)} 秒。"
                )
            else:
                state = self.state_for_enter_action(definition.action_id)
                weight = _nominal_weight_text(
                    definition.autoplay_weight,
                    interaction_total,
                    "自主小动作",
                )
                if state is None:
                    behavior = f"{weight}"
                else:
                    resident_total = sum(
                        choice.weight for choice in state.resident_actions
                    )
                    resident_text = "、".join(
                        f"{self.definition(choice.action_id).label}约"
                        f"{choice.weight / resident_total * 100:.0f}%"
                        for choice in state.resident_actions
                    )
                    ramp_end = state.min_duration_ms + state.ramp_duration_ms
                    behavior = (
                        f"这是“{state.label}”常驻状态的进入动作。坐稳后至少停留"
                        f" {_seconds(state.min_duration_ms)} 秒；到"
                        f" {_seconds(ramp_end)} 秒后每个坐姿小动作结束时的退出概率提高到"
                        f" {state.exit_chance_after_ramp}%，最迟"
                        f" {_seconds(state.max_duration_ms)} 秒强制起身。状态内随机为："
                        f"{resident_text}；不会连续重复同一小动作。再次选择本项可请求自然结束。"
                        f"{weight}"
                    )
                if definition.cooldown_ms:
                    behavior += (
                        f"；播放一次后至少冷却 {_seconds(definition.cooldown_ms)} 秒，"
                        "冷却期间随机动作不会再次选中它"
                    )
                if definition.autoplay_group:
                    behavior += (
                        f"；属于“{definition.autoplay_group}”特效组，程序会避免同组动作连续出现"
                    )
                behavior += "。"
            details[definition.action_id] = f"{timing}。{behavior}{speed_note}"
        return details

    def digit_shortcut_labels(self) -> tuple[tuple[int, str], ...]:
        """Return the current pet's resolved labels for the fixed 1–9/0 slots."""
        labels: list[tuple[int, str]] = []
        for digit in (*range(1, 10), 0):
            requested = KEY_TO_ACTION[digit]
            if requested is ActionId.RANDOM:
                labels.append((digit, "按权重随机"))
                continue
            try:
                action = self.resolve_action(requested)
            except ValueError:
                continue
            labels.append((digit, self.definition(action).label))
        return tuple(labels)

    def autoplay_actions(self) -> tuple[tuple[ActionKey, int], ...]:
        return tuple(
            (definition.action_id, definition.autoplay_weight)
            for definition in self._action_definitions
            if definition.role is ActionRole.INTERACTION
            and definition.autoplay_weight > 0
        )

    def interaction_actions(self) -> tuple[ActionKey, ...]:
        return tuple(
            definition.action_id
            for definition in self._action_definitions
            if definition.role is ActionRole.INTERACTION
        )

    def showcase_actions(self) -> tuple[ActionKey, ...]:
        return tuple(
            definition.action_id
            for definition in self._action_definitions
            if definition.role is ActionRole.INTERACTION
            and (definition.show_in_menu or definition.autoplay_weight > 0)
            and definition.action_id not in self._state_by_enter_action
        )

    def movement_actions(
        self, direction: int, *, include_burst: bool = True
    ) -> tuple[PetActionDefinition, ...]:
        roles = (
            {ActionRole.MOVE, ActionRole.BURST_MOVE}
            if include_burst
            else {ActionRole.MOVE}
        )
        return tuple(
            definition
            for definition in self._action_definitions
            if definition.role in roles and definition.direction == direction
        )

    def resolve_action(self, requested: ActionKey) -> ActionKey:
        if requested in self._actions:
            return self._action_map[requested].action_id
        if requested is ActionId.IDLE:
            return self.idle_action
        if requested in {ActionId.RUN_LEFT, ActionId.RUN_RIGHT}:
            direction = -1 if requested is ActionId.RUN_LEFT else 1
            candidates = self.movement_actions(direction, include_burst=False)
            if candidates:
                return candidates[0].action_id
        preferred_keys = {
            ActionId.WAVE: "greet",
            ActionId.JUMP: "jump",
            ActionId.BELLY_FLOP: "special",
            ActionId.EXPECT: "wait",
            ActionId.PATROL: "observe",
            ActionId.CURIOUS: "curious",
        }
        preferred = preferred_keys.get(requested)
        if preferred in self._actions:
            return self._action_map[preferred].action_id
        if not isinstance(requested, ActionId):
            raise ValueError(f"unsupported action: {requested}")
        interactions = self.interaction_actions()
        if interactions:
            return interactions[0]
        raise ValueError(f"unsupported action: {requested}")

    def look_frame(self, degrees: float) -> FrameAsset:
        step = 360.0 / len(self._look_frames) if self._look_frames else 0.0
        index = round(degrees / step) if step else 0
        if (
            not self.supports_gaze
            or not 0.0 <= degrees < 360.0
            or abs(degrees - index * step) > 1e-6
        ):
            raise ValueError("direction must be a supported gaze step")
        return self._look_frames[index % len(self._look_frames)]

    def nearest_look_frame(self, degrees: float) -> FrameAsset:
        """Return the nearest clear gaze keyframe for an arbitrary angle."""
        if (
            not self.supports_gaze
            or not isinstance(degrees, (int, float))
            or isinstance(degrees, bool)
            or not 0.0 <= float(degrees) < 360.0
        ):
            raise ValueError("direction must be between 0 and 360 degrees")
        step = 360.0 / len(self._look_frames)
        index = round(float(degrees) / step) % len(self._look_frames)
        return self._look_frames[index]

    def hit_test(self, frame: FrameAsset, x: float, y: float, scale: float) -> bool:
        if scale <= 0 or x < 0 or y < 0:
            return False
        source_x, source_y = int(x / scale), int(y / scale)
        if not 0 <= source_x < CELL_WIDTH or not 0 <= source_y < CELL_HEIGHT:
            return False
        return frame.image.pixelColor(source_x, source_y).alpha() > 0
