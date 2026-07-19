# v3 动态宠物包模板

这里提供可直接复制修改的 `pet.json`。模板不包含 `spritesheet.webp`，因为图集必须由制作者按自己的角色绘制。

使用步骤：

1. 复制整个文件夹并改成英文宠物 ID，例如 `snow_cat`。
2. 把 `pet.json` 中的 `id` 同样改成 `snow_cat`。
3. 修改名称和动作；不需要遁光时可删除 `dashRight`、`dashLeft` 及对应图集行。
4. 按[添加新宠物指南](../../docs/添加新宠物指南.md)制作透明 `spritesheet.webp`。
5. 把 JSON 和图集放在同一个文件夹中。

模板使用8列、4个直接绘制行，因此示例图集为 `1536 × 832`；两个向左动作通过 `mirrorOf` 共用向右素材。动作和帧数改变后，图集尺寸也可以改变。

如果增加多套施法或强特效，可给这些 `interaction` 统一添加 `"autoplayGroup": "spell"`，防止它们连续自动播放。

精确规则见 [v3 动态宠物包规范](../../docs/pet-pack-format-v3.md)，编辑器可加载 [v3 JSON Schema](../../schemas/pet-pack-v3.schema.json)。旧图集兼容规则仍保留在 [v2 规范](../../docs/pet-pack-format-v2.md)。
