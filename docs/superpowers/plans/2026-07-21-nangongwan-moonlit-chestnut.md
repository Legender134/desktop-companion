# Nangong Wan Moonlit Chestnut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为桌面灵伴版南宫婉增加 36 帧、9.1 秒的标志性“月下含栗”动作，使它可以手动播放、按约 1/20 的基础权重自主触发并加入动作展示，同时把旧“栗糕轻尝”完整保留为以后彩蛋使用。

**Architecture:** 沿用 v3 宠物包的动态跨行取帧机制，不修改动画播放器。新帧追加到南宫婉图集第 24–26 行（零基行为 23–25）；`pet.json` 负责动作时序、权重与冷却。动作目录仅增加一条窄筛选规则，让既不显示菜单、又不参与自主播放的休眠动作不进入“动作展示”。

**Tech Stack:** CPython 3.12、PySide6/QImage、Pillow、WebP RGBA、pytest/pytest-qt、PyInstaller、Inno Setup。

## Global Constraints

- 仅修改桌面灵伴版，不修改 `C:\Users\23644\.codex\pets\nangongwan`。
- 旧 `tasteCake` 的 10 帧、时序和资源必须保留；只删除其 `autoplayWeight`、设 `showInMenu=false`，不能删除动作 ID。
- 新动作 ID 固定为 `moonlitChestnut`，标签固定为“月下含栗”，36 帧时长总和必须为 9100 ms，`repeatCount=1`、`autoplayWeight=5`、`cooldownMs=90000`、`showInMenu=true`。
- 新动作以透明 RGBA 单元格呈现；不得把矩形夜空烘焙成不透明背景，不得出现编造的雷电、法阵或花瓣特效。
- 角色使用当前蓝银元婴造型；栗糕为金黄色、有纹理的块状糕点；紫色灵力只包裹手指和栗糕。
- 私有动漫片段和抽帧只作参考，不能提交、打包或发布。
- `.superpowers/`、`work/` 和 `private-reference/` 不进入提交。

---

### Task 1: Lock the Resource and Selection Contracts with Failing Tests

**Files:**

- Modify: `tests/test_resource_contract.py`
- Modify: `tests/test_animation_catalog.py`
- Modify: `tests/test_menu_controller.py`

- [ ] **Step 1: Extend the Nangong Wan resource contract**

Change the expected action count from 20 to 21, the summed frame count from 238 to 274, and the atlas size from `3072×4784` to `3072×5408`. Add exact assertions:

```python
moonlit = manifest["actions"]["moonlitChestnut"]
assert moonlit == {
    "label": "月下含栗",
    "role": "interaction",
    "row": 23,
    "frameCount": 36,
    "frameDurations": [
        180, 180, 220, 300, 260, 300, 420, 500,
        150, 150, 160, 170, 180, 220,
        180, 220, 200, 240,
        140, 150, 170, 190, 260,
        140, 150, 170, 190, 260,
        260, 350, 500, 450, 650, 220, 260, 360,
    ],
    "repeatCount": 1,
    "autoplayWeight": 5,
    "cooldownMs": 90000,
    "showInMenu": True,
}
assert sum(moonlit["frameDurations"]) == 9100

legacy = manifest["actions"]["tasteCake"]
assert "autoplayWeight" not in legacy
assert legacy["showInMenu"] is False
```

Also assert that cells `(25, 4)` through `(25, 15)` have zero alpha so unused atlas space stays transparent.

- [ ] **Step 2: Specify menu, autoplay, showcase and legacy-resolution behavior**

Add a catalog test that loads `nangongwan` and asserts:

```python
menu = dict(catalog.action_menu_items())
autoplay = dict(catalog.autoplay_actions())

assert menu["月下含栗"] == "moonlitChestnut"
assert "栗糕轻尝" not in menu
assert autoplay["moonlitChestnut"] == 5
assert "tasteCake" not in autoplay
assert "moonlitChestnut" in catalog.showcase_actions()
assert "tasteCake" not in catalog.showcase_actions()
assert len(catalog.frames("tasteCake")) == 10
assert autoplay["moonlitChestnut"] / sum(autoplay.values()) == pytest.approx(5 / 101)
```

The expected 101 denominator is the interaction-only configured pool: all retained interaction weights are multiplied by three to total 96, then “月下含栗” contributes 5.

- [ ] **Step 3: Specify the updated showcase help text**

Add a menu test with `display_details=True` that inspects “动作展示” and requires wording that includes “菜单可见或允许自主触发” and “休眠/彩蛋动作不会播放”.

