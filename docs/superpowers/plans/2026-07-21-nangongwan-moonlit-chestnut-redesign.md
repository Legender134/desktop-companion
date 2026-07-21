# 南宫婉“月下含栗”原地展开式重做实施计划

> 依据：`docs/superpowers/specs/2026-07-21-nangongwan-moonlit-chestnut-redesign.md`

**目标：** 把 2.4.1 中像“播放动画片”的 36 帧“月下含栗”完整替换为 48 帧、9600 毫秒的原地桌面动作，同时把 2.4.1 旧图集作为第二张 WebP 原样随程序安装。候选动态预览通过用户验收前，不更新本机安装、不构建正式 Release、不推送 GitHub/Gitee。

**核心约束：** 人物保持正常桌面尺寸和屏幕锚点；完整表现站立、场景渐显、坐下、御物含栗、起身和场景消散；取消远景小人和脸部大特写；旧 WebP 保持字节、大小和 SHA256 不变。

---

## 任务 1：隔离工作区并恢复可重复测试环境

**操作：**

1. 从当前 `main` 创建 `feature/moonlit-chestnut-redesign`，工作树放在 `.worktrees/moonlit-chestnut-redesign`。
2. 不带入主工作区未跟踪的 `.superpowers/` 和 `backups/`。
3. 在工作树中使用 Python 3.12 创建 `.venv`，安装 `requirements/dev.txt` 和可编辑项目。
4. 运行基线测试：

```powershell
& .\.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
```

5. 记录现有 2.4.1 图集的大小、SHA256、图集尺寸和现有动作配置，作为不可变基线。

**通过条件：** 基线测试结果明确；如果存在与本功能无关的既有失败，单独记录，不能误报为本轮引入。

## 任务 2：先建立旧 WebP 归档契约

**文件：**

- 修改：`tests/test_resource_contract.py`
- 修改：`tests/test_packaging.py`
- 新增：`src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet-moonlit-chestnut-v2.4.1-legacy.webp`

**测试先行：**

1. 新增测试，要求归档文件存在、大小为 `8,634,008` 字节、SHA256 为 `990D1EE9DB3632102E9F07984301519606A9CC3591585E8EF892D0BA975A9D3E`。
2. 验证 `pet.json` 的活动图集仍只指向 `spritesheet.webp`，不会加载归档图集。
3. 验证 PyInstaller 资源收集规则会把归档文件带入冻结目录。
4. 运行测试并确认在复制前失败。
5. 按字节复制当前 `spritesheet.webp` 为归档文件，不重新编码。
6. 重跑测试并确认通过。

**提交：** `test: preserve legacy Nangong Wan atlas`

## 任务 3：建立 48 帧和 9600 毫秒动作契约

**文件：**

- 修改：`tests/test_resource_contract.py`
- 修改：`tests/test_animation_catalog.py`
- 修改：`tests/test_app.py`
- 修改：`tests/test_moonlit_asset_builder.py`
- 修改：`src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json`

**测试先行：**

1. 把 `moonlitChestnut` 的期望改为：`row=23`、`frameCount=48`、48 项精确时长、总和 `9600`、`repeatCount=1`。
2. 验证 48 帧正好占满零基第 23–25 行，最后一帧位于第 25 行第 15 列，图集仍为 `3072×5408`。
3. 验证动作在 9599 毫秒尚未结束、9600 毫秒只完成一次，随后无缝返回待机。
4. 保持 `autoplayWeight=5`、`cooldownMs=90000`、`showInMenu=true` 和约 `5/101` 名义权重。
5. 先运行定向测试并确认旧 36 帧配置失败，再更新 `pet.json` 使配置契约通过；素材测试在新图集完成前仍应保持失败。

**提交：** `test: define 48-frame moonlit chestnut contract`

## 任务 4：制作可复用角色参考板

**文件：**

- 新增：`tools/assets/nangongwan-moonlit-chestnut-redesign-reference.png`
- 新增或修改：`tools/build_nangongwan_moonlit_chestnut.py`
- 本地审图：`work/moonlit-chestnut-redesign/reference-audit.png`

**操作：**

1. 从活动图集中抽取南宫婉正常待机、侧面、抬手、蓝银衣装和现有栗糕相关画面，组合成透明参考板。
2. 参考板标注固定的脚底基准、人物头部尺度、右手、发饰、袖口、栗糕颜色和屋檐透视方向。
3. 把动漫参考仅用于本地观察；不得把原视频截图打入安装包或发布资源。
4. 人工检查参考板，确保它不包含旧动作的远景比例和脸部大特写作为目标构图。

