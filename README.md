# KCC Plugin Market

KangKang 的个人 Claude Code Skill 市场。通过 Claude Code 的 plugin 功能，一次配置，多端同步。

## 已收录 Skills

| Skill | 描述 |
|-------|------|
| [pr-review-resolver](pr-review-resolver/SKILL.md) | 自动处理 GitHub PR 未解决的 Review 评论，修复真实问题并输出处理报告 |

## 安装到 Claude Code

在 `~/.claude/settings.json` 中添加本仓库地址（推送到 GitHub 后填写实际 URL）：

```json
{
  "plugins": [
    "https://github.com/zhangkangkang/KCCPluginMarket"
  ]
}
```

保存后重启 Claude Code，Skills 即可使用，通过 `/KCCPluginMarket:pr-review-resolver` 调用。

## 添加新 Skill

1. 在仓库根目录创建以 skill id 命名的目录
2. 在目录内创建 `SKILL.md`，按以下格式编写：

```markdown
---
name: skill-id
description: "触发描述。Claude Code 用这段话判断何时自动激活此 Skill。"
---

# Skill 标题

具体指令内容...
```

3. 在 `README.md` 的表格中补充条目
4. `git push` 后，所有已配置本市场的 Claude Code 实例执行 `/update` 即可同步