- [ ] **Step 4: Run focused tests and confirm RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_resource_contract.py tests\test_animation_catalog.py tests\test_menu_controller.py -q
```

Expected: FAIL because `moonlitChestnut` does not exist, the atlas is still 4784 px high, `tasteCake` is still public/autonomous, and `showcase_actions()` still returns every interaction.

---

### Task 2: Implement the Catalog Rule and Manifest Metadata

**Files:**

- Modify: `src/shiyi_desktop_pet/animation_catalog.py:392`
- Modify: `src/shiyi_desktop_pet/menu_controller.py:341`
- Modify: `src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json`

- [ ] **Step 1: Narrow the showcase pool**

Replace the pass-through implementation with:

```python
def showcase_actions(self) -> tuple[ActionKey, ...]:
    return tuple(
        definition.action_id
        for definition in self._action_definitions
        if definition.role is ActionRole.INTERACTION
        and (definition.show_in_menu or definition.autoplay_weight > 0)
    )
```

This retains menu-hidden autonomous actions such as `gatherSleeves`, but excludes a dormant action only when both public discovery paths are disabled.

- [ ] **Step 2: Update the detail text for “动作展示”**

Explain that showcase plays interaction actions that are menu-visible or autonomous, including hidden autonomous actions, but skips dormant/easter-egg actions that are both menu-hidden and weightless.

- [ ] **Step 3: Update the Nangong Wan manifest**

Apply these exact metadata changes:

- `tasteCake`: preserve row, frames, durations, repeat count and cooldown; remove `autoplayWeight`; set `showInMenu` to `false`.
- Multiply interaction weights by three for `offerVeil` through `reincarnationLight`, excluding `tasteCake`: `6,15,9,18,12,12,6,3,3,3,3,3,3,3` in existing action order.
- Add `moonlitChestnut` after `reincarnationLight`, using the exact 36 durations from Task 1 and row 23.
- Update the pet description to mention the moonlit rooftop signature action and eight effect/story actions.

- [ ] **Step 4: Run the non-image catalog tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_animation_catalog.py tests\test_menu_controller.py -q
```

Expected: PASS. `test_resource_contract.py` remains red only because the new atlas cells do not exist yet.

- [ ] **Step 5: Commit the behavioral change**

```powershell
git add src/shiyi_desktop_pet/animation_catalog.py src/shiyi_desktop_pet/menu_controller.py src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json tests/test_animation_catalog.py tests/test_menu_controller.py tests/test_resource_contract.py
git commit -m "feat: define Nangong Wan moonlit chestnut action"
```

---

### Task 3: Produce and Assemble the 36-Frame Transparent Action

**Files:**

- Create: `tools/build_nangongwan_moonlit_chestnut.py`
- Create: `work/moonlit-chestnut/keyframes/*.png` (ignored working evidence)
- Create: `work/moonlit-chestnut/frames/frame-01.png` through `frame-36.png` (ignored working evidence)
- Create: `work/moonlit-chestnut/audit.png` (ignored working evidence)
- Modify: `src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet.webp`

- [ ] **Step 1: Build approved keyframes from the official reference**

Use the image-generation workflow with the current sprite character as the identity/style reference and official trailer frames only as pose/composition references. Produce transparent keyframes for these beats: empty moon/eave opening, far seated silhouette, medium seated full figure, raised hand with purple aura, floating golden栗糕, at-lips hold/blink, moonward look, and far-shot fade.

Reject and regenerate any keyframe that violates the Global Constraints or changes face, hairstyle, clothing, eave orientation, light direction, hand count, or栗糕 identity.

- [ ] **Step 2: Implement a deterministic frame builder**

`tools/build_nangongwan_moonlit_chestnut.py` must:

- require the approved keyframe PNGs and fail with a clear missing-file error;
- normalize every frame to 192×208 RGBA without an opaque rectangular background;
- create 36 distinct frames using staged scale/translation/opacity interpolation plus separately animated fog, moonlight, hair/sleeve drift, blink, hand and栗糕 motion;
- preserve alpha edges and save frame PNGs to `work/moonlit-chestnut/frames`;
- expand the existing 3072×4784 atlas onto a transparent 3072×5408 canvas;
- paste frames sequentially from zero-based row 23, column 0, wrapping at 16 columns;
- keep row 25 columns 4–15 fully transparent;
- save lossless RGBA WebP to the packaged `spritesheet.webp`;
- create a labeled 6×6 audit sheet on a checkerboard background without modifying packaged resources beyond the WebP atlas.

