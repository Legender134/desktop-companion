# 十一桌面宠物发布验收记录

## 验收范围与环境

本记录对应本文件所在的最终发布提交和由该提交生成的 Windows 当前用户安装包。验收于 2026-07-18 在 Windows 11 x64（10.0.26100）、Python 3.12.10、PySide6/Qt 6.11.1 环境完成；真实 UI 操作对象为安装在以下路径的冻结版程序：

```text
C:\Users\23644\AppData\Local\Programs\ShiyiDesktopPet\ShiyiDesktopPet.exe
```

普通发布窗口使用无边框 `Qt.Tool`，Windows 控制工具无法枚举这种窗口。截图阶段显式使用隐藏的内部 `--qa-window` 参数，使同一个 `DesktopPetApplication`/`PetWindow` 只把顶层窗口类型换为可枚举的 `Qt.Window` 并设置标题 `ShiyiDesktopPet QA`；资源、行为、菜单、计时器、键盘钩子、托盘、设置和单实例逻辑均为正式版路径。验收完成后已切回正式 `--startup` 启动，不保留 QA 窗口。

自动门禁结果：

- `pip check`：通过；
- 完整测试：130 项通过；
- 源码覆盖率：91%，门槛 85%；
- PyInstaller 冻结自检：`ok=true`、WebP 插件可用、图集 1536×2288、共 74 帧；
- Inno Setup 普通安装/自检/卸载与覆盖安装设置保留：通过；
- 安装版最终 `--self-test`：退出码 0，单行 JSON，`ok=true`、`webp_plugin=true`、74 帧。

## 截图与窗口元数据

`outputs/十一桌面宠物/qa/` 中每个 JSON 记录被测进程、窗口句柄/标题和同编号 JPG 的窗口边界。共 40 份 JSON、48 张 JPG；编号 36、41 是命令/状态转换，没有伪造独立截图。以下结果均与实际文件逐项对应。

| 编号 | 检查与结果 | JSON / JPG 证据 |
|---|---|---|
| 01 | 初始安装版窗口可见，100% 尺寸为 192×208，无边框透明宠物正常显示。 | `01-initial.json`; `01-initial.jpg` |
| 02 | 宠物右键根菜单可打开，动作、闲逛、注视、悬停数字、置顶、启动项、大小、两种速度、回中、关于和退出均可见。 | `02-menu-root.json`; `02-menu-root-0.jpg`, `02-menu-root-1.jpg` |
| 03 | “动作”子菜单完整显示休息、左右奔跑、招手、跳跃、撒娇翻肚、期待、原地巡视、好奇观察、随机动作和观察方向。 | `03-menu-actions.json`; `03-menu-actions-0.jpg`, `03-menu-actions-1.jpg`, `03-menu-actions-2.jpg` |
| 04 | “观察方向”完整显示 000° 至 337.5°、每 22.5° 一项，共 16 个方向。 | `04-menu-directions-16.json`; `04-menu-directions-16-0.jpg`, `04-menu-directions-16-1.jpg`, `04-menu-directions-16-2.jpg`, `04-menu-directions-16-3.jpg` |
| 05 | 左键拖动后窗口原点从初始位置变化到 `(3395, 1635)`，拖动生效。 | `05-drag-after.json`; `05-drag-after.jpg` |
| 06 | 左键双击触发跳跃，未留下拖动事务。 | `06-double-click-jump.json`; `06-double-click-jump.jpg` |
| 07 | 中键触发一次非位移随机动作。 | `07-middle-random.json`; `07-middle-random.jpg` |
| 08 | 光标命中可见像素时数字 `1` 触发休息。 | `08-digit-1-idle.json`; `08-digit-1-idle.jpg` |
| 09 | 数字 `2` 触发向右奔跑并产生右移。 | `09-digit-2-run-right.json`; `09-digit-2-run-right.jpg` |
| 10 | 数字 `3` 触发向左奔跑并产生左移。 | `10-digit-3-run-left.json`; `10-digit-3-run-left.jpg` |
| 11 | 数字 `4` 触发招手。 | `11-digit-4-wave.json`; `11-digit-4-wave.jpg` |
| 12 | 数字 `5` 触发跳跃。 | `12-digit-5-jump.json`; `12-digit-5-jump.jpg` |
| 13 | 数字 `6` 触发撒娇翻肚。 | `13-digit-6-belly-flop.json`; `13-digit-6-belly-flop.jpg` |
| 14 | 数字 `7` 触发期待。 | `14-digit-7-expect.json`; `14-digit-7-expect.jpg` |
| 15 | 数字 `8` 触发原地巡视。 | `15-digit-8-patrol.json`; `15-digit-8-patrol.jpg` |
| 16 | 数字 `9` 触发好奇观察。 | `16-digit-9-curious.json`; `16-digit-9-curious.jpg` |
| 17 | 数字 `0` 从 4–9 中触发随机非位移动作。 | `17-digit-0-random.json`; `17-digit-0-random.jpg` |
| 18 | 透明角显示后方测试窗口内容，宠物输入区域没有扩大为整个矩形。 | `18-alpha-corner-before.json`; `18-alpha-corner-before.jpg` |
| 19 | 在透明角输入数字不会触发宠物动作；后方内容可交互，数字抑制只发生在可见非透明宠物像素。 | `19-alpha-corner-digit-suppressed.json`; `19-alpha-corner-digit-suppressed.jpg` |
| 20 | 光标位于上方时切换到向上注视帧。 | `20-gaze-up.json`; `20-gaze-up.jpg` |
| 21 | 光标位于右侧时切换到向右注视帧。 | `21-gaze-right.json`; `21-gaze-right.jpg` |
| 22 | 光标位于下方时切换到向下注视帧。 | `22-gaze-down.json`; `22-gaze-down.jpg` |
| 23 | 光标位于左侧时切换到向左注视帧。 | `23-gaze-left.json`; `23-gaze-left.jpg` |
| 24 | 代表性右上对角线注视正确。 | `24-gaze-up-right.json`; `24-gaze-up-right.jpg` |
| 25 | 代表性左下对角线注视正确。 | `25-gaze-down-left.json`; `25-gaze-down-left.jpg` |
| 26 | “回到屏幕中央”把宠物移到光标所在显示器中央，提供可见性恢复入口。 | `26-reset-center.json`; `26-reset-center.jpg` |
| 27 | 75% 尺寸边界为 144×156，画面清晰且透明形状保持。 | `27-size-75.json`; `27-size-75.jpg` |
| 28 | 100% 尺寸边界为 192×208。 | `28-size-100.json`; `28-size-100.jpg` |
| 29 | 125% 尺寸边界为 240×260，缩放清晰。 | `29-size-125.json`; `29-size-125.jpg` |
| 30 | 150% 尺寸边界为 288×312，缩放清晰。 | `30-size-150.json`; `30-size-150.jpg` |
| 31 | 开启自动闲逛后进入闲逛调度。 | `31-wander-enabled-start.json`; `31-wander-enabled-start.jpg` |
| 32 | 闲逛产生向右并向上的有效移动，仍在显示器可用区域。 | `32-wander-right-up.json`; `32-wander-right-up.jpg` |
| 33 | 后续闲逛产生向左移动，并在底边/任务栏可用区域内保持完整窗口。 | `33-wander-left.json`; `33-wander-left.jpg` |
| 34 | 闲逛期间左键双击跳跃会立即中断移动并播放手动动作。 | `34-wander-interrupted-by-jump.json`; `34-wander-interrupted-by-jump.jpg` |
| 35 | 闲逛期间中键随机动作也会中断移动。 | `35-wander-interrupted-by-middle-action.json`; `35-wander-interrupted-by-middle-action.jpg` |
| 37 | 保存 `wander=true`、动画/移动速度 `fast/fast`、显示器 `U27G4` 和位置后重启：位置与模式恢复，闲逛自动继续。 | `37-restart-position-mode-restore.json`; `37-restart-position-mode-restore.jpg` |
| 38 | 开机启动菜单项可见且状态与 HKCU Run 一致；关闭/开启的注册表证据见下节。 | `38-startup-before.json`; `38-startup-before-0.jpg`, `38-startup-before-1.jpg` |
| 39 | 关闭“始终置顶”后，普通资源管理器窗口能够覆盖宠物。 | `39-always-on-top-off-covered.json`; `39-always-on-top-off-covered.jpg` |
| 40 | 重新开启“始终置顶”后宠物恢复在前方。 | `40-always-on-top-restored.json`; `40-always-on-top-restored.jpg` |
| 42 | 最终菜单状态复核：自动闲逛关闭，看向鼠标、悬停数字、始终置顶和开机启动开启；大小 100%、两种速度正常。 | `42-final-settings-menu.json`; `42-final-settings-menu-0.jpg`, `42-final-settings-menu-1.jpg` |

