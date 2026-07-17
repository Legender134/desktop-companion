# 桌面灵伴 v2 宠物包格式

桌面灵伴 2.2 支持从 `%APPDATA%\DesktopCompanion\pets` 动态发现数据型宠物包。宠物包不能包含或执行 Python、JavaScript、DLL、EXE 等代码；程序只读取清单和固定格式的透明 WebP 图集。

这是供制作者查阅的精确技术规范。第一次制作宠物时，建议先按[添加新宠物指南](添加新宠物指南.md)逐步操作，再回来核对本页。可直接复制的文件位于 [`examples/pet-pack-template`](../examples/pet-pack-template)，支持 JSON Schema 的编辑器可加载 [`schemas/pet-pack-v2.schema.json`](../schemas/pet-pack-v2.schema.json)。

兼容性判断以桌面灵伴运行时校验为准。JSON Schema 只能检查清单字段，不能检查目录名是否匹配，也不能检查 WebP 的尺寸、透明通道和每格占用情况。

## 目录和清单

目录名必须与 `pet.json` 中的小写 `id` 相同：

```text
new_pet\
├─ pet.json
└─ spritesheet.webp
```

```json
{
  "id": "new_pet",
  "displayName": "新宠物",
  "description": "这只宠物的简短说明。",
  "spriteVersionNumber": 2,
  "spritesheetPath": "spritesheet.webp",
  "iconFrame": {"row": 0, "column": 0},
  "actions": {
    "idle": {"label": "安静站立", "autoplayWeight": 0},
    "moveRight": {"label": "向右轻行", "autoplayWeight": 0},
    "moveLeft": {"label": "向左轻行", "autoplayWeight": 0},
    "greet": {"label": "挥手问候", "autoplayWeight": 3},
    "jump": {"label": "翩然旋舞", "autoplayWeight": 1},
    "special": {"label": "舒展衣袖", "autoplayWeight": 2},
    "wait": {"label": "安静等候", "autoplayWeight": 3},
    "observe": {"label": "凝神静气", "autoplayWeight": 2},
    "curious": {"label": "若有所思", "autoplayWeight": 3}
  }
}
```

字段规则：

| 字段 | 规则 |
|---|---|
| `id` | 1–64 个字符；只允许小写英文字母、数字、下划线和连字符；首字符必须是字母或数字 |
| `displayName` | 必填，去除首尾空白后长度不超过 64 个字符 |
| `description` | 可选文本，最长 500 个字符 |
| `spriteVersionNumber` | 必须是数字 `2` |
| `spritesheetPath` | 必须精确写为 `spritesheet.webp` |
| `iconFrame` | 可选；包含整数 `row`（0–10）和 `column`（0–7），指定该宠物的托盘代表帧；省略时默认为第 0 行第 0 列 |
| `actions` | 2.2 动作元数据；新宠物包应完整填写 9 个固定动作槽位。为兼容 2.1 宠物包，整个字段省略时使用中性默认名称和安全默认权重 |

内置 ID `shiyi`、`ziling` 已被占用。用户宠物不能覆盖内置宠物，其他用户宠物之间也不能重名。

## 图集契约

- 格式：可由 Qt 解码的 WebP，必须有透明通道。
- 整图尺寸：`1536 × 2288` 像素。
- 单格尺寸：`192 × 208` 像素。
- 网格：8 列 × 11 行。
- 所有未使用格必须完全透明；所有标记为有效的格必须至少包含一个非透明像素。
- 文件大小必须大于 0 且不超过 32 MiB。

| 行号（从 0 开始） | 内容 | 有效格数 |
|---|---|---:|
| 0 | `idle`：待机 | 7 |
| 1 | `moveRight`：向右移动 | 8 |
| 2 | `moveLeft`：向左移动 | 8 |
| 3 | `greet`：问候类动作 | 4 |
| 4 | `jump`：跃起或同位置动态动作 | 5 |
| 5 | `special`：角色特色动作 | 8 |
| 6 | `wait`：等待类动作 | 6 |
| 7 | `observe`：观察或凝神类动作 | 6 |
| 8 | `curious`：好奇或思考类动作 | 6 |
| 9 | 观察方向 000°–157.5° | 8 |
| 10 | 观察方向 180°–337.5° | 8 |

观察方向按每格增加 22.5° 的顺序排列。

`iconFrame` 必须指向表中实际使用且含有非透明像素的格子。程序会裁剪该帧的透明边界、补成带 8% 留白的正方形，并在切换宠物时立即更新托盘图标和提示名称。这样每个角色都使用自己的形象，不需要额外提供通用产品图标或单独的 ICO 文件。

## 动作名称和自主权重

`actions` 的键是稳定的技术槽位，不会显示给普通用户，也不会改变图集行号或窗口移动规则。`label` 是 1–32 个可打印字符，切换宠物后，宠物菜单和托盘菜单会在下次打开时立即使用当前宠物自己的名称。

`autoplayWeight` 必须是 0–10 的整数，不能使用布尔值：

- `idle`、`moveRight`、`moveLeft` 必须为 `0`，因此自主小动作永远不会改变宠物位置。
- `greet`、`jump`、`special`、`wait`、`observe`、`curious` 可按角色气质设置权重；数值越大，单击回应、数字 `0`、中键随机和自主小动作越容易选中。
- 六个原地动作中至少一个权重大于 `0`。
- 随机选择不会连续两次播放同一个动作。
- `actions` 一旦出现，就必须恰好包含上述 9 个键；每项必须同时包含 `label` 和 `autoplayWeight`，未知或缺失字段会使该宠物包被忽略。

旧版宠物包可以完全省略 `actions` 并继续运行；程序会使用“待机、向右移动、向左移动、打招呼、跃起、特别动作、等待、环顾四周、好奇观察”等中性名称。建议重新制作或更新的宠物包显式填写完整动作元数据。

## 安装与重新扫描

1. 在桌面灵伴右键菜单中选择“打开宠物目录”。
2. 把完整宠物文件夹复制进去，不要只复制 WebP。
3. 返回菜单选择“重新扫描宠物”。
4. 在“切换宠物”子菜单中选择新角色。

扫描会验证 JSON、ID、动作名称与权重、文件边界、图像解码、尺寸、透明通道和每格占用情况。某个包校验失败时只忽略该包；当前宠物包被删除或失效时，程序会回退到十一并保存设置。

## 安全和备份

- 宠物目录、`pet.json` 和 `spritesheet.webp` 不能是符号链接或目录联接。
- 不接受绝对路径、`..` 路径或自定义图集文件名。
- `pet.json` 最大 64 KiB。
- 覆盖安装会保留用户宠物；卸载桌面灵伴会删除 `%APPDATA%\DesktopCompanion`，卸载前应备份自制宠物。
