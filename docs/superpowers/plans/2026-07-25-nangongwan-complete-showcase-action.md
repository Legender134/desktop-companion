# 南宫婉完整动作展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在桌面灵伴2.4.7的南宫婉右键菜单中增加一个只可手动触发的“完整动作展示”，用单个448帧有限动作原样播放已验收视频的15段、82433毫秒内容。

**Architecture:** 继续使用V3单图集和现有 `AnimationTimeline`，把2473个30fps输出帧按连续相同源帧压缩为448个RGBA单元格，并用448项 `frameDurations` 恢复时间线。运行时新增通用 `includeInShowcase` 元数据并把V3普通动作上限从64提高到512；构建器从已哈希固定的本地历史素材生成图集、清单和审片证据，不从MP4反向截图。

**Tech Stack:** Python 3.12、PySide6/QImage、Pillow/WebP、pytest、JSON Schema 2020-12、PyInstaller、Inno Setup 6.7.3、PowerShell 7。

## Global Constraints

- 仅修改工作树 `D:\workspace\desktop-companion\十一桌面宠物-新电脑交接包\桌面灵伴-2.0\.worktrees\moonlit-chestnut-redesign`。
- 不得修改或提交用户现有未提交文件：`tests/test_moonlit_asset_builder.py`、`tools/build_nangongwan_giant_moon_webp.py`、`tools/build_nangongwan_moonlit_rooftop_state.py`。
- 动作固定为15段、448个压缩帧、82433毫秒；单帧时长必须在33–666毫秒。
- 动作ID为 `completeShowcase`，标签为“完整动作展示”，`autoplayWeight=0`、`showInMenu=true`、`includeInShowcase=false`。
- 正常速度82.433秒；慢速乘1.25，快速乘0.75。
- 图集固定16列、每格192×208；新图集3072×12896、992格、39,616,512像素。
- V3普通动作 `frameCount` 上限为512；`gaze` 仍只允许16、32或64帧。
- 保留2048总格、5000万像素、32 MiB WebP、64 KiB JSON、最多64个动作等现有上限。
- 当前正式图集字节备份到 `tools/archives/nangongwan-complete-showcase-v2.4.6/spritesheet.webp`，不得放入PyInstaller资源。
- 现有南宫婉动作、常驻状态、历史WebP和视频均不得删除或替换。
- 不向GitHub或Gitee上传；完成本机安装后再由用户另行决定发布。

---

## File Structure

### New files

- `tools/build_nangongwan_complete_showcase_action.py`：编译15段源时间线、追加图集、更新清单、生成报告和审片图。
- `tests/test_nangongwan_complete_showcase_action.py`：构建器、压缩时长、原子发布、幂等和素材保护测试。
- `tools/archives/nangongwan-complete-showcase-v2.4.6/README.md`：归档来源、用途、哈希和“不进入安装包”说明。
- `tools/archives/nangongwan-complete-showcase-v2.4.6/pet.json`：构建前2.4.6南宫婉清单。
- `tools/archives/nangongwan-complete-showcase-v2.4.6/spritesheet.webp`：构建前正式图集的逐字节副本。
- `docs/manual-qa-v2.4.7.md`：本次源码、资源、安装包和本机升级验收记录。

### Modified files

- `src/shiyi_desktop_pet/models.py`：给 `PetActionDefinition` 增加 `include_in_showcase: bool`。
- `src/shiyi_desktop_pet/pet_registry.py`：解析新字段并允许最多512帧的普通V3动作。
- `src/shiyi_desktop_pet/animation_catalog.py`：通用动作展示排除标志和菜单详情。
- `schemas/pet-pack-v3.schema.json`：同步512帧和 `includeInShowcase`。
- `docs/pet-pack-format-v3.md`、`docs/添加新宠物指南.md`、`examples/pet-pack-template/README.md`：面向制作者解释新规则。
- `tests/test_pet_registry.py`、`tests/test_animation_catalog.py`、`tests/test_documentation.py`：运行时和文档契约测试。
- `src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json`：新增 `completeShowcase`。
- `src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet.webp`：在旧544格后追加448格。
- `tests/test_resource_contract.py`：锁定南宫婉新资源尺寸、哈希、菜单和自动池行为。
- `tests/test_animation_player.py`、`tests/test_app.py`：验证长时长有限动作结束和中断。
- `pyproject.toml`、`src/shiyi_desktop_pet/__init__.py`、`src/shiyi_desktop_pet/product.py`、`packaging/installer.iss`：版本2.4.7。
- `tests/test_packaging.py`、`tests/test_app.py`、`CHANGELOG.md`：同步版本和更新说明。

