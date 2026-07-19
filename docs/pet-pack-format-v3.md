# 桌面灵伴 v3 动态宠物包格式

v3 把旧版“固定 11 行、固定 9 个动作”改成“基础能力必需，其他动作自由增加”。宠物包仍然只有数据文件，程序不会执行宠物包中的脚本或程序。

> 该格式从桌面灵伴 2.3.0 开始正式支持。桌面灵伴 2.2.0 及更早安装程序不识别 v3 宠物包。

第一次制作建议先阅读[添加新宠物指南](添加新宠物指南.md)，再复制 [`examples/pet-pack-template`](../examples/pet-pack-template)。支持 JSON Schema 的编辑器可加载 [`schemas/pet-pack-v3.schema.json`](../schemas/pet-pack-v3.schema.json)。旧版固定图集仍可按 [v2 格式](pet-pack-format-v2.md)继续使用。

## 文件结构

```text
my_pet\
├─ pet.json
└─ spritesheet.webp
```

目录名必须与 `pet.json` 的小写 `id` 完全相同。`spritesheetPath` 必须是 `spritesheet.webp`，文件不能是链接或目录联接。JSON 最大 64 KiB，图集最大 32 MiB。

## 图集规则

- 带透明通道的 WebP。
- 每格固定为 `192 × 208` 像素，保证不同宠物切换时窗口比例稳定。
- 整图宽高不固定，但必须分别是 192 和 208 的整数倍。
- 最多 2048 格，解码后总像素不能超过 5000 万。
- 动作通过 `row`、`startColumn` 和 `frameCount`定位；帧按从左到右、再换到下一行的顺序读取。
- 每个被动作或 `iconFrame` 引用的格子必须至少有一个非透明像素；未引用的格子可以为空。

图集只需容纳实际使用的帧。动作少可以只有几行，动作多可以继续增加行，不再要求固定 11 行。

## 必需能力

v3 不固定动作 ID 和中文名称，但运行时会检查以下能力：

1. 恰好一个 `idle`：待机，必须循环。
2. 至少一个向左和一个向右的普通 `move`。
3. 至少一个 `interaction`：单击回应、随机动作和动作展示使用。

如果左右造型可以安全镜像，一侧可使用 `mirrorOf` 引用另一侧；发饰、服装或特效不对称时应分别绘制。`burstMove`、`gaze` 和更多互动动作均为可选。

## 动作角色

| `role` | 用途 | 特有字段 |
|---|---|---|
| `idle` | 基础待机 | 必须 `loop: true` |
| `move` | 自动闲逛的普通移动 | `direction`，权重参与移动方式选择 |
| `interaction` | 原地互动或角色动作 | 权重参与随机和自主动作选择 |
| `burstMove` | 先光化、快速跨越、再显形等一次性移动 | `direction`、移动阶段、最小距离和冷却 |
| `gaze` | 看向鼠标 | 支持 16、32 或 64 帧；从正上方 0° 开始顺时针等角度排列，不显示在随机动作菜单 |

动作 ID 是 `actions` 下的英文键，可自由命名，但必须以小写英文字母开头，只能包含英文字母、数字、下划线和连字符，长度不超过 64。

## 动画字段

直接使用图集帧的动作必须填写：

- `label`：菜单显示名称，1–32 个可打印字符。
- `role`：上表中的行为类型。
- `row`：起始行。
- `startColumn`：起始列，省略时为 0。
- `frameCount`：1–64 帧。
- `frameMs`：所有帧使用同一时长，范围 33–2000 毫秒；或者改用 `frameDurations` 为每帧分别设置时长，两者只能选一个。
- `loop`：持续循环；省略时只有待机默认为循环。
- `repeatCount`：非循环动作重复 1–20 次，省略为 1。
- `holdMs`：结束后保持最后一帧 0–10000 毫秒。
- `showInMenu`：是否出现在右键动作菜单，默认除 `gaze` 外均显示。

