R='raw/1512.03385 residual_v1_arxiv_release.tex'; F='en_papers/resnet/ref/'
VGG=F+'Very Deep Convolutional Networks for Large-Scale Image Recognition_Simonyan.pdf'
L('ae7d3bb2bc','false_alarm','judge_error',R+':77「Deep convolutional neural networks [22,21]」；[22] LeCun et al. 1989 卷积网络开山之作','引 LeNet 与 AlexNet 作为深度卷积网络的出处是标准写法。',sev=False)
L('165e92bbc2','false_alarm','judge_error',R+':870「8 anchors are randomly sampled for each image, where the sampled positive and negative anchors have a ratio of 1:1 [32]」；Faster R-CNN p?「we randomly sample 256 anchors ... ratio of up to 1:1」','8 是 ResNet 自己的设置，[32] 支持的是正负样本 1:1 的采样做法。',sel='被引文献不支持',sev=False)
L('165e92bbc2','false_alarm','judge_error','同上','同上。',sel='label:unsupported',sev=False)
L('165e92bbc2','true_issue','real_grammar',R+':870「To avoid negative samples being dominate」','原文语法错误，应为 dominating 或 dominant。',sel='typo')
L('6bda2c298f','false_alarm','retrieval_miss',VGG+' p10「considers only the bounding box prediction for the ground truth class (to factor out the classification errors)」','VGG 定位实验确有用真实类别的设定，片段检索没取到附录。',sev=False)
L('c77120984d','false_alarm','retrieval_miss',VGG+' p11 Table 8「GT class localisation error ... all PCR 33.1」','33.1 出自 VGG 定位表，模型看的是分类表 Table 7。',sev=False)
for u in ['20edc29cfb','47716f9ac3']:
    L(u,'false_alarm','retrieval_miss',F+'Neural networks for pattern recognition_Bishop.pdf 与 Pattern Recognition and Neural Networks_Ripley.pdf 均只有 4 页封面和目录；Bishop 1995、Ripley 1996 与 Venables & Ripley 的 nnet 均讨论 skip-layer connections','教科书全文不在本地，模型只看到封面就判不支持；三本书是 ResNet 引 shortcut 前史的经典出处。',sev=False)
L('7e0a748ed4','false_alarm','retrieval_miss',F+' 本地无 Venables & Ripley 全文，只取到版权页；MASS 的 nnet 函数提供 skip-layer 线性连接','模型拿版权页做判断。',sev=False)
L('fe2f700697','false_alarm','retrieval_miss','Jégou et al. TPAMI 2011 IVFADC 一节对残差向量编码，并报告优于直接编码；本地只用了摘要','只看摘要，摘要只讲乘积量化。',sev=False)
for u in ['b689f53751','54b62ddbff']:
    L(u,'false_alarm','judge_error',R+':140「“highway networks” [42,43] present shortcut connections with gating functions [15]」；LSTM 摘要「Multiplicative gate units learn to open and close access」','[15] 是门控函数的出处，句法上只修饰 gating functions。',sev=False)
L('bc2f4d4c6b','false_alarm','judge_error',R+':270「shorter side randomly sampled in [256, 480] for scale augmentation [41]」；'+VGG+' p4「we used Smin = 256 and Smax = 512」','引用指尺度增强方法本身，区间是 ResNet 自己的设置。',sev=False)
L('cab6db7127','false_alarm','retrieval_miss',F+'Microsoft COCO p7「we have limited the 2014 release to a subset of 80 categories」','原文明确 2014 发布版为 80 类，模型取了 91 类那句。',sev=False)
L('011660bae5','false_alarm','judge_error',R+':795「10 points higher than the previous state-of-the-art result [6]」','[6] 指明被比较的此前最优结果，10 个点是 ResNet 自己的结果差。',sev=False)
L('baa5d0ae87','false_alarm','retrieval_miss',VGG+' p11 Table 8 列名「GT class localisation error」','VGG 表格正是这一列。',sev=False)
L('07fcbf0231','false_alarm','retrieval_miss',VGG+' p10「is class-specific (per-class regression, PCR)」','VGG 附录明确定义 PCR。',sev=False)
