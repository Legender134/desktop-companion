# 十一独立桌面宠物 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个不依赖 Codex、Python 或 Qt 预安装环境的 Windows 10/11 x64 桌面宠物，并交付默认开机启动、可卸载的“十一桌面宠物安装程序.exe”。

**Architecture:** 应用使用 PySide6 绘制透明无边框宠物窗口，以纯逻辑状态机协调手动动作、闲逛、看向鼠标和拖动。Windows 专属适配层负责低级键盘钩子、当前用户开机启动和单实例 IPC；PyInstaller one-folder 构建交给 Inno Setup 封装为单一安装程序。

**Tech Stack:** CPython 3.12.10、PySide6 6.11.1、PyInstaller 6.21.0、pytest 9.1.1、pytest-qt 4.5.0、coverage 7.15.1、Pillow 12.3.0（仅构建图标）、Inno Setup 7.0.2、Windows `ctypes`/`winreg` API。

## Global Constraints

- Before Task 1, read and follow the user-requested `hatch-pet` skill for v2 resource validation and packaging constraints; reuse the approved atlas unchanged rather than generating new art.
- Before Task 12's native UI inspection, read and follow `computer-use:computer-use`; use it only after automated gates pass.
- 目标平台固定为 Windows 10/11 x64，按当前用户安装，`PrivilegesRequired=lowest`，不请求管理员权限。
- 运行时不联网、不上传数据、不记录键盘文本；低级钩子只识别并按规则消费数字键的按下与抬起。
- 唯一动画来源是现有 `shiyi` v2 资源：RGBA WebP、`1536×2288`、`8×11`、单元格 `192×208`、74 个必需帧和 14 个透明空槽。
- 动作优先级固定为 `DRAGGING > MANUAL_ACTION > WANDER > GAZE > IDLE`。
- 首次启动：自动闲逛关、看向鼠标开、数字快捷键开、置顶开、开机启动开、100% 大小、正常速度。
- 设置保存在 `%APPDATA%\ShiyiDesktopPet\settings.ini`；日志保存在 `%LOCALAPPDATA%\ShiyiDesktopPet\logs`。
- 安装目录固定为 `%LOCALAPPDATA%\Programs\ShiyiDesktopPet`；安装器 AppId 固定为 `{5F4B3AD9-7C91-4E2D-A4C4-70C5C4F5A211}`。
- 覆盖安装保留设置和用户当前开机启动选择；卸载删除 Run 值、程序、设置和日志。
- 所有功能和修复遵循 TDD：先观察目标测试因缺少行为而失败，再写最小实现，再跑完整相关测试。
- 现有 Codex 宠物目录、原始照片/视频和 `outputs/shiyi-pet` 不得修改。

## Dependency Sources

- PySide6: `https://pypi.org/project/PySide6/`
- PyInstaller: `https://pypi.org/project/pyinstaller/`
- pytest: `https://pypi.org/project/pytest/`
- pytest-qt: `https://pypi.org/project/pytest-qt/`
- Inno Setup: `https://jrsoftware.org/isinfo.php`

## Planned File Structure

```text
pyproject.toml
requirements/
  runtime.txt
  dev.txt
src/shiyi_desktop_pet/
  __init__.py              # version and package identity
  __main__.py              # process entry point
  app.py                   # application composition and CLI modes
  models.py                # enums and immutable data models
  constants.py             # atlas contract, action specs, product constants
  resource_locator.py      # source/frozen resource resolution
  animation_catalog.py     # atlas loading, slicing, alpha hit masks
  animation_player.py      # deterministic frame/loop/hold timeline
  behavior.py              # behavior state machine and command priority
  gaze.py                  # cursor angle quantization and stabilization
  geometry.py              # pure point/rect/clamp helpers
  wander.py                # random target and boundary-aware motion
  settings.py              # versioned INI persistence
  startup.py               # HKCU Run value adapter
  keyboard_hook.py         # decision engine and WH_KEYBOARD_LL thread
  pet_window.py            # transparent shaped widget and mouse signals
  menu_controller.py       # shared pet/tray command menus
  tray_controller.py       # QSystemTrayIcon integration
  single_instance.py       # mutex plus QLocalServer/QLocalSocket IPC
  logging_setup.py         # rotating logs and exception hook
  resources/
    pet.json
    spritesheet.webp
    app.ico
tests/
  conftest.py
  test_resource_contract.py
  test_animation_catalog.py
  test_animation_player.py
  test_behavior.py
  test_gaze.py
  test_wander.py
  test_settings.py
  test_startup.py
  test_keyboard_hook.py
  test_pet_window.py
  test_menu_controller.py
  test_single_instance.py
  test_app.py
  integration/test_frozen_smoke.py
tools/make_icon.py
packaging/ShiyiDesktopPet.spec
packaging/installer.iss
scripts/build_app.ps1
scripts/build_installer.ps1
scripts/verify_release.ps1
THIRD_PARTY_NOTICES.md
README.md
```

---

### Task 1: Scaffold the Package and Lock the V2 Resource Contract

**Files:**
- Modify: `.gitignore`
- Create: `pyproject.toml`
- Create: `requirements/runtime.txt`
- Create: `requirements/dev.txt`
- Create: `src/shiyi_desktop_pet/__init__.py`
- Create: `src/shiyi_desktop_pet/resource_locator.py`
- Create: `src/shiyi_desktop_pet/resources/pet.json`
- Create: `src/shiyi_desktop_pet/resources/spritesheet.webp`
- Create: `tests/conftest.py`
- Create: `tests/test_resource_contract.py`

**Interfaces:**
- Consumes: approved installed resources `C:\Users\admin\.codex\pets\shiyi\pet.json` and `spritesheet.webp`.
- Produces: `resource_path(name: str) -> pathlib.Path`, pinned build environment, immutable source resources for every later task.

- [ ] **Step 1: Create the isolated environment and dependency lock files**

```text
# requirements/runtime.txt
PySide6==6.11.1

# requirements/dev.txt
-r runtime.txt
PyInstaller==6.21.0
pytest==9.1.1
pytest-qt==4.5.0
coverage==7.15.1
Pillow==12.3.0
```

Run:

```powershell
$BasePython = 'C:\Users\admin\.codex\runtimes\hatch-pet-python\Scripts\python.exe'
& $BasePython -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
& .\.venv\Scripts\python.exe -m pip check
```

Expected: `No broken requirements found.`

- [ ] **Step 2: Write the failing resource contract test**

```python
# tests/test_resource_contract.py
import json
from PySide6.QtGui import QImage
from shiyi_desktop_pet.resource_locator import resource_path

FRAME_COUNTS = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)

def alpha_count(image: QImage) -> int:
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    )

def test_packaged_resources_obey_shiyi_v2_contract():
    manifest = json.loads(resource_path("pet.json").read_text(encoding="utf-8"))
    assert manifest == {
        "id": "shiyi",
        "displayName": "十一",
        "description": "一只好奇亲人、略带呆萌气质的银黑经典虎斑猫。",
        "spriteVersionNumber": 2,
        "spritesheetPath": "spritesheet.webp",
    }
    atlas = QImage(str(resource_path("spritesheet.webp")))
    assert not atlas.isNull()
    assert (atlas.width(), atlas.height()) == (1536, 2288)
    assert atlas.hasAlphaChannel()
    for row, used in enumerate(FRAME_COUNTS):
        for column in range(8):
            cell = atlas.copy(column * 192, row * 208, 192, 208)
            assert (alpha_count(cell) > 0) is (column < used)
```

- [ ] **Step 3: Run the test and verify the missing package fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_resource_contract.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'shiyi_desktop_pet'`.

- [ ] **Step 4: Implement package metadata and resource resolution**

```python
# src/shiyi_desktop_pet/__init__.py
__version__ = "1.0.0"

