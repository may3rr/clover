J=lambda u,ev,note: L(u,'false_alarm','judge_error',ev,note,sev=False)
J('6c6e0cf612','raw/2010.11929 03_method.tex:54「feature maps of a CNN (LeCun et al., 1989)」','LeCun 1989 是 CNN 的出处，引用只修饰 CNN。')
for u in ['18d3a7ec2b','aa6c029035']:
    L(u,'false_alarm','partial_overstrict','raw/2010.11929 04_experiments.tex:11「ImageNet-21k with 21k classes and 14M images (Deng et al., 2009)」；Deng 2009 摘要「12 subtrees with 5247 synsets and 3.2 million images」','Deng 2009 是 ImageNet 的标准出处，数据集后来扩充到 21k 类 14M 图像；按论文发表时的规模判不支持过严。',sev=False)
J('3472062a47','raw/2006.11239 main.tex:298「a weighted variational bound that emphasizes different aspects of reconstruction compared to the standard variational bound (Gregor et al., 2016; Higgins et al., 2017)」','两篇共同支撑重加权变分界会改变重建侧重这一点，Gregor 2016 讨论压缩与重建的权衡；句中公式引用被渲染掉也不影响判断。')
J('08912a851d','raw/2006.11239 main.tex:649「self-attention blocks at the 16 × 16 resolution between the convolutional blocks (Chen et al., 2018b)」','PixelSNAIL 是卷积与自注意力交替的出处，具体层数是 DDPM 自己的配置。')
