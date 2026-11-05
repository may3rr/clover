E=lambda u,ev,note='综述中逐项列举方法或数据集，每一项各带自己的引用，属正常写法，不是堆砌。': L(u,'false_alarm','stacking_normal_in_survey',ev,note,sel='distribution',sub='enumeration_each_item_cited')
Gp=lambda u,ev,note: L(u,'false_alarm','stacking_normal_in_survey',ev,note,sel='distribution',sub='group_cite')
GY='guyingjie_mrc 第1节「例如抽取式类别的TriviaQA[15], WikiQA[16], NewsQA[17], SQuAD 2.0[18], SearchQA[19]等, 多项选择类别的SciQ…」'
for u in '48c82539c5 62a168239f a9ed22b1ba 055d9a4eed 143bae7d55 474853193d 0218f49636 9cd342a803 4a76a6101e 9ea8e2e8e5 378023a961 16df145011 3e1b3a75ab 071e9c108a 565c441abf 3d9e5d587b 4e8250bb05 011b38d6da a4c44df9fc'.split():
    E(u,GY,'20 个数据集逐一列举，每个数据集各引一篇，属正常写法；同一条报警被摊到 19 个论断单元上重复计数。')
for u in ['99ceb797ff','973bfba2a0']:
    Gp(u,'guyingjie_mrc 第3节「Seo等人[47]在总结了前人在阅读理解中使用注意力机制[1,38,121-124]的研究工作之后提出了BiDAF模型」','综述中对一类前人工作做概括时成组引用，属正常写法。')
Gp('1b23ed40bf','yinhongpeng 引言「如文献[18−22],这部分工作极大地推动并促进了该领域的研究与发展」','列举 5 篇既有综述，成组引用属正常写法。')
E('fc02c25ebc','yinhongpeng 第1节 PDF「统计模型[28-29]、聚类模型[30-31]…稀疏模型[38]、变换域模型[39−40] 等背景模型」')
L('fc02c25ebc','false_alarm','conversion_artifact','zh_pdfs/aas_yinhongpeng_2016.pdf「稀疏模型[38]、变⏎换域模型[39−40] 等背景模型」；docx 为「变等背景模型. Bouwmans 等分别在换域模型」','PDF 分栏文字在转换时错位，原刊无漏字。',sel='typo')
for u in '4e1d23bdf0 a0e5f88945 3cb9bf5ba6'.split(): E(u,'yinhongpeng「PCA-SIFT[49]、GLOH[50]、SURF[51]、DAISY[52]等」')
for u in 'a0bf14abea 13f550faba 74be7d8961'.split(): E(u,'yinhongpeng「Haar-like[60]、CENTRIST[61]、Poselets[62]、Sparselets[63]…LAB[66]等」')
for u in 'fc68ce5e63 d66e694a10 de76241b48 a0e6feab80 1818232c6e 73b99dc41e'.split(): E(u,'yinhongpeng「形状上下文[69]、角矩阵[70]、kAS[71]、图形基元[72]、BOLD[73]、尺度不变形状特征[74]等」')
E('e787e850ee','yinhongpeng「颜色SIFT特征[76]、颜色属性[77]、CCM[78]、CSS[79]、LSS[80]、GSS[81]…」')
E('8113a95428','yinhongpeng「Torch7[94]、Cuda-ConvNet[95]、MatConvNet[96]、Pylearn2[97]、Theano[98]等」')
E('4d3d5284ce','yinhongpeng「线性回归[146]、均值漂移[147]、隐马尔科夫模型[148]、卡尔曼滤波[149]以及粒子滤波[150]等」')
for u in '2c924fbe37 4f0c55b756 385a9c03da'.split(): E(u,'luohuilan 引言「Sharma等人[9,10]…Chahal等人[11]…Kemal等人[12]…Zhao等人[13]…」')
E('80429ffb6b','luohuilan 第4节「PASCAL VOC2007[19]、PASCAL VOC2012[67]、MS COCO[46]、ImageNet[45]、Open Images[68]、LIVS[69]等」')
E('5f708ff66d','zhaoyangyang 第3节「马尔可夫模型[84]、CRF[25,85-88]、RNN[89]」','逐项列举模型，各带引用，CRF 一项五篇也属综述常态。')
