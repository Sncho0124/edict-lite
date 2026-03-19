# edict-lite

最小版 2-agent 工作流项目。

## Agents
- editor: 执行任务
- reviewer: 审核任务并给出具体反馈

## 目录
- `config/workflow.json`: 状态与流转规则
- `config/agents.json`: agent 定义
- `config/slack.json`: Slack 通知配置
- `data/tasks.json`: 真实任务状态
- `data/logs/`: 运行日志目录
- `prompts/`: agent prompt
- `scripts/`: 脚本
- `runtime/state.json`: run loop 状态

## 安装
```bash
cd ~/edict-lite
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量
复制并编辑 `.env`：
```bash
EDICTLITE_ENABLE_SLACK_LISTENER=false
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_EDITOR_WEBHOOK_URL=
SLACK_REVIEWER_WEBHOOK_URL=
SLACK_REVIEWER_DELEGATE_BOT_USER_ID=
SLACK_REVIEWER_DELEGATE_TIMEOUT_SECONDS=180
SLACK_REVIEWER_DELEGATE_POLL_SECONDS=3
```

说明：
- `EDICTLITE_ENABLE_SLACK_LISTENER=false` 是推荐默认值。这样启动 `scripts/main.py` 时只跑 orchestrator，不抢 Slack 入口。
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` 只有在你**明确启用** `EDICTLITE_ENABLE_SLACK_LISTENER=true` 时才用于监听 Slack 并回帖。
- `SLACK_TRIGGER_BOT_USER_ID` 用来指定 **哪个 Slack bot mention 会被当成任务入口**。请设成你实际要在 Slack 里 @ 的 bot user id（当前环境示例：`U0AC705HRPS`）。
- `SLACK_EDITOR_WEBHOOK_URL` / `SLACK_REVIEWER_WEBHOOK_URL` 仍用于 editor / reviewer 侧的纯文本通知。
- `SLACK_REVIEWER_DELEGATE_BOT_USER_ID` 可选；设置后，reviewer 会把 **Slack 来源任务** 委托给该 bot（在原线程里 `@bot` 并等待回帖）。
- `SLACK_REVIEWER_DELEGATE_TIMEOUT_SECONDS` / `SLACK_REVIEWER_DELEGATE_POLL_SECONDS` 控制等待该 bot 回帖的超时与轮询频率。

## 初始化
```bash
python3 scripts/init_project.py
```

## 创建任务
```bash
python3 scripts/create_task.py "写一个 README 初稿"
```

## 交接任务
```bash
python3 scripts/handoff_task.py <task_id> in_review reviewer
```

## 审核任务
```bash
python3 scripts/review_task.py <task_id> approved "内容完整，结构清晰"
python3 scripts/review_task.py <task_id> revision_required "请补充安装步骤"
python3 scripts/review_task.py <task_id> blocked "缺少必要输入，无法验证"
```

## 运行循环
```bash
python3 scripts/run_loop.py
```

默认每 10 秒扫描任务并更新 `runtime/state.json`。

## 推荐启动方式（避免和 OpenClaw 抢 Slack）
```bash
cd ~/edict-lite
python3 scripts/main.py
```

这会默认只启动 orchestrator，不启动 `slack_listener.py`。

如果你**明确要让 edict-lite 自己接 Slack**，才临时这样开：
```bash
cd ~/edict-lite
EDICTLITE_ENABLE_SLACK_LISTENER=true python3 scripts/main.py
```

当前推荐用法：
- OpenClaw 继续负责你和 Rui 的正常 Slack 对话
- edict-lite 的 listener 只处理 **`<@SLACK_TRIGGER_BOT_USER_ID>` 被 mention 的消息**
- 被触发后，listener 会创建任务，后续仍由 orchestrator → editor/reviewer 流程处理

不建议长期和 OpenClaw 争抢同一个普通聊天入口。

## 说明
- 只实现 editor / reviewer 两个 agent
- 真实状态源只有 `data/tasks.json`
- Slack 仅用于纯文本通知
- 不包含 Web UI、数据库、Docker 或复杂多 agent 扩展

11