# src/shiyi_desktop_pet/resource_locator.py
from pathlib import Path
import sys

def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / "resources" / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing desktop-pet resource: {path}")
    return path
```

Create the package configuration:

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"

[project]
name = "shiyi-desktop-pet"
version = "1.0.0"
requires-python = ">=3.12,<3.13"
dependencies = ["PySide6==6.11.1"]

[tool.setuptools]
package-dir = {"" = "src"}
include-package-data = true

[tool.setuptools.package-data]
shiyi_desktop_pet = ["resources/*"]

[tool.pytest.ini_options]
pythonpath = ["src"]
qt_api = "pyside6"
testpaths = ["tests"]
```

Add the shared repository fixture used by the later frozen-build test:

```python
# tests/conftest.py
from pathlib import Path
import pytest

@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
```

Copy the approved `pet.json` and `spritesheet.webp` byte-for-byte into `src/shiyi_desktop_pet/resources/`. Add `.venv/`, `build/`, `dist/`, `.pytest_cache/`, `__pycache__/`, `*.pyc`, and `artifacts/` to `.gitignore`.

- [ ] **Step 5: Run the contract test and verify exact resource hashes**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe -m pytest tests\test_resource_contract.py -q
Get-FileHash -Algorithm SHA256 src\shiyi_desktop_pet\resources\pet.json,src\shiyi_desktop_pet\resources\spritesheet.webp
```

Expected: `1 passed`; manifest SHA-256 `199D74D126E07C6DD1742F99856FBA94EF1403238F2698B648A4203B7710392F`; atlas SHA-256 `D9D16415521CFC61D90BDA99AAF975EA54382A4767A0ABFF72063656CE43F5E2`.

- [ ] **Step 6: Commit**

```powershell
git add .gitignore pyproject.toml requirements src\shiyi_desktop_pet\__init__.py src\shiyi_desktop_pet\resource_locator.py src\shiyi_desktop_pet\resources tests\conftest.py tests\test_resource_contract.py
git commit -m "build: scaffold Shiyi desktop pet"
```

---

### Task 2: Load, Slice, and Hit-Test Every Animation Frame

**Files:**
- Create: `src/shiyi_desktop_pet/models.py`
- Create: `src/shiyi_desktop_pet/constants.py`
- Create: `src/shiyi_desktop_pet/animation_catalog.py`
- Create: `tests/test_animation_catalog.py`

**Interfaces:**
- Consumes: `resource_path("spritesheet.webp")`.
- Produces: `ActionId`, `AnimationSpec`, `FrameAsset`, `AnimationCatalog.load_default()`, `frames(action)`, `look_frame(degrees)`, and `hit_test(frame, x, y, scale)`.

- [ ] **Step 1: Write failing catalog and alpha-hit tests**

```python
# tests/test_animation_catalog.py
import pytest
from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import ActionId

def test_catalog_exposes_all_actions_and_look_directions():
    catalog = AnimationCatalog.load_default()
    expected = {
        ActionId.IDLE: 7, ActionId.RUN_RIGHT: 8, ActionId.RUN_LEFT: 8,
        ActionId.WAVE: 4, ActionId.JUMP: 5, ActionId.BELLY_FLOP: 8,
        ActionId.EXPECT: 6, ActionId.PATROL: 6, ActionId.CURIOUS: 6,
    }
    assert {action: len(catalog.frames(action)) for action in expected} == expected
    assert tuple(catalog.look_degrees) == tuple(index * 22.5 for index in range(16))
    assert all(not catalog.look_frame(degrees).image.isNull() for degrees in catalog.look_degrees)

def test_alpha_hit_test_uses_scaled_visible_pixel():
    catalog = AnimationCatalog.load_default()
    frame = catalog.frames(ActionId.IDLE)[0]
    assert catalog.hit_test(frame, 96, 150, 1.0)
    assert not catalog.hit_test(frame, 0, 0, 1.0)
    assert catalog.hit_test(frame, 192, 300, 2.0)

def test_unknown_direction_is_rejected():
    with pytest.raises(ValueError, match="22.5-degree"):
        AnimationCatalog.load_default().look_frame(13.0)
```

- [ ] **Step 2: Run tests and verify missing interfaces fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_animation_catalog.py -q`

Expected: FAIL importing `shiyi_desktop_pet.animation_catalog`.

- [ ] **Step 3: Define the exact action model and atlas constants**

```python
# src/shiyi_desktop_pet/models.py
from dataclasses import dataclass
from enum import StrEnum
from PySide6.QtGui import QImage

class ActionId(StrEnum):
    IDLE = "idle"
    RUN_RIGHT = "running-right"
    RUN_LEFT = "running-left"
    WAVE = "waving"
    JUMP = "jumping"
    BELLY_FLOP = "failed"
    EXPECT = "waiting"
    PATROL = "running"
    CURIOUS = "review"
    RANDOM = "random"

@dataclass(frozen=True)
class AnimationSpec:
    row: int
    frame_count: int
    frame_ms: int
    loops: int | None
    hold_ms: int = 0
    movement: int = 0

@dataclass(frozen=True)
class FrameAsset:
    image: QImage
    row: int
    column: int
```

```python
# src/shiyi_desktop_pet/constants.py
from .models import ActionId, AnimationSpec

CELL_WIDTH, CELL_HEIGHT, COLUMNS, ROWS = 192, 208, 8, 11
LOOK_DEGREES = tuple(index * 22.5 for index in range(16))
ACTION_SPECS = {
    ActionId.IDLE: AnimationSpec(0, 7, 180, None),
    ActionId.RUN_RIGHT: AnimationSpec(1, 8, 90, 1, movement=1),
    ActionId.RUN_LEFT: AnimationSpec(2, 8, 90, 1, movement=-1),
    ActionId.WAVE: AnimationSpec(3, 4, 150, 2),
    ActionId.JUMP: AnimationSpec(4, 5, 120, 1),
    ActionId.BELLY_FLOP: AnimationSpec(5, 8, 150, 1, hold_ms=1000),
    ActionId.EXPECT: AnimationSpec(6, 6, 180, 1),
    ActionId.PATROL: AnimationSpec(7, 6, 140, 1),
    ActionId.CURIOUS: AnimationSpec(8, 6, 170, 1),
}
KEY_TO_ACTION = {
    1: ActionId.IDLE, 2: ActionId.RUN_RIGHT, 3: ActionId.RUN_LEFT,
    4: ActionId.WAVE, 5: ActionId.JUMP, 6: ActionId.BELLY_FLOP,
    7: ActionId.EXPECT, 8: ActionId.PATROL, 9: ActionId.CURIOUS,
    0: ActionId.RANDOM,
}
```

- [ ] **Step 4: Implement atlas validation, slicing, and scaled alpha hit-testing**

`AnimationCatalog.__init__` must reject null images, non-`1536×2288` images, images without alpha, empty used cells, and non-empty unused cells. Implement the module with this exact behavior:

```python
from PySide6.QtGui import QImage
from .constants import ACTION_SPECS, CELL_HEIGHT, CELL_WIDTH, LOOK_DEGREES
from .models import ActionId, FrameAsset
from .resource_locator import resource_path

def _has_visible_pixel(image: QImage) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )

class AnimationCatalog:
    def __init__(self, atlas: QImage):
        if atlas.isNull():
            raise ValueError("spritesheet could not be decoded")
        if (atlas.width(), atlas.height()) != (1536, 2288):
            raise ValueError("spritesheet must be 1536x2288")
        if not atlas.hasAlphaChannel():
            raise ValueError("spritesheet must have alpha")
        self._atlas = atlas.convertToFormat(QImage.Format.Format_RGBA8888)
        self.look_degrees = LOOK_DEGREES
        used_counts = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
        for row, used in enumerate(used_counts):
            for column in range(8):
                visible = _has_visible_pixel(self._cell(row, column))
                if visible is not (column < used):
                    raise ValueError(f"unexpected occupancy at row {row} column {column}")
        self._actions = {
            action: tuple(
                FrameAsset(self._cell(spec.row, column), spec.row, column)
                for column in range(spec.frame_count)
            )
            for action, spec in ACTION_SPECS.items()
        }

    @classmethod
    def load_default(cls) -> "AnimationCatalog":
        return cls(QImage(str(resource_path("spritesheet.webp"))))

    def _cell(self, row: int, column: int) -> QImage:
        return self._atlas.copy(column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)

    def frames(self, action: ActionId) -> tuple[FrameAsset, ...]:
        return self._actions[action]

    def look_frame(self, degrees: float) -> FrameAsset:
        index = round(degrees / 22.5)
        if not 0.0 <= degrees < 360.0 or abs(degrees - index * 22.5) > 1e-6:
            raise ValueError("direction must be a 22.5-degree step from 0 through 337.5")
        row, column = 9 + index // 8, index % 8
        return FrameAsset(self._cell(row, column), row, column)

    def hit_test(self, frame: FrameAsset, x: float, y: float, scale: float) -> bool:
        if scale <= 0:
            return False
        source_x, source_y = int(x / scale), int(y / scale)
        if not 0 <= source_x < CELL_WIDTH or not 0 <= source_y < CELL_HEIGHT:
            return False
        return frame.image.pixelColor(source_x, source_y).alpha() > 0
```

- [ ] **Step 5: Run catalog plus resource contract tests**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_resource_contract.py tests\test_animation_catalog.py -q`

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```powershell
git add src\shiyi_desktop_pet\models.py src\shiyi_desktop_pet\constants.py src\shiyi_desktop_pet\animation_catalog.py tests\test_animation_catalog.py
git commit -m "feat: load Shiyi animation catalog"
```

---

### Task 3: Implement Deterministic Playback and Behavior Priority

**Files:**
- Create: `src/shiyi_desktop_pet/animation_player.py`
- Create: `src/shiyi_desktop_pet/behavior.py`
- Create: `tests/test_animation_player.py`
- Create: `tests/test_behavior.py`

**Interfaces:**
- Consumes: `ActionId`, `ACTION_SPECS`.
- Produces: `AnimationTimeline.start(action, now_ms)`, `advance(now_ms) -> PlaybackStep`; `BehaviorEngine` intent methods and `BehaviorMode`.

- [ ] **Step 1: Write failing playback tests for loops, hold, and completion**

```python
# tests/test_animation_player.py
from shiyi_desktop_pet.animation_player import AnimationTimeline
from shiyi_desktop_pet.models import ActionId

def test_wave_runs_exactly_two_loops_then_finishes():
    timeline = AnimationTimeline()
    timeline.start(ActionId.WAVE, now_ms=0)
    assert timeline.advance(0).frame_index == 0
    assert timeline.advance(1050).frame_index == 3
    assert not timeline.advance(1050).finished
    assert timeline.advance(1200).finished

def test_belly_flop_holds_last_frame_for_one_second():
    timeline = AnimationTimeline()
    timeline.start(ActionId.BELLY_FLOP, now_ms=0)
    assert timeline.advance(1199).frame_index == 7
    assert not timeline.advance(2199).finished
    assert timeline.advance(2200).finished
```

- [ ] **Step 2: Write failing behavior-priority tests**

```python
# tests/test_behavior.py
from shiyi_desktop_pet.behavior import BehaviorEngine, BehaviorMode
from shiyi_desktop_pet.models import ActionId

def test_priority_and_manual_return_to_remembered_wander():
    engine = BehaviorEngine()
    engine.set_wander_enabled(True)
    assert engine.mode is BehaviorMode.WANDER
    engine.trigger_manual(ActionId.WAVE)
    assert engine.mode is BehaviorMode.MANUAL_ACTION
    engine.begin_drag()
    assert engine.mode is BehaviorMode.DRAGGING
    engine.end_drag()
    assert engine.mode is BehaviorMode.MANUAL_ACTION
    engine.manual_finished()
    assert engine.mode is BehaviorMode.WANDER

def test_manual_idle_disables_current_action_but_not_saved_wander_setting():
    engine = BehaviorEngine(wander_enabled=True)
    engine.trigger_manual(ActionId.IDLE)
    assert engine.mode is BehaviorMode.IDLE
    assert engine.wander_enabled
```

- [ ] **Step 3: Run both tests and verify imports fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_animation_player.py tests\test_behavior.py -q`

Expected: collection FAIL because both modules are missing.

- [ ] **Step 4: Implement playback using elapsed time, never sleep calls**

```python
from dataclasses import dataclass
from .constants import ACTION_SPECS
from .models import ActionId

@dataclass(frozen=True)
class PlaybackStep:
    frame_index: int
    finished: bool

class AnimationTimeline:
    def __init__(self):
        self.action = ActionId.IDLE
        self.started_ms = 0

    def start(self, action: ActionId, now_ms: int) -> None:
        self.action = action
        self.started_ms = now_ms

    def advance(self, now_ms: int) -> PlaybackStep:
        spec = ACTION_SPECS[self.action]
        elapsed = max(0, now_ms - self.started_ms)
        cycle_ms = spec.frame_count * spec.frame_ms
        if spec.loops is None:
            return PlaybackStep((elapsed // spec.frame_ms) % spec.frame_count, False)
        animation_ms = cycle_ms * spec.loops
        if elapsed < animation_ms:
            return PlaybackStep((elapsed // spec.frame_ms) % spec.frame_count, False)
        if elapsed < animation_ms + spec.hold_ms:
            return PlaybackStep(spec.frame_count - 1, False)
        return PlaybackStep(spec.frame_count - 1, True)
```

No component blocks the Qt event loop; all timing derives from the caller-provided monotonic millisecond value.

- [ ] **Step 5: Implement the pure state machine**

```python
from dataclasses import dataclass, field
from enum import StrEnum
from .models import ActionId

class BehaviorMode(StrEnum):
    IDLE = "idle"
    GAZE = "gaze"
    WANDER = "wander"
    MANUAL_ACTION = "manual_action"
    DRAGGING = "dragging"
    SHUTTING_DOWN = "shutting_down"

@dataclass
class BehaviorEngine:
    wander_enabled: bool = False
    gaze_degrees: float | None = None
    mode: BehaviorMode = BehaviorMode.IDLE
    current_action: ActionId | None = None
    _mode_before_drag: BehaviorMode = field(default=BehaviorMode.IDLE, init=False)

    def trigger_manual(self, action: ActionId) -> None:
        if action is ActionId.IDLE:
            self.current_action = None
            self.mode = BehaviorMode.IDLE
            return
        self.current_action = action
        self.mode = BehaviorMode.MANUAL_ACTION

    def manual_finished(self) -> None:
        self.current_action = None
        self.mode = self._base_mode()

    def begin_drag(self) -> None:
        self._mode_before_drag = self.mode
        self.mode = BehaviorMode.DRAGGING

    def end_drag(self) -> None:
        self.mode = self._mode_before_drag

    def set_wander_enabled(self, enabled: bool) -> None:
        self.wander_enabled = enabled
        if self.mode not in {BehaviorMode.MANUAL_ACTION, BehaviorMode.DRAGGING, BehaviorMode.SHUTTING_DOWN}:
            self.mode = self._base_mode()

    def request_gaze(self, degrees: float | None) -> None:
        self.gaze_degrees = degrees
        if self.mode in {BehaviorMode.IDLE, BehaviorMode.GAZE}:
            self.mode = self._base_mode()

    def begin_shutdown(self) -> None:
        self.mode = BehaviorMode.SHUTTING_DOWN

    def _base_mode(self) -> BehaviorMode:
        if self.wander_enabled:
            return BehaviorMode.WANDER
        if self.gaze_degrees is not None:
            return BehaviorMode.GAZE
        return BehaviorMode.IDLE
```