---

### Task 1: 扩展V3动作元数据和单动作帧数上限

**Files:**
- Modify: `src/shiyi_desktop_pet/models.py:33-52`
- Modify: `src/shiyi_desktop_pet/pet_registry.py:306-404,573-795`
- Modify: `src/shiyi_desktop_pet/animation_catalog.py:310-454`
- Test: `tests/test_pet_registry.py`
- Test: `tests/test_animation_catalog.py`

**Interfaces:**
- Produces: `PetActionDefinition.include_in_showcase: bool = True`
- Produces: V3 JSON字段 `includeInShowcase: boolean`
- Produces: 普通V3直接动作 `1 <= frameCount <= 512`
- Consumes: 现有 `AnimationCatalog.showcase_actions()` 和 `action_menu_details()`

- [ ] **Step 1: 写解析器失败测试**

在 `tests/test_pet_registry.py` 增加直接动作448帧、513帧、字段缺省、字段显式为假和非法类型测试：

```python
def test_v3_allows_512_frame_actions_and_parses_showcase_opt_out():
    manifest = valid_v3_manifest()
    manifest["actions"]["longShowcase"] = {
        "label": "完整动作展示",
        "role": "interaction",
        "row": 4,
        "frameCount": 448,
        "frameDurations": [33] * 447 + [34],
        "repeatCount": 1,
        "autoplayWeight": 0,
        "showInMenu": True,
        "includeInShowcase": False,
    }
    actions = {
        item.action_id: item
        for item in PetRegistry._parse_v3_actions(manifest["actions"])
    }
    assert actions["longShowcase"].include_in_showcase is False
    assert actions["greet"].include_in_showcase is True


def test_v3_rejects_more_than_512_frames_and_non_boolean_showcase_flag():
    manifest = valid_v3_manifest()
    manifest["actions"]["greet"]["frameCount"] = 513
    manifest["actions"]["greet"]["frameDurations"] = [33] * 513
    with pytest.raises(ValueError, match="1 through 512"):
        PetRegistry._parse_v3_actions(manifest["actions"])

    manifest = valid_v3_manifest()
    manifest["actions"]["greet"]["includeInShowcase"] = 0
    with pytest.raises(ValueError, match="includeInShowcase must be boolean"):
        PetRegistry._parse_v3_actions(manifest["actions"])
```

保留现有 `gaze` 非16/32/64帧失败测试，并新增448帧 `gaze` 仍失败的断言。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pet_registry.py -q
```

Expected: FAIL，错误分别指向未知字段 `includeInShowcase` 和旧的 `frameCount must be 1 through 64`。

- [ ] **Step 3: 实现最小解析和模型改动**

在 `PetActionDefinition` 增加：

```python
include_in_showcase: bool = True
```

在 `_parse_v3_common()` 中读取并验证：

```python
include_in_showcase = entry.get("includeInShowcase", True)
if not isinstance(include_in_showcase, bool):
    raise ValueError(f"actions.{key}.includeInShowcase must be boolean")
```

把该值加入 `_parse_v3_common()` 返回元组，并在直接动作和镜像动作的 `PetActionDefinition(...)` 中传入。直接动作与镜像动作允许字段集合都加入 `"includeInShowcase"`。

把直接动作帧数校验改为：

```python
if not PetRegistry._is_int_between(frame_count, 1, 512):
    raise ValueError(f"actions.{key}.frameCount must be 1 through 512")
