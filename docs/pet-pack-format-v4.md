# 桌面灵伴 v4 分层多形态宠物包格式

v4 用多个透明 WebP 图集、按锚点组合的图层、形态、变形和动作序列描述宠物。宠物包仍是纯数据：运行时只读取 UTF-8 JSON 和 WebP，不执行包内的 Python、JavaScript、DLL 或 EXE。

第一次制作普通单形态宠物时，v3 更简单；只有需要多图集分层、超出身体宽度的特效、可切换形态或可安全中止的连段时才应选择 v4。固定 11 行旧图集继续使用 [v2 规范](pet-pack-format-v2.md)，单图集动态动作继续使用 [v3 规范](pet-pack-format-v3.md)。支持 JSON Schema 的编辑器可加载 [`schemas/pet-pack-v4.schema.json`](../schemas/pet-pack-v4.schema.json)。

兼容性以运行时校验为准。Schema 能检查字段形状和数值范围，但不能读取文件、解码图像，也不能完成全部跨字段检查。

## 目录、文件和总量限制

目录名必须与 `pet.json` 的 `id` **逐字符、区分大小写地相同**：

```text
myPetV4\
├─ pet.json
├─ character.webp
└─ effects.webp
```

- `pet.json` 必须是 UTF-8，最大 64 KiB。
- 允许 1–8 个图集；所有图集的编码文件大小合计必须大于 0 且不超过 32 MiB。
- 所有图集解码后的像素总数不超过 50,000,000，即对每张图求 `width × height` 后相加。
- 图集必须是 Qt 可解码、带 alpha 通道的 WebP。宽和高必须分别是该图集 `cellWidth`、`cellHeight` 的正整数倍。
- 宠物目录、`pet.json` 和图集文件不能是符号链接；宠物目录也不能是目录联接。
- 图集文件名必须是当前目录中的裸文件名，匹配 `[A-Za-z0-9][A-Za-z0-9._-]*\.webp`；后缀必须写成小写 `.webp`。不接受绝对路径、子目录或 `..`。
- 不同 atlas ID 必须指向不同文件。

v4 不使用 `spritesheetPath`，也不支持 v3 的 `states` 字段。出现任意未列出的字段都会使整个包失效。

## 命名、大小写和公共文本

v4 的 `id`，以及 atlas、action、form、transformation、sequence、bucket 和 cooldown group 的键，都匹配：

```text
^[a-z][A-Za-z0-9]{0,63}$
```

也就是 1–64 个 ASCII 字符，首字符必须是小写英文字母，后续只能是英文字母或数字。推荐 lower camelCase，例如 `defaultHuman`、`wideSpell`。名称区分大小写；`wideSpell` 和 `widespell` 是两个键。下划线、连字符、空格和中文都不能出现在这些技术键中，因此 `multiform_v4` 不是合法 v4 ID。

根对象的公共字段如下：

| 字段 | 必需 | 规则 |
|---|---:|---|
| `id` | 是 | 上述 v4 技术键；必须与目录名完全相同 |
| `displayName` | 是 | 去除首尾空白后 1–80 个可打印字符；不能含 C0、DEL 或 C1 控制字符 |
| `description` | 否 | 最多 500 字符；不能含 C0 或 DEL 控制字符；默认空字符串 |
| `spriteVersionNumber` | 是 | 必须是数字 `4`，布尔值无效 |
| `defaultForm` | 是 | 已声明的 form ID |
| `iconFrame` | 否 | `atlas`、`row`、`column`；省略时使用第一项 atlas 的第 0 行第 0 列 |
| `atlases` | 是 | 1–8 项 |
| `cooldownGroups` | 否 | 0–32 项 |
| `actions` | 是 | 1–128 项 |
| `forms` | 是 | 1–16 项 |
| `transformations` | 否 | 0–32 项 |
| `sequences` | 否 | 0–16 项 |

`label` 用于 action、form、transformation 和 sequence 的用户可见名称：去除首尾空白后 1–80 个字符，不能含 C0、DEL 或 C1 控制字符。

