# 测试集评测结果

## liuqiao_kg
- 注入检出: 1/9（fake1、fake2、uncited、wrongyear、misattr1、misattr2、typo1、typo2 未检出）
- 论断级: TP=1 FP=1 FN=0 TN=68 既有问题=0 支持度判定覆盖=0/70
- 文献级: TP=0 FP=4 FN=3 TN=43
- 合计 P/R/Acc: 0.167 / 0.250 / 0.933

## luohuilan_odt
- 注入检出: 2/9（fake1、fake2、wrongyear、misattr1、misattr2、typo1、typo2 未检出）
- 论断级: TP=1 FP=0 FN=0 TN=86 既有问题=1 支持度判定覆盖=0/88
- 文献级: TP=1 FP=1 FN=3 TN=66
- 合计 P/R/Acc: 0.667 / 0.400 / 0.975

## zhaoyangyang_tod
- 注入检出: 1/9（fake1、fake2、uncited、wrongyear、misattr1、misattr2、typo1、typo2 未检出）
- 论断级: TP=1 FP=0 FN=0 TN=176 既有问题=5 支持度判定覆盖=0/182
- 文献级: TP=0 FP=2 FN=4 TN=236
- 合计 P/R/Acc: 0.333 / 0.200 / 0.986

## yinhongpeng_odt
- 注入检出: 2/9（fake1、fake2、wrongyear、misattr1、misattr2、typo1、typo2 未检出）
- 论断级: TP=1 FP=0 FN=0 TN=158 既有问题=11 支持度判定覆盖=0/170
- 文献级: TP=1 FP=0 FN=3 TN=208
- 合计 P/R/Acc: 1.000 / 0.400 / 0.992

## guyingjie_mrc
- 注入检出: 3/9（fake1、fake2、misattr1、misattr2、typo1、typo2 未检出）
- 论断级: TP=1 FP=0 FN=0 TN=130 既有问题=2 支持度判定覆盖=0/133
- 文献级: TP=2 FP=0 FN=2 TN=112
- 合计 P/R/Acc: 1.000 / 0.600 / 0.992

---

## 五篇汇总（论断级 + 文献级）
- TP=9 FP=8 FN=15 TN=1283
- **查准率 0.529　查全率 0.375　准确率 0.983**
