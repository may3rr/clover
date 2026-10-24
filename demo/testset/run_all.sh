#!/bin/bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude
cd /Users/jackielyu/Coding/tmall
for d in liuqiao_kg luohuilan_odt zhaoyangyang_tod yinhongpeng_odt guyingjie_mrc; do
  for v in clean injected; do
    if [ -f "demo/testset/reports/${d}_${v}.json" ]; then echo "skip ${d}_${v}"; continue; fi
    echo "=== ${d}_${v} ==="
    python demo/run_pipeline.py "demo/testset/zh_papers/${d}/manuscript${v:+_$v}.docx" \
      "demo/testset/reports/${d}_${v}.json" > "demo/testset/reports/${d}_${v}.log" 2>&1
    echo "exit=$? $(tail -1 demo/testset/reports/${d}_${v}.log | head -c 100)"
  done
done
echo ALL_DONE
