L('1b26779a11','false_alarm','parse_error','zhaoyangyang PDF p13 公式(19)「q=γ^{t-t0} r_t + γ^{t[1]-t[0]} max ...」，[0] 是公式下标','公式中的下标被当作引用标记。',sev=False)
for u,n,ev in [('9f0b072eda',140,'表5「[140−141] Detection Test」'),('8d1d949d6a',141,'表5「[140−141]」'),('6c6a300354',209,'表6「1 [209−210] Visual Tracker」'),('8947a33539',210,'表6「[209−210]」')]:
    L(u,'false_alarm','conversion_artifact','zh_pdfs/aas_yinhongpeng_2016.pdf '+ev+'；docx 表格单元格中为「140−141」或「209−210]」，方括号丢失','原刊在表格中以范围引用，转换后括号丢失，标记识别失败。')
for u,n,ev in [('8397e91275',23,'「背景初始化(Background initialization)[23] 指对背景模型的初始化工作」'),('129b1d04c7',24,'「Wang等[24] 对初始化背景模型Median 进行改进」'),('3cea771895',25,'「Colombari 等[25] 提出了基于块的背景初始化方法」')]:
    L(u,'false_alarm','conversion_artifact','zh_pdfs/aas_yinhongpeng_2016.pdf '+ev+'；docx 中这一段正文缺失','原刊正文引用了这条文献，转换生成的 docx 漏掉了整段。')
L('2c0a7f7381','true_issue','real_duplicate_ref','软件学报官网全文参考文献 [71] 与 [122] 均为 Bahdanau D, Cho K, Bengio Y, et al. Neural machine translation by jointly learning to align and translate, ICLR 2015','原刊参考文献重复。')
L('4d879c9232','true_issue','real_duplicate_ref','软件学报官网全文参考文献 [6] 与 [89] 均为 Berant J et al. Semantic parsing on freebase from question-answer pairs, EMNLP 2013','原刊参考文献重复。')
L('191b5ec20f','false_alarm','other','r9 为 Findings of the 2014 WMT（W14-3302），r10 为 Findings of the 2015 WMT（W15-3001）','两条是不同年份的评测报告，去重规则忽略了题名中的年份。',sub='dedup_ignores_digits')
L('09d9f5afde','true_issue','real_duplicate_ref','raw/2005.14165 main.bbl:819 ZSW+19a ziegler2019finetuning 与 :824 ZSW+19b Ziegler2019FineTuningLM 为同一篇 arXiv:1909.08593','GPT-3 原文 bib 里同一文献用了两个键。')
L('89ca3b1c02','true_issue','real_duplicate_ref','raw/2010.11929 main.bbl:308 与 :315 两条 Axial-DeepLab，分别为 ECCV 2020 与 arXiv:2003.07853','ViT 原文同一工作的会议版和预印本各列一条。')
