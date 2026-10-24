#!/bin/bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude
export DASHSCOPE_API_KEY=$(python3 "$(dirname "$0")/get_key.py")
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
