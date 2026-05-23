# KCC Plugin Market

KangKang 的个人 Claude Code 插件市场。通过 Claude Code 的插件机制，一次配置，多端同步。

## 结构说明

```
KCCPluginMarket/     ← 市场仓库
└── kcc/             ← 插件（Plugin），对应 enabledPlugins 中的插件 ID
    └── <skill-id>/  ← Skill，kcc 插件下的具体能力
        └── SKILL.md
```

## 已收录 Skills（kcc 插件）

| Skill | 描述 |
|-------|------|
| [pr-review-resolver](kcc/pr-review-resolver/SKILL.md) | 自动处理 GitHub PR 未解决的 Review 评论，修复真实问题并输出处理报告 |

## 安装

将以下内容添加到 `~/.claude/settings.json`：

```json
{
  "extraKnownMarketplaces": {
    "kcc": {
      "source": {
        "source": "github",
        "repo": "zhangkangkang/KCCPluginMarket"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "kcc@kcc": true
  }
}
```

重启 Claude Code 后即可使用 `kcc` 插件下的所有 Skills。

## 添加新 Skill

```bash
mkdir -p kcc/my-new-skill
# 编写 kcc/my-new-skill/SKILL.md
git add kcc/my-new-skill
git commit -m "feat: add my-new-skill"
git push
```

新 Skill 会随 `kcc` 插件一起加载，无需修改任何配置。