```

不要修改后面的 `gaze` 枚举限制。

- [ ] **Step 4: 写目录行为失败测试**

在 `tests/test_animation_catalog.py` 的动态动作清单中加入一个菜单可见、权重0、`includeInShowcase=false` 的有限动作，并断言：

```python
assert dict(catalog.action_menu_items())["完整动作展示"] == "longShowcase"
assert "longShowcase" not in dict(catalog.autoplay_actions())
assert "longShowcase" not in catalog.showcase_actions()
assert "不参加通用“动作展示”" in catalog.action_menu_details()["longShowcase"]
```

- [ ] **Step 5: 实现展示过滤和详情说明**

把 `showcase_actions()` 的过滤条件增加：

```python
and definition.include_in_showcase
```

在 `action_menu_details()` 为 `include_in_showcase=False` 的动作追加：

```python
behavior += "；该动作仅供手动播放，不参加随机动作、自主小动作或通用“动作展示”"
```

- [ ] **Step 6: 运行聚焦测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pet_registry.py tests/test_animation_catalog.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交运行时改动**

```powershell
git add -- src/shiyi_desktop_pet/models.py src/shiyi_desktop_pet/pet_registry.py src/shiyi_desktop_pet/animation_catalog.py tests/test_pet_registry.py tests/test_animation_catalog.py
git commit -m "feat: support manual-only showcase actions"
```

---

### Task 2: 同步JSON Schema和新增宠物规范

**Files:**
- Modify: `schemas/pet-pack-v3.schema.json`
- Modify: `docs/pet-pack-format-v3.md`
- Modify: `docs/添加新宠物指南.md`
- Modify: `examples/pet-pack-template/README.md`
- Test: `tests/test_documentation.py`

**Interfaces:**
- Consumes: Task 1的 `includeInShowcase` 和512帧运行时规则
- Produces: 可供第三方宠物制作者验证的同名JSON Schema契约

- [ ] **Step 1: 写文档契约失败测试**

在 `tests/test_documentation.py` 的V3 Schema测试中加入：

```python
common = schema["$defs"]["common"]["properties"]
direct = schema["$defs"]["direct"]["allOf"][1]["properties"]
assert common["includeInShowcase"] == {"type": "boolean"}
assert direct["frameCount"]["maximum"] == 512
assert direct["frameDurations"]["maxItems"] == 512
assert direct["travelStartFrame"]["maximum"] == 511
assert direct["travelEndFrame"]["maximum"] == 511
assert "includeInShowcase" in format_guide
assert "1–512" in format_guide
assert "16、32 或 64" in format_guide
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_documentation.py -q
```

Expected: FAIL，Schema仍为64且没有 `includeInShowcase`。

- [ ] **Step 3: 更新Schema**

在 `$defs.common.properties` 增加：

```json
"includeInShowcase": {"type": "boolean"}
```

把直接动作限制更新为：

```json
"frameCount": {"type": "integer", "minimum": 1, "maximum": 512},
"frameDurations": {
  "type": "array",
  "minItems": 1,
  "maxItems": 512,
  "items": {"type": "integer", "minimum": 33, "maximum": 2000}
},
"travelStartFrame": {"type": "integer", "minimum": 0, "maximum": 511},
"travelEndFrame": {"type": "integer", "minimum": 1, "maximum": 511}
```

保留 `gaze` 的 `[16, 32, 64]` 条件枚举。

- [ ] **Step 4: 更新面向用户的说明**

`docs/pet-pack-format-v3.md` 必须明确：

- 普通动作1–512帧；
- `gaze` 仍限16、32、64帧；
- `includeInShowcase` 缺省为 `true`；
- `showInMenu=true` 且 `includeInShowcase=false` 可实现“菜单可手动播放、通用展示跳过”；
- `autoplayWeight=0` 才能同时排除自主和随机动作；
- 512帧不能绕过图集、文件和JSON总量限制。

`docs/添加新宠物指南.md` 增加一个“长动作只供手动观看”的完整JSON示例。`examples/pet-pack-template/README.md` 链接到对应章节，不把模板自身改成长动作。

- [ ] **Step 5: 运行文档和解析器测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_documentation.py tests/test_pet_registry.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交规范改动**

```powershell
git add -- schemas/pet-pack-v3.schema.json docs/pet-pack-format-v3.md docs/添加新宠物指南.md examples/pet-pack-template/README.md tests/test_documentation.py
git commit -m "docs: extend the v3 long-action contract"
```

---

### Task 3: 实现15段到448帧的确定性编译器

**Files:**
- Create: `tools/build_nangongwan_complete_showcase_action.py`
- Create: `tests/test_nangongwan_complete_showcase_action.py`
- Read: `tools/render_nangongwan_action_showcase_v2.py`
- Read: `tools/nangongwan_action_showcase_v2.py`

**Interfaces:**
- Consumes: `build_showcase_plan(root: Path, background_source: Path) -> ShowcasePlan`
- Consumes: `_concatenate_actions(source: ShowcaseSource) -> TimedFrames`
- Consumes: `_segment_source_indices(segment: ShowcaseSegment, timed: TimedFrames) -> tuple[int, ...]`
- Produces: `compile_showcase_action(plan: ShowcasePlan) -> CompiledShowcaseAction`
- Produces: `build_complete_showcase(root: Path, background: Path) -> BuildResult`

- [ ] **Step 1: 写压缩时间线失败测试**

新建测试文件并定义一个使用192×208 RGBA帧的最小计划。测试公开返回对象：

```python
def test_compile_collapses_only_adjacent_equal_source_indices(monkeypatch):
    plan = synthetic_plan(output_indices=(0, 0, 1, 1, 1, 0), fps=30)
    compiled = builder.compile_showcase_action(plan)

    assert len(compiled.frames) == 3
    assert compiled.durations_ms == (67, 100, 33)
    assert sum(compiled.durations_ms) == 200