Preserve the interrupted manual action across a temporary drag; restore `WANDER`, `GAZE`, or `IDLE` after action completion according to saved settings and current gaze request.

- [ ] **Step 6: Run the focused tests and all tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_animation_player.py tests\test_behavior.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: focused tests pass; entire suite passes.

- [ ] **Step 7: Commit**

```powershell
git add src\shiyi_desktop_pet\animation_player.py src\shiyi_desktop_pet\behavior.py tests\test_animation_player.py tests\test_behavior.py
git commit -m "feat: add desktop pet behavior engine"
```

---

### Task 4: Map Cursor Gaze and Boundary-Safe Wandering

**Files:**
- Create: `src/shiyi_desktop_pet/geometry.py`
- Create: `src/shiyi_desktop_pet/gaze.py`
- Create: `src/shiyi_desktop_pet/wander.py`
- Create: `tests/test_gaze.py`
- Create: `tests/test_wander.py`

**Interfaces:**
- Produces: `Point`, `Rect`, `Size`, `clamp_position`; `quantize_gaze`; `GazeStabilizer`; `WanderPlanner.choose_target` and `step_toward`.

- [ ] **Step 1: Write failing cardinal, diagonal, and dead-zone tests**

```python
# tests/test_gaze.py
from shiyi_desktop_pet.gaze import quantize_gaze, GazeStabilizer

def test_screen_vectors_map_clockwise_from_up():
    assert quantize_gaze(0, -100, 18) == 0.0
    assert quantize_gaze(100, 0, 18) == 90.0
    assert quantize_gaze(0, 100, 18) == 180.0
    assert quantize_gaze(-100, 0, 18) == 270.0
    assert quantize_gaze(100, -100, 18) == 45.0
    assert quantize_gaze(2, 2, 18) is None

def test_stabilizer_requires_80_ms_before_direction_switch():
    gaze = GazeStabilizer(stable_ms=80)
    assert gaze.update(90.0, 0) is None
    assert gaze.update(90.0, 79) is None
    assert gaze.update(90.0, 80) == 90.0
```

- [ ] **Step 2: Write failing boundary and deterministic wandering tests**

```python
# tests/test_wander.py
from random import Random
from shiyi_desktop_pet.geometry import Point, Rect, Size, clamp_position
from shiyi_desktop_pet.wander import WanderPlanner

def test_position_is_clamped_inside_available_geometry():
    area = Rect(100, 50, 1000, 700)
    assert clamp_position(Point(20, 900), Size(192, 208), area) == Point(100, 542)

def test_planner_target_stays_visible_and_direction_matches():
    planner = WanderPlanner(Random(7))
    target = planner.choose_target(Point(500, 300), Size(192, 208), Rect(0, 0, 1200, 800))
    assert 0 <= target.position.x <= 1008
    assert 0 <= target.position.y <= 592
    assert target.direction in (-1, 1)
    assert (target.position.x - 500) * target.direction > 0

def test_step_toward_never_overshoots_target():
    planner = WanderPlanner(Random(7))
    assert planner.step_toward(Point(100, 50), Point(107, 50), 10) == Point(107, 50)
```

- [ ] **Step 3: Run tests and verify missing modules fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_gaze.py tests\test_wander.py -q`

Expected: collection FAIL for missing `gaze` and `geometry`.

- [ ] **Step 4: Implement pure geometry, gaze quantization, and stabilization**

Define immutable geometry values and clamp against the monitor's available rectangle:

```python
# src/shiyi_desktop_pet/geometry.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Point:
    x: float
    y: float

@dataclass(frozen=True)
class Size:
    width: float
    height: float

@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

def clamp_position(position: Point, pet: Size, area: Rect) -> Point:
    max_x = max(area.x, area.x + area.width - pet.width)
    max_y = max(area.y, area.y + area.height - pet.height)
    return Point(
        min(max(position.x, area.x), max_x),
        min(max(position.y, area.y), max_y),
    )
```

Use `degrees = math.degrees(math.atan2(dx, -dy)) % 360`; quantize with `round(degrees / 22.5) % 16 * 22.5`. Dead-zone distance is Euclidean. `GazeStabilizer` resets its candidate timestamp whenever the candidate direction changes.

- [ ] **Step 5: Implement injected-RNG wandering**

`WanderPlanner` must never use module-global randomness. Choose a target on the same screen with at least 80 logical pixels of useful horizontal motion when space permits, clamp by pet size, and expose `step_toward(current, target, pixels) -> Point` without overshoot.

- [ ] **Step 6: Run focused and full suites**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_gaze.py tests\test_wander.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src\shiyi_desktop_pet\geometry.py src\shiyi_desktop_pet\gaze.py src\shiyi_desktop_pet\wander.py tests\test_gaze.py tests\test_wander.py
git commit -m "feat: add gaze and wandering geometry"
```

---

### Task 5: Persist Settings and Manage Per-User Startup

**Files:**
- Create: `src/shiyi_desktop_pet/settings.py`
- Create: `src/shiyi_desktop_pet/startup.py`
- Create: `tests/test_settings.py`
- Create: `tests/test_startup.py`

**Interfaces:**
- Produces: `AppSettings`, `SettingsStore.load/save`, `StartupManager.is_enabled/set_enabled`, `build_run_command`.

- [ ] **Step 1: Write failing default, round-trip, and corrupt-file tests**

```python
# tests/test_settings.py
from pathlib import Path
from shiyi_desktop_pet.settings import AppSettings, SettingsStore

def test_first_launch_defaults_match_approved_design(tmp_path: Path):
    settings = SettingsStore(tmp_path / "settings.ini").load()
    assert settings == AppSettings(
        schema_version=1, wander_enabled=False, gaze_enabled=True,
        hover_digits_enabled=True, always_on_top=True,
        scale_percent=100, animation_speed="normal", movement_speed="normal",
        screen_name="", relative_x=0.85, relative_y=0.75,
    )

def test_round_trip_and_corrupt_file_fallback(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.ini")
    changed = AppSettings(wander_enabled=True, scale_percent=125)
    store.save(changed)
    assert store.load().wander_enabled
    store.path.write_text("not-an-ini", encoding="utf-8")
    assert store.load().scale_percent == 100

def test_older_schema_is_migrated_with_new_defaults(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text("[settings]\nschema_version=0\nwander_enabled=true\n", encoding="utf-8")
    loaded = SettingsStore(path).load()
    assert loaded.schema_version == 1
    assert loaded.wander_enabled is True
    assert loaded.gaze_enabled is True
```

- [ ] **Step 2: Write failing startup registry-adapter tests**

```python
# tests/test_startup.py
from pathlib import Path
from shiyi_desktop_pet.startup import StartupManager, build_run_command

class FakeRunKey:
    value = None
    def read(self, name): return self.value
    def write(self, name, value): self.value = value
    def delete(self, name): self.value = None

def test_startup_command_quotes_path_and_round_trips():
    backend = FakeRunKey()
    manager = StartupManager(backend, Path(r"C:\Program Files\Shiyi\ShiyiDesktopPet.exe"))
    manager.set_enabled(True)
    assert backend.value == r'"C:\Program Files\Shiyi\ShiyiDesktopPet.exe" --startup'
    assert manager.is_enabled()
    manager.set_enabled(False)
    assert not manager.is_enabled()
```