JSON 字段名固定使用表中所示的 camelCase，且区分大小写。例如必须写 `frameCount`，不能写 `frame_count`、`FrameCount` 或 `framecount`。所有对象都拒绝未知字段。

## 图集与托盘代表帧

`atlases` 的每一项恰好包含：

```json
"character": {
  "path": "character.webp",
  "cellWidth": 192,
  "cellHeight": 208
}
```

| 字段 | 规则 |
|---|---|
| `path` | 当前目录中唯一的裸 `.webp` 文件名 |
| `cellWidth` | 1–2,147,483,647 的整数 |
| `cellHeight` | 1–2,147,483,647 的整数 |

不同图集可以采用不同单格尺寸，例如身体格 `192 × 208`，宽特效格 `384 × 208`。图集按固定格网切分；行、列从 0 开始。

`iconFrame` 恰好包含 `atlas`、`row` 和 `column`。行列必须是非负整数且位于该 atlas 的格网内；所选格必须至少有一个非透明像素。程序从这一整格生成宠物托盘图标。

## Action 对象

每个 action 至少包含 `label`、`role`、`frameCount`、`layers`，并且必须在 `frameMs` 与 `frameDurations` 中恰好选择一个。

### 通用字段

| 字段 | 必需 | 范围或默认值 |
|---|---:|---|
| `label` | 是 | 1–80 个可打印字符 |
| `role` | 是 | `idle`、`move`、`interaction`、`burstMove` 或 `gaze` |
| `direction` | 移动类是 | `left` 或 `right`；只能用于 `move`、`burstMove` |
| `frameCount` | 是 | 1–512 |
| `frameMs` | 二选一 | 33–2000 毫秒，所有帧相同 |
| `frameDurations` | 二选一 | 长度必须等于 `frameCount`，每项 33–2000 毫秒 |
| `loop` | 否 | `idle` 默认 `true`，其余默认 `false` |
| `repeatCount` | 否 | 1–20，默认 1；只用于非循环动作，不能与 `loop: true` 同时出现 |
| `holdMs` | 否 | 0–10000，默认 0；动作轮次结束后保持末帧 |
| `showInMenu` | 否 | `gaze` 默认 `false`，其余默认 `true` |
| `includeInShowcase` | 否 | 默认 `true` |
| `autoplayWeight` | 否 | 0–100；`move` 默认 10，其余默认 0 |
| `cooldownMs` | 否 | 0–1,200,000，默认 0；普通 action 自主播放冷却 |
| `autoplayGroup` | 否 | 空字符串或 v4 技术键，默认空；非空值只能用于 `interaction` |
| `mirrorOf` | 否 | 直接绘制的同 role、反方向 action ID |
| `layers` | 是 | 1–8 层，按数组顺序从后景绘制到前景 |

角色约束：

- `idle` 必须循环，且 `autoplayWeight` 必须为 0。
- `interaction` 和 `burstMove` 不能永久循环。
- `gaze` 必须有 16、32 或 64 帧，`autoplayWeight` 必须为 0。
- `move`、`burstMove` 必须声明方向；其他 role 禁止声明方向。
- `burstMove` 至少 3 帧、`repeatCount` 必须为 1。

role 限制按有效值判断：非 `interaction` action 可以显式写 `autoplayGroup: ""`，效果与省略相同；只有非空组名才要求 role 为 `interaction`。同理，非 `burstMove` action 可以显式写 `minDistance: 0`，只有非零距离才要求 role 为 `burstMove`。换句话说，显式 `autoplayGroup: ""` 和显式 `minDistance: 0` 都是运行时接受的中性值。

`includeInShowcase`、`showInMenu`、action 自身的 `autoplayWeight`/`cooldownMs`/`autoplayGroup` 保留 v3 动作菜单和普通自主动作语义。它们不是下文 transformation/sequence 的 bucket 调度字段；v4 长事件只有声明自己的 `autoplay` 对象才进入 bucket 调度。