```

另外对真实计划断言：

```python
assert [segment.frame_count for segment in compiled.segments] == [
    7, 10, 7, 36, 7, 48, 7, 166, 7, 44, 7, 44, 7, 44, 7
]
assert len(compiled.frames) == 448
assert len(compiled.durations_ms) == 448
assert sum(compiled.durations_ms) == 82433
assert min(compiled.durations_ms) == 33
assert max(compiled.durations_ms) == 666
```

- [ ] **Step 2: 运行新测试并确认导入失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_nangongwan_complete_showcase_action.py -q
```

Expected: FAIL with `ModuleNotFoundError: tools.build_nangongwan_complete_showcase_action`。

- [ ] **Step 3: 实现编译数据模型和精确时间边界**

实现：

```python
@dataclass(frozen=True)
class CompiledSegment:
    id: str
    start_frame: int
    end_frame: int
    output_frames: int


@dataclass(frozen=True)
class CompiledShowcaseAction:
    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]
    segments: tuple[CompiledSegment, ...]


def frame_boundary_ms(frame_index: int) -> int:
    return round(Fraction(frame_index * 1000, FPS))
```

对每个片段单独用 `itertools.groupby(indices)` 合并相邻相同源索引，不得跨片段边界合并。每个run的时长使用全局输出帧起止边界相减；帧图像使用 `timed.frames[source_index].copy().convert("RGBA")`。

- [ ] **Step 4: 实现图集追加和像素保护**

实现：

```python
def append_frames(
    atlas: Image.Image,
    frames: tuple[Image.Image, ...],
    *,
    first_cell: int = 34 * 16,
) -> Image.Image:
    result = Image.new("RGBA", (3072, 12896), (0, 0, 0, 0))
    result.paste(atlas.convert("RGBA"), (0, 0))
    for offset, frame in enumerate(frames):
        row, column = divmod(first_cell + offset, 16)
        result.paste(frame, (column * 192, row * 208))
    return result
```

`paste` 不得传入Alpha蒙版；这里要逐像素保存RGBA，不能把半透明Alpha再次相乘。保存使用：

```python
result.save(path, "WEBP", lossless=True, method=6, exact=True)
```

- [ ] **Step 5: 写原子发布和幂等失败测试**

测试必须覆盖：

- 输入图集不是3072×7072时拒绝首次构建；
- 输入图集SHA256不是 `564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e` 时拒绝首次构建；
- 旧544格逐像素不变；
- 构建异常时正式图集和 `pet.json` 字节不变；
- 已有正确 `completeShowcase` 和新图集时再次运行不重复追加；
- 归档已存在但哈希不匹配时失败；
- 输出WebP大于32 MiB时不发布；
- 历史输入路径包含 `anime-reference` 或 `do-not-publish` 时拒绝读取。

