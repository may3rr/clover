#!/bin/bash
# F8 English corpus: arXiv LaTeX sources (raw/) -> reports/en_<name>_{clean,injected}.json
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude
export DASHSCOPE_API_KEY=$(python3 "$(dirname "$0")/get_key.py")
cd /Users/jackielyu/Coding/tmall
variants=${1:-"clean injected"}
for pair in resnet:1512.03385 t5:1910.10683 gpt3:2005.14165 ddpm:2006.11239 vit:2010.11929; do
  d=${pair%%:*}; a=${pair##*:}
  for v in $variants; do
    out="demo/testset/reports/en_${d}_${v}.json"
    if [ -f "$out" ]; then echo "skip en_${d}_${v}"; continue; fi
    echo "=== en_${d}_${v} ==="
    if [ "$v" = "clean" ]; then f="demo/testset/raw/${a}.tar.gz"; else f="demo/testset/en_papers/${d}/manuscript_injected.zip"; fi
    python demo/run_pipeline.py "$f" "$out" > "demo/testset/reports/en_${d}_${v}.log" 2>&1
    echo "exit=$? $(tail -1 demo/testset/reports/en_${d}_${v}.log | head -c 100)"
  done
done
echo ALL_DONE