- [ ] **Step 3: Run tests and verify missing modules fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_settings.py tests\test_startup.py -q`

Expected: collection FAIL.

- [ ] **Step 4: Implement versioned INI persistence**

Use these exact first-launch defaults, then serialize the dataclass with `configparser`:

```python
# src/shiyi_desktop_pet/settings.py
from dataclasses import dataclass

@dataclass(frozen=True)
class AppSettings:
    schema_version: int = 1
    wander_enabled: bool = False
    gaze_enabled: bool = True
    hover_digits_enabled: bool = True
    always_on_top: bool = True
    scale_percent: int = 100
    animation_speed: str = "normal"
    movement_speed: str = "normal"
    screen_name: str = ""
    relative_x: float = 0.85
    relative_y: float = 0.75
```

Accept only scales `{75,100,125,150}` and speeds `{slow,normal,fast}`. Clamp relative positions to `[0.0, 1.0]`. Migrate schema `0` by overlaying known stored keys on the schema-1 defaults; unknown future schema versions and malformed files log a warning through an injected logger and return defaults. Write atomically through a sibling `.tmp` and `Path.replace`.

- [ ] **Step 5: Implement `winreg` startup backend with dependency injection**

Registry path: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; value name: `ShiyiDesktopPet`. The manager considers startup enabled only when the normalized stored command exactly matches the current executable plus `--startup`.

- [ ] **Step 6: Run tests and full suite**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_settings.py tests\test_startup.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src\shiyi_desktop_pet\settings.py src\shiyi_desktop_pet\startup.py tests\test_settings.py tests\test_startup.py
git commit -m "feat: persist pet settings and startup"
```

---

### Task 6: Gate Hover Digits with a Windows Low-Level Keyboard Hook

**Files:**
- Create: `src/shiyi_desktop_pet/keyboard_hook.py`
- Create: `tests/test_keyboard_hook.py`

**Interfaces:**
- Consumes: `KEY_TO_ACTION`, callable `hover_hit_test() -> bool`.
- Produces: `KeyboardDecisionEngine.handle(vk_code, is_down, enabled, hovered) -> HookDecision`; `LowLevelKeyboardHook.start/stop`; Qt signal `digit_pressed(int)`.

- [ ] **Step 1: Write failing decision-engine tests**

```python
# tests/test_keyboard_hook.py
from shiyi_desktop_pet.keyboard_hook import KeyboardDecisionEngine

def test_top_row_and_numpad_are_consumed_only_during_visible_hover():
    engine = KeyboardDecisionEngine()
    down = engine.handle(0x35, is_down=True, enabled=True, hovered=True)
    assert down.consume and down.digit == 5
    up = engine.handle(0x35, is_down=False, enabled=True, hovered=False)
    assert up.consume and up.digit is None
    assert not engine.handle(0x35, True, True, False).consume
    assert engine.handle(0x63, True, True, True).digit == 3

def test_repeat_keydown_emits_once_until_keyup():
    engine = KeyboardDecisionEngine()
    assert engine.handle(0x34, True, True, True).digit == 4
    assert engine.handle(0x34, True, True, True).digit is None
    engine.handle(0x34, False, True, True)
    assert engine.handle(0x34, True, True, True).digit == 4
```

- [ ] **Step 2: Run tests and verify the missing module fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_keyboard_hook.py -q`

Expected: collection FAIL.

- [ ] **Step 3: Implement the pure key decision engine**

Track active consumed virtual keys so their key-up remains consumed even if the pointer leaves the sprite. Support `0x30–0x39` and `0x60–0x69`. Suppress auto-repeat until key-up.

- [ ] **Step 4: Implement the hook thread and callback**

Use `ctypes.WINFUNCTYPE` to define the hook procedure, then call `SetWindowsHookExW` with `WH_KEYBOARD_LL`, `GetMessageW` for the hook-thread loop, `CallNextHookEx` for pass-through events, and `PostThreadMessageW` with `WM_QUIT` during shutdown. The callback must:

1. return `CallNextHookEx` for `nCode < 0`;
2. evaluate only `WM_KEYDOWN`, `WM_SYSKEYDOWN`, `WM_KEYUP`, `WM_SYSKEYUP`;
3. call the injected alpha hit tester on the hook thread through an immutable snapshot updated by the UI;
4. emit `digit_pressed` via Qt queued connection;
5. return `1` only when `HookDecision.consume` is true;
6. keep the callback object alive until `stop()` unhooks.

- [ ] **Step 5: Add a Windows-only lifecycle test**

Test `start()` creates a live hook thread and `stop()` joins it within two seconds. Skip only when `sys.platform != "win32"`; do not synthesize global keypresses in the unit suite.

- [ ] **Step 6: Run focused and full suites**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_keyboard_hook.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass; no hook thread remains alive.

- [ ] **Step 7: Commit**

```powershell
git add src\shiyi_desktop_pet\keyboard_hook.py tests\test_keyboard_hook.py
git commit -m "feat: add hover digit keyboard hook"
```

---

### Task 7: Render the Transparent Pet Window and Shared Menus

**Files:**
- Create: `src/shiyi_desktop_pet/pet_window.py`
- Create: `src/shiyi_desktop_pet/menu_controller.py`
- Create: `src/shiyi_desktop_pet/tray_controller.py`
- Create: `tests/test_pet_window.py`
- Create: `tests/test_menu_controller.py`

**Interfaces:**
- Consumes: `FrameAsset`, `AnimationCatalog`, `ActionId`, `AppSettings`.
- Produces: `PetWindow` signals `action_requested`, `menu_requested`, `drag_started`, `drag_moved`, `drag_finished`; `MenuController(settings_supplier, startup_supplier, dispatch)`; `TrayController`.

- [ ] **Step 1: Write failing Qt tests for rendering, mask, and mouse signals**

```python
# tests/test_pet_window.py
from PySide6.QtCore import QPoint, Qt
from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import ActionId
from shiyi_desktop_pet.pet_window import PetWindow

def test_window_uses_frame_mask_and_emits_mouse_intents(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)
    assert (window.width(), window.height()) == (192, 208)
    assert not window.mask().isEmpty()
    with qtbot.waitSignal(window.action_requested) as signal:
        qtbot.mouseDClick(window, Qt.LeftButton, pos=QPoint(96, 150))
    assert signal.args == [ActionId.JUMP]

    with qtbot.waitSignal(window.action_requested) as signal:
        qtbot.mouseClick(window, Qt.MiddleButton, pos=QPoint(96, 150))
    assert signal.args == [ActionId.RANDOM]

    with qtbot.waitSignal(window.menu_requested):
        qtbot.mouseClick(window, Qt.RightButton, pos=QPoint(96, 150))

    with qtbot.waitSignal(window.drag_started):
        qtbot.mousePress(window, Qt.LeftButton, pos=QPoint(96, 150))
    with qtbot.waitSignal(window.drag_moved):
        qtbot.mouseMove(window, pos=QPoint(110, 160))
    with qtbot.waitSignal(window.drag_finished):
        qtbot.mouseRelease(window, Qt.LeftButton, pos=QPoint(110, 160))
```

- [ ] **Step 2: Write failing menu coverage tests**

```python
# tests/test_menu_controller.py
from shiyi_desktop_pet.menu_controller import MenuController
from shiyi_desktop_pet.settings import AppSettings