### 快速移动字段

这些字段用于 `role: "burstMove"`。`travelStartFrame`、`travelEndFrame`、`travelDistanceRatio`、`maxVerticalRatio` 只要出现就要求该 role；`minDistance` 的非零值要求该 role，显式 0 是所有 role 都可接受的中性值：

| 字段 | 范围或默认值 |
|---|---|
| `minDistance` | 0–10000，默认 0 |
| `travelStartFrame` | 默认约为前三分之一处 |
| `travelEndFrame` | 默认约为后三分之一处 |
| `travelDistanceRatio` | 可选，0.05–1 |
| `maxVerticalRatio` | 可选，0–1 |

帧边界必须满足 `0 <= travelStartFrame < travelEndFrame < frameCount`。位移、屏幕边界和方向选择与 v3 `burstMove` 相同。

## Layer 对象、取帧和镜像

每个 layer 必须包含：

```json
{
  "atlas": "character",
  "row": 0,
  "startColumn": 0,
  "anchorX": 96,
  "anchorY": 208,
  "hitTest": true
}
```

| 字段 | 必需 | 范围或默认值 |
|---|---:|---|
| `atlas` | 是 | 已声明的 atlas ID |
| `row` | 是 | 非负整数 |
| `startColumn` | 是 | 非负整数 |
| `anchorX` | 是 | 非负整数，位于源格坐标系中，不要求落在格内 |
| `anchorY` | 是 | 非负整数，位于源格坐标系中，不要求落在格内 |
| `offsetX` | 否 | -100000–100000，默认 0 |
| `offsetY` | 否 | -100000–100000，默认 0 |
| `scalePercent` | 否 | 1–1000，默认 100 |
| `opacityPercent` | 否 | 0–100，默认 100 |
| `hitTest` | 否 | 默认 `false`；一个 action 必须恰好有一层为 `true` |
| `optionalInSimplified` | 否 | 默认 `false` |
| `frameMap` | 否 | 整体为 `null`，或由 `frameCount` 个整数/`null` 组成的数组 |

`frameMap` 字段整体显式写为 `null` 与省略该字段完全相同：第 N 个 action 帧读取该 layer 的第 N 个本地帧。从 `row`、`startColumn` 开始按从左到右读取，超过本行列数后继续下一行。

`frameMap` 为数组时，数组长度必须恰好等于 action 的 `frameCount`。整数是本地图层帧索引，必须在 `0..511` 内；可以映射到 action 帧数之外的本地格，也可以重复以复用一格。只有 `frameMap` 数组中的某一项为 `null` 时，对应的 action 帧才不绘制此 layer。被引用格最终还必须位于对应 atlas 内，否则图像目录加载阶段失败。

v4 的 `mirrorOf` **不继承**源 action 的时长、层或帧数。镜像 action 仍须完整声明自己的 `frameCount`、时长和 `layers`。源 action 必须存在、不能自身也是镜像，并且两者 role 相同、方向相反。运行时先正常合成镜像 action 自己的全部层，再把整张合成图、身体图和身体几何一起水平翻转。

## 锚点等式和跨帧定位

所有层共享一个世界锚点 `(0, 0)`。缩放后的层尺寸为：

```text
scaledWidth  = round(cellWidth  × scalePercent / 100)
scaledHeight = round(cellHeight × scalePercent / 100)
```

未镜像 layer 左上角相对世界锚点的位置是：

```text
layerLeft = offsetX - round(anchorX × scalePercent / 100)
layerTop  = offsetY - round(anchorY × scalePercent / 100)
```

运行时求当前帧所有实际绘制层的并集 `union`，然后得到窗口内公开锚点：

```text
renderedAnchor = (-union.left, -union.top)
renderedLayerTopLeft = (layerLeft - union.left, layerTop - union.top)
```

因此任一层相对锚点的位置始终满足：

```text
renderedLayerTopLeft - renderedAnchor == (layerLeft, layerTop)
```

