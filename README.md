# KCC Plugin Market

KangKang 的个人 Claude Code 插件市场。通过 Claude Code 的插件机制，一次配置，多端同步。

## 结构说明

```
KCCPluginMarket/
├── .claude-plugin/
│   └── marketplace.json      ← 市场 manifest（市场 ID "kk-common-market"，列出所有插件）
└── plugins/
    └── <plugin-name>/
        ├── .claude-plugin/
        │   └── plugin.json   ← 插件 manifest
        └── skills/
            └── <skill-id>/
                └── SKILL.md
```

## 已收录 Skills

| Skill | 所属插件 | 描述 |
|-------|---------|------|
| [issue-implementer](plugins/kk-dev-plugin/skills/issue-implementer/SKILL.md) | kk-dev-plugin | 拉取指定 GitHub issue（含全部评论），确认方案后端到端实现：建分支、编码、自检、提交、开 PR |
| [pr-reviewer](plugins/kk-dev-plugin/skills/pr-reviewer/SKILL.md) | kk-dev-plugin | 审查当前分支最新 PR 的 diff，输出中文报告并把问题写成行内评论 |
| [pr-review-resolver](plugins/kk-dev-plugin/skills/pr-review-resolver/SKILL.md) | kk-dev-plugin | 自动处理 GitHub PR 未解决的 Review 评论，修复真实问题并输出处理报告 |
| [ios-gui-tester](plugins/kk-dev-plugin/skills/ios-gui-tester/SKILL.md) | kk-dev-plugin | 按指定代码改动（PR / 本地改动 / 分支比较）分析界面影响范围，生成 GUI 用例并在 iOS 模拟器逐条执行，输出带截图的测试报告 |
| [news-hotspots](plugins/kk-life-tool/skills/news-hotspots/SKILL.md) | kk-life-tool | 获取最近 2 天中国国内和国际新闻热点事件摘要 |

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
mkdir -p plugins/<plugin-name>/skills/<skill-id>
# 编写 plugins/<plugin-name>/skills/<skill-id>/SKILL.md
git add plugins/<plugin-name>/skills/<skill-id>
git commit -m "feat(<plugin-name>): add <skill-id>"
git push
```

新 Skill 随所属插件自动加载，无需修改插件配置。

## 添加新插件

```bash
# 1. 创建插件目录与 manifest
mkdir -p plugins/<new-plugin>/{.claude-plugin,skills/<skill-id>}
# 编写 plugins/<new-plugin>/.claude-plugin/plugin.json

# 2. 在 .claude-plugin/marketplace.json 的 plugins 数组中添加新插件条目
# 3. 在个人 settings.json 中启用新插件
git add .
git commit -m "feat: add <new-plugin> plugin"
git push
```
