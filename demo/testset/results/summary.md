# 测试集评测结果

## liuqiao_kg
- 注入检出: 5/9（fake1、fake2、misattr1、typo1 未检出）
- 论断级: TP=1 FP=3 FN=1 TN=55 既有问题=15 支持度判定覆盖=25/74
- 文献级: TP=2 FP=0 FN=2 TN=47
- 合计 P/R/Acc: 0.500 / 0.500 / 0.946

## luohuilan_odt
- 注入检出: 7/9（misattr1、misattr2 未检出）
- 论断级: TP=3 FP=3 FN=2 TN=69 既有问题=17 支持度判定覆盖=34/93
- 文献级: TP=4 FP=1 FN=0 TN=53
- 合计 P/R/Acc: 0.636 / 0.778 / 0.956

## zhaoyangyang_tod
- 注入检出: 8/9（misattr1 未检出）
- 论断级: TP=3 FP=6 FN=1 TN=134 既有问题=62 支持度判定覆盖=85/196
- 文献级: TP=3 FP=2 FN=1 TN=213
- 合计 P/R/Acc: 0.429 / 0.750 / 0.972

## yinhongpeng_odt
- 注入检出: 4/9（fake1、fake2、wrongyear、misattr1、typo2 未检出）
- 论断级: TP=2 FP=2 FN=1 TN=164 既有问题=63 支持度判定覆盖=98/230
- 文献级: TP=1 FP=1 FN=3 TN=199
- 合计 P/R/Acc: 0.500 / 0.429 / 0.981

## guyingjie_mrc
- 注入检出: 6/9（fake1、fake2、misattr1 未检出）
- 论断级: TP=1 FP=8 FN=2 TN=112 既有问题=48 支持度判定覆盖=77/167
- 文献级: TP=2 FP=3 FN=2 TN=114
- 合计 P/R/Acc: 0.214 / 0.429 / 0.939

---

## 五篇汇总（论断级 + 文献级）
- TP=22 FP=29 FN=15 TN=1160
- **查准率 0.431　查全率 0.595　准确率 0.964**