切帧、切换 full/simplified 或窗口尺寸变化时，程序保持公开锚点的全局位置不动。宽特效可以让窗口向身体两侧扩展，但不会推动身体在桌面上跳动。

镜像后的合成宽度为 `W` 时：

```text
mirroredAnchorX = W - renderedAnchorX
mirroredBodyX   = W - bodyRect.x - bodyRect.width
```

注意这里是 `W - x`，不是 `W - 1 - x`；公开锚点可位于像素边界。整张图与 `bodyImage` 同时翻转。

## 身体层：命中、拖动、尺寸和位置

每个 action 恰好一个 `hitTest: true` layer，这一层就是身体层。运行时从它单独生成 `bodyImage` 和 `bodyRect`：

- 鼠标左/中/右键、双击和拖动起点只检查身体层 alpha；伸到身体外的光环、尾迹和宽特效不能接收点击或开始拖动。
- 宠物的保存位置、移动目标、屏幕夹取和对外尺寸都使用身体矩形，而不是所有层的并集窗口。
- 拖动偏移相对身体左上角计算，特效出现或消失不会改变抓取位置。
- hover alpha、穿透判断同样读取 `bodyImage`，不会把特效算作身体。
- `opacityPercent` 会作用于身体 alpha；身体 layer 的 `frameMap` 数组中对应 action 帧的一项为 `null` 时，该帧会产生透明身体。通常不要把身体层设为完全透明或 `optionalInSimplified: true`。

## Full 与 Simplified 特效质量

`full` 绘制该帧所有未被 `frameMap` 数组当前项 `null` 跳过的 layer。`simplified` 在此基础上再跳过 `optionalInSimplified: true` 的层；它不会改变动作进度、当前 form、身体 layer、身体世界坐标或窗口保存位置。

由于并集只包含实际绘制的层，simplified 的窗口尺寸和 `renderedAnchor` 数值可以比 full 小；上述锚点等式保证身体相对世界锚点仍相同。质量设置只对 v4 显示。切换质量会在当前动作、当前帧上重新合成。

每一种特效质量下的每一个 action 帧都必须至少有一层实际绘制。若某个 action 帧在所有 layer 的 `frameMap` 数组中对应项都是 `null`，full 也没有内容；若 simplified 下该帧所有未被数组项 `null` 跳过的 layer 都是 `optionalInSimplified: true`，简化质量同样没有内容。运行时不会生成一个无层帧，而会拒绝渲染并报告：

```text
action <id> frame has no rendered layers
```

身体 layer 的 `frameMap` 数组当前项为 `null` 不一定立即触发该错误：只要仍有其他实际绘制层，帧可以合成，但 `bodyImage` 会变成同尺寸的全透明图，身体命中消失。身体 layer 若标为 `optionalInSimplified: true`，simplified 合成图不会画它，运行时却仍从源格生成 `bodyImage`，可能形成“身体不可见但仍可点击”的区域；当其余层也被省略时还会触发无层错误。制作者应让身体在每帧都有本地帧、不要把身体标为 optional，并逐 action、逐 frame 验证 full 与 simplified 两种质量；失败消息可用于定位并隔离有问题的宠物包，而不应靠全空帧表达“暂时隐藏”。

## Form 对象和注视限制

每个 form 恰好包含以下字段，`gazeAction` 除外均为必需：

| 字段 | 规则 |
|---|---|
| `label` | 1–80 个可打印字符 |
| `idleAction` | 已存在、role 为 `idle` |
| `moveRightAction` | 已存在、role 为 `move`、方向为 `right` |
| `moveLeftAction` | 已存在、role 为 `move`、方向为 `left` |
| `gazeAction` | 可选；已存在、role 为 `gaze` |
| `representativeAction` | 已存在的 action；用于表示当前 form |
| `interactionActions` | 1–128 个互不重复、role 为 `interaction` 的 action ID |