- [ ] **Step 6: 实现CLI、清单更新和审片证据**

CLI：

```text
python tools/build_nangongwan_complete_showcase_action.py
  [--root PATH]
  [--background PATH]
  [--validate-only]
```

默认背景仅用于复用已批准视频的不可变计划：

```text
work/nangongwan-action-showcase-450px/background.png
```

它不得进入输出图集。清单追加：

```json
"completeShowcase": {
  "label": "完整动作展示",
  "role": "interaction",
  "row": 34,
  "startColumn": 0,
  "frameCount": 448,
  "frameDurations": [448个确定整数],
  "repeatCount": 1,
  "autoplayWeight": 0,
  "showInMenu": true,
  "includeInShowcase": false
}
```

输出审片证据到 `work/nangongwan-complete-showcase-action/`：

- `build-report.json`：输入哈希、输出哈希、15段边界、448项时长摘要；
- `contact-sheet-15x3.png`：每段首/中/末帧；
- `segment-boundaries/`：30张首尾原尺寸PNG。

构建到同目录临时文件，全部验证通过后才用 `Path.replace()` 发布正式图集和清单。

- [ ] **Step 7: 运行构建器测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_nangongwan_complete_showcase_action.py -q
```

Expected: PASS。

- [ ] **Step 8: 提交构建器**

```powershell
git add -- tools/build_nangongwan_complete_showcase_action.py tests/test_nangongwan_complete_showcase_action.py
git commit -m "feat: compile the complete Nangong Wan showcase"
```

---

### Task 4: 生成正式图集、归档和南宫婉动作

**Files:**
- Create: `tools/archives/nangongwan-complete-showcase-v2.4.6/README.md`
- Create: `tools/archives/nangongwan-complete-showcase-v2.4.6/pet.json`
- Create: `tools/archives/nangongwan-complete-showcase-v2.4.6/spritesheet.webp`
- Modify: `src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json`
- Modify: `src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet.webp`
- Modify: `tests/test_resource_contract.py`
- Modify: `tests/test_animation_catalog.py`

**Interfaces:**
- Consumes: Task 3的 `build_complete_showcase()`
- Produces: 正式 `completeShowcase` 动作和可审计归档
- Produces: 新图集SHA256 `6c1df790c2807c6b0293cada191fbf47be644b56a77894a3feb9407f8581c728`

- [ ] **Step 1: 先写正式资源失败测试**

在 `tests/test_resource_contract.py` 中把南宫婉契约更新为：

```python
complete = manifest["actions"]["completeShowcase"]
assert complete["label"] == "完整动作展示"
assert complete["row"] == 34
assert complete["startColumn"] == 0
assert complete["frameCount"] == 448
assert len(complete["frameDurations"]) == 448
assert sum(complete["frameDurations"]) == 82433
assert (min(complete["frameDurations"]), max(complete["frameDurations"])) == (33, 666)
assert complete["repeatCount"] == 1
assert complete["autoplayWeight"] == 0
assert complete["showInMenu"] is True
assert complete["includeInShowcase"] is False

assert (atlas.width(), atlas.height()) == (3072, 12896)
assert sha256(atlas_path.read_bytes()).hexdigest() == (
    "6c1df790c2807c6b0293cada191fbf47be644b56a77894a3feb9407f8581c728"
)
```

同时断言归档图集SHA256为：

```text
564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e
```

- [ ] **Step 2: 运行资源测试并确认缺少动作**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_resource_contract.py -q
```

Expected: FAIL with missing `completeShowcase` and old atlas size3072×7072。

- [ ] **Step 3: 执行正式构建**

Run:

```powershell
.\.venv\Scripts\python.exe tools/build_nangongwan_complete_showcase_action.py
```

Expected:

- 448帧、82433毫秒；
- 图集3072×12896；
- WebP 19,435,428字节，18.535 MiB；
- SHA256 `6C1DF790C2807C6B0293CADA191FBF47BE644B56A77894A3FEB9407F8581C728`；
- 原544格逐像素一致；
- `build-report.json` 标记全部门禁通过。

- [ ] **Step 4: 补写归档README**

README必须记录：

