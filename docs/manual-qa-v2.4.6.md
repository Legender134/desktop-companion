# 桌面灵伴 2.4.6“屋檐动作扩充”验收记录

## 本次改动

- 屋檐常驻动作由 6 种增加到 9 种，新增“抬手拢发”“轻触朱雀环”“白鹤掠月”。
- 原“闭目小憩”扩展为 13 帧“含栗欲眠”，表现眼皮渐沉、轻轻点头、短暂停顿和回神。
- “月下含栗”由 28 帧、约 4.32 秒扩展为 44 帧、约 8.99 秒，补齐端详、小口含栗、停顿回味、第二口和空手收势。
- 屋檐驻留时间调整为最短 25 秒、渐变 20 秒、最长 60 秒；常驻动作权重合计仍为 100，其中“月下含栗”为 20。60 秒是常驻动作的硬启动边界：若下一动作会越界则直接起身，退出动画可在边界后自然播完。

## 素材与视觉检查

- 图集尺寸：3072×7072 WebP RGBA；屋檐状态共 166 帧。
- 棋盘格逐帧审片：`work/moonlit-rooftop-state/audit-166-transparent-v9.png`。
- 坐点锚线抽查：`work/moonlit-rooftop-state/anchor-audit-v9.png`。
- 明暗桌面连续预览：`work/moonlit-rooftop-state/moonlit-rooftop-transparent-v9.mp4`。
- 8.99 秒含栗单独预览：`work/moonlit-rooftop-state/rooftop-chestnut-extended-v9.mp4`。
- 所有坐姿保持同一骨盆代理点和第 203 行附近的脚底线；动作仍使用完整人物帧，不粘贴固定下半身。
- 已清理生成素材中的低透明度色键尘点和“小憩”源图的多余白色点；透明画布四角保持透明。

## 自动验证

- 完整源码测试：215 项通过。
- 冻结程序自检通过；独立冻结冒烟测试 1 项通过，确认 Qt 6.11.1、WebP 读取和 3 个内置宠物均正常。
- Inno Setup 6.7.3 构建成功，安装程序大小为 58,501,921 字节。
- 安装程序：`artifacts/DesktopCompanion-2.4.6-setup.exe`。
- 安装程序 SHA256：`D451BC1FB6D548892D6F10C46BB9AE92BFECACDA3DFC3F6F5AB2BC530A09AE9C`。
- 本机从 2.4.5 覆盖升级到 2.4.6 通过；注册表版本、桌面快捷方式、南宫婉选择、设置和旧版兼容素材均保留。
- 已安装图集与源码图集 SHA256 一致：`564793E6C2E090D8E882CC4A829CECCB9BDE2AB98B54B9F6126C65CF41FAC77E`。
- 覆盖安装前备份：`work/local-install-backup-before-v2.4.6-expanded-20260722-110751`。