默认 form 和每个非默认 form 都必须具备 idle 与左右普通移动。只有 `defaultForm` 可以声明 `gazeAction`；进入任一非默认形态后，普通鼠标注视暂停。默认 form 没有 gaze 也合法。

每个非默认 form 必须至少是一个 transformation 的 `toForm`，这样运行时才能找到返回默认 form 的 exit；否则构造多形态运行时会报告 `non-default forms must have a transformation exit: ...`。

## Transformation

transformation 描述“默认形态进入另一形态、驻留、再退出”的有限过程：

```json
"becomeAnimal": {
  "label": "变成小动物",
  "fromForm": "defaultHuman",
  "toForm": "smallAnimal",
  "enterAction": "transformEnter",
  "residentActions": [{"action": "animalRest", "weight": 100}],
  "exitAction": "transformExit",
  "minDurationMs": 20000,
  "maxDurationMs": 40000,
  "showInMenu": true
}
```

| 字段 | 规则 |
|---|---|
| `label` | 1–80 个可打印字符 |
| `fromForm` | 必须等于 `defaultForm` |
| `toForm` | 已声明的 form |
| `enterAction` | 已声明的 action |
| `residentActions` | 1–128 个互不重复的 `{action, weight}`；`weight` 为 1–100 |
| `exitAction` | 已声明的 action |
| `minDurationMs` | 0–1,200,000 |
| `maxDurationMs` | 0–1,200,000，且不小于最短值 |
| `showInMenu` | 布尔值 |
| `autoplay` | 可选，见“Bucket 自主调度” |

运行时开始时在最短和最长驻留时间之间抽取一个真实时间 deadline。`enterAction` 完成后才把当前 form 设为 `toForm`，然后按 resident 权重选择动作。每个 resident action 完整结束时检查 deadline 或停止请求；满足退出条件后播放 `exitAction`，exit 完成后回到 `defaultForm`。

这些 action 引用在注册表层面只校验“存在”，不会替制作者验证姿势连续性或是否有限。若 enter、resident 或 exit 使用永不完成的循环动作，状态不会自然前进。

已经处于目标 form 时再次请求同一 transformation，会播放该 form 的 `representativeAction`，并把这次请求视为已经开始。处于另一非默认 form 时，手动请求会先播放当前形态对应的 exit，再开始最后请求的目标 transformation；自动请求会被忽略。

## Sequence、repeat、hold、formAfter 与 safeStop

sequence 是 1–128 个 step 的有限列表：

```json
"shapeBurst": {
  "label": "形态连段",
  "showInMenu": true,
  "steps": [
    {
      "action": "wideSpell",
      "repeatCount": 2,
      "holdMs": 125,
      "formAfter": "smallAnimal",
      "safeStopAfter": false
    },
    {
      "action": "animalRest",
      "repeatCount": 1,
      "holdMs": 0,
      "formAfter": "defaultHuman",
      "safeStopAfter": true
    }
  ]
}
```

sequence 本身包含 `label`、`showInMenu`、`steps`，以及可选 `autoplay`。每个 step 恰好包含：

| 字段 | 规则 |
|---|---|
| `action` | 已声明的 action；不能引用另一个 sequence |
| `repeatCount` | 1–20；该 step 重启并完整播放 action 的次数 |
| `holdMs` | 0–10000；step 的所有完整播放结束后再保持末帧 |
| `formAfter` | 可选；step 完整结束后把当前 form 设为该 form |
| `safeStopAfter` | 布尔值；该 step 结束后是否允许已提出的停止/恢复请求执行硬清理 |

一次“完整播放”仍遵守 action 自己的 `repeatCount` 和 `holdMs`；step 的 `repeatCount` 是外层完整播放次数，step 的 `holdMs` 是所有外层播放之后追加的一次末帧停留。为避免意外相乘，sequence 专用 action 通常把 action 自身写成 `repeatCount: 1`、`holdMs: 0`。