- 来源为桌面灵伴2.4.6正式南宫婉图集；
- 图集3072×7072、9,838,046字节；
- SHA256 `564793E6C2E090D8E882CC4A829CECCB9BDE2AB98B54B9F6126C65CF41FAC77E`；
- 仅供回退和复现；
- 位于 `tools/archives`，不会被PyInstaller收集，也不会安装到用户电脑。

- [ ] **Step 5: 验证菜单和三个候选池**

在 `tests/test_animation_catalog.py` 增加：

```python
catalog = AnimationCatalog.load_pet("nangongwan")
menu = dict(catalog.action_menu_items())
assert menu["完整动作展示"] == "completeShowcase"
assert "completeShowcase" not in dict(catalog.autoplay_actions())
assert "completeShowcase" not in catalog.showcase_actions()
assert len(catalog.frames("completeShowcase")) == 448
assert catalog.spec("completeShowcase").cycle_ms == 82433
```

- [ ] **Step 6: 运行资源和目录测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_resource_contract.py tests/test_animation_catalog.py tests/test_nangongwan_complete_showcase_action.py -q
```

Expected: PASS。

- [ ] **Step 7: 人工查看审片图**

打开：

```text
work/nangongwan-complete-showcase-action/contact-sheet-15x3.png
```

逐列确认站立吃栗子、36帧版、48帧版、V9小圆月、184月、232月、巨月和8段眨眼；确认没有桌面背景、任务栏、文字、黑帧、透明棋盘格、尺寸跳变或屋檐锚点漂移。

- [ ] **Step 8: 提交正式资源**

```powershell
git add -- tools/archives/nangongwan-complete-showcase-v2.4.6 src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet.webp tests/test_resource_contract.py tests/test_animation_catalog.py
git commit -m "feat: add the complete Nangong Wan showcase action"
```

---

### Task 5: 验证82秒动作的结束、中断和恢复

**Files:**
- Modify: `tests/test_animation_player.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `completeShowcase` 的 `AnimationSpec`
- Consumes: `DesktopPetController._play_action()` 的既有手动中断逻辑
- Produces: 长动作不需要专用运行时分支的回归证据

- [ ] **Step 1: 写时间线边界测试**

在 `tests/test_animation_player.py` 加载南宫婉目录并验证：

```python
catalog = AnimationCatalog.load_pet("nangongwan")
spec = catalog.spec("completeShowcase")
timeline = AnimationTimeline()
timeline.start("completeShowcase", 1_000)

assert timeline.advance(1_000, spec).frame_index == 0
assert not timeline.advance(83_432, spec).finished
assert timeline.advance(83_433, spec).finished
```

并验证快速/慢速由控制器现有速度换算测试覆盖，不在资源中改写时长。

- [ ] **Step 2: 写控制器中断和恢复测试**

在 `tests/test_app.py` 使用测试控制器：

```python
controller._play_action("completeShowcase", defer_autonomous=True)
assert controller.behavior.current_action == "completeShowcase"
controller._play_action(controller.catalog.idle_action, defer_autonomous=False)
assert controller.behavior.current_action == controller.catalog.idle_action
assert not controller._showcase_active
```

再模拟自然结束，断言 `_resume_base_mode()` 恢复测试原先启用的闲逛或注视设置。

- [ ] **Step 3: 运行失败测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_animation_player.py tests/test_app.py -q
```

Expected: 若测试暴露长动作边界或恢复缺陷则FAIL；若现有通用逻辑已经正确则直接PASS，不为追求改代码而增加专用分支。

- [ ] **Step 4: 只在测试证明需要时修复通用逻辑**

若82.433秒边界存在问题，修复 `AnimationTimeline.advance()` 的累计时长比较；若中断不恢复，修复 `_play_action()` / 手动完成路径。不得为 `completeShowcase` 写ID硬编码分支。

- [ ] **Step 5: 运行聚焦测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_animation_player.py tests/test_app.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交回归测试**

```powershell
git add -- tests/test_animation_player.py tests/test_app.py
git commit -m "test: verify long showcase playback recovery"
```

如果通用运行时代码确需修复，把对应源码一并加入该提交。

---

### Task 6: 升级桌面灵伴版本到2.4.7

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/shiyi_desktop_pet/__init__.py`
- Modify: `src/shiyi_desktop_pet/product.py`
- Modify: `packaging/installer.iss`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_app.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `PRODUCT_VERSION == __version__ == project.version == AppVersion == 2.4.7`
- Consumes: 安装包固定产品ID，允许从2.4.6覆盖升级

