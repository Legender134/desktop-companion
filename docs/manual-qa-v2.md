# 桌面灵伴 2.0 验收记录

验收环境：Windows 11 x64，当前用户安装，Qt/PySide6 6.11.1。

## 自动门禁

- `pip check`：通过，无损坏依赖。
- 源码测试：`133 passed`。
- 冻结版自检测试：`1 passed`。
- 覆盖率：`90%`，高于 85% 门槛。
- PyInstaller 冻结：通过；`DesktopCompanion.exe --self-test` 返回 `ok=true`、WebP 可用、每只宠物 74 帧。
- Inno Setup 6.7.3：成功生成“桌面灵伴安装程序.exe”。
- 真实发布验证：普通安装、自检、自启动值生命周期、卸载清理、覆盖升级、设置保留和状态恢复全部通过。

自检中的宠物清单为：

```json
{"pets":["shiyi","ziling"]}
```

## 原生界面检查

| 项目 | 结果 |
|---|---|
| 首次/默认角色 | 显示十一，窗口为 192×208，透明边缘正常 |
| 右键菜单 | 显示“切换宠物（十一 ⇄ 紫灵）”和 2.0 的完整菜单 |
| 十一切换到紫灵 | 单击后无需重启，窗口中立即显示紫灵 |
| 设置持久化 | `settings.ini` 立即写入 `schema_version = 2`、`pet_id = ziling` |
| 重启恢复 | 退出并重新启动后仍显示紫灵 |
| 资源契约 | 十一、紫灵均为 v2、1536×2288、透明 WebP，动作与观察方向占用表一致 |
| 图标 | 从紫灵休息帧重新生成，包含 16/32/48/256 像素图层，已不同于 1.0 图标 |
| 1.0 共存 | 2.0 使用独立 EXE、目录、设置、日志、自启动项、互斥量、IPC 名称和卸载 GUID，不覆盖 1.0 |

## 产品身份

- 显示名称：桌面灵伴
- 版本：2.0.0
- 可执行文件：`DesktopCompanion.exe`
- 安装目录：`%LOCALAPPDATA%\Programs\DesktopCompanion`
- 设置：`%APPDATA%\DesktopCompanion\settings.ini`
- 日志：`%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log`
- 自启动值：`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DesktopCompanion`

## 说明

原 1.0 的历史验收记录保存在 `docs/manual-qa-1.0.md`。本次没有删除或覆盖原项目、原安装包或原安装目录。安装包未做商业 Authenticode 签名，首次从其他电脑运行时可能出现 Windows SmartScreen 提示。