`formAfter` 在动作轮次和 step hold 全部完成后才生效。若它改变了 form，下一条播放命令同时发布新 form，锚点仍保持。sequence action 应是会完成的动作；引用无限循环 action 会使 sequence 停在该 step。

`safeStopAfter` 不会自行停止 sequence。它只是安全边界：只有已经有停止或恢复请求时，运行时才在该 step 完成后清空剩余 step、回到默认 form 并执行 cleanup。没有安全边界时，sequence 会继续到后续 step；序列自然完成后保留最后一个 `formAfter` 指定的 form，除非恢复请求要求再经 transformation exit 返回默认 form。

## Started、pending、restore 与 cleanup

运行时一次只执行一个 transformation 或 sequence：

- 空闲时接受请求，第一条 action 命令带上 `started kind/key/manual`，此时才记为真正 started。
- 忙碌时自动请求不排队。手动请求只保留一个 pending；后来的手动 transformation/sequence 会覆盖先前 pending。
- pending 不提前记 cooldown。当前过程到达可启动边界、pending 真正开始时才记账。
- transformation 的普通停止会在 enter 或 resident 动作完整结束时转入 exit，不从半帧切断。
- “恢复默认形态”会清除 pending。空闲非默认形态先播放对应 transformation 的 exit；忙碌时设置停止/恢复请求，sequence 只在 `safeStopAfter` 执行硬清理，没有安全边界时自然播完后再恢复。
- `hard cleanup` 可从任意边界调用且幂等：清除 transformation、sequence、pending、repeat、hold 和 form 状态，回到 `defaultForm`。显示上改用默认 idle 第一帧的**身体图像本身**，因此所有特效层都会被剥离，即使特效没有标记 `optionalInSimplified`。

拖动开始、切换宠物、退出程序、开始其他普通动作或动作展示等需要立即夺回控制权的路径会执行硬清理。

## Bucket 自主调度和共享冷却

只有 transformation 或 sequence 的可选 `autoplay` 会成为 v4 长事件候选：

```json
"autoplay": {
  "bucket": "shapeEvents",
  "weight": 3,
  "minDelayMs": 30000,
  "maxDelayMs": 60000,
  "cooldownGroups": ["sharedShape"]
}
```

`cooldownGroups` 在根对象声明：

```json
"cooldownGroups": {
  "sharedShape": {"cooldownMs": 120000}
}
```

字段边界：

- `bucket`：v4 技术键。
- `weight`：1–100 的整数。
- `minDelayMs`、`maxDelayMs`：0–1,200,000，且最短不大于最长。
- `cooldownGroups`：0–32 个互不重复、已声明的 group ID。
- group 的 `cooldownMs`：0–1,200,000。

调度语义：

1. 一个 bucket 只有一个 deadline，不是每个候选一个。reset 时从该 bucket 的闭区间 `[minDelayMs, maxDelayMs]` 抽一次延迟。
2. 同 bucket 所有候选的最短/最长延迟和 `cooldownGroups` 顺序必须完全相同；`weight` 可以不同。
3. 到期时只在该 bucket 当前可用候选中按 `weight` 加权选择一个。不同 bucket 的权重不互相比较；多个 bucket 同时到期时先处理 deadline 更早的 bucket。
4. 只有默认 form、未闲逛、未处于“始终注视”、没有活动的多形态过程且自主动作开启时才可自动选择。暂停不会消费 deadline。
5. 候选真正 started 时才更新它列出的共享 cooldown，deadline 使用 `max(旧值, startedTime + cooldownMs)`，较早记录不能缩短已有冷却。
6. 手动 started 同样写共享 cooldown，但不消费、不重抽 bucket deadline；自动 started 才从开始时刻为该 bucket 抽取下一 deadline。
7. deadline 已到但因共享 cooldown或当时状态没有可用候选时，应用会 `defer`：把所有已经到期的 bucket 移到 `now + 1000ms`，避免热轮询。这不是抽取一个新的完整延迟窗口。

## 最小分层片段

