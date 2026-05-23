# KCC Plugin Market

KangKang 的个人 Claude Code 插件市场。通过 Claude Code 的插件机制，一次配置，多端同步。

## 结构说明

```
KCCPluginMarket/
├── .claude-plugin/
│   ├── plugin.json       ← 插件 manifest（定义插件名为 "kk-common-plugin"，skills 路径为 ./skills）
│   └── marketplace.json  ← 市场 manifest（定义市场 ID 为 "kk-common-market"）
└── skills/
    └── <skill-id>/
        └── SKILL.md
```

## 已收录 Skills

| Skill | 描述 |
|-------|------|
| [pr-review-resolver](skills/pr-review-resolver/SKILL.md) | 自动处理 GitHub PR 未解决的 Review 评论，修复真实问题并输出处理报告 |

## 安装到 Claude Code

在 `~/.claude/settings.json` 中添加：

```json
{
  "extraKnownMarketplaces": {
    "kk-common-market": {
      "source": {
        "source": "github",
        "repo": "twoFiveOneTen/KCCPluginMarket"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "kk-common-plugin@kk-common-market": true
  }
}
```

重启 Claude Code 后，`skills/` 下所有 Skill 即可使用。

## 添加新 Skill

```bash
mkdir -p skills/my-new-skill
# 编写 skills/my-new-skill/SKILL.md
git add skills/my-new-skill
git commit -m "feat: add my-new-skill"
git push
```

新 Skill 随 `kk-common-plugin` 插件自动加载，无需修改任何配置。