def test_menu_contains_every_action_direction_and_toggle():
    menu_controller = MenuController(
        settings_supplier=AppSettings,
        startup_supplier=lambda: True,
        dispatch=lambda command: None,
    )
    labels = menu_controller.flattened_labels()
    for label in ("休息", "向右奔跑", "向左奔跑", "招手", "跳跃", "撒娇翻肚",
                  "期待", "原地巡视", "好奇观察", "随机动作"):
        assert label in labels
    assert sum(label.startswith("观察 ") for label in labels) == 16
    for label in ("自动闲逛", "看向鼠标", "悬停数字快捷键", "始终置顶", "开机启动"):
        assert label in labels
    for label in ("75%", "100%", "125%", "150%", "慢速", "正常", "快速",
                  "回到屏幕中央", "关于十一", "退出"):
        assert label in labels
```

- [ ] **Step 3: Run tests and verify UI modules are missing**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_pet_window.py tests\test_menu_controller.py -q`

Expected: collection FAIL.

- [ ] **Step 4: Implement the shaped translucent window**

Use `Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint` and `WA_TranslucentBackground`. Build the mask with `QBitmap.fromImage(frame.image.createAlphaMask())`, scale it to the current window size with `Qt.IgnoreAspectRatio` and `Qt.SmoothTransformation`, then pass it to `setMask`. Paint with `QPainter` and smooth transformation. Window mouse handling must emit intents only; dragging stores the press offset and emits global target positions.

- [ ] **Step 5: Implement one command model shared by body and tray menus**

Create actions from data rather than duplicated callbacks. `MenuController` accepts `settings_supplier: Callable[[], AppSettings]`, `startup_supplier: Callable[[], bool]`, and `dispatch: Callable[[MenuCommand], None]`; `flattened_labels()` exposes the generated hierarchy for deterministic tests. Scale values are `{75,100,125,150}`; animation and movement speeds are `{slow,normal,fast}`. Direction actions carry exact float degrees. Checked state is updated from current settings and the real registry startup state every time the menu opens.

- [ ] **Step 6: Implement the tray icon and recovery actions**

`TrayController` exposes the same menu, double-click shows/raises the pet, and “回到屏幕中央” emits a controller command. If `QSystemTrayIcon.isSystemTrayAvailable()` is false, return a disabled tray object without failing startup.

- [ ] **Step 7: Run Qt and full suites**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests\test_pet_window.py tests\test_menu_controller.py -q
Remove-Item Env:QT_QPA_PLATFORM
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src\shiyi_desktop_pet\pet_window.py src\shiyi_desktop_pet\menu_controller.py src\shiyi_desktop_pet\tray_controller.py tests\test_pet_window.py tests\test_menu_controller.py
git commit -m "feat: add transparent pet window and menus"
```

---

### Task 8: Compose Runtime Control, Multi-Monitor Recovery, and Logging

**Files:**
- Create: `src/shiyi_desktop_pet/logging_setup.py`
- Create: `src/shiyi_desktop_pet/single_instance.py`
- Create: `src/shiyi_desktop_pet/app.py`
- Create: `src/shiyi_desktop_pet/__main__.py`
- Create: `tests/test_single_instance.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Consumes: all prior components.
- Produces: `DesktopPetApplication`, `resolve_digit_action(digit, rng)`, `restore_window_position(settings, screens, primary_name, pet_size)`, `parse_args`, CLI `main(argv: list[str] | None) -> int`, IPC commands `activate` and `quit`, `--self-test`, `--startup`, `--quit-existing`.

- [ ] **Step 1: Write failing single-instance IPC tests**

```python
# tests/test_single_instance.py
from uuid import uuid4
from shiyi_desktop_pet.single_instance import SingleInstanceGuard

def test_second_guard_sends_activate_to_first(qtbot):
    instance_name = f"ShiyiDesktopPet.Test.{uuid4().hex}"
    first = SingleInstanceGuard(instance_name)
    assert first.acquire()
    with qtbot.waitSignal(first.command_received) as signal:
        second = SingleInstanceGuard(instance_name)
        assert not second.acquire(command="activate")
    assert signal.args == ["activate"]
    first.close()
```

- [ ] **Step 2: Write failing controller and self-test tests**

```python
# tests/test_app.py
from dataclasses import replace
from random import Random
import pytest
from shiyi_desktop_pet.app import (
    parse_args, resolve_digit_action, restore_window_position, run_self_test,
)
from shiyi_desktop_pet.geometry import Point, Rect, Size
from shiyi_desktop_pet.models import ActionId
from shiyi_desktop_pet.settings import AppSettings

def test_digit_and_random_action_mapping():
    assert resolve_digit_action(4, Random(0)) is ActionId.WAVE
    assert resolve_digit_action(0, Random(0)) in {
        ActionId.WAVE, ActionId.JUMP, ActionId.BELLY_FLOP,
        ActionId.EXPECT, ActionId.PATROL, ActionId.CURIOUS,
    }

def test_self_test_reports_resources_qt_and_webp():
    report = run_self_test()
    assert report["ok"] is True
    assert report["atlas"] == {"width": 1536, "height": 2288, "frames": 74}
    assert report["webp_plugin"] is True

def test_first_launch_and_missing_screen_are_recoverable():
    screens = {"primary": Rect(0, 0, 1920, 1040)}
    selected, first = restore_window_position(
        AppSettings(), screens, "primary", Size(192, 208)
    )
    assert selected == "primary"
    assert first == Point(1696, 808)
    missing = replace(AppSettings(), screen_name="disconnected", relative_x=2.0, relative_y=-1.0)
    selected, restored = restore_window_position(
        missing, screens, "primary", Size(192, 208)
    )
    assert selected == "primary"
    assert 0 <= restored.x <= 1728 and 0 <= restored.y <= 832

def test_cli_modes_are_mutually_exclusive():
    assert parse_args(["--startup"]).startup
    assert parse_args(["--self-test"]).self_test
    assert parse_args(["--quit-existing"]).quit_existing
    with pytest.raises(SystemExit):
        parse_args(["--self-test", "--quit-existing"])
```

- [ ] **Step 3: Run tests and verify missing modules fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_single_instance.py tests\test_app.py -q`

Expected: collection FAIL.

- [ ] **Step 4: Implement rotating logs and exception cleanup**

Use `RotatingFileHandler(maxBytes=1_048_576, backupCount=3, encoding="utf-8")`. Install `sys.excepthook` that logs the exception, stops the keyboard hook, removes the tray icon, and schedules `QApplication.quit()`.

- [ ] **Step 5: Implement mutex plus local-socket IPC**

Names: mutex `Local\\ShiyiDesktopPet.Singleton.v1`; local server `ShiyiDesktopPet.IPC.v1`. Acquire the mutex with `CreateMutexW`. The owner removes stale local-server endpoints, listens, and emits decoded newline-delimited commands. A second instance sends `activate` or `quit` with a one-second timeout and exits.

- [ ] **Step 6: Compose timers and state transitions**

`DesktopPetApplication` owns:

- one 16 ms animation timer;
- one 50 ms gaze timer;
- one wander scheduler timer;
- current frame snapshot for hook hit-testing;
- screen-change connections;
- settings save on controlled exit.

Use `QGuiApplication.screenAt(QCursor.pos())` for “回到屏幕中央”. On first launch (`screen_name == ""`), place the pet 32 logical pixels from the primary screen's right edge and 24 pixels above its available bottom edge. Otherwise restore by screen name and relative position; fall back to the primary screen when the saved screen disappeared, then clamp to `availableGeometry`. Manual run actions move each frame; wander movement uses the same running rows continuously until the target is reached.

If keyboard-hook startup raises, log the exception, force `hover_digits_enabled=False` for the session, and show one tray notification when the tray exists. If the tray is unavailable, the pet body menu remains fully functional. If atlas construction raises, show one critical error dialog, write the error to the rotating log, release the instance guard, and exit nonzero without showing an empty window.

Use constructor/factory injection for the hook, tray, settings store, and catalog so `tests/test_app.py` can cover both failure paths without installing a real global hook or opening a native dialog. Add tests asserting that hook failure leaves the pet running with the session shortcut disabled, and atlas failure releases the instance guard and returns nonzero.

- [ ] **Step 7: Implement CLI modes before creating the visible window**

`--self-test` loads resources, verifies Qt WebP support, prints one JSON object, and exits. `--quit-existing` sends `quit`. `--startup` starts normally without stealing foreground focus. Normal duplicate launch sends `activate`.

- [ ] **Step 8: Run focused, full, and coverage suites**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_single_instance.py tests\test_app.py -q
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m coverage run -m pytest
& .\.venv\Scripts\python.exe -m coverage report --fail-under=85
```

