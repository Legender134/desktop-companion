# 桌面灵伴 2.4

桌面灵伴是面向 Windows 10/11 x64 的透明桌面宠物。它内置“十一”“紫灵”和同人宠物“南宫婉”，支持切换宠物、单击互动、看向鼠标、自动闲逛、自主小动作和自制宠物包。程序本身不发起网络请求。

## 第一次来这里？从这里开始

| 你想做什么 | 应该点击哪里 |
|---|---|
| 只想安装使用 | [Gitee 直接下载](https://gitee.com/legender134/desktop-companion/releases/download/v2.4.0/DesktopCompanion-2.4.0-setup.exe) / [GitHub 直接下载](https://github.com/Legender134/desktop-companion/releases/download/v2.4.0/DesktopCompanion-2.4.0-setup.exe) |
| 完全不懂代码托管网站 | [查看新手使用指南](docs/新手使用指南.md) |
| 想知道每版更新了什么 | [查看完整更新日志](CHANGELOG.md) |
| 想添加自己的宠物 | [查看添加新宠物指南](docs/添加新宠物指南.md) |
| 已经会制作图集，需要查精确标准 | [查看 v3 动态宠物包技术规范](docs/pet-pack-format-v3.md) |
| 想修改或构建程序 | 跳到[从源码准备、构建与验证](#从源码准备构建与验证) |

> 普通用户只需要下载其中一个平台的 `DesktopCompanion-2.4.0-setup.exe`。不要下载名字中带有 `Source`、`源代码` 的压缩包，它们是给开发者看的源码，不能直接安装。

### 三步开始使用

1. 从 Gitee 或 GitHub 下载并双击 `DesktopCompanion-2.4.0-setup.exe`。
2. 按安装向导完成安装；不需要安装 Python、Qt、Codex 或开发工具。
3. 从桌面“桌面灵伴”快捷方式启动。右键宠物或右下角托盘图标即可切换宠物、播放动作和修改设置。

如果下载、安装、托盘图标或卸载过程不清楚，请直接按照[新手使用指南](docs/新手使用指南.md)逐步操作。

## 它能做什么

- 内置十一、紫灵和南宫婉，并能在运行时切换；
- 单击随机回应、双击跳跃、拖动改变位置；
- 沿最短方向平滑看向鼠标、自动闲逛和不改变位置的自主小动作；
- 动作展示、大小与速度调整、开机启动和多显示器位置记忆；
- 从 `%APPDATA%\DesktopCompanion\pets` 读取由 `pet.json` 和 `spritesheet.webp` 组成的用户宠物包；
- 每只宠物可以动态定义动作数量、每个动作的帧数与时长、托盘代表帧、自动权重和低频快速移动；旧 v2 固定图集继续兼容。

## 下载文件怎么选

[Gitee v2.4.0 发布页](https://gitee.com/legender134/desktop-companion/releases/tag/v2.4.0)和 [GitHub 最新版发布页](https://github.com/Legender134/desktop-companion/releases/latest)都提供可直接下载的安装程序：

| 文件 | 用途 | 普通用户需要吗 |
|---|---|---|
| `DesktopCompanion-2.4.0-setup.exe` | Windows 安装程序 | **需要，下载这个** |
| GitHub 自动生成的 `Source code` | 标签源码快照 | 不需要 |

本项目已经完成源码测试、PyInstaller 冻结、Inno Setup 当前用户安装、真实安装/升级/卸载冒烟测试和 Windows 桌面交互验收。v2.4.0 发布验证结果见 [docs/manual-qa-v2.4.md](docs/manual-qa-v2.4.md)，每个正式版本的主要变化见[更新日志](CHANGELOG.md)。

### 历史版本

新用户应优先安装 v2.4.0。旧版本仍保留用于学习、比较和回退：

| 版本 | 主要内容 | Gitee 下载页 | GitHub 下载页 |
|---|---|---|---|
| v2.4.0 | 南宫婉 64 方向平滑注视、两种注视模式、菜单圆形问号与参数级详情 | [Gitee Release](https://gitee.com/legender134/desktop-companion/releases/tag/v2.4.0) | [GitHub Release](https://github.com/Legender134/desktop-companion/releases/tag/v2.4.0) |
| v2.3.0 | 内置南宫婉、v3 动态动作、可变帧数、遁光移动、动作分组和闲逛强度 | [Gitee Release](https://gitee.com/legender134/desktop-companion/releases/tag/v2.3.0) | [GitHub Release](https://github.com/Legender134/desktop-companion/releases/tag/v2.3.0) |
| v2.2.0 | 单击互动、自主小动作、动作展示、宠物专属动作名称与权重 | [Gitee Release](https://gitee.com/legender134/desktop-companion/releases/tag/v2.2.0) | [GitHub Release](https://github.com/Legender134/desktop-companion/releases/tag/v2.2.0) |
| v2.1.0 | 动态宠物包与跟随当前宠物的托盘图标 | [Gitee Release](https://gitee.com/legender134/desktop-companion/releases/tag/v2.1.0) | [GitHub Release](https://github.com/Legender134/desktop-companion/releases/tag/v2.1.0) |
| v2.0.0 | 项目更名为桌面灵伴，支持十一与紫灵切换 | [Gitee Release](https://gitee.com/legender134/desktop-companion/releases/tag/v2.0.0) | [GitHub Release](https://github.com/Legender134/desktop-companion/releases/tag/v2.0.0) |
| v1.0.0 | 最初的十一桌面宠物 | [Gitee Release](https://gitee.com/legender134/desktop-companion/releases/tag/v1.0.0) | [GitHub Release](https://github.com/Legender134/desktop-companion/releases/tag/v1.0.0) |

## 从源码准备、构建与验证

需要 Windows、64 位 CPython 3.12 和 PowerShell；生成安装程序还需要已签名的 Inno Setup 6.7.3 或兼容的 6.x 编译器。以下命令均从仓库根目录运行：

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe tools\make_icon.py
& .\.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
& .\.venv\Scripts\python.exe -m coverage run -m pytest --ignore=tests/integration/test_frozen_smoke.py
& .\.venv\Scripts\python.exe -m coverage report --fail-under=85
& .\.venv\Scripts\python.exe -m shiyi_desktop_pet --self-test
& .\scripts\build_installer.ps1
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_frozen_smoke.py -q
& .\scripts\verify_release.ps1 `
    -Installer .\artifacts\桌面灵伴安装程序.exe `
    -TestDir (Join-Path $PWD 'work\release-smoke')
```

`tools\make_icon.py` 读取默认宠物十一的休息动作第 0 行第 0 列，裁剪透明边界后居中并加入 8% 透明留白，确定性生成包含 16、32、48 和 256 像素图层的静态 `app.ico`。安装程序、EXE、开始菜单和桌面快捷方式使用这个十一图标；应用运行后，托盘图标会改为当前宠物在 `pet.json` 中指定的代表帧。整个过程不重绘角色。

通过自检后可从源码启动：

```powershell
& .\.venv\Scripts\python.exe -m shiyi_desktop_pet
```

源码模式主要用于开发和验证。请不要在源码模式下打开“开机启动”：该开关按冻结后的应用可执行文件设计，而源码模式中的 `sys.executable` 是 Python 解释器。

面向用户的命令行模式彼此互斥：

- `--self-test`：验证图集、帧契约、Qt 和 WebP 插件，输出一个 JSON 对象后退出。
- `--quit-existing`：请求正在运行的实例退出。
- `--startup`：以开机启动模式运行，不主动抢占前台焦点。

程序只允许一个实例。普通的第二次启动会激活现有宠物，不会创建第二只宠物。

## 首次启动和记忆内容

首次启动默认显示十一；自动闲逛关闭、看向鼠标开启、注视方式为“鼠标活动时”、自主小动作开启、悬停数字快捷键开启、始终置顶开启、“显示详情”关闭，大小为 100%，动画和移动速度均为正常。宠物出现在主屏幕右下方、任务栏上方。安装向导首次安装时默认勾选开机启动；也可在安装前取消，或安装后随时从宠物右键菜单关闭。

切换角色时会立即保存当前宠物；受控退出时还会保存自动闲逛、看向鼠标、注视方式、自主小动作、数字快捷键、始终置顶、显示详情、大小、两种速度、显示器和相对位置：

```text
%APPDATA%\DesktopCompanion\settings.ini
```

“开机启动”不写入 INI，而是读取或修改当前用户的以下注册表值：

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DesktopCompanion
```

日志位于：

```text
%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log
```

日志以 UTF-8 轮转；单文件最大 1 MiB，保留 3 个备份。

## 安装用户宠物包

> v2.3.0 已正式支持 v3 动态动作宠物包；旧 v2 固定图集继续兼容。

在宠物或托盘菜单中选择“打开宠物目录”，程序会打开并在需要时创建：

```text
%APPDATA%\DesktopCompanion\pets
```

每只宠物必须独占一个以宠物 ID 命名的子目录，其中只能依赖数据文件：

```text
pets\
└─ new_pet\
   ├─ pet.json
   └─ spritesheet.webp
```

复制完成后选择“重新扫描宠物”。通过校验的角色会出现在“切换宠物”子菜单中；损坏、重复或不符合 v2/v3 图集契约的宠物包会被忽略并显示通知，不会阻止内置宠物启动。内置 ID `shiyi` 和 `ziling` 不允许被用户包覆盖。

第一次制作时请按[添加新宠物指南](docs/添加新宠物指南.md)操作，并从 [`examples/pet-pack-template`](examples/pet-pack-template) 复制 v3 JSON 模板。动态动作、帧数、快速移动和安全限制见 [v3 宠物包格式](docs/pet-pack-format-v3.md)，旧式图集见 [v2 兼容格式](docs/pet-pack-format-v2.md)。覆盖升级会保留用户宠物目录；卸载会清理整个 `%APPDATA%\DesktopCompanion`，需要保留自制宠物时请先备份 `pets` 文件夹。

## 鼠标和托盘控制

- 左键单击且没有拖动：等待 Windows 的双击判定时间后，按当前宠物的 JSON 权重随机做一个原地动作。
- 左键按住并拖动：移动宠物，不触发单击动作。
- 左键双击：跳跃。
- 中键单击：按当前宠物的 JSON 权重随机选择一个非位移动作。
- 右键单击：打开宠物完整菜单。
- 光标移动到宠物附近：在没有拖动或手动动作时，视线沿最短方向依次经过 16 张清晰关键姿态，避免大角度直接跳变；鼠标活动会优先中断闲逛。
- 托盘图标右键：打开与宠物右键相同的完整菜单。
- 托盘图标双击：显示并激活宠物窗口。

托盘使用当前宠物自己的代表帧；切换宠物时图标和提示名称立即同步变化，例如“桌面灵伴 · 紫灵”。Windows 11 可能把首次出现的通知图标放入右下角 `^` 的隐藏图标区域；是否固定在任务栏主区域由 Windows 和用户偏好决定，应用不会擅自修改该系统设置。

窗口只用当前帧的非透明像素作为输入区域，外接矩形中的透明部分不会阻挡后面的桌面或应用。

## 数字动作映射

主键盘和数字小键盘的 `0–9` 使用相同动作槽位；菜单中的实际名称由当前宠物的 `pet.json` 决定：

| 数字 | 动作 | 规则 |
|---|---|---|
| 1 | `idle` | 返回持续循环的待机动作 |
| 2 | `moveRight` | 播放一轮并向右移动 |
| 3 | `moveLeft` | 播放一轮并向左移动 |
| 4 | `greet` | 播放三轮后返回原模式 |
| 5 | `jump` | 播放一轮，结束帧停留约 0.4 秒 |
| 6 | `special` | 播放一轮，结束帧停留约 1 秒 |
| 7 | `wait` | 播放两轮后返回原模式 |
| 8 | `observe` | 播放两轮，不移动窗口 |
| 9 | `curious` | 播放两轮后返回原模式 |
| 0 | 随机动作 | 按 `autoplayWeight` 从非位移动作中选择，且不连续重复 |

只有“悬停数字快捷键”已开启、宠物可见，并且光标命中当前帧的非透明宠物像素时，数字键才会触发动作并被宠物消费；其余按键和其余位置的数字输入均透传给前台应用。程序不记录键入内容。

## 右键菜单

宠物菜单和托盘菜单共享以下命令：

```text
动作
  当前宠物 JSON 定义的 9 个动作名称 / 随机动作 / 动作展示
  观察方向 > 000° 至 337.5°，每 22.5° 一个方向，共 16 个
自动闲逛
闲逛强度 > 安静 / 标准 / 活跃
看向鼠标
注视方式 > 鼠标活动时（推荐） / 始终看向鼠标
自主小动作
悬停数字快捷键
始终置顶
开机启动
切换宠物 > 十一 / 紫灵 / 所有通过校验的用户宠物
重新扫描宠物
打开宠物目录
大小 > 75% / 100% / 125% / 150%
动画速度 > 慢速 / 正常 / 快速
移动速度 > 慢速 / 正常 / 快速
回到屏幕中央
显示详情
关于桌面灵伴
退出
```

首次使用菜单时，可以勾选“显示详情”。开启后，每个菜单项右侧都会出现一个圆形 `?`；把鼠标移入圆圈及其周围 4 像素后会立即弹出该项的详细解释，无需停留等待，停在文字、勾选框或子菜单箭头上不会弹出。说明会给出实际数值，例如三级闲逛的 8–18 / 2–6 / 1–3 秒，普通移动的 75 / 120 / 180 像素/秒，动画速度的 ×1.25 / ×1 / ×0.75，以及当前宠物每个动作从 JSON 读取的帧数、帧时长、总时长、权重、名义概率和冷却秒数。看懂后再次点击“显示详情”即可恢复简洁菜单，选择会在退出时保存。

“动作展示”会连续播放当前宠物的原地动作，单击、双击或拖动宠物即可切换或中断。“回到屏幕中央”使用光标所在显示器的可用区域。自动闲逛会在宠物当前显示器的可用区域内选择朝左或朝右的目标位置，移动窗口时也可能改变垂直位置，但不会进入任务栏区域；拖动、手动动作、菜单命令或重新移动鼠标会中断当前闲逛。

闲逛强度分为三档：“安静”每次等待约 8–18 秒，并把单次目标距离限制在可移动宽度的 25%；“标准”保持原有约 2–6 秒等待和全屏目标范围；“活跃”把等待缩短到约 1–3 秒。升级旧设置时默认使用“标准”。

“鼠标活动时”是推荐注视方式：移动鼠标时宠物立即看向鼠标；连续静止约 8 秒后暂时释放注视。此时若已勾选自动闲逛就开始闲逛；否则在勾选自主小动作时触发原地动作；两项都未勾选则保持待机。鼠标再次移动会立即恢复注视。选择“始终看向鼠标”后不会因静止而释放注视，并暂停自动闲逛和自主小动作。

v3 宠物包的 `gaze` 支持 16、32 或 64 个等角度方向。南宫婉使用 64 方向、每 5.625° 一帧的伪连续注视；右键“观察方向”仍只保留16个常用测试角度，自动看向鼠标会使用完整64帧。

不支持 `gaze` 的宠物和关闭看向鼠标时，仍按约 15–35 秒随机间隔触发自主动作。动作结束后还有独立冷却，左右移动不会进入自主动作池，同一动作不会连续出现；具有相同 `autoplayGroup` 的术法或强特效也不会连续随机播放。

实现语义和验收方法见[动作分组、视线门槛与闲逛强度](docs/behavior-groups-and-wander-intensity.md)。

## 开机启动

冻结或安装后的应用中，打开“开机启动”会写入带引号的应用绝对路径和 `--startup` 参数，关闭则删除同名当前用户 `Run` 值，不需要管理员权限。`--startup` 启动仍遵守单实例规则；已有实例时只激活它。

如果安装后移动了可执行文件，请先关闭再重新打开“开机启动”，以刷新注册表中的绝对路径。不要手工复制源码解释器命令作为启动项。

## 安装与卸载

使用发布目录内的 `桌面灵伴安装程序.exe`，不要直接复制 `.venv`、`dist` 或源码目录：

1. 双击安装程序并按向导安装。默认目标为 `%LOCALAPPDATA%\Programs\DesktopCompanion`，仅写当前用户，不请求管理员权限；安装程序会在当前用户桌面创建“桌面灵伴”快捷方式。
2. 首次安装默认勾选开机启动；向导末页可立即运行。覆盖安装会先请求现有实例安全退出，并保留已有设置和用户当前的开机启动选择。
3. 卸载时打开 Windows“设置 > 应用 > 已安装的应用”，找到“桌面灵伴”并选择卸载。卸载程序会请求现有实例退出，并清除应用文件、该应用的 HKCU 启动项、设置和日志。

桌面灵伴使用新的安装目录、卸载 GUID、设置目录、自启动项和单实例标识，可以与“十一桌面宠物 1.0”同时安装；安装或卸载 2.x 不会删除 1.0。两版也能同时运行，但初始位置可能重叠，建议拖开或只保留一版开机启动。

## 同人内容说明

南宫婉和紫灵为基于《凡人修仙传》角色制作的非官方同人桌面宠物，仅用于学习与交流，不代表原作、动画制作方或相关权利方。角色及原作相关权利归其各自权利人所有；请勿将相关视觉资源用于商业用途。

如需核验下载文件，请在 PowerShell 中运行 `Get-FileHash -Algorithm SHA256`，并与同目录的 `SHA256SUMS.txt` 比较。更简明的用户说明见发布目录中的 `安装说明.md`。

## 隐私

- 没有网络请求、账号、遥测、广告或自动更新。
- Windows 低级键盘钩子只判断主键盘/小键盘数字键的按下和抬起，不记录文字或按键历史，也不把按键写入日志。
- 数字事件仅在光标命中可见宠物像素时消费；其他输入保持原样。
- 设置和日志只保存在当前用户目录，开机启动只修改 HKCU。
- 程序运行和当前用户安装均不要求管理员权限。

## 排错

### 宠物跑到屏幕外或显示器已断开

程序会在启动、分辨率变化和显示器变化时把宠物限制到可用屏幕。仍找不到宠物时，先右键托盘图标，选择“回到屏幕中央”；该命令会把宠物移到光标所在显示器中央。如果托盘也不可用，运行 `--quit-existing`，备份后删除 `%APPDATA%\DesktopCompanion\settings.ini`，再重新启动以恢复默认位置。

### 数字快捷键没有反应

确认“悬停数字快捷键”已勾选，宠物处于可见状态，并把光标放在宠物身体的非透明像素上；仅位于透明边缘时不会触发。主键盘和数字小键盘均支持。若键盘钩子启动失败，本次会话会自动关闭快捷键并尝试显示一次托盘通知，鼠标与菜单功能仍可使用。可重启程序并检查 `%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log`；安全软件、系统策略或高完整性前台程序也可能限制全局钩子。

### 资源或 WebP 自检失败

运行 `--self-test` 查看 JSON 结果；成功报告中的 `pets` 应为 `["shiyi","ziling"]`。源码模式中重新安装精确锁定的 `requirements\dev.txt`，并确认 `src\shiyi_desktop_pet\resources\pets\shiyi`、`pets\ziling` 和 `app.ico` 没有缺失。资源契约失败时程序会记录错误并退出，不会显示空白宠物窗口。

### 新宠物没有出现在菜单中

确认文件夹位于 `%APPDATA%\DesktopCompanion\pets\<pet_id>`，目录名与 JSON 的 `id` 完全对应，并且文件名正好是 `pet.json` 和 `spritesheet.webp`。选择“重新扫描宠物”后查看托盘通知和 `%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log`。内置宠物自检只报告 `shiyi`、`ziling`；用户宠物由正常启动和重新扫描流程单独校验。

第三方组件及许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