**通过条件：** 后续所有生成阶段均引用同一参考板，人物造型和锚点有统一依据。

## 任务 5：分阶段重画 48 个直接运行帧

**文件：**

- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-01-standing.png`（4 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-02-reveal.png`（6 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-03-sit.png`（10 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-04-settle.png`（5 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-05-chestnut.png`（8 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-06-taste.png`（6 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-07-stand.png`（6 帧）
- 新增：`tools/assets/nangongwan-moonlit-redesign/phase-08-fade.png`（3 帧）

**生成策略：**

1. 每个阶段单独生成较小的连续分镜，不再要求一次模型生成 48 格大图。
2. 第一阶段引用统一参考板；后续阶段同时引用统一参考板和上一阶段最后一帧，维持人物、屋檐和月面连续。
3. 每一格都是直接运行帧；不再用 8 张关键图配合全图缩放凑出 48 帧。
4. 先完成站立到坐下 20 帧并做第一次静态审图；确认人物尺度、脚底和屋檐锚点后再继续御物、含栗和起身。
5. 紫色灵光只出现在右手和栗糕附近；月亮使用局部弧面；场景边缘透明渐隐。
6. 若任何阶段出现人物换脸、服装变化、屋檐翻向、手指数目异常或身体漂移，整阶段重生成，不能靠缩放掩盖。

**通过条件：** 48 个直接运行帧均可解析；至少 20 个独立姿态关键帧；站到坐不少于 8 个不同身体姿态，起身不少于 6 个，御物和含栗不少于 6 个。

## 任务 6：重写素材构建器并替换活动图集

**文件：**

- 修改：`tools/build_nangongwan_moonlit_chestnut.py`
- 修改：`src/shiyi_desktop_pet/resources/pets/nangongwan/spritesheet.webp`
- 修改：`tests/test_moonlit_asset_builder.py`
- 新增本地审图：`work/moonlit-chestnut-redesign/audit-48.png`

**实现：**

1. 构建器按八个阶段的显式网格说明裁出 48 帧，统一到 `192×208 RGBA`。
2. 构建器只允许写入第 23–25 行，写入前后比较第 0–22 行像素哈希，确保其他动作不变。
3. 构建器不得读取或改写归档 WebP；每次运行后再次验证归档大小和 SHA256。
4. 生成 8×6 的 48 帧透明棋盘格审图，并输出每帧 alpha 边界、脚底基准和相邻帧差异指标。
5. 更新构建器测试：源图布局、48 帧数量、活动区域、旧区域保持、归档不可变、输出确定性。

**提交：** `feat: rebuild moonlit chestnut as anchored desktop action`

## 任务 7：动态连贯性诊断和候选预览

**文件：**

- 新增或修改：`tools/preview_nangongwan_moonlit_chestnut.py`
- 本地输出：`work/moonlit-chestnut-redesign/moonlit-chestnut-9600ms.gif`
- 本地输出：`work/moonlit-chestnut-redesign/moonlit-chestnut-9600ms.mp4`
- 本地输出：`work/moonlit-chestnut-redesign/transition-metrics.json`
- 本地输出：`work/moonlit-chestnut-redesign/hardest-seams.png`

**验证：**

1. 严格使用 `pet.json` 中 48 项时长生成正常速度预览，并另生成 75% 和 125% 速度版本。
2. 分别合成在深色和浅色桌面背景上；不能只看透明棋盘格。
3. 对人物与屋檐有效 alpha 区域计算相邻帧平均 RGB 差值和变化像素占比；平均差值不得超过 35，变化超过 20 灰度级的像素占比不得超过 35%。
4. 单独输出最大差异接缝，人工检查站到坐、坐到御物、含栗到起身、场景消散到待机。
5. 第一帧和最后一帧与真实待机首帧叠加检查；窗口锚点不变。
6. 在源程序中以 75%、100%、125% 三种宠物缩放手动播放候选动作，不安装正式版本。

**通过条件：** 自动指标达标、动态预览没有突跳、没有整幅动画片替换宠物的感觉。

## 任务 8：候选交付和用户视觉验收门

**交付：**

1. 向用户展示正常速度 GIF/MP4、48 帧审图和最大接缝图。
2. 明确列出与 2.4.1 旧版的差异，并提供旧版归档 WebP 路径。
3. 此时停止，不更新本机安装、不改正式版本号、不构建发布安装包、不上传远端。
4. 用户确认动态效果后，另行执行版本升级、完整测试、冻结构建、安装验证和 GitHub/Gitee 发布；用户要求修改则回到对应阶段重画。

**最终候选提交：** `feat: prepare anchored moonlit chestnut candidate`