## 启动项、单实例和恢复证据

- 通过真实右键菜单关闭“开机启动”后，`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ShiyiDesktopPet` 不存在。
- 重新开启后，其值精确为：

  ```text
  "C:\Users\23644\AppData\Local\Programs\ShiyiDesktopPet\ShiyiDesktopPet.exe" --startup
  ```

- 直接执行该 Run 命令产生客户端 PID `28200`，退出码 0；既有 owner PID `6744` 在执行前后保持不变，精确路径进程数始终为 1，证明启动命令通过 IPC 激活现有实例而没有创建第二个持久宠物。
- “回到屏幕中央”的真实 UI 证据见 26；普通第二实例和 Run 命令的真实 IPC 激活均成功。
- 最终正式运行实例为 PID `30212`，命令行带 `--startup` 而非 `--qa-window`。

## 托盘检查边界

Windows 控制工具按规范尝试枚举/点击系统托盘，但其应用边界不返回 `Shell_TrayWnd`，因此没有声称直接点击过托盘图标。托盘恢复行为由以下独立证据覆盖：

- 真实 UI 的“回到屏幕中央”（26）；
- 真实普通第二实例和 Run 启动命令通过 IPC 激活现有窗口；
- 自动化测试 `tests/test_menu_controller.py::test_available_tray_reuses_menu_and_double_click_recovers_pet` 验证托盘复用完整菜单，双击调用显示、前置和激活。

这是验收工具的可访问范围限制，不是观察到的产品缺陷；直接托盘图标点击仍列为未由该工具亲自执行的项目。

## 发布后的规范化最终状态

人工覆盖测试完成后，当前用户设置已恢复为面向交付的状态：

```ini
[settings]
schema_version = 1
wander_enabled = False
gaze_enabled = True
hover_digits_enabled = True
always_on_top = True
scale_percent = 100
animation_speed = normal
movement_speed = normal
screen_name = U27G4
relative_x = 0.5
relative_y = 0.5
```

最终安装版自检退出码为 0，stdout 为一个 JSON 对象：

```json
{"ok":true,"qt":"6.11.1","atlas":{"width":1536,"height":2288,"frames":74},"webp_plugin":true}
```

除上述托盘工具边界外，未观察到可见缺陷；透明输入区域、菜单、鼠标动作、数字快捷键、注视、闲逛、缩放、置顶、位置/模式恢复、启动项和单实例均通过。