下面展示宽特效与身体的关键写法；完整可运行的测试包见 [`tests/fixtures/pets/multiformV4`](../tests/fixtures/pets/multiformV4)。

```json
"wideSpell": {
  "label": "宽幅几何波",
  "role": "interaction",
  "frameCount": 3,
  "frameMs": 80,
  "layers": [
    {
      "atlas": "effects",
      "row": 0,
      "startColumn": 0,
      "anchorX": 192,
      "anchorY": 208,
      "optionalInSimplified": true,
      "frameMap": [0, null, 2]
    },
    {
      "atlas": "character",
      "row": 6,
      "startColumn": 0,
      "anchorX": 96,
      "anchorY": 208,
      "hitTest": true,
      "frameMap": [0, 1, 2]
    }
  ]
}
```

## 校验、隔离与错误消息

建议在仓库根目录运行：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_pet_pack_v4_fixture.py tests\test_pet_registry.py tests\test_animation_catalog.py -q
```

测试包还会用 Draft 2020-12 validator 直接校验 `pet.json`。制作者自己的包最终仍应经过 `PetRegistry(..., validator=AnimationCatalog.load_definition)`，因为运行时还会检查文件、图像和跨引用。

某个包失败时只忽略该包，并把目录和错误写入 `%LOCALAPPDATA%\DesktopCompanion\DesktopCompanion.log`；其他宠物包继续加载。常见原始错误消息示例：

| 错误消息 | 含义 |
|---|---|
| `invalid v4 pet id` | ID 不符合 v4 camelCase 技术键 |
| `pet id must match its directory name` | ID 与目录名的字符或大小写不同 |
| `v4 manifest contains unknown fields: spritesheetPath` | v4 根对象出现旧字段或拼错字段 |
| `atlases.effects atlas file is missing` | atlas 文件不存在 |
| `v4 encoded atlas files may total at most 32 MiB` | 所有 WebP 编码大小超限 |
| `v4 atlases may contain at most 50,000,000 decoded pixels` | 解码像素总量超限 |
| `actions.wideSpell must contain exactly one of frameMs or frameDurations` | 时长字段缺失或同时出现 |
| `actions.wideSpell must contain exactly one hitTest layer` | 没有身体层或有多个身体层 |
| `actions.wideSpell.layers[0].frameMap length must match frameCount` | 映射长度错误 |
| `actions.wideSpell.layers[0].frameMap entries must be null or integers from 0 through 511` | 映射值不是 `null` 或超出本地索引范围 |
| `action layer references an unavailable effects atlas cell` | 取帧越过 atlas 格网 |
| `action wideSpell frame has no rendered layers` | 当前质量下该帧所有 layer 都被 `frameMap` 数组项 `null` 或 optional 规则跳过 |
| `forms.smallAnimal references an unknown action` | form action 引用不存在 |
| `only the default form may define gazeAction` | 非默认 form 声明了 gaze |
| `autoplay bucket shapeEvents references an unknown cooldown group` | bucket 使用未声明共享冷却 |
| `autoplay bucket definitions must match` | 同 bucket 的延迟或 group 列表不同 |

## v2、v3 与 v4 兼容

- 当前运行时继续读取 `spriteVersionNumber` 为 2、3、4 的包；现有 v2/v3 包无需迁移。
- v2：一张固定 `1536 × 2288`、8 列 × 11 行图集和固定动作槽位，适合已有旧素材。
- v3：一张 `spritesheet.webp`、每格固定 `192 × 208`，动态 action 和可选常驻 `states`，适合绝大多数单形态宠物。
- v4：1–8 张不同格尺寸图集、分层锚点、forms、transformations、sequences 和 bucket 调度；不使用 v3 `states`。
- v4 ID/key 语法比 v2/v3 更严格，不允许 `_` 和 `-`。不要只把版本号改成 4；清单结构和图集定位方式都不同。
- 旧版桌面灵伴不识别 v4。需要兼容旧安装程序时，应另外发布 v2 或 v3 包。
