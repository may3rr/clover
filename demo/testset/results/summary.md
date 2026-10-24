# 测试集评测结果

## liuqiao_kg
- 注入检出: 4/9（fake1、fake2、misattr1、misattr2、typo1 未检出）
- 论断级: TP=0 FP=3 FN=0 TN=56 既有问题=17 支持度判定覆盖=25/74
- 文献级: TP=2 FP=0 FN=2 TN=47
- 合计 P/R/Acc: 0.400 / 0.500 / 0.955

## luohuilan_odt
- 注入检出: 7/9（misattr1、misattr2 未检出）
- 论断级: TP=1 FP=4 FN=1 TN=70 既有问题=19 支持度判定覆盖=34/93
- 文献级: TP=4 FP=1 FN=0 TN=53
- 合计 P/R/Acc: 0.500 / 0.833 / 0.955

## zhaoyangyang_tod
- 注入检出: 6/9（uncited、misattr1、misattr2 未检出）
- 论断级: TP=1 FP=6 FN=0 TN=135 既有问题=65 支持度判定覆盖=85/196
- 文献级: TP=3 FP=2 FN=1 TN=213
- 合计 P/R/Acc: 0.333 / 0.800 / 0.975

## yinhongpeng_odt
- 注入检出: 3/9（fake1、fake2、wrongyear、misattr1、misattr2、typo2 未检出）
- 论断级: TP=1 FP=3 FN=0 TN=165 既有问题=63 支持度判定覆盖=98/230
- 文献级: TP=1 FP=1 FN=3 TN=199
- 合计 P/R/Acc: 0.333 / 0.400 / 0.981

## guyingjie_mrc
- 注入检出: 5/9（fake1、fake2、misattr1、misattr2 未检出）
- 论断级: TP=0 FP=9 FN=0 TN=114 既有问题=48 支持度判定覆盖=77/167
- 文献级: TP=2 FP=3 FN=2 TN=114
- 合计 P/R/Acc: 0.143 / 0.500 / 0.943

---

## 五篇汇总（论断级 + 文献级）
- TP=15 FP=32 FN=9 TN=1166
- **查准率 0.319　查全率 0.625　准确率 0.966**