Expected: all tests pass and total coverage is at least 85%.

- [ ] **Step 9: Commit**

```powershell
git add src\shiyi_desktop_pet\logging_setup.py src\shiyi_desktop_pet\single_instance.py src\shiyi_desktop_pet\app.py src\shiyi_desktop_pet\__main__.py tests\test_single_instance.py tests\test_app.py
git commit -m "feat: compose standalone desktop pet"
```

---

### Task 9: Create the Application Icon, Notices, and User Documentation

**Files:**
- Create: `tools/make_icon.py`
- Create: `src/shiyi_desktop_pet/resources/app.ico`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `README.md`
- Create: `tests/test_app_icon.py`

**Interfaces:**
- Consumes: idle row 0 column 0.
- Produces: multi-size Windows icon and distributable source documentation.

- [ ] **Step 1: Write the failing icon contract test**

```python
# tests/test_app_icon.py
from PIL import Image
from shiyi_desktop_pet.resource_locator import resource_path

def test_icon_contains_required_windows_sizes():
    icon = Image.open(resource_path("app.ico"))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes()
```

- [ ] **Step 2: Run the test and verify `app.ico` is missing**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_app_icon.py -q`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Implement deterministic icon extraction**

`tools/make_icon.py` opens the source atlas with Pillow, crops `(0,0,192,208)`, trims transparent bounds, centers the sprite on a transparent square with 8% padding, and saves ICO sizes `[16,32,48,256]`. It does not redraw or alter the pet.

Run: `& .\.venv\Scripts\python.exe tools\make_icon.py`

- [ ] **Step 4: Write notices and operating instructions**

`README.md` must include build commands, action mapping, all mouse controls, the right-click menu, startup behavior, settings/log locations, install/uninstall instructions, privacy statement, and troubleshooting for off-screen pets and disabled shortcuts. `THIRD_PARTY_NOTICES.md` must identify Python, Qt/PySide6, PyInstaller, Pillow, pytest tooling, Inno Setup, their licenses, and official project URLs.

- [ ] **Step 5: Run icon and full tests**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_app_icon.py -q; & .\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add tools\make_icon.py src\shiyi_desktop_pet\resources\app.ico THIRD_PARTY_NOTICES.md README.md tests\test_app_icon.py
git commit -m "docs: add desktop pet icon and notices"
```

---

### Task 10: Build and Smoke-Test the Self-Contained PyInstaller Application

**Files:**
- Create: `packaging/ShiyiDesktopPet.spec`
- Create: `scripts/build_app.ps1`
- Create: `tests/integration/test_frozen_smoke.py`

**Interfaces:**
- Consumes: `python -m shiyi_desktop_pet`, package resources, app icon.
- Produces: `dist/ShiyiDesktopPet/ShiyiDesktopPet.exe` and its private runtime folder.

- [ ] **Step 1: Write the failing frozen smoke test**

```python
# tests/integration/test_frozen_smoke.py
import json, subprocess
from pathlib import Path

def test_frozen_exe_self_test(repo_root: Path):
    exe = repo_root / "dist" / "ShiyiDesktopPet" / "ShiyiDesktopPet.exe"
    assert exe.is_file(), f"missing frozen executable: {exe}"
    result = subprocess.run([exe, "--self-test"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["webp_plugin"] is True
    assert report["atlas"]["frames"] == 74
```