- [ ] **Step 1: 先更新版本测试期望**

把 `tests/test_packaging.py` 测试名改为 `test_product_and_installer_versions_are_2_4_7`，所有版本断言改为2.4.7；把 `tests/test_app.py` “关于桌面灵伴”期望改为：

```text
桌面灵伴 2.4.7
可用宠物：3（南宫婉、十一、紫灵）
```

- [ ] **Step 2: 运行版本测试并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_packaging.py tests/test_app.py -q
```

Expected: FAIL，实际仍为2.4.6。

- [ ] **Step 3: 更新五处产品版本**

更新：

```text
pyproject.toml                         2.4.7
src/shiyi_desktop_pet/__init__.py     2.4.7
src/shiyi_desktop_pet/product.py      2.4.7
packaging/installer.iss AppVersion    2.4.7
packaging/installer.iss VersionInfo   2.4.7.0
```

保留Inno Setup `AppId`、安装目录、快捷方式和升级逻辑不变。

- [ ] **Step 4: 写更新日志**

在 `CHANGELOG.md` 顶部新增 `2.4.7（2026-07-25）`：

- 南宫婉新增82.433秒“完整动作展示”；
- 仅右键手动触发；
- 包含15段历史阶段和三种月亮背景；
- V3普通动作上限扩展到512帧；
- 新增 `includeInShowcase`；
- 旧2.4.6图集已归档且不进入安装包。

不要把README和新手指南的公开下载链接改到尚未发布的2.4.7。

- [ ] **Step 5: 运行版本测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_packaging.py tests/test_app.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交版本改动**

```powershell
git add -- pyproject.toml src/shiyi_desktop_pet/__init__.py src/shiyi_desktop_pet/product.py packaging/installer.iss tests/test_packaging.py tests/test_app.py CHANGELOG.md
git commit -m "chore: bump Desktop Companion to 2.4.7"
```

---

### Task 7: 全量验证并构建2.4.7安装包

**Files:**
- Create: `docs/manual-qa-v2.4.7.md`
- Generated, not committed: `artifacts/桌面灵伴安装程序.exe`
- Generated, not committed: `artifacts/DesktopCompanion-2.4.7-setup.exe`

**Interfaces:**
- Consumes: Tasks 1–6的源码和资源
- Produces: 可安装的Windows当前用户安装包和完整QA证据

- [ ] **Step 1: 检查工作树边界**

Run:

```powershell
git status --short
git diff --check
```

Expected: 只显示三项用户原有未提交修改；本计划自己的改动均已提交。

- [ ] **Step 2: 运行全部源码测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 全部PASS，无跳过本功能关键测试。

- [ ] **Step 3: 运行构建器只验证模式**

Run:

```powershell
.\.venv\Scripts\python.exe tools/build_nangongwan_complete_showcase_action.py --validate-only
```

Expected: 图集、清单、归档、15段、448帧、82433毫秒和审片报告全部通过，正式文件mtime不变化。

- [ ] **Step 4: 构建冻结应用和安装包**

Run:

```powershell
& .\scripts\build_installer.ps1
```

Expected:

- PyInstaller构建成功；
- Inno Setup版本在 `>=6.7.3,<8`；
- 生成 `artifacts\桌面灵伴安装程序.exe`；
- 安装包包含新活动图集，但不包含 `tools\archives`。

- [ ] **Step 5: 复制为版本化安装包并记录哈希**

Run:

```powershell
Copy-Item -LiteralPath '.\artifacts\桌面灵伴安装程序.exe' -Destination '.\artifacts\DesktopCompanion-2.4.7-setup.exe' -Force
Get-FileHash -Algorithm SHA256 -LiteralPath '.\artifacts\DesktopCompanion-2.4.7-setup.exe'
Get-Item -LiteralPath '.\artifacts\DesktopCompanion-2.4.7-setup.exe' | Select-Object Length,LastWriteTime
```

Expected: 两个安装包字节相同，SHA256相同。

- [ ] **Step 6: 运行发布验证脚本**

先用独立测试目录，不碰正式安装：

```powershell
& .\scripts\verify_release.ps1 -Installer '.\artifacts\DesktopCompanion-2.4.7-setup.exe' -TestDir '.\work\release-test-v2.4.7'
```

Expected: 安装、启动、自检、设置持久化、快捷方式、升级/卸载和回滚保护全部PASS。

- [ ] **Step 7: 写QA文档**

`docs/manual-qa-v2.4.7.md` 记录实际：

- 完整pytest通过数量；
- 图集尺寸、字节、SHA256；
- 448帧、82433毫秒、15段；
- 安装包字节和SHA256；
- `verify_release.ps1` 结果；
- 接触表路径；
- 归档哈希；
- 仍待执行的正式本机覆盖安装状态。

- [ ] **Step 8: 提交QA记录**

```powershell
git add -- docs/manual-qa-v2.4.7.md
git commit -m "docs: record Desktop Companion 2.4.7 verification"
```

---

### Task 8: 备份并覆盖安装到本机

**Files:**
- Backup: `work/local-install-backup-before-v2.4.7-complete-showcase-<timestamp>/`
- Install target: `%LOCALAPPDATA%\Programs\DesktopCompanion`
- User state: `%APPDATA%\DesktopCompanion`

**Interfaces:**
- Consumes: `artifacts/DesktopCompanion-2.4.7-setup.exe`
- Produces: 本机可右键播放“完整动作展示”的桌面灵伴2.4.7

- [ ] **Step 1: 记录并备份当前安装**

用PowerShell创建带时间戳备份目录，复制：

- `%LOCALAPPDATA%\Programs\DesktopCompanion`；
- `%APPDATA%\DesktopCompanion`；
- `%LOCALAPPDATA%\DesktopCompanion`；
- `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DesktopCompanion`；
- 桌面快捷方式；
- Inno卸载注册表项。

备份目录必须解析为工作树下 `work\` 的子目录后才允许递归复制。

- [ ] **Step 2: 静默覆盖安装**

Run:

```powershell
Start-Process -FilePath '.\artifacts\DesktopCompanion-2.4.7-setup.exe' -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CLOSEAPPLICATIONS' -Wait -WindowStyle Hidden
```

Expected: exit code 0，保留用户设置和南宫婉当前选择。

- [ ] **Step 3: 核对安装版本和资源**

验证：

```text
%LOCALAPPDATA%\Programs\DesktopCompanion\DesktopCompanion.exe
```

文件版本及卸载注册表 `DisplayVersion` 均为2.4.7；冻结资源中的南宫婉活动图集SHA256为 `6C1DF...F8581C728`，不存在 `tools/archives` 归档目录。

- [ ] **Step 4: 启动并验证菜单**

启动安装版，切换到南宫婉，右键确认：

- 存在“完整动作展示”；
- 详情显示448帧、约82.43秒、仅手动播放；
- “随机动作”不触发它；
- “动作展示”不重复收录它。

- [ ] **Step 5: 播放一次完整动作**

从右键菜单选择“完整动作展示”，至少检查：

- 开头眨眼和站立吃栗子；
- 36帧与48帧版本；
- V9小圆月；
- 184月、232月和巨月吃栗子；
- 最后眨眼后恢复原基础模式；
- 人物窗口位置和当前100%大小不改变。

另一次播放中途选择“静立凝神”，确认立即中断且下次从第一帧重播。

- [ ] **Step 6: 回写正式本机验收**

在 `docs/manual-qa-v2.4.7.md` 补充：

- 备份目录；
- 覆盖安装时间；
- 注册表和文件版本；
- 桌面快捷方式；
- 设置保留；
- 完整动作和中断验证结果。

提交：

```powershell
git add -- docs/manual-qa-v2.4.7.md
git commit -m "docs: record the local 2.4.7 upgrade"
```

- [ ] **Step 7: 最终核验**

Run:

```powershell
git status --short
git log -10 --oneline
```

Expected: 仍只保留任务开始前的三项用户未提交修改；安装包、work输出和本机备份不提交；不得执行任何远程推送。
