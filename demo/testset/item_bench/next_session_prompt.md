# 新会话提示词：向量检索与重排上线到正式版

把下面整段贴进新的编码助手会话，工作目录设为 `/Users/jackielyu/Coding/tmall`。

---

先完整阅读仓库根目录的 `AGENTS.md`，它的约束优先于本提示词。再读 `demo/testset/item_bench/results.md` 第 12 到 15 节，了解向量检索和重排的评测依据。

## 背景

Clover 的支持度判断会先在被引文献全文中检索片段，再交给 qwen 判断。最近加了两项检索改进：

- 向量检索与 BM25 融合，代码在 `backend/citecheck/llm/embed.py`，提交 F18。
- Qwen3-Reranker 对融合后的前 40 个候选重排，代码在 `backend/citecheck/llm/rerank.py`，提交 F20。
- 两者在 `backend/citecheck/support/sources.py` 的 `_bm25_excerpt` 中接入。配置在 `[llm.embedding]` 和 `[llm.rerank]` 两节，模型类在 `backend/citecheck/config.py`。

效果：在 Citation-Integrity 人工证据句上，首轮片段命中率从 BM25 的 0.70 升到融合加重排的 0.75。端到端报警准确率从 0.71 升到 0.73，查出率从 0.42 升到 0.45。

现状：两项目前只在开发版生效。

- 本机 `backend/config.toml` 不入库，里面这两项是打开的。
- `backend/config.example.toml` 里这两项默认关闭。
- 服务商是硅基流动，模型是 `Qwen/Qwen3-Embedding-0.6B` 和 `Qwen/Qwen3-Reranker-0.6B`。key 从环境变量 `SILICONFLOW_API_KEY` 读取，只写在 `~/.zshrc` 里。

## 要解决的问题

1. **打包后不生效。** 打包版读 `~/Library/Application Support/Clover/config.toml`。这个文件不存在时会退回示例配置，示例配置里两项是关闭的。
2. **用户没有地方填 key。** 设置页 `app/src/renderer/src/screens/Settings.tsx` 只能填百炼的 key。
3. **失败时没有提示。** 从 Dock 或访达启动时拿不到 zshrc 里的 key，`embed.enabled()` 返回 False，系统悄悄退回 BM25，没有任何提示。
4. **服务商与隐私。** 赛题是阿里云的，向量检索会把被引 PDF 的文本片段和论断句发给第三方。

## 任务

1. **查百炼的替代模型。** 用官方文档查阿里云百炼 DashScope 是否提供向量模型和重排模型，记下：
   - 模型名与是否基于 Qwen3；
   - 接口地址和请求格式，重排接口可能不是 OpenAI 兼容格式；
   - 价格与限流。

   结论写进 `results.md` 新的一节。不要凭印象写模型名。
2. **百炼可用时让检索支持百炼。**
   - 改 `embed.py` 和 `rerank.py`，使其能用百炼。
   - 模型名、地址、key 的环境变量名全部走配置。
   - key 复用 `DASHSCOPE_API_KEY`，它在 `backend/.env` 里，打包版写在用户目录的 `.env`。这样用户只需要一个 key。
3. **重跑检索评测。** 在同一套数据上对比百炼与硅基流动的命中率：

   ```
   python demo/testset/item_bench/external_eval.py retrieval
   ```

   - 脚本里 `methods` 列表写死了硅基流动的模型名，需要调整。
   - 数据在 `demo/testset/item_bench/runs/external/`，不入库，已经下载好。
   - 硅基流动 0.6B 的向量缓存在 `runs/emb/`，以及 `cache.sqlite` 的 `vectors` 表。
4. **决定默认值。**
   - 若百炼效果不低于硅基流动，把示例配置改为默认开启百炼。
   - 若明显更差，保留硅基流动作为可选项，并在设置页加 key 输入框。设置页按 `AGENTS.md` 第 6 节的设计规范写。
   - 这一步需要我确认，先把对比数字和建议给我。
5. **补启动提示。** 配置开启但 key 缺失时，后端日志写一条警告。若报告里有合适位置，也给用户一条说明。
6. **核对隐私说明。** 检查 `AGENTS.md` 的稿件隐私一条与实际行为是否一致。被引 PDF 的片段和论断句会发到云端向量服务，如需修改措辞，先给我看。

## 约束

- **环境：** Python 用 `source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude`。
- **key：** 不要打印任何 key。需要硅基流动的 key 时用 `zsh -ic 'printf %s "$SILICONFLOW_API_KEY"'` 读进环境变量，不要回显。
- **花钱：**
  - 百炼余额估计约 37 元，以控制台为准，只用 qwen 的 flash 模型，不用 max。
  - 检索评测只花向量和重排的钱，很少，可以直接跑。
  - 任何端到端判断评测跑之前，先估算费用告诉我，等我同意。
- **测试：**
  - `cd backend && pytest` 必须全部通过，上次是 415 passed、3 skipped。
  - `tests/conftest.py` 用 `CITECHECK_EMBED=0`、`CITECHECK_RERANK=0` 关掉了真实调用。新增功能要有测试，测试里不发真实请求。
- **git：**
  - 提交信息以 F22 开头，只 add 具体文件，不要 `git add -A`。
  - 不要动 `app/site/` 下未提交的改动，以及未跟踪的 `submission/`、`demo/testset/precision_audit/`。
- **写作：** 每轮最后给我的总结必须用中文。中文学术写作不用括号补充、不用引号强调、不用破折号，不用核心、显著、机理、然而等词。

## 完成标准

- 文档里有百炼与硅基流动的对比数字和选择理由。
- 正式版在用户只填一个 key 时就能用上向量检索和重排；或者经我确认保留可选，并且设置页能填 key。
- key 缺失时有警告，测试全部通过，改动已提交。
