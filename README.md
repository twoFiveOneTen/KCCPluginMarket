# KCC Plugin Market

KangKang 的个人 Claude Code 插件市场。通过 Claude Code 的插件机制，一次配置，多端同步。

## 结构说明

```
KCCPluginMarket/
├── .claude-plugin/
│   ├── plugin.json       ← 开发插件 manifest（定义插件名为 "kk-dev-plugin"，skills 路径为 ./skills）
│   └── marketplace.json  ← 市场 manifest（定义市场 ID 为 "kk-common-market"，列出所有插件）
└── skills/
    └── <plugin-name>/
        └── <skill-id>/
            └── SKILL.md
```

## 已收录 Skills

| Skill | 所属插件 | 描述 |
|-------|---------|------|
| [pr-review-resolver](skills/kk-dev-plugin/pr-review-resolver/SKILL.md) | kk-dev-plugin | 自动处理 GitHub PR 未解决的 Review 评论，修复真实问题并输出处理报告 |
| [news-hotspots](skills/kk-life-tool/news-hotspots/SKILL.md) | kk-life-tool | 获取最近 2 天中国国内和国际新闻热点事件摘要 |

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
    "kk-dev-plugin@kk-common-market": true,
    "kk-life-tool@kk-common-market": true
  }
}
```

重启 Claude Code 后，已启用的插件下的所有 Skill 即可使用。

## 添加新 Skill

```bash
# 在对应插件目录下创建 skill
mkdir -p skills/<plugin-name>/<skill-id>
# 编写 skills/<plugin-name>/<skill-id>/SKILL.md
git add skills/<plugin-name>/<skill-id>
git commit -m "feat(<plugin-name>): add <skill-id>"
git push
```

新 Skill 随所属插件自动加载，无需修改插件配置。

## 添加新插件

```bash
# 1. 在 skills/ 下创建插件目录
mkdir -p skills/<new-plugin>/<skill-id>

# 2. 在 .claude-plugin/marketplace.json 的 plugins 数组中添加新插件条目
# 3. 在个人 settings.json 中启用新插件
git add .
git commit -m "feat: add <new-plugin> plugin"
git push
```
