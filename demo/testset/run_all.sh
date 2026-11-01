#!/bin/bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude
# 百炼密钥由 backend/.env 读取；向量与重排的硅基流动密钥取自 ~/.zshrc
# （F36 前这里把 DeepSeek 密钥塞进 DASHSCOPE_API_KEY，英文 F8 结果因此是 deepseek-flash 跑的）
[ -n "$SILICONFLOW_API_KEY" ] || export SILICONFLOW_API_KEY=$(zsh -ic 'printf %s "$SILICONFLOW_API_KEY"' 2>/dev/null)
cd /Users/jackielyu/Coding/tmall
variants=${1:-"clean injected"}
for d in liuqiao_kg luohuilan_odt zhaoyangyang_tod yinhongpeng_odt guyingjie_mrc; do
  for v in $variants; do
    if [ -f "demo/testset/reports/${d}_${v}.json" ]; then echo "skip ${d}_${v}"; continue; fi
    echo "=== ${d}_${v} ==="
    if [ "$v" = "clean" ]; then f="manuscript.docx"; else f="manuscript_injected.docx"; fi
    lib="demo/testset/zh_papers/${d}/ref"
    [ -d "$lib" ] || lib=""
    python demo/run_pipeline.py "demo/testset/zh_papers/${d}/${f}" \
      "demo/testset/reports/${d}_${v}.json" $lib > "demo/testset/reports/${d}_${v}.log" 2>&1
    echo "exit=$? $(tail -1 demo/testset/reports/${d}_${v}.log | head -c 100)"
  done
done
echo ALL_DONE
