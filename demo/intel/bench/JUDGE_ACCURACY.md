# 本地 judge 准确率（T3）

数据：`judge_pairs.zip` 解压后的 508 对标注（仓库外 `C:\clover-data\judge_pairs.json`），variant 为 `current`（`J._PROMPT` + focused 句），报出规则与 `demo/testset/judge_ab.py` 一致：`label == unsupported` 或 `off_topic`。

## 结果

| 组 | 模型 / 设备 | injected | true_issue | false_alarm | failed | 证据降级 | 墙钟 | 每对平均 | 200 对估算 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 云端基线 | qwen3.8-flash 首轮 | 37 / 41 | 39 / 52 | 233 / 415 | 0 | — | — | — | — |
| a | Qwen3-8B-int4-ov / GPU，批处理 | 27 / 41 | 24 / 52 | 127 / 415 | 8 | 120 | 911.6 s | 27.9 s | 约 6.0 min |
| b | Qwen3-4B-int4-ov / GPU，批处理 | — | — | — | 508 | — | — | — | 无法加载 |
| c | Qwen3-8B-int4-cw-ov / NPU，逐条 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 |

- 8B GPU 与云端逐条一致率：**311 / 500 = 62.2%**（8 条本地失败，不计入）。
- 分歧 189 条；本地整体更保守：false_alarm 从 233 降到 127，但 injected/true_issue 的召回也明显下降。
- 120 条出现证据降级（模型给的 evidence 没能在 excerpt 里逐字定位，`supported/partial` 被降为 `undetermined`），是召回损失的主要来源之一。
- 每对平均 27.9 s 是含排队延迟的单请求平均；按吞吐 508/911.6 = 0.557 对/s 折算，200 对约 6.0 分钟（略高于 5 分钟目标）。

## 分歧示例（前 10 条，id / want / 本地 / 云端）

| id | want | why | 本地 label | 本地 off_topic | 云端 label |
| --- | --- | --- | --- | --- | --- |
| reports/liuqiao_kg/c24/r23 | false | false_alarm | undetermined | false | unsupported |
| reports/luohuilan_odt/c3/r10 | true | true_issue | undetermined | false | unsupported |
| reports/luohuilan_odt/c42/r1 | true | injected | supported | false | supported |
| reports/zhaoyangyang_tod/c101/r135 | true | true_issue | partial | false | unsupported |
| reports/zhaoyangyang_tod/c128/r153 | false | false_alarm | partial | false | supported |
| reports/zhaoyangyang_tod/c129/r169 | false | false_alarm | partial | false | undetermined |
| reports/zhaoyangyang_tod/c129/r172 | false | false_alarm | unsupported | false | unsupported |
| reports/zhaoyangyang_tod/c130/r173 | false | false_alarm | undetermined | false | unsupported |
| reports/zhaoyangyang_tod/c145/r192 | true | true_issue | unsupported | true | supported |
| reports/zhaoyangyang_tod/c157/r204 | false | false_alarm | partial | false | unsupported |

## 4B

Qwen3-4B-int4-ov 的 sha256 与 HF LFS 一致，但在 OpenVINO 2026.4.1 下 CPU/GPU 都加载失败：

```text
Check 'false' failed at src/core/shape_inference/include/reshape_shape_inference.hpp:210:
While validating node 'opset1::Reshape Reshape_295
(opset1::Multiply self.model.layers.0.mlp.down_proj.weight/fq_weights_1[0]:f16[2560,76,128],
 opset1::Constant Constant_209892[0]:i64[2]) -> ()':
Output pattern dim[1] has invalid bounds: -3891109803858067456,-3891109803858067456
```

因此 508 对所有失败，batch/quality 也无法执行。

## 备注

- 本地 8B 的 8 条失败是生成/校验失败（`judge_claim` 返回 None），不是路由失败。
- 本地对 8B 的 judge 单条输出上限是 1024 token；judge 实际输出通常 100–300 token，但少数长输出会拖慢整批。若要压到 5 分钟内，建议给 judge 设 `max_new_tokens=256` 并在提示词里限制 rationale 长度。
- NPU 组在 8B-cw 上逐条跑，预计约 1 小时，放在最后。
