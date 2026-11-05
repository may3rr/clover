YP='zh_pdfs/aas_yinhongpeng_2016.pdf'
FN=lambda u,ev,note='原刊页脚脚注编号 [2][3][4]… 与网址被转换进正文，被当作参考文献标记，指向参考文献表的同号条目。': L(u,'false_alarm','parse_error',ev,note,sub='footnote_as_citation')
FN('6b8baf8c6e',YP+' 第2节「在UCI数据集2上进行实验」，脚注 2 为 https://archive.ics.uci.edu/ml/datasets.html')
for u in ['a8d5b98f91','9de1d7f241','f5a8dc6208']:
    FN(u,YP+'「Lin 等[201]将目标与背景分别看作高斯分布」，docx 中插入了脚注「[2]https://archive.ics.uci.edu…[3]http://www.cvpapers.com…」')
L('e2e75bae5c','true_issue','real_miscitation',YP+'「Li 等[203]将二维线性判别分析引入了跟踪目标的表观建模中」；[203] Li X, Hu W M 等 Visual tracking via incremental log-Euclidean Riemannian subspace learning, CVPR 2008，摘要「Based on the Log-Euclidean Riemannian metric ... covariance matrices ... represent object appearance」','[203] 用的是协方差矩阵的黎曼子空间学习，不涉及二维线性判别分析；原文所指应是另一篇 Li 等人的 2D-LDA 跟踪工作，原刊引用编号或文献有误。')
FN('451ed912bc',YP+' 第2节「能用于目标跟踪评测的公开视频序列比较多3,4,5,6」，3–6 为页脚数据集网址脚注')
FN('bd08fa9d2a',YP+' 表6说明句后的脚注「[5]http://www.computervisiononline.com/datasets[6]http://riemenschneider.hayko.at/…」')
L('8755106759','debatable','survey_generalization',YP+' 结束语「深度学习框架相继开源[92-98]」；[92] Dean et al. 2012 DistBelief 摘要「We have developed a software framework called DistBelief」','DistBelief 本身没有开源，概括对 [92] 不准确，但成组引用的其余框架均开源，属可商榷。',sev=False)
L('8755106759','false_alarm','stacking_normal_in_survey',YP+'「深度学习框架相继开源[92-98]」','逐一引用七个框架，属正常写法。',sel='distribution',sub='enumeration_each_item_cited')
for u in ['ec8cda0c1a','f0e7302ec3']:
    L(u,'false_alarm','conversion_artifact',YP+'「Bouwmans 等分别在2010 年[28]、2011 年[29]和2014 年[14]对背景建模进行了综述工作」；docx 把前一句的「换域模型[39-40]」错位拼进本句','原刊本句只引三篇 Bouwmans 综述，[39][40] 是分栏错位带进来的。')
L('83e087823a','false_alarm','judge_error',YP+'「Girshick 等将空间金字塔池化网络(SPPNet)[114]用于R-CNN」','[114] 是 SPPNet 这一术语的出处，主语 Girshick 指后面的 Fast R-CNN，模型把术语引用误读为作者归属。')
L('e0090a4c23','false_alarm','retrieval_miss','Kavukcuoglu et al. CVPR 2009（koray-cvpr-09.pdf）p6「traditional sparse coding algorithms are prone to produce unstable representations under small distortions of the input」','只看了摘要；全文明确支持稀疏编码对微小形变敏感。')