- [ ] **Step 2: Run the smoke test and verify the executable is missing**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\integration\test_frozen_smoke.py -q`

Expected: FAIL with `missing frozen executable`.

- [ ] **Step 3: Create the PyInstaller spec**

The spec must:

- use `console=False`, `uac_admin=False`, `name="ShiyiDesktopPet"`;
- include `pet.json`, `spritesheet.webp`, `app.ico`, and `THIRD_PARTY_NOTICES.md`;
- include PySide6 `platforms`, `imageformats` (including `qwebp.dll`), and `styles` plugins;
- include `PySide6.QtNetwork` for `QLocalServer`;
- build `EXE` plus `COLLECT` one-folder output;
- exclude unused Qt modules such as WebEngine, Charts, Multimedia, QML, SQL, Test, and 3D.

- [ ] **Step 4: Implement the repeatable app build script**

```powershell
# scripts/build_app.ps1 behavior
$ErrorActionPreference = 'Stop'
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging\ShiyiDesktopPet.spec
& .\dist\ShiyiDesktopPet\ShiyiDesktopPet.exe --self-test
if ($LASTEXITCODE -ne 0) { throw 'Frozen self-test failed' }
```

The script resolves repository-relative paths from `$PSScriptRoot`, not the caller's current directory.

- [ ] **Step 5: Build and rerun the frozen smoke test**

Run:

```powershell
& .\scripts\build_app.ps1
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_frozen_smoke.py -q
```

Expected: build exits 0; frozen self-test prints `ok: true`; smoke test passes.

- [ ] **Step 6: Verify the frozen process has no source-environment dependency**

Run the EXE from a fresh PowerShell process with `PATH` set only to Windows system directories and with `PYTHONHOME`, `PYTHONPATH`, and `QT_PLUGIN_PATH` removed. Expected: `--self-test` exits 0 and reports the WebP plugin.

- [ ] **Step 7: Commit build definitions**

```powershell
git add packaging\ShiyiDesktopPet.spec scripts\build_app.ps1 tests\integration\test_frozen_smoke.py
git commit -m "build: freeze Shiyi desktop app"
```

---

### Task 11: Build, Install, Upgrade, and Uninstall with Inno Setup

**Files:**
- Create: `packaging/installer.iss`
- Create: `scripts/build_installer.ps1`
- Create: `scripts/verify_release.ps1`

**Interfaces:**
- Consumes: `dist/ShiyiDesktopPet/**`.
- Produces: `artifacts/十一桌面宠物安装程序.exe`, silent-install and verification commands.

- [ ] **Step 1: Install or locate Inno Setup 7.0.2**

Run:

```powershell
$Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $Iscc) {
  winget install --id JRSoftware.InnoSetup -e --version 7.0.2 --scope user --silent --accept-package-agreements --accept-source-agreements
}
$Iscc = Get-Command ISCC.exe -ErrorAction Stop
& $Iscc.Source /?
```

Expected: compiler starts and reports Inno Setup 7.0.2. If winget has not indexed 7.0.2, install the official signed current stable from `https://jrsoftware.org/isdl.php`, record its exact version in the Task 11 report, and require version `>=6.7.3,<8`.

- [ ] **Step 2: Write the installer definition**

Required directives:

```ini
[Setup]
AppId={{5F4B3AD9-7C91-4E2D-A4C4-70C5C4F5A211}
AppName=十一桌面宠物
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\ShiyiDesktopPet
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\artifacts
OutputBaseFilename=十一桌面宠物安装程序
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\ShiyiDesktopPet.exe

[Languages]
Name: chinesesimplified; MessagesFile: compiler:Languages\ChineseSimplified.isl

[Tasks]
Name: startup; Description: 开机自动启动十一; Flags: checkedonce

[Files]
Source: ..\dist\ShiyiDesktopPet\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\十一桌面宠物; Filename: {app}\ShiyiDesktopPet.exe

[Registry]
Root: HKCU; Subkey: Software\Microsoft\Windows\CurrentVersion\Run; ValueType: string; ValueName: ShiyiDesktopPet; ValueData: """{app}\ShiyiDesktopPet.exe"" --startup"; Tasks: startup; Flags: uninsdeletevalue; Check: ShouldWriteStartup

[Run]
Filename: {app}\ShiyiDesktopPet.exe; Description: 立即运行十一; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: {app}\ShiyiDesktopPet.exe; Parameters: --quit-existing; Flags: runhidden waituntilterminated skipifdoesntexist

[UninstallDelete]
Type: filesandordirs; Name: {userappdata}\ShiyiDesktopPet
Type: filesandordirs; Name: {localappdata}\ShiyiDesktopPet
```

The `[Code]` section stores whether this is an upgrade before files are copied, runs the existing EXE with `--quit-existing` in `PrepareToInstall`, and makes `ShouldWriteStartup` true only for first install with the startup task selected. Upgrade must not re-enable startup after the user disabled it. Assert that the Simplified Chinese message file exists before compiling; if the installed Inno distribution omits it, fetch the official Inno translation file into `packaging/languages/ChineseSimplified.isl`, change `MessagesFile` to that repository-relative path, and include it in the Task 11 commit.

- [ ] **Step 3: Implement build and release verification scripts**

`build_installer.ps1` runs `build_app.ps1`, locates `ISCC.exe`, compiles `installer.iss`, and asserts exactly one installer exists. `verify_release.ps1` accepts an installer path and a test install directory. Before testing, it copies any existing `%APPDATA%\ShiyiDesktopPet`, `%LOCALAPPDATA%\ShiyiDesktopPet`, Run value, and product uninstall-registry entry into a unique backup below `work/`; a `try/finally` restores that exact prior state even when a command fails. It then:

1. runs silent install with `/DIR=` set to the provided `-TestDir` value and `/MERGETASKS=!startup`;
2. runs installed `ShiyiDesktopPet.exe --self-test`;
3. verifies no test Run value was created;
4. runs installed `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`;
5. verifies the test process, Run value, uninstall entry, test install directory, settings, and logs created by the smoke install are gone;
6. restores the pre-test user data and registry state from the backup and removes only the verified unique backup directory.

All recursive cleanup uses resolved absolute paths checked to be descendants of the supplied test directory or repository `work/`; do not construct deletion commands by passing paths between shells.

- [ ] **Step 4: Compile and run the isolated install/uninstall smoke test**

Run:

```powershell
& .\scripts\build_installer.ps1
& .\scripts\verify_release.ps1 -Installer .\artifacts\十一桌面宠物安装程序.exe -TestDir (Join-Path $PWD 'work\installer-smoke')
```

Expected: install, frozen self-test, and uninstall all exit 0; no HKCU startup value remains from the isolated smoke install.

- [ ] **Step 5: Test upgrade preservation**

Install to a second isolated directory, create a settings file with `wander_enabled=true`, disable the Run value through `StartupManager`, run the installer again to the same directory, and verify both the settings sentinel and disabled Run state remain. Then silently uninstall.

- [ ] **Step 6: Commit installer definitions**

```powershell
git add packaging\installer.iss scripts\build_installer.ps1 scripts\verify_release.ps1
git commit -m "build: add Shiyi Windows installer"
```

---

### Task 12: Perform Real Desktop QA, Install the Final Build, and Export Deliverables

**Files:**
- Modify: `README.md`
- Create: `docs/manual-qa.md`
- Create: `outputs/十一桌面宠物/十一桌面宠物安装程序.exe`
- Create: `outputs/十一桌面宠物/安装说明.md`
- Create: `outputs/十一桌面宠物/SHA256SUMS.txt`
- Create: `outputs/十一桌面宠物/十一桌面宠物源代码.zip`
- Create: `outputs/十一桌面宠物/qa/**`

**Interfaces:**
- Consumes: passing source suite, frozen build, installer smoke test.
- Produces: installed desktop pet and user-facing release package.

- [ ] **Step 1: Run the complete automated verification gate fresh**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m coverage run -m pytest
& .\.venv\Scripts\python.exe -m coverage report --fail-under=85
& .\scripts\build_installer.ps1
& .\scripts\verify_release.ps1 -Installer .\artifacts\十一桌面宠物安装程序.exe -TestDir (Join-Path $PWD 'work\final-installer-smoke')
```

Expected: zero failed tests; coverage at least 85%; frozen self-test and installer smoke pass.

- [ ] **Step 2: Install the final build for the current user**

Run the installer normally or silently with startup selected. Verify:

- `%LOCALAPPDATA%\Programs\ShiyiDesktopPet\ShiyiDesktopPet.exe` exists;
- HKCU Run value equals the quoted installed EXE plus `--startup`;
- `ShiyiDesktopPet.exe --self-test` returns `ok: true`;
- launching a second instance does not create a second visible pet.

- [ ] **Step 3: Perform real UI inspection with Windows computer control**

Launch the installed application and record screenshots plus notes under `outputs/十一桌面宠物/qa/`. Verify each item manually:

- transparent edges and click-through outside the sprite;
- right-click menu contains every action, 16 directions, toggles, scales and speeds;
- drag, double-click jump, middle-click random action;
- hover digits `0–9`, including suppression only over visible alpha pixels;
- cursor gaze traverses all four cardinals and representative diagonals;
- auto wander moves left/right, respects taskbar and screen edges, and is interruptible;
- tray recovery, always-on-top toggle and reset-to-center;
- 75%, 100%, 125%, 150% sizes remain sharp;
- position and mode restore after restart.

Any visible defect is a failed gate: diagnose with `superpowers:systematic-debugging`, add a failing automated test where feasible, repair, rebuild, reinstall, and repeat affected checks.

- [ ] **Step 4: Verify startup without waiting for a reboot**

Read the exact HKCU Run command, start it in a fresh process, and confirm it activates the existing instance rather than creating a duplicate. Toggle startup off through the menu and verify the value is removed; toggle it on and verify it returns exactly.

- [ ] **Step 5: Export installer, source, docs, hashes, and QA evidence**

Copy the final installer into `outputs/十一桌面宠物/`. Create the source ZIP from tracked source files at the release commit, excluding `.git`, `.venv`, `build`, `dist`, `artifacts`, `work`, and prior outputs. Write `安装说明.md` with install, controls, startup, recovery and uninstall steps. Generate SHA-256 entries for the installer and source ZIP.

- [ ] **Step 6: Validate exported artifacts**

Run the installer hash, source ZIP hash, ZIP content list, and one final `--self-test` from the installed executable. Confirm the exported installer byte hash matches `artifacts/十一桌面宠物安装程序.exe`.

- [ ] **Step 7: Commit release documentation**

```powershell
git add README.md docs\manual-qa.md
git commit -m "docs: document Shiyi desktop pet release"
```

- [ ] **Step 8: Invoke verification-before-completion and final review**

Read and follow `superpowers:verification-before-completion`, then request a fresh whole-requirements reviewer using `superpowers:requesting-code-review`. Do not claim completion until the reviewer finds no Critical or Important issues and the fresh commands from Step 1 still pass.