- [ ] **Step 3: Generate, inspect and revise the frame audit**

Run:

```powershell
& .\.venv\Scripts\python.exe tools\build_nangongwan_moonlit_chestnut.py
```

Inspect `work/moonlit-chestnut/audit.png` at 100% and verify the nine approved story stages, exact character identity, readable hand/栗糕 interaction, smooth far-to-near and near-to-far transitions, and visible motion in every adjacent pair. Correct keyframes or interpolation until no duplicate-looking filler frame remains.

- [ ] **Step 4: Run the resource contract and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_resource_contract.py -q
```

Expected: PASS with a 3072×5408 alpha atlas, all 36 new cells non-empty, and all 12 unused trailing cells transparent.

- [ ] **Step 5: Commit the reproducible asset pipeline and atlas**

```powershell
git add tools/build_nangongwan_moonlit_chestnut.py src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet.webp
git commit -m "art: add Nangong Wan moonlit rooftop animation"
```

---

### Task 4: Verify Playback, Manual Access and Autonomous Timing

**Files:**

- Modify: `tests/test_app.py`
- Modify: `tests/test_animation_catalog.py`

- [ ] **Step 1: Add a 36-frame playback regression test**

Load Nangong Wan, play `moonlitChestnut`, advance using the exact per-frame durations, and assert:

- all coordinates are exactly `(23,0)` through `(25,3)` in row-major order;
- frame 36 is reached once;
- the next completion returns to idle rather than looping or indexing out of bounds;
- the normal-speed elapsed duration is 9100 ms.

- [ ] **Step 2: Add manual/autonomous integration assertions**

Assert the generated menu includes “月下含栗”; dispatching it starts the exact action regardless of cooldown state. Assert autonomous selection records the 90-second cooldown, while a second manual dispatch still starts immediately. Assert showcase contains the new action exactly once and omits `tasteCake`.

- [ ] **Step 3: Run the focused application suite**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_animation_catalog.py tests\test_app.py -q
```

Expected: PASS with no timer, cooldown or showcase regression.

- [ ] **Step 4: Commit integration coverage**

```powershell
git add tests/test_app.py tests/test_animation_catalog.py
git commit -m "test: cover moonlit chestnut playback"
```

---

### Task 5: Documentation, Full Verification and Visual Acceptance

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `tests/test_documentation.py`
- Create: `docs/manual-qa-v2.4.1.md`
- Modify: `docs/superpowers/specs/2026-07-21-nangongwan-moonlit-chestnut-design.md`

- [ ] **Step 1: Document the completed feature**

Mark the design status approved/implemented. Add a `2.4.1（2026-07-21）` changelog entry describing the new 36-frame rooftop action, 1/20 nominal autonomous chance, 90-second cooldown, manual menu access, and retirement of the old short action into a future easter egg. Update README’s verification link to `docs/manual-qa-v2.4.1.md`.

Also repair the pre-existing stale documentation assertion by changing the expected installer name in `tests/test_documentation.py` from `DesktopCompanion-2.3.0-Setup.exe` to the 2.4.1 name documented by README.

- [ ] **Step 2: Run source tests and integrity checks**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
git diff --check
git status --short
```

Expected: zero failures, no whitespace errors, and only intentional tracked changes plus ignored/untracked `.superpowers/` evidence.

- [ ] **Step 3: Build and smoke-test the frozen application**

Run:

```powershell
& .\scripts\build_installer.ps1
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_frozen_smoke.py -q
```

Expected: build exits 0; the frozen EXE self-test loads the 3072×5408 WebP and all pet definitions; frozen smoke passes.

- [ ] **Step 4: Perform interactive visual QA**

At 75%, 100% and 125% pet sizes, manually trigger “月下含栗” and verify the complete 9.1-second arc. Then enable autonomous actions and use a deterministic/random-seed harness to confirm eligibility and cooldown without waiting for twenty natural cycles. Check that drag, pet switch, another manual action and exit safely interrupt playback. Record results and screenshots/audit references in `docs/manual-qa-v2.4.1.md`.

- [ ] **Step 5: Final review and commit**

Review the diff against every Global Constraint, confirm private references are absent from `git status`, then run:

```powershell
git add CHANGELOG.md README.md docs/manual-qa-v2.4.1.md docs/superpowers/specs/2026-07-21-nangongwan-moonlit-chestnut-design.md
git commit -m "docs: record moonlit chestnut release verification"
```

Expected final state: clean tracked worktree; `.superpowers/` may remain untracked locally but must not be added.
