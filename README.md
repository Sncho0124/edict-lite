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
SLACK_EDITOR_WEBHOOK_URL=
SLACK_REVIEWER_WEBHOOK_URL=
```

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

## 说明
- 只实现 editor / reviewer 两个 agent
- 真实状态源只有 `data/tasks.json`
- Slack 仅用于纯文本通知
- 不包含 Web UI、数据库、Docker 或复杂多 agent 扩展
