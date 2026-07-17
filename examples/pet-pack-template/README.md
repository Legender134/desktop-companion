# 宠物包模板

这个目录提供可直接复制修改的 `pet.json`。它故意不包含 `spritesheet.webp`，因为图集必须由宠物制作者按自己的角色绘制，不能用空文件或普通单张图片代替。

使用步骤：

1. 复制整个 `pet-pack-template` 文件夹。
2. 把文件夹改成自己的宠物 ID，例如 `snow_cat`。
3. 修改 `pet.json` 中的 `id`，使其同样为 `snow_cat`。
4. 修改显示名称、说明和各动作的中文名称。
5. 按[添加新宠物指南](../../docs/添加新宠物指南.md)制作 `1536 × 2288` 的透明 `spritesheet.webp`。
6. 把两个文件一起放入复制后的宠物文件夹。

完成后的结构：

```text
snow_cat\
├─ pet.json
└─ spritesheet.webp
```

精确规则见 [桌面灵伴 v2 宠物包技术规范](../../docs/pet-pack-format-v2.md)。JSON 编辑器可使用仓库中的 [JSON Schema](../../schemas/pet-pack-v2.schema.json)进行字段提示和基础校验。
