# paper-bot

每日读取 arXiv 最新论文，关键词初筛后用 DeepSeek 判定相关性并生成结构化摘要，可推送飞书、收录到 Zotero。入口保持 `python main.py`，不需要 Zotero 桌面插件。

公开代码仓库：[WhiteVolcanoRestaurant/paper-bot](https://github.com/WhiteVolcanoRestaurant/paper-bot)。此仓库使用新的提交历史，只包含代码、文档、配置模板和工作流，不包含私人运行状态。自己的运行仓库建议保持 Private，并配置自己的 Secrets 和 Variables。

**默认关闭历史状态持久化。** 本地与 GitHub Actions 默认只在本次运行的内存中记录进度，不创建状态文件、不读取或更新 `bot-state`、不自动提交 Git。Zotero 仍会通过云端条目查重；AI 筛选结果和飞书发送历史不会跨运行保留，因此可能重复调用 AI、重复推送，也不能跨运行累计每日预算或恢复已离开最新列表的失败论文。需要这些功能时再主动开启持久化。关闭此功能不影响文献写入 Zotero，也不会删除已有状态分支、历史提交或 Actions 日志。

## 资料与笔记

- **自动收录集合**：默认 Zotero 顶层集合“自动收录”，用于资料留存，不表示待阅读。新条目的 `abstractNote` 只保留原文摘要，Extra 单独记录无版本 arXiv ID 与首次收录版本。
- **AI 预览｜基于摘要**：默认关闭。开启后复用筛选/飞书已经生成的 AI 输出，不增加模型调用。子笔记包含来源、版本、日期、模型、阅读范围、研究问题、方法、作者声称的效果、未交代的信息、研究关联推测及检索词。事实、作者声称、AI 推测分别标注；缺失字段显示“摘要未说明”。模型仍可能理解错误，不能把摘要预览当作阅读全文后的结论。
- **个人阅读记录**：真正开始读时再创建，脚本从不创建空白个人笔记，也从不更新或删除笔记。机器笔记同时使用专用标签 `paper-bot:ai-preview:v1` 和正文管理标记识别，绝不只按标题匹配。不要把这两个标记复制到个人笔记。

在 Zotero 中选中论文，右键“添加笔记”，复制 [个人阅读模板](docs/personal-reading-note.md) 的各节，再填写自己的判断、证据和用途。可用 Zotero 自带编辑器整理；Better Notes 是可选工具，核心功能不依赖它。

## 项目结构

| 文件 | 职责 |
| --- | --- |
| `main.py` | 流程编排、预算和独立恢复 |
| `paperbot/config.py` | 环境变量和开关 |
| `paperbot/arxiv.py` | 抓取、关键词、现代/旧式 ID 与版本解析 |
| `paperbot/ai.py` | AI 调用、JSON 校验及摘要展示 |
| `paperbot/zotero.py` | 查重、集合、条目及子笔记 |
| `paperbot/feishu.py` | 卡片与响应检查 |
| `paperbot/state.py` | 原子 JSON、运行锁、Git 状态检查点 |
| `paperbot/http.py` | 有限 GET 重试 |
| `tests/` | 固定样本与 mock 测试，无真实服务调用 |

飞书保持简洁的五段预览：标题翻译、一句话总结、痛点与场景、核心架构/方法、评估效果，保留原有主题及“阅读原文”按钮。详细的未交代信息、关联推测和检索词只展示在 Zotero AI 子笔记中，避免在日常推送里反复插入判断标签。提示词要求直接、紧凑地描述摘要，缺失数值仍不补造。已有缓存继续复用，不为更换风格额外调用模型或改写旧笔记；缓存中尚未发送的摘要只切换为五段展示。作者来自 arXiv 作者列表；不再通过末位作者猜通讯作者或机构，也不再查询 OpenAlex。无法确认的信息不显示为事实。

## 本地运行与安全验证

建议 Python 3.12：

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py --dry-run
```

测试不使用凭据、不访问网络；旧入口 `python test_arxiv.py` 也改为运行离线测试。`--dry-run` **只读取 arXiv**，会访问它的公共 API；不调用 AI，不读取 Zotero，不发飞书，不创建状态目录、锁或提交状态。不需要任何密钥。需要完全离线验证时运行 unittest，而不是 dry-run。

正式本地运行通过 shell 设置环境变量，然后 `python main.py`，默认不保存历史。需要在自己的电脑保存状态时，运行 `python main.py --state .bot-state/state.json`，或者设置 `ENABLE_PERSISTENCE=true` 后运行 `python main.py`；后者使用同一路径。保留并备份此目录即可跨运行查重，本地运行不会自动提交 Git，只有显式使用 `--state-git` 才会提交并推送专用状态分支。不要与 Actions 或另一台机器同时操作同一库；本地锁只能保护同一个状态路径。

`.env.example` 是配置参考，脚本**不自动加载 `.env`**。密钥只从环境变量读取，日志不输出服务异常正文、API 密钥或 webhook 地址。诊断日志只记录失败阶段、异常类型、HTTP 状态码和有限重试次数。读取故障最多尝试 3 次，重试间隔为 3 秒、6 秒；不会打印请求头、环境变量值、响应正文或请求 URL。arXiv 抓取失败发生在筛选和发送之前，下次运行可重新尝试。

## 配置

Secrets（仓库 Settings → Secrets and variables → Actions → Secrets）：

| 名称 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 任一目标开启时，用于筛选与摘要 |
| `ZOTERO_API_KEY` | 启用 Zotero 时需要，个人库读写权限 |
| `ZOTERO_USER_ID` | Zotero 个人库数字用户 ID，不是用户名；仅支持个人库 |
| `FEISHU_WEBHOOK` | 启用飞书时需要，自定义机器人 webhook |

Variables（同页面 Variables；也可作为本地环境变量）：

| 名称 | 默认值 | 说明 |
| --- | --- | --- |
| `ENABLE_FEISHU` | `true` | 是否发送飞书 |
| `ENABLE_ZOTERO` | `true` | 是否向 Zotero 写入 |
| `ENABLE_AI_NOTES` | `false` | 是否补建 AI 子笔记，Zotero 关闭时不生效 |
| `ENABLE_PERSISTENCE` | `false` | 是否保留跨运行状态；Actions 开启后保存到 `bot-state`，本地开启后保存到 `.bot-state/state.json` |
| `ZOTERO_COLLECTION` | `自动收录` | 固定顶层集合名；同名顶层集合多个时停止该端写入 |
| `AI_MODEL` | `deepseek-chat` | 支持 JSON mode 的 DeepSeek 模型 |
| `MAX_DAILY_PUSH` | `3` | 默认每次运行的发送尝试上限；保留状态时按上海日期全日累计，失败也占用预算 |

布尔值支持 `true/false/1/0`。关闭自动笔记不影响飞书摘要和文献入库。两个目标均关闭时正式运行直接结束，不调用服务。更换模型不会自动重生成已缓存摘要；集合名更改不会批量移动已收录文献。

## fork 后启用 Actions

1. Fork 仓库，先在 Actions 中启用 fork 的 workflow。检查自己的默认分支上已包含本次代码。
2. 填写需要的 Secrets；在 Variables 里设置目标开关。只用 Zotero 可令 `ENABLE_FEISHU=false`，只用飞书可令 `ENABLE_ZOTERO=false`。笔记按需开启。
3. 默认无需配置状态存储，保持 `ENABLE_PERSISTENCE=false` 或不设置此变量即可。工作流不会读取、创建或推送 `bot-state`，每次运行重新处理最新列表。若不希望重复推送或需要跨运行恢复，可在 Variables 设置 `ENABLE_PERSISTENCE=true`。
4. 仅在开启持久化时，检查仓库/组织 Actions 策略允许 `daily` job 的 `contents: write` 及状态分支写入。首次会自动创建**独立无父历史的 `bot-state` 分支**，只包含 `.gitignore` 和 `state.json`；已有状态分支则直接复用。不要从代码分支复制出 `bot-state`。状态推送使用临时 `GITHUB_TOKEN`，无需个人 token；权限、网络或分支冲突失败时会中止，不会退回空状态。
5. 先在本地运行离线测试和 dry-run。准备好真实收录时再在 Actions 手动运行 `Daily paper bot`；手动运行是正式操作，会产生真实外部写入和 AI 费用。
6. 定时任务每天 UTC 04:00（北京时间 12:00）运行，也可手动触发。GitHub 可能排队延迟执行，消息会在抓取与筛选完成后发送，不能保证恰好 12:00 到达；以实际运行日志为准。Fork 的定时任务可能需要手动启用；长期无活动时检查平台是否停用了定时运行。

AI 调用按自己的 DeepSeek 账户计费，实际费用取决于模型、用量与实际请求时间。参见 [DeepSeek 官方价目表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。

## 开始使用

Fork 本仓库后，在自己的仓库中完成配置；只需要飞书推送时，无需配置 Zotero。下表列出自定义变量和研究方向的修改位置。

| 要修改的内容 | 修改位置 | 具体操作 |
| --- | --- | --- |
| AI 密钥、飞书机器人 | GitHub `Settings → Secrets and variables → Actions → Secrets` | 添加自己的 `DEEPSEEK_API_KEY` 和 `FEISHU_WEBHOOK`，不要写入代码或 README |
| 只开启飞书推送 | 同页面 `Variables` | 添加 `ENABLE_FEISHU=true`、`ENABLE_ZOTERO=false`；`ENABLE_AI_NOTES` 保持默认关闭 |
| 推送尝试上限 | 同页面 `Variables` | 设置 `MAX_DAILY_PUSH`，例如 `3`；默认每次运行单独计数，持久化开启后按日累计，失败也计数 |
| 历史状态持久化 | 同页面 `Variables` | 默认 `ENABLE_PERSISTENCE=false`；设置为 `true` 才会向 `bot-state` 分支保存处理记录 |
| AI 模型 | 同页面 `Variables` | 设置 `AI_MODEL`，默认 `deepseek-chat` |
| arXiv 学科范围 | [`paperbot/arxiv.py`](paperbot/arxiv.py) 的 `fetch_papers()` | 修改 `search_query`，当前为 `cat:cs.DC OR cat:cs.NI OR cat:cs.LG OR cat:cs.AI` |
| 关键词初筛 | [`paperbot/arxiv.py`](paperbot/arxiv.py) 顶部的 `EDGE`、`MODEL` | 换成自己方向的关键词，建议用小写英文；标题或摘要命中任一关键词才进入 AI 筛选 |
| AI 判断研究方向 | [`paperbot/ai.py`](paperbot/ai.py) 的 `PROMPT` | 修改开头的研究领域、任务1的相关性条件，以及任务2中 `relation` 的方向描述；保留 JSON 字段名和类型要求 |
| 每天运行时间 | [`.github/workflows/paper-bot.yml`](.github/workflows/paper-bot.yml) 的 `on.schedule` | 当前 `cron: '0 4 * * *'`，即北京时间每天 12:00；cron 使用 UTC，北京时间减 8 小时换算 |

**改研究方向时，学科范围、关键词和 AI 提示词需要一起调整。** 例如关注计算机视觉，可以将 `search_query` 改为 `cat:cs.CV`，将关键词换成自己的主题词，并让 `PROMPT` 按同一方向判定相关性。只改关键词，仍可能被原来的边云协同 AI 条件拒绝。`relation` 在机器输出中的字段名不变，其展示标签可在 `paperbot/ai.py` 的 `FIELDS['relation']` 中同步修改。

在 GitHub 网页修改代码：打开对应文件，点击编辑按钮，修改后提交到自己仓库的默认分支。首次配置后到 `Actions` 启用工作流，选择 `Daily paper bot → Run workflow` 手动验证；这会调用 AI 并发送真实消息。定时运行也使用默认分支上的工作流，因此只改本地文件不会改变 GitHub 的定时任务。

开启持久化后，已有论文的 AI 筛选结果会缓存。修改研究方向后，已缓存的论文不会自动重新筛选；不要删除 `bot-state` 分支来刷新，否则会丢失推送查重记录。若要长期运行多个不同研究方向，建议分别使用独立仓库保存各自的状态。

Workflow 使用固定 concurrency group `paper-bot-state`，`cancel-in-progress: false`，避免正在发送时被新的触发取消。所有写相同状态分支的 workflow 都必须复用此组。GitHub 排队不保证每次触发都执行；开启持久化后，后续运行会恢复待处理论文。

**状态分支不是私密笔记库。** 它保存公开论文信息、筛选决定、复用所需 AI 摘要、观察到的版本、Zotero 条目/笔记 key、飞书状态和日期预算，不存 API 密钥、webhook、个人阅读记录或敏感配置。公开 fork 的状态也会公开，包含你的自动筛选方向；若不希望公开这些元数据，请使用私有仓库。不要在 state.json 中手写个人批注。

## 在运行仓库同步最新代码

公开代码仓库与私人运行仓库各自维护提交历史。运行仓库无需与公开仓库合并历史；将公开仓库的最新代码复制到运行仓库的 `main` 并提交即可。GitHub Secrets、Variables 和独立的 `bot-state` 分支不会随代码同步改变；已启用持久化的运行仓库继续保持 `ENABLE_PERSISTENCE=true`。

在**运行仓库的本地克隆目录**中操作，先提交或备份自己的代码改动，确认 `git status --short` 没有输出。首次添加公开仓库作为上游：

```sh
git remote add upstream https://github.com/WhiteVolcanoRestaurant/paper-bot.git
```

如果之前已经添加过 `upstream`，改用 `git remote set-url upstream https://github.com/WhiteVolcanoRestaurant/paper-bot.git` 更新地址。若运行仓库曾改名，也要先用 `git remote set-url origin <运行仓库的新地址>` 更新它；旧名称被其他仓库复用后，不能继续依赖旧地址的重定向。

以后每次更新执行：

```sh
git switch main
git pull --ff-only origin main
git fetch upstream main
git restore --source=upstream/main --staged --worktree -- .
git diff --cached --stat
git diff --cached
python -m unittest discover -s tests -v
git commit -m "chore: sync latest public paper bot code"
git push origin main
```

`git restore` 会将当前目录中的受 Git 管理的文件同步为公开仓库版本，包括更新、新增和删除文件。自己的关键词、提示词或其他代码改动可能被覆盖，请先备份并在提交前重新应用需要保留的修改。未纳入 Git 的 `.env`、`.bot-state` 不属于代码同步范围。若没有代码差异，就无需提交；若发现意外的私人文件被加入提交，先处理它们再推送。仅在运行仓库的默认分支同步，不在 `bot-state` 分支执行这些命令；推送后定时任务会使用更新的代码。

开发和分享新功能时，在公开代码仓库提交、推送；运行仓库按上述步骤按需更新。不要将运行仓库的分支或旧提交历史推送到公开仓库，也不要使用 `git push --mirror` 或 `git push --all`。

## 持久化与历史清理建议

- **简单体验或偶尔运行**：保持默认关闭，GitHub 不新增状态提交；接受 AI 重复处理与飞书重复推送的可能。Actions 日志仍由 GitHub 保存，关闭持久化不等于没有运行日志。
- **长期每日推送**：需要跨日去重、缓存和失败恢复时再开启持久化。私人运行仓库保持 Private，公开分享代码使用另一独立仓库；公开仓库无法单独隐藏 `bot-state`。
- **希望记录只留在自己的电脑**：运行 `python main.py --state .bot-state/state.json`，用系统定时任务每天启动，保留并定期备份 `.bot-state`。该目录已加入 `.gitignore`，无需 Git 提交，但电脑需要在运行时间开机并联网。
- **已开启 GitHub 持久化**：定期检查状态分支体积。普通清理提交只缩小最新文件，不会清除旧 Git 历史；保留当前 `state.json` 的完整快照，定期重建状态分支历史，才能避免持续积累旧版本。建议按月检查，确实需要时再维护，不自动按月删记录。

维护状态分支前，先停用工作流并等待正在运行的任务结束，备份当前 `state.json`。重建时必须保留当前完整状态，将它和 `.gitignore` 放入新的无父历史 `bot-state` 提交，再替换远端状态分支；这涉及重写历史和强制更新，应人工维护。完成后验证状态可读，再恢复工作流。不要删除 `papers` 或将 `sent` 改回 `pending` 来减少体积，否则会破坏去重。GitHub 对不可达对象的回收不一定立即完成，重建分支也不能保证立即清除所有旧数据。

**已有用户升级注意**：默认关闭后，旧 `bot-state` 不会自动删除，但也不会读取；需要延续原有去重和恢复能力时，请在下一次运行前设置 `ENABLE_PERSISTENCE=true`。如果原仓库已有私人状态，即使关闭持久化也不要直接公开它，应该另外创建只含代码的公开仓库。本项目目前不自动清理状态或重写 Git 历史。

## 查重、版本与失败恢复

以下 AI 缓存、版本累计、跨运行飞书查重、日预算及失败恢复说明以开启持久化并保留同一状态为前提。默认关闭时，Zotero 云端查重仍然执行，AI 与飞书状态只在本次运行内保留；每次运行的发送尝试上限独立计算。

身份是去掉 `vN` 后的 arXiv ID，支持现代编号和 `hep-th/9901001` 等旧式编号。首次入库前分页检查 Zotero 顶层条目的 Extra、URL、DOI、archiveLocation，兼容没有专用 ID 字段的旧条目。找到一条时仅按需加入固定集合，保留旧摘要和其他内容；找到多条时打印 ID 和条目 key，暂停该论文 Zotero 写入，**不删除、不合并**。不进行全库历史迁移，无法从这些字段识别的历史条目仍可能无法查重。

本次范围只保存版本：在 state 中累计本次抓取观察到的版本，新条目 Extra 和 AI 笔记保存首次处理版本。已处理论文出现 v2 不会再调用 AI、重发飞书或改写旧摘要/笔记；拒稿也不会因版本变化重新判定。没有主动追踪版本或重写旧笔记的功能，个人笔记始终不修改。

`state.json` 原子替换，同一目录用排他锁避免并发；Actions 每个关键步骤提交并推送状态分支，而不是等任务最后才保存。成功筛选、入库、笔记、飞书分别记录。Git push 失败或冲突即停止后续操作，绝不强推。状态 JSON 损坏时拒绝启动，绝不自动清空。

- **AI 失败/无效 JSON**：作为错误记录日志并使任务失败，不等同拒稿。待处理论文元数据先持久化，后续即使离开最新 feed 也可重试。只有明确 `relevant:false` 才缓存为拒稿。相同论文的成功输出复用，不无意义调用 AI。
- **Zotero 失败、飛书成功**：保留已发送状态，下次只补齐 Zotero。条目成功、笔记失败：保留条目 key，只补笔记。开启笔记后可为状态中已有的收录记录补建笔记，不扫描全库批量创建。
- **Zotero 写入响应丢失**：下次重新读取条目/子笔记，发现已有记录就复用，减少重复创建。笔记同时检查专用标签和正文标记；已有脚本笔记也不重写。其他独立客户端并发创建不受本 workflow 锁控制，因此不声称全库事务级唯一。
- **飞书失败、Zotero 成功**：保留 Zotero 成功 key；下一次 workflow 尝试重发待发送消息。发送前保存 `pending` 和当日尝试次数，收到 HTTP 成功且业务码为 0 后再保存 `sent`。确认成功的论文以后不重复推送。失败占用日预算，重试可以是当日下一次运行，也可以是次日。

飞书 webhook **不能保证严格恰好一次投递**：服务器已收到消息但响应超时，或收到成功后状态 push 失败时，远端状态仍可能为 pending。这里选择继续重试，优先恢复遗漏，因而可能重复送达。发送请求不在同一次调用里自动重试；每日最多 3 次尝试（默认）控制刷屏，包括不确定的重试。这个上限保证的是尝试次数，不是精确的成功篇数。正常已确认送达时，状态查重跨日也有效。不要删除状态分支来“重试”，否则会丢失飞书历史。

请求都有超时。只读 GET 最多 3 次尝试，对 429/5xx/连接故障退避；AI SDK 最多额外重试 2 次。Zotero/飞书写入仅一次请求，校验 HTTP 状态和业务响应，再由下次运行对账恢复。自动重试不会无限持续在单次运行内；长期服务故障时修复配置后再运行。发生部分失败，任务返回非零，成功端状态仍已持久保存。

异常终止可能留下本地 `state.lock`。确认该本地进程已结束后再移除锁文件，切勿在另一个进程运行中删锁。Actions 每次使用新的 checkout，不持久保存锁。需要人工恢复状态时先停用 workflow，备份 state.json，只调整机器状态；不要把正常的 sent 改成 pending。已删除的 Zotero 条目或笔记不会自动检测重建，恢复这类人工删除需检查相应 key 状态。

## 验证覆盖与接口依据

离线测试覆盖 ID/版本、重复运行、旧条目识别、历史重复报告、新版本只记录、个人笔记保护、AI 失败及无效结构/缺失字段、两端部分失败恢复、HTML 转义、日预算、功能开关、状态锁及损坏、dry-run 零写入，以及默认关闭持久化、不读写旧状态、无状态重复运行时 Zotero 查重和本地持久化主动开启。测试替代所有外部写入，没有真实凭据测试。

接口实现参考 [Zotero 写入响应与版本条件](https://www.zotero.org/support/dev/web_api/v3/write_requests)、[Zotero 分页读取](https://www.zotero.org/support/dev/web_api/v3/basics)、[DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/) 和 [飞书自定义机器人示例](https://open.feishu.cn/community/articles/7271149634339422210)。上线前仍需在自己的 fork 配置正确权限与机器人安全设置。
