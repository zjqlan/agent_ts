# 作业批改多智能体

给高中单科老师用的本机副驾驶：出题、出卡、批改、学情、备课都在一个教师端里完成。老师用自然语言点谁就调谁，页面按钮和底栏对话走同一条链路。

## 亮点

- **四个业务 Agent 同级，不是流水线。** 作业生成、答题卡与批改、学情、备课彼此平级，经 A2A 协作；一句话可以只叫一个，也可以按点名顺序连着派。老师始终拿着节奏。
- **工具走 MCP。** 排版、OMR、OCR、出卡渲染、图表都当工具调，Agent 不直接互相 import 业务函数。
- **该准的准，该人审的人审。** 客观题认答题卡气泡像素，不靠大模型猜选项；主观题只给建议分，老师确认后才进长期学情。
- **班级名单是硬门禁。** 没导入名单只能闲聊，避免对着空班出卡、批改、按人分析。
- **教师端一体。** Streamlit 八页（对话 / 名单 / 试卷 / 答题卡 / 批改 / 确认队列 / 学情 / 备课）+ 顶栏班级/作业/阶段 + 全局底栏对话，聊天和按钮都进 `/ask/stream`。
- **账本分得清。** MySQL 存教务事实，Redis 管会话和进行中任务，FAISS 做检索，扫描件和试卷只落本地文件。

## 操作

环境：Python 3.11+、Node.js（作业排版）、Docker。

```bash
docker compose up -d
copy .env.example .env          # macOS / Linux 用 cp
```

在 `.env` 里填 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`（OpenAI 兼容，例如百炼 `.../compatible-mode/v1`）。主观题 OCR 填 `OCR_URL=https://mineru.net/api/v4` 和 `MINERU_TOKEN`。

```bash
pip install -r requirements.txt
pip install -e .
cd tools/edupaper-mcp && npm install && cd ../..

python -m zypg          # 网关  http://127.0.0.1:8765
python -m zypg ui       # 教师端 http://127.0.0.1:8501
```

浏览器打开教师端。可以按下面顺序试一遍（每句只干一件事，顺序可打乱）：

1. `导入示例名单`
2. `导入示例试卷` 或 `按等差数列出题`
3. `只出卡`
4. `用刚出的卡当扫描件批改`
5. `看看这班学情`
6. `备课提纲` / `下一份作业`
7. `什么是等差数列`（闲聊，不派 Agent）

示例数据：`samples/roster.example.csv`、`samples/paper.example.md`。