`gaze` 的方向间隔由运行时根据帧数自动计算：16 帧为 22.5°、32 帧为 11.25°、64 帧为 5.625°。64 帧最接近连续转头，推荐用于对注视连贯度要求较高的宠物。无论实际有多少注视帧，右键“观察方向”只列出 16 个常用角度，自动看向鼠标会使用全部帧。
- `autoplayWeight`：0–100。互动动作中控制随机频率，移动动作中控制闲逛时选择该移动方式的频率。
- `cooldownMs`：自动触发冷却，0–600000 毫秒。
- `autoplayGroup`：可选的自动播放组名，只能用于 `interaction`。如果上一次随机动作具有非空组名，下一次会优先排除同组动作，防止不同术法或强特效连续播放。组名以小写英文字母开头，只能包含英文字母、数字、下划线和连字符，最长 32 个字符。

使用 `mirrorOf` 时不再填写行、列、帧数和时长，这些信息从被引用动作继承。镜像动作必须与来源角色相同、方向相反，且不能继续镜像另一个镜像动作。

## 快速移动

`burstMove` 额外支持：

- `minDistance`：目标距离不足该像素值时不自动触发。
- `travelStartFrame`：从这一帧开始离开起点。
- `travelEndFrame`：到这一帧时抵达终点。
- `travelDistanceRatio`：可选，0.05–1；按当前显示器扣除宠物宽度后的可移动宽度计算遁光距离。例如 `0.5` 表示横向移动半屏。
- `maxVerticalRatio`：可选，0–1；使用比例距离时，限制纵向变化不超过可移动高度的该比例。例如 `0.1` 表示纵向最多变化一成屏幕。

快速移动必须是一次性动作，不能永久循环，`repeatCount` 必须为 1。

开始帧之前窗口保持在起点，两个移动帧之间采用平滑插值，结束帧之后停在终点。因此作者可以自由安排“人物—起光—完全光化—遁光—收束—人物”的帧序列。省略 `travelDistanceRatio` 时，手动播放默认沿对应方向移动至少 320 像素；设置比例后，自动播放会选择拥有足够空间的一侧，手动朝屏幕外播放且剩余空间过短时也会改用反方向动作，所有目标和中间位置都会限制在当前显示器内。

普通移动权重为 19、遁光权重为 1 时，在距离和冷却都允许的情况下，遁光约占移动选择的 5%，即平均约每 20 次移动出现一次。

## 避免同类动作连续播放

多个动作可以使用相同的 `autoplayGroup`。例如把所有术法动作写成：

```json
{
  "label": "月轮映身",
  "role": "interaction",
  "row": 5,
  "frameCount": 10,
  "frameMs": 180,
  "autoplayWeight": 1,
  "cooldownMs": 60000,
  "autoplayGroup": "spell"
}
```

随机播放一套 `spell` 后，只要还有不属于 `spell` 的可用互动动作，下一次随机选择就不会继续选术法。手动菜单播放不受该限制；冷却仍按每个动作独立计算。省略该字段或填写空值时保持旧版行为。

## 最小示例

```json
{
  "id": "my_pet",
  "displayName": "我的宠物",
  "spriteVersionNumber": 3,
  "spritesheetPath": "spritesheet.webp",
  "iconFrame": {"row": 0, "column": 0},
  "actions": {
    "idle": {
      "label": "安静陪伴", "role": "idle", "row": 0,
      "frameCount": 4, "frameMs": 180, "loop": true
    },
    "moveRight": {
      "label": "向右移动", "role": "move", "direction": "right",
      "row": 1, "frameCount": 8, "frameMs": 90, "loop": true,
      "autoplayWeight": 19
    },
    "moveLeft": {
      "label": "向左移动", "role": "move", "direction": "left",
      "mirrorOf": "moveRight", "autoplayWeight": 19
    },
    "greet": {
      "label": "打个招呼", "role": "interaction", "row": 2,
      "frameCount": 6, "frameMs": 150, "repeatCount": 2,
      "autoplayWeight": 3
    }
  }
}
```

完整的普通移动加遁光示例见[模板 pet.json](../examples/pet-pack-template/pet.json)。

## 兼容性

- 新运行时同时读取 `spriteVersionNumber: 2` 和 `3`。
- 十一、紫灵及已有 v2 宠物包无需修改。
- v3 宠物包不能在旧版桌面灵伴中使用。
- 某个宠物包校验失败时只忽略该包，不影响其他宠物启动。
