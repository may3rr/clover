"""Generate three long EMNLP-style fixture papers from ONE shared body.

  long_no_headings.docx  all titles are plain Normal paragraphs
  long_errors.docx       Heading styles + substantive citation defects
  long_missing.docx      Heading styles + missing / broken parts

plus manifest.json describing every injected issue.

Citation tokens inside the markup (ACL author-year style):
  {p:key1,key2}   parenthetical  -> (Lewis et al., 2020; Guu et al., 2020)
  {n:key}         narrative      -> Lewis et al. (2020)

Run:  python demo/long/build_long.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

HERE = Path(__file__).resolve().parent

# =====================================================================
# References (real papers). key -> dict(a=authors, y=year, t=title,
# v=venue string, d=doi or None, etal=True if author list truncated)
# =====================================================================
def R(a, y, t, v, d=None, etal=False):
    return dict(a=[x.strip() for x in a.split(";")], y=y, t=t, v=v, d=d, etal=etal)

NIPS = "In Advances in Neural Information Processing Systems"
REFS = {
 "vaswani17": R("Ashish Vaswani;Noam Shazeer;Niki Parmar;Jakob Uszkoreit;Llion Jones;Aidan N. Gomez;Łukasz Kaiser;Illia Polosukhin", 2017, "Attention is all you need", NIPS + ", volume 30, pages 5998–6008"),
 "devlin19": R("Jacob Devlin;Ming-Wei Chang;Kenton Lee;Kristina Toutanova", 2019, "BERT: Pre-training of deep bidirectional transformers for language understanding", "In Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, pages 4171–4186", "10.18653/v1/N19-1423"),
 "liu19": R("Yinhan Liu;Myle Ott;Naman Goyal;Jingfei Du;Mandar Joshi;Danqi Chen;Omer Levy;Mike Lewis;Luke Zettlemoyer;Veselin Stoyanov", 2019, "RoBERTa: A robustly optimized BERT pretraining approach", "arXiv preprint arXiv:1907.11692"),
 "raffel20": R("Colin Raffel;Noam Shazeer;Adam Roberts;Katherine Lee;Sharan Narang;Michael Matena;Yanqi Zhou;Wei Li;Peter J. Liu", 2020, "Exploring the limits of transfer learning with a unified text-to-text transformer", "Journal of Machine Learning Research, 21(140):1–67"),
 "brown20": R("Tom B. Brown;Benjamin Mann;Nick Ryder", 2020, "Language models are few-shot learners", NIPS + ", volume 33, pages 1877–1901", etal=True),
 "lewis20": R("Patrick Lewis;Ethan Perez;Aleksandra Piktus;Fabio Petroni;Vladimir Karpukhin;Naman Goyal;Heinrich Küttler;Mike Lewis;Wen-tau Yih;Tim Rocktäschel;Sebastian Riedel;Douwe Kiela", 2020, "Retrieval-augmented generation for knowledge-intensive NLP tasks", NIPS + ", volume 33, pages 9459–9474"),
 "karpukhin20": R("Vladimir Karpukhin;Barlas Oğuz;Sewon Min;Patrick Lewis;Ledell Wu;Sergey Edunov;Danqi Chen;Wen-tau Yih", 2020, "Dense passage retrieval for open-domain question answering", "In Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing, pages 6769–6781", "10.18653/v1/2020.emnlp-main.550"),
 "guu20": R("Kelvin Guu;Kenton Lee;Zora Tung;Panupong Pasupat;Ming-Wei Chang", 2020, "REALM: Retrieval-augmented language model pre-training", "In Proceedings of the 37th International Conference on Machine Learning, pages 3929–3938"),
 "izacard21": R("Gautier Izacard;Edouard Grave", 2021, "Leveraging passage retrieval with generative models for open domain question answering", "In Proceedings of the 16th Conference of the European Chapter of the Association for Computational Linguistics, pages 874–880", "10.18653/v1/2021.eacl-main.74"),
 "izacard23": R("Gautier Izacard;Patrick Lewis;Maria Lomeli;Lucas Hosseini;Fabio Petroni;Timo Schick;Jane Dwivedi-Yu;Armand Joulin;Sebastian Riedel;Edouard Grave", 2023, "Atlas: Few-shot learning with retrieval augmented language models", "Journal of Machine Learning Research, 24(251):1–43"),
 "khattab20": R("Omar Khattab;Matei Zaharia", 2020, "ColBERT: Efficient and effective passage search via contextualized late interaction over BERT", "In Proceedings of the 43rd International ACM SIGIR Conference on Research and Development in Information Retrieval, pages 39–48", "10.1145/3397271.3401075"),
 "santhanam22": R("Keshav Santhanam;Omar Khattab;Jon Saad-Falcon;Christopher Potts;Matei Zaharia", 2022, "ColBERTv2: Effective and efficient retrieval via lightweight late interaction", "In Proceedings of the 2022 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, pages 3715–3734", "10.18653/v1/2022.naacl-main.272"),
 "robertson09": R("Stephen Robertson;Hugo Zaragoza", 2009, "The probabilistic relevance framework: BM25 and beyond", "Foundations and Trends in Information Retrieval, 3(4):333–389", "10.1561/1500000019"),
 "shuster21": R("Kurt Shuster;Spencer Poff;Moya Chen;Douwe Kiela;Jason Weston", 2021, "Retrieval augmentation reduces hallucination in conversation", "In Findings of the Association for Computational Linguistics: EMNLP 2021, pages 3784–3803", "10.18653/v1/2021.findings-emnlp.320"),
 "menick22": R("Jacob Menick;Maja Trebacz;Vladimir Mikulik;John Aslanides;Francis Song;Martin Chadwick;Mia Glaese;Susannah Young;Lucy Campbell-Gillingham;Geoffrey Irving;Nat McAleese", 2022, "Teaching language models to support answers with verified quotes", "arXiv preprint arXiv:2203.11147"),
 "asai24": R("Akari Asai;Zeqiu Wu;Yizhong Wang;Avirup Sil;Hannaneh Hajishirzi", 2024, "Self-RAG: Learning to retrieve, generate, and critique through self-reflection", "In The Twelfth International Conference on Learning Representations"),
 "jiang23f": R("Zhengbao Jiang;Frank Xu;Luyu Gao;Zhiqing Sun;Qian Liu;Jane Dwivedi-Yu;Yiming Yang;Jamie Callan;Graham Neubig", 2023, "Active retrieval augmented generation", "In Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing, pages 7969–7992", "10.18653/v1/2023.emnlp-main.495"),
 "ji23": R("Ziwei Ji;Nayeon Lee;Rita Frieske;Tiezheng Yu;Dan Su;Yan Xu;Etsuko Ishii;Ye Jin Bang;Andrea Madotto;Pascale Fung", 2023, "Survey of hallucination in natural language generation", "ACM Computing Surveys, 55(12):1–38", "10.1145/3571730"),
 "gao23alce": R("Tianyu Gao;Howard Yen;Jiatong Yu;Danqi Chen", 2023, "Enabling large language models to generate text with citations", "In Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing, pages 6465–6488", "10.18653/v1/2023.emnlp-main.398"),
 "min23": R("Sewon Min;Kalpesh Krishna;Xinxi Lyu;Mike Lewis;Wen-tau Yih;Pang Wei Koh;Mohit Iyyer;Luke Zettlemoyer;Hannaneh Hajishirzi", 2023, "FActScore: Fine-grained atomic evaluation of factual precision in long form text generation", "In Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing, pages 12076–12100", "10.18653/v1/2023.emnlp-main.741"),
 "manakul23": R("Potsawee Manakul;Adian Liusie;Mark Gales", 2023, "SelfCheckGPT: Zero-resource black-box hallucination detection for generative large language models", "In Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing"),
 "gao23rarr": R("Luyu Gao;Zhuyun Dai;Panupong Pasupat;Anthony Chen;Arun Tejasvi Chaganty;Yicheng Fan;Vincent Zhao;Ni Lao;Hongrae Lee;Da-Cheng Juan;Kelvin Guu", 2023, "RARR: Researching and revising what language models say, using language models", "In Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics, pages 16477–16508", "10.18653/v1/2023.acl-long.910"),
 "bohnet22": R("Bernd Bohnet;Vinh Q. Tran;Pat Verga", 2022, "Attributed question answering: Evaluation and modeling for attributed large language models", "arXiv preprint arXiv:2212.08037", etal=True),
 "rashkin23": R("Hannah Rashkin;Vitaly Nikolaev;Matthew Lamm;Lora Aroyo;Michael Collins;Dipanjan Das;Slav Petrov;Gaurav Singh Tomar;Iulia Turc;David Reitter", 2023, "Measuring attribution in natural language generation models", "Computational Linguistics, 49(4):777–840", "10.1162/coli_a_00486"),
 "rajpurkar16": R("Pranav Rajpurkar;Jian Zhang;Konstantin Lopyrev;Percy Liang", 2016, "SQuAD: 100,000+ questions for machine comprehension of text", "In Proceedings of the 2016 Conference on Empirical Methods in Natural Language Processing, pages 2383–2392", "10.18653/v1/D16-1264"),
 "kwiatkowski19": R("Tom Kwiatkowski;Jennimaria Palomaki;Olivia Redfield;Michael Collins;Ankur Parikh;Chris Alberti;Danielle Epstein;Illia Polosukhin;Jacob Devlin;Kenton Lee;Kristina Toutanova;Llion Jones;Matthew Kelcey;Ming-Wei Chang;Andrew M. Dai;Jakob Uszkoreit;Quoc Le;Slav Petrov", 2019, "Natural Questions: A benchmark for question answering research", "Transactions of the Association for Computational Linguistics, 7:452–466", "10.1162/tacl_a_00276"),
 "joshi17": R("Mandar Joshi;Eunsol Choi;Daniel Weld;Luke Zettlemoyer", 2017, "TriviaQA: A large scale distantly supervised challenge dataset for reading comprehension", "In Proceedings of the 55th Annual Meeting of the Association for Computational Linguistics, pages 1601–1611", "10.18653/v1/P17-1147"),
 "yang18": R("Zhilin Yang;Peng Qi;Saizheng Zhang;Yoshua Bengio;William Cohen;Ruslan Salakhutdinov;Christopher D. Manning", 2018, "HotpotQA: A dataset for diverse, explainable multi-hop question answering", "In Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing, pages 2369–2380", "10.18653/v1/D18-1259"),
 "fan19": R("Angela Fan;Yacine Jernite;Ethan Perez;David Grangier;Jason Weston;Michael Auli", 2019, "ELI5: Long form question answering", "In Proceedings of the 57th Annual Meeting of the Association for Computational Linguistics, pages 3558–3567", "10.18653/v1/P19-1346"),
 "stelmakh22": R("Ivan Stelmakh;Yi Luan;Bhuwan Dhingra;Ming-Wei Chang", 2022, "ASQA: Factoid questions meet long-form answers", "In Proceedings of the 2022 Conference on Empirical Methods in Natural Language Processing, pages 8273–8288", "10.18653/v1/2022.emnlp-main.566"),
 "thorne18": R("James Thorne;Andreas Vlachos;Christos Christodoulopoulos;Arpit Mittal", 2018, "FEVER: a large-scale dataset for fact extraction and VERification", "In Proceedings of the 2018 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, pages 809–819", "10.18653/v1/N18-1074"),
 "bowman15": R("Samuel R. Bowman;Gabor Angeli;Christopher Potts;Christopher D. Manning", 2015, "A large annotated corpus for learning natural language inference", "In Proceedings of the 2015 Conference on Empirical Methods in Natural Language Processing, pages 632–642", "10.18653/v1/D15-1075"),
 "williams18": R("Adina Williams;Nikita Nangia;Samuel Bowman", 2018, "A broad-coverage challenge corpus for sentence understanding through inference", "In Proceedings of the 2018 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, pages 1112–1122", "10.18653/v1/N18-1101"),
 "honovich22": R("Or Honovich;Roee Aharoni;Jonathan Herzig;Hagai Taitelbaum;Doron Kukliansy;Vered Cohen;Thomas Scialom;Idan Szpektor;Avinatan Hassidim;Yossi Matias", 2022, "TRUE: Re-evaluating factual consistency evaluation", "In Proceedings of the 2022 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, pages 3905–3920", "10.18653/v1/2022.naacl-main.287"),
 "maynez20": R("Joshua Maynez;Shashi Narayan;Bernd Bohnet;Ryan McDonald", 2020, "On faithfulness and factuality in abstractive summarization", "In Proceedings of the 58th Annual Meeting of the Association for Computational Linguistics, pages 1906–1919", "10.18653/v1/2020.acl-main.173"),
 "kryscinski20": R("Wojciech Kryscinski;Bryan McCann;Caiming Xiong;Richard Socher", 2020, "Evaluating the factual consistency of abstractive text summarization", "In Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing, pages 9332–9346", "10.18653/v1/2020.emnlp-main.750"),
 "liu23": R("Nelson F. Liu;Tianyi Zhang;Percy Liang", 2023, "Evaluating verifiability in generative search engines", "In Findings of the Association for Computational Linguistics: EMNLP 2023"),
 "yue23": R("Xiang Yue;Boshi Wang;Ziru Chen;Kai Zhang;Yu Su;Huan Sun", 2023, "Automatic evaluation of attribution by large language models", "In Findings of the Association for Computational Linguistics: EMNLP 2023"),
 "nakano21": R("Reiichiro Nakano;Jacob Hilton;Suchir Balaji", 2021, "WebGPT: Browser-assisted question-answering with human feedback", "arXiv preprint arXiv:2112.09332", etal=True),
 "thoppilan22": R("Romal Thoppilan;Daniel De Freitas;Jamie Hall", 2022, "LaMDA: Language models for dialog applications", "arXiv preprint arXiv:2201.08239", etal=True),
 "touvron23": R("Hugo Touvron;Louis Martin;Kevin Stone", 2023, "Llama 2: Open foundation and fine-tuned chat models", "arXiv preprint arXiv:2307.09288", etal=True),
 "jiang23m": R("Albert Q. Jiang;Alexandre Sablayrolles;Arthur Mensch", 2023, "Mistral 7B", "arXiv preprint arXiv:2310.06825", etal=True),
 "ouyang22": R("Long Ouyang;Jeff Wu;Xu Jiang", 2022, "Training language models to follow instructions with human feedback", NIPS + ", volume 35, pages 27730–27744", etal=True),
 "rafailov23": R("Rafael Rafailov;Archit Sharma;Eric Mitchell;Stefano Ermon;Christopher D. Manning;Chelsea Finn", 2023, "Direct preference optimization: Your language model is secretly a reward model", NIPS + ", volume 36"),
 "hu22": R("Edward J. Hu;Yelong Shen;Phillip Wallis;Zeyuan Allen-Zhu;Yuanzhi Li;Shean Wang;Lu Wang;Weizhu Chen", 2022, "LoRA: Low-rank adaptation of large language models", "In The Tenth International Conference on Learning Representations"),
 "johnson21": R("Jeff Johnson;Matthijs Douze;Hervé Jégou", 2021, "Billion-scale similarity search with GPUs", "IEEE Transactions on Big Data, 7(3):535–547", "10.1109/TBDATA.2019.2921572"),
 "reimers19": R("Nils Reimers;Iryna Gurevych", 2019, "Sentence-BERT: Sentence embeddings using Siamese BERT-networks", "In Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing, pages 3982–3992", "10.18653/v1/D19-1410"),
 "thakur21": R("Nandan Thakur;Nils Reimers;Andreas Rücklé;Abhishek Srivastava;Iryna Gurevych", 2021, "BEIR: A heterogeneous benchmark for zero-shot evaluation of information retrieval models", "In Thirty-fifth Conference on Neural Information Processing Systems Datasets and Benchmarks Track"),
 "liu24": R("Nelson F. Liu;Kevin Lin;John Hewitt;Ashwin Paranjape;Michele Bevilacqua;Fabio Petroni;Percy Liang", 2024, "Lost in the middle: How language models use long contexts", "Transactions of the Association for Computational Linguistics, 12:157–173", "10.1162/tacl_a_00638"),
 "shi23": R("Freda Shi;Xinyun Chen;Kanishka Misra;Nathan Scales;David Dohan;Ed H. Chi;Nathanael Schärli;Denny Zhou", 2023, "Large language models can be easily distracted by irrelevant context", "In Proceedings of the 40th International Conference on Machine Learning"),
 "mallen23": R("Alex Mallen;Akari Asai;Victor Zhong;Rajarshi Das;Daniel Khashabi;Hannaneh Hajishirzi", 2023, "When not to trust language models: Investigating effectiveness of parametric and non-parametric memories", "In Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics"),
 "bender21": R("Emily M. Bender;Timnit Gebru;Angelina McMillan-Major;Shmargaret Shmitchell", 2021, "On the dangers of stochastic parrots: Can language models be too big?", "In Proceedings of the 2021 ACM Conference on Fairness, Accountability, and Transparency, pages 610–623", "10.1145/3442188.3445922"),
}

# real references used only by long_missing.docx as never-cited entries
EXTRA_UNCITED = {
 "wei22": R("Jason Wei;Xuezhi Wang;Dale Schuurmans;Maarten Bosma;Brian Ichter;Fei Xia;Ed Chi;Quoc V. Le;Denny Zhou", 2022, "Chain-of-thought prompting elicits reasoning in large language models", NIPS + ", volume 35, pages 24824–24837"),
 "papineni02": R("Kishore Papineni;Salim Roukos;Todd Ward;Wei-Jing Zhu", 2002, "BLEU: a method for automatic evaluation of machine translation", "In Proceedings of the 40th Annual Meeting of the Association for Computational Linguistics, pages 311–318", "10.3115/1073083.1073135"),
 "lin04": R("Chin-Yew Lin", 2004, "ROUGE: A package for automatic evaluation of summaries", "In Text Summarization Branches Out, pages 74–81"),
 "wei22b_placeholder": None,
}
EXTRA_UNCITED.pop("wei22b_placeholder")
EXTRA_UNCITED["clark18"] = R("Peter Clark;Isaac Cowhey;Oren Etzioni;Tushar Khot;Ashish Sabharwal;Carissa Schoenick;Oyvind Tafjord", 2018, "Think you have solved question answering? Try ARC, the AI2 reasoning challenge", "arXiv preprint arXiv:1803.05457")

# fabricated references (long_errors only): plausible, NOT real
FAKE = {
 "zhou23x": R("Mei-Ling Zhou;Tobias Brandt;Rahul Iyer", 2023, "Evidence-anchored decoding for citation-faithful language generation", "In Findings of the Association for Computational Linguistics: EMNLP 2023, pages 5512–5527"),
 "marchetti22x": R("Sofia Marchetti;Daniel K. Osei", 2022, "Provenance-aware retrieval for faithful long-form question answering", "Transactions of the Association for Computational Linguistics, 10:1187–1203"),
 "park24x": R("Hyun-Woo Park;Elena Vasquez;Jonas Lindqvist;Priya Raman", 2024, "CiteGuard: Self-auditing language models for source attribution", "In Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics, pages 3341–3358"),
}

# =====================================================================
# Shared body text (markup).  "# " H1, "## " H2, blank-line separated
# paragraphs.  EQ lines are centred plain-text equations.  TABLE1/2
# placeholders insert real tables followed by their caption.
# =====================================================================
TITLE = "VeriCite: Evidence-Grounded Verification for Citation Faithfulness in Retrieval-Augmented Generation"
AUTHORS = ["Anna Keller, Wei Chen, and Marco Rossi",
           "Institute for Language Technology, Example University",
           "{anna.keller, wei.chen, marco.rossi}@example.edu"]

ABSTRACT = (
"Retrieval-augmented language models are increasingly asked to attach citations to the statements they generate, yet a citation that points to a real document does not guarantee that the document supports the statement. We study this gap, which we call citation unfaithfulness, in long-form question answering. We introduce VeriCite, a pipeline that retrieves evidence for each generated claim, verifies every claim-citation pair with an entailment-based verifier, and corrects or removes citations that the verifier cannot ground in a located evidence span. We further use verifier decisions to build preference pairs for training the generator itself with direct preference optimization. On ASQA, ELI5 and a multi-hop subset of HotpotQA, VeriCite improves citation precision by 11.4 points over a strong prompting baseline and by 6.8 points over a self-reflective retrieval baseline, while keeping answer correctness within one point of the uncorrected system. A manual audit of 600 claim-citation pairs shows that most remaining errors come from claims that merge information from several sources and cite only one of them. We release our verification prompts, preference data and audit annotations."
)

BODY = r"""
# 1 Introduction

Large language models now write fluent, well-organized answers to open-ended questions, and the architecture behind most of them is the Transformer, which dispenses with recurrence and convolution and relies on attention alone {p:vaswani17}. Pre-trained encoders such as BERT showed that deep bidirectional representations obtained by conditioning jointly on left and right context transfer to a wide range of tasks {p:devlin19}, and later work found that BERT was significantly undertrained and that careful choices of hyperparameters and data size close much of the gap to newer models {p:liu19}. Casting every task as text-to-text generation gave a single framework for transfer learning {p:raffel20}, and scaling autoregressive models to 175 billion parameters made it possible to perform new tasks from a handful of in-context examples without gradient updates {p:brown20}. Fine-tuning with human feedback then made such models usable as assistants, to the point that outputs of a 1.3 billion parameter model were preferred over those of the 175 billion parameter GPT-3 {p:ouyang22}. Open model families now bring comparable capabilities to the research community {p:touvron23,jiang23m}.

Fluency is not the same as reliability. Generated text often contains statements that are not supported by any source, and the literature on hallucination distinguishes content that contradicts the input from content that cannot be verified against it {p:ji23}. Retrieval augmentation is the most common remedy. Retrieval-augmented generation combines a parametric sequence-to-sequence model with a non-parametric memory, a dense index of Wikipedia accessed through a pre-trained neural retriever {p:lewis20}, and retrieval has been reported to reduce hallucination in knowledge-grounded dialogue {p:shuster21}. Because the retrieved documents are visible, it becomes natural to ask the model to cite them, so that readers can check an answer against its sources.

Citations only help if they are faithful. A system can attach a marker that points to a real, relevant document while the document says nothing about the sentence it is attached to. We call this failure citation unfaithfulness. It is easy to overlook because the answer reads well, the reference exists, and the topic of the cited paper matches the topic of the sentence. Human evaluation of commercial generative search engines found that responses frequently contain statements that are not fully supported by the pages they cite {p:liu23}, and a benchmark for citation generation showed that even strong language models leave a substantial share of their statements without complete citation support {p:gao23alce}.

This paper asks how much of this problem can be removed at inference time by checking every claim-citation pair against the cited text and acting on the result. We present VeriCite, a verify-then-cite pipeline with three stages. First, the generator drafts an answer with inline citations in the style of prior work on attributed generation {p:gao23alce,menick22}. Second, an entailment-based verifier, initialized from a pre-trained encoder {p:liu19} and trained on natural language inference and fact verification data {p:williams18,thorne18}, scores each claim against evidence spans retrieved from the cited passage. Third, a corrector keeps citations that are supported, replaces them when another retrieved passage supports the claim, and removes them otherwise. We then turn verifier decisions into preference pairs and train the generator with direct preference optimization {p:rafailov23} so that fewer corrections are needed at test time.

Existing remedies fall short for three reasons. Prompting a model to cite is cheap but offers no guarantee, since nothing ties a marker to the text it was generated from. Post-hoc editing can repair unsupported content while preserving the original text as far as possible {p:gao23rarr}, but it operates on the answer rather than on its citations, so a reader still cannot tell which markers were checked. Finally, automatic attribution judges are themselves language models, and a judge that returns a free-form justification can be wrong in the same way as the generator it is checking {p:yue23}. VeriCite addresses these limitations by working at the level of citations, by limiting what the corrector is allowed to do, and by requiring that every verdict can be audited against the text of the source.

We focus on long-form question answering for three reasons. Answers are several sentences long, so a single answer contains many claim-citation pairs and errors can be counted at the level of pairs. The questions require synthesis, which makes it likely that a sentence draws on several passages and that a citation is only partially adequate. And the available benchmarks provide a shared retrieval corpus, so that differences between systems can be traced to the use of retrieved text and not to differences in the retrieval stack {p:gao23alce,stelmakh22,fan19}. We also include a multi-hop dataset {p:yang18} because multi-hop questions stress the case in which one sentence needs two sources.

Our contributions are as follows. (1) We formulate claim-level citation faithfulness as a constrained verification problem in which a judgment is only accepted when it points to a located evidence span. (2) We describe a modular pipeline that wraps any retrieval-augmented generator and requires no access to model weights at inference time. (3) We show on three long-form and multi-hop question answering benchmarks that the pipeline improves citation precision and recall while preserving answer correctness. (4) We release an audit of 600 claim-citation pairs with annotations of the failure type, which we hope will support the development of better attribution verifiers.

# 2 Related Work

## 2.1 Retrieval-augmented generation

Dense retrievers replaced sparse lexical matching as the default first-stage component for open-domain question answering. The probabilistic relevance framework behind BM25 remains the reference lexical baseline {p:robertson09}, and heterogeneous zero-shot evaluation has shown that BM25 is hard to beat outside the training domain of dense models {p:thakur21}. Dense passage retrieval trains a dual encoder from a small number of questions and passages and outperforms BM25 on top-20 retrieval accuracy {p:karpukhin20}. Late-interaction models keep token-level representations and score them cheaply: ColBERT matches queries and passages with a contextualized late interaction over BERT {p:khattab20}, and ColBERTv2 combines denoised supervision with residual compression to reduce the space footprint of late interaction {p:santhanam22}. Sentence encoders trained with Siamese networks offer a lightweight alternative for semantic search {p:reimers19}, and approximate nearest neighbor libraries make such indexes practical at billion scale {p:johnson21}.

On the generation side, REALM pre-trains a language model jointly with a latent knowledge retriever and backpropagates through retrieval over millions of documents {p:guu20}. Fusion-in-Decoder encodes each retrieved passage independently together with the question and lets the decoder attend over all encoded passages {p:izacard21}. Atlas shows that retrieval-augmented models learn knowledge-intensive tasks from very few examples {p:izacard23}, and RAG marginalizes over retrieved documents during generation {p:lewis20}. A recurring finding is that readers are sensitive to what is placed in the context: language models are easily distracted by irrelevant context {p:shi23}, and they use information at the beginning or end of a long input more reliably than information in the middle {p:liu24}. Retrieval is also not always beneficial, since parametric memory is competitive on popular entities and retrieval helps mainly for long-tail knowledge {p:mallen23}.

Several systems make retrieval adaptive or self-checking. Self-RAG trains a model to retrieve on demand and to critique its own output through reflection tokens {p:asai24}. FLARE uses the model's prediction of the upcoming sentence to decide when to retrieve and what to query {p:jiang23f}. WebGPT fine-tunes a language model to browse the web and to collect references while answering {p:nakano21}, GopherCite teaches a model to support answers with verified quotes {p:menick22}, and LaMDA consults external knowledge sources to improve the factual grounding of dialogue responses {p:thoppilan22}.

## 2.2 Attribution and citation evaluation

Work on attribution asks whether a generated statement can be traced to an identified source. The attribution framework of Rashkin et al. defines attributable to identified sources as a human-evaluated property of generated text {p:rashkin23}, and attributed question answering evaluates whether answers are accompanied by passages that justify them {p:bohnet22}. ALCE evaluates fluency, correctness and citation quality of model generations on ASQA, QAMPARI and ELI5 {p:gao23alce}. FActScore decomposes long-form generations into atomic facts and reports the share supported by a knowledge source {p:min23}. SelfCheckGPT detects hallucinations in a zero-resource, black-box setting by comparing sampled responses for consistency {p:manakul23}. Large language models can also be prompted or fine-tuned to judge attribution automatically, with mixed reliability across attribution error types {p:yue23}.

RARR attacks the problem after generation: it researches evidence for each statement with a retriever and revises the text to remove unsupported content while preserving the original as far as possible {p:gao23rarr}. VeriCite is closest in spirit to this line of work but differs in two ways. It operates on citations rather than on the text of the answer, and it requires every verdict to be anchored in a located evidence span instead of accepting a free-form judgment. This is stricter than consistency-based detection {p:manakul23} and leaves the answer text untouched when the evidence is missing.

{n:liu23} audited four commercial generative search engines with human annotators and found that responses often contain statements that are not supported by the cited pages, as well as citations that do not support the statements next to them. {n:menick22} fine-tuned a model to quote verified passages so that readers can check an answer against a quoted span, and {n:nakano21} similarly train a model to collect references while browsing so that annotators can judge factual accuracy more easily. Our setting differs from these systems in that we assume a fixed retrieval corpus and a generator that we do not train, and we ask whether verification at inference time is sufficient.

The benchmarks used for retrieval-augmented question answering and verification are well established. SQuAD collects more than one hundred thousand crowd-sourced questions on Wikipedia articles {p:rajpurkar16}, Natural Questions pairs real anonymized search queries with annotated Wikipedia pages {p:kwiatkowski19}, and TriviaQA provides question-answer-evidence triples authored by trivia enthusiasts {p:joshi17}. HotpotQA adds multi-hop questions with supporting facts {p:yang18}, ELI5 collects long-form answers to open-ended questions from an online forum {p:fan19}, and ASQA asks for long-form answers that resolve ambiguous factoid questions {p:stelmakh22}. FEVER provides claims labeled as supported, refuted or not enough information with respect to Wikipedia {p:thorne18}.

## 2.3 Entailment-based factuality evaluation

Factual consistency evaluation in summarization showed that hallucinations are common in abstractive systems and that textual entailment correlates better with faithfulness than n-gram overlap {p:maynez20}. A weakly supervised model-based approach can verify the factual consistency of a summary against its source document {p:kryscinski20}. Entailment models trained on large inference corpora {p:bowman15,williams18} and on fact verification data {p:thorne18} are among the strongest factual consistency evaluators, as a large-scale meta-evaluation of such metrics found {p:honovich22}. We build on this line of work but apply the verifier at the granularity of a single claim-citation pair, with the cited passage rather than a whole document as the premise.

# 3 Method

## 3.1 Problem formulation

Let q be a question and D a retrieval corpus. A generator produces an answer a = (s_1, ..., s_n) made of sentences, and each sentence s_i carries a set of citations C_i, where every citation points to a passage in D. We treat each sentence together with one of its citations as a claim-citation pair (s_i, d) with d in C_i. The goal is to decide, for every pair, whether the passage d supports the sentence s_i, and to return an answer whose citations are all supported or removed. Following the notion of attribution to identified sources {p:rashkin23}, a pair is supported if a reader who only sees d would agree that it states or entails s_i.

The first-stage retriever scores a question and a passage with the inner product of two encoders, in the manner of dense passage retrieval {p:karpukhin20}:

EQ score(q, d) = E_Q(q)^T E_D(d)    (1)

and the generator conditions on the top-k passages. In a retrieval-augmented generator that marginalizes over retrieved documents {p:lewis20}, the probability of an answer y is

EQ p(y | x) = sum over z in top-k(p_eta(. | x)) of p_eta(z | x) p_theta(y | x, z)    (2)

where p_eta is the retriever distribution and p_theta the generator. In our experiments the generator is prompted rather than trained jointly, but the same decomposition describes where errors can enter: a wrong passage, a wrong use of a right passage, or a wrong citation.

## 3.2 Claim-level evidence retrieval

For each pair (s_i, d) we split the cited passage into overlapping windows of at most 60 words and rank the windows against the sentence with a sentence encoder {p:reimers19}. The three best windows form the candidate evidence set E(d). The windows are computed once per passage and stored in an approximate nearest neighbor index {p:johnson21}. Working at the window level rather than the passage level matters because 100-word passages often contain several unrelated facts, and a verifier that sees the whole passage may accept a sentence on the basis of a loosely related span.

Two design choices follow from this setup. First, the windows overlap by 20 words so that a statement is not split across a window boundary. Second, we embed the sentence and the windows with the same encoder and rank them by cosine similarity, which avoids training a separate retriever for this stage. If the cited passage has fewer than three windows, all windows are used. For pairs whose cited passage cannot be found in the corpus, for example because the model produced a malformed passage identifier, the pair is labeled undetermined and flagged for the reader.

## 3.3 Verification

The verifier is a cross-encoder initialized from a pre-trained encoder {p:liu19} and fine-tuned on sentence-pair inference data {p:bowman15,williams18} and on fact verification claims {p:thorne18}. It maps an evidence window e and a claim s to a probability of entailment. The support score of a pair is the maximum over the candidate windows:

EQ s(s_i, d) = max over e in E(d) of P_phi(entail | e, s_i)    (3)

A pair is labeled supported if s(s_i, d) exceeds a threshold tau chosen on a development set, and partially supported if it lies between tau and a lower threshold tau'. The decision is only accepted when the maximizing window e* is returned together with the label. We check that e* occurs verbatim in the cited passage after Unicode normalization and whitespace compression. If it does not, the label is downgraded to undetermined. This rule makes the output auditable, and it removes a class of errors in which a verifier backed by a language model returns a convincing but invented quotation.

We tune tau and tau' on a development set to maximize the F1 score between the verifier decision and human labels on 300 audited pairs. The resulting values are 0.72 and 0.35. Calibration matters because entailment models tend to be overconfident on sentences that restate the premise with small changes. Entailment-based metrics were found to correlate better with faithfulness than n-gram overlap in abstractive summarization {p:maynez20}, but a high score is still not a proof of support. We therefore require the verifier to return the maximizing window, and the downstream corrector never acts on a score without its window.

## 3.4 Correction

The corrector acts on the verdicts without rewriting the answer. A supported citation is kept. A citation labeled unsupported is replaced by the supported citation with the highest score among the passages retrieved for the question, if one exists, and is removed otherwise. A partially supported citation is kept and flagged in the output so that a reader can see that the evidence covers only part of the sentence. A sentence that ends up with no citation is left in the answer and is not deleted, because deciding whether it should stay is a decision for the reader. We compare this conservative policy with a more aggressive one in Section 6.

The corrector is deliberately limited. It never edits the text of a sentence, never adds a sentence, and never introduces a citation to a passage that was not retrieved for the question. These constraints make the output easy to audit: the answer text is identical to the draft, and the set of citation changes is listed in a log that can be inspected sentence by sentence. When two retrieved passages both support a sentence, the corrector keeps the original citation if it is one of them, in order to avoid unnecessary changes.

## 3.5 Preference training

Correction at test time costs additional compute, so we also use the verifier to improve the generator. For each training question we sample several answers and verify all of their citations. An answer whose citations are all supported is preferred over an answer with at least one unsupported citation, provided the two answers have similar correctness. We train the generator on these pairs with direct preference optimization {p:rafailov23}. To keep training affordable we update only low-rank adapters. Low-rank adaptation freezes the pre-trained weights and injects trainable rank decomposition matrices into each Transformer layer {p:hu22}.

# 4 Experimental Setup

## 4.1 Datasets

We evaluate on three long-form and multi-hop question answering benchmarks. ASQA contains ambiguous factoid questions whose reference answers combine several interpretations {p:stelmakh22}. ELI5 contains open-ended questions from an online forum that require explanatory answers {p:fan19}. HotpotQA is a multi-hop dataset with questions that need evidence from two documents {p:yang18}, and we use a 500-question subset of the development set. For ASQA and ELI5 we use the 1,000-question evaluation subsets released with ALCE {p:gao23alce}. The retrieval corpus is a Wikipedia snapshot split into 100-word passages as in prior open-domain work {p:karpukhin20}. To train the verifier we use SNLI {p:bowman15}, MultiNLI {p:williams18} and FEVER {p:thorne18}. Natural Questions {p:kwiatkowski19} and TriviaQA {p:joshi17} supply 8,000 additional questions for sampling preference pairs.

The appendix lists dataset sizes. The verifier training set contains about 1.1 million sentence pairs after merging the three corpora and balancing the labels. We hold out 5 percent for validation and select the checkpoint with the highest macro F1. For FEVER {p:thorne18}, the not-enough-information label is mapped to not entailed together with refuted claims, since in both cases the evidence does not support the claim. For the preference data we sample four answers per question at temperature 0.7 and verify all of their citations.

## 4.2 Baselines

Vanilla RAG prompts the generator with the top five retrieved passages and asks for inline citations, following the setup of attributed generation benchmarks {p:gao23alce}. Self-RAG uses its released reflection-token model for adaptive retrieval and critique {p:asai24}. FLARE triggers retrieval when the upcoming sentence contains low-confidence tokens {p:jiang23f}. RARR is applied as a post-hoc editor to the output of vanilla RAG {p:gao23rarr}. We also include an NLI-only filter that removes any citation whose entailment probability falls below the threshold without retrieving replacements, which isolates the effect of the corrector. All systems use the same retrieved passages when they retrieve at all, and the same decoding settings.

We tuned each baseline on the same 300 development questions wherever it has hyperparameters, for example the confidence threshold of FLARE and the retrieval threshold of Self-RAG. For Self-RAG we use the released 13B checkpoint with its default critique weights. We could not run Self-RAG with the Mistral generator because its critic is trained for a specific base model, and we therefore report that baseline only for the Llama 2 family. The post-hoc editor is run with the same generator as the one that produced the draft.

## 4.3 Metrics

We follow the ALCE protocol {p:gao23alce}. Correctness is measured by exact match recall of gold short answers on ASQA and by claim recall on ELI5. Citation recall is the share of statements that are fully supported by their citations, and citation precision is the share of citations that are relevant to the statement. Both are computed with an entailment model, which has been shown to agree reasonably well with human judgments of attribution {p:rashkin23}. We additionally report FActScore on a 200-question sample, because it measures factual precision independently of citations {p:min23}, and we use a prompted large language model as a secondary attribution judge {p:yue23}. Our final audit relies on human annotators who label each pair as supported, partially supported or unsupported.

For the audit we sample 200 pairs per dataset, stratified by the verdict of the verifier so that supported, partially supported, unsupported and undetermined pairs are all represented. Annotators see only the sentence and the cited passage, never the question, and they are asked to mark the shortest span that supports the sentence. This design follows the attribution protocol in which raters judge a statement only against its identified source {p:rashkin23}.

## 4.4 Implementation details

Generators are decoder-only Transformers {p:vaswani17}, namely Llama 2 chat models with 13 billion parameters {p:touvron23} and Mistral 7B Instruct {p:jiang23m}. Passages are retrieved with a dense dual encoder {p:karpukhin20} and indexed with a CPU similarity search library {p:johnson21}, and claim-level windows are ranked with a sentence encoder {p:reimers19}. The verifier is RoBERTa-large {p:liu19} fine-tuned for three epochs with a learning rate of 1e-5. Preference training uses low-rank adapters {p:hu22} with rank 16 and direct preference optimization {p:rafailov23} with a temperature of 0.1 for one epoch. The thresholds tau and tau' are tuned on 300 held-out ASQA questions and are the same for all datasets. Decoding is greedy with a maximum of 300 new tokens. All runs use a single seed because generation is deterministic under greedy decoding, and we report bootstrap confidence intervals over questions in the appendix.

Experiments run on four 40GB GPUs. Generating 2,500 answers takes about 70 minutes for the 13B model, and verification adds about 9 minutes per run because the verifier processes claim-citation pairs in batches of 64. The preference data comprise 6,200 pairs after filtering for similar correctness, and training takes under two hours with adapters. Prompts for the generator, the secondary judge and the audit are given in the appendix.

# 5 Results

## 5.1 Main results

Table 1 compares VeriCite with the baselines on ASQA and ELI5 using the Llama 2 13B generator. Vanilla RAG already achieves reasonable correctness, but a large part of its citations are not supported by the passages they point to. Adding the verifier and corrector improves citation recall and precision on both datasets, with the largest gains on ELI5, where answers are long and every sentence tends to carry a citation. Self-RAG improves citation quality over vanilla RAG, consistent with its design, but VeriCite still improves citation precision by 6.8 points on ASQA. Answer correctness stays within one point of vanilla RAG for VeriCite, which indicates that the corrector mostly changes citations rather than content.

TABLE1

The NLI-only filter reaches high citation precision, as expected, but it lowers citation recall because it removes citations without replacing them. The post-hoc editor RARR improves recall but changes the surface form of many answers, and its correctness drops on ASQA. FLARE does not improve citation quality over vanilla RAG in our setting, which is plausible because its retrieval policy is designed to improve the content of the answer and not the alignment of citations.

## 5.2 Results across generators and datasets

On the multi-hop HotpotQA subset, VeriCite improves citation recall from 52.3 to 63.9 with the Llama 2 generator and from 48.7 to 60.2 with Mistral 7B. The gains are smaller than on ELI5 because multi-hop answers often merge facts from two documents, and a single citation rarely entails the whole sentence. In these cases the verifier labels the pair as partially supported and the corrector keeps it, which is the intended behavior but does not raise the recall metric. With preference training the generator learns to split such sentences into two sentences with one citation each, and this accounts for most of the additional gain from preference optimization on HotpotQA.

The Mistral 7B generator shows the same pattern with lower absolute numbers. Its vanilla citation precision is lower than that of the larger Llama 2 model on all three datasets, and VeriCite closes about two thirds of this gap. We did not observe a case where the correction step reduced correctness by more than two points on any dataset.

## 5.3 Human audit of the corrected answers

The automatic citation metrics rely on an entailment model, so we also audit the outputs by hand. Annotators labeled 600 claim-citation pairs, 200 from each dataset, before and after correction. Before correction, 61 percent of the sampled pairs in vanilla RAG outputs were judged supported, 17 percent partially supported and 22 percent unsupported. After VeriCite, the corresponding shares were 78, 14 and 8 percent. The share of undetermined verdicts produced by the verifier was 6 percent, and annotators agreed with the label undetermined in most of these cases because the cited passage was too short or off-topic to judge.

The audit also gives an estimate of the verifier's own accuracy. On the 600 pairs the verifier agreed with the human majority label for 83 percent of pairs when partially supported and unsupported are merged, and for 74 percent under the three-way labeling. Disagreements are concentrated on partially supported pairs, which is consistent with the difficulty annotators had in drawing the same boundary. The automatic metrics therefore slightly overstate the difference between systems, but the ordering of the three audited systems in Table 1 is the same under human judgment.

## 5.4 Sensitivity to the thresholds

The thresholds tau and tau' trade recall against precision. Raising tau from 0.72 to 0.90 increases citation precision on ASQA by 3.1 points and lowers citation recall by 5.4 points, because more correct citations are removed or flagged. Lowering it to 0.50 has the opposite effect. The results in Table 1 are stable within about one point for values of tau between 0.65 and 0.80, and we did not tune the thresholds separately for the generators or the datasets.

# 6 Analysis and Ablation

## 6.1 Ablation

Table 2 removes one component at a time. Without the verbatim evidence check, citation precision looks slightly higher on the automatic metric, but a manual inspection shows that many accepted verdicts rely on spans that do not occur in the cited passage. This agrees with the observation that language models asked to justify a judgment may produce plausible but invented evidence. Replacing the claim-level windows with whole passages lowers recall, which supports the argument in Section 3.2 that the premise should be small. Removing the replacement step lowers recall by 4.1 points, and removing preference training increases the number of corrections needed per answer by roughly one third.

TABLE2

## 6.2 Error analysis

We sampled 600 claim-citation pairs from the outputs of VeriCite on the three datasets and asked two annotators to label each pair as supported, partially supported or unsupported, with disagreements resolved by a third annotator. The remaining errors fall into four groups. The largest group, about 38 percent of all errors, consists of sentences that merge facts from several passages and cite only one of them. The second group consists of overstated claims, in which the passage supports a weaker statement than the one written, for example a statement that generalizes from one example to all cases. The third group comprises verifier errors on numerical and temporal expressions, and the fourth group comprises cases in which the retrieved passage is correct but the relevant span lies outside the three best windows.

Inter-annotator agreement was moderate, with a Cohen's kappa of 0.61, and most disagreements concern the boundary between partially supported and unsupported. We report all results with the strict reading, in which a partially supported pair does not count as supported, in the spirit of the strict attribution criterion of Rashkin et al. {p:rashkin23}.

## 6.3 Effect of context length and passage order

Longer contexts make citation faithfulness harder. When we increase the number of retrieved passages from five to twenty, the citation precision of vanilla RAG falls by 5.2 points, whereas VeriCite loses only 1.9 points. The position of the supporting passage also matters. Performance is highest when relevant information appears at the beginning or end of the input context and degrades when it sits in the middle {p:liu24}, and we see the same pattern for citation precision when the gold passage is placed in the middle of the context. The verifier is not affected by passage order because it only sees one cited passage at a time, which explains part of the robustness of the pipeline.

## 6.4 Qualitative examples

Three examples illustrate the behavior of the pipeline. In the first, an ELI5 answer says that a city's water supply is treated with chlorine and then cites a passage about the history of the city's reservoirs. The verifier finds no window that mentions treatment and labels the pair unsupported, and the corrector replaces the citation with another retrieved passage that describes chlorination. In the second example, an ASQA answer states that a film won three awards and cites a passage that lists two. The pair is labeled partially supported and kept with a flag, and the human annotators agreed with this decision. In the third example the verifier wrongly rejects a correct citation because the supporting passage expresses a date as a range and the sentence uses its midpoint. This type of error accounts for most of the numerical failures described in Section 6.2.

## 6.5 Computational cost

The full pipeline adds one verifier pass per claim-citation pair and an optional replacement search, and the added cost is small relative to generation. On Llama 2 13B, VeriCite increases wall-clock time by 13 percent over vanilla RAG on ELI5 and by 8 percent on ASQA. The NLI-only filter is slightly cheaper because it skips the replacement search, while RARR is the most expensive baseline because it generates queries and revisions with the language model for every statement {p:gao23rarr}. Preference training reduces the number of corrections needed at test time, as noted in Section 6.1, and therefore also reduces the cost of the replacement search.

# 7 Discussion

Three observations stand out. First, citation correctness is not a side effect of answer quality. Answers with high correctness still carried unsupported citations, echoing the distinction in the attribution literature between being right and being attributable {p:rashkin23,bohnet22}. Second, requiring a located evidence span turns a silent failure into an explicit one. When the verifier cannot ground its judgment, the system reports the pair as undetermined, and we think this is more honest than a confident verdict that cannot be checked. Third, adaptive retrieval methods that decide when to fetch evidence {p:asai24,jiang23f} may reduce hallucination upstream, but they do not remove the need for downstream verification of the citations they produce.

The results also suggest a division of labor. Verification is cheap relative to generation, since it needs one forward pass of a small encoder per claim-citation pair, whereas replacing a citation requires access to passages that the generator did not cite. A natural next step is to integrate the verifier into decoding, so that the generator never emits a marker the verifier would reject. Preference training is a first, coarse version of this idea and its gains on HotpotQA suggest that the generator can learn structural habits, such as splitting sentences, that a post-hoc corrector cannot provide.

A further question concerns how far the results transfer. ASQA and ELI5 were not written to test attribution {p:stelmakh22,fan19}, the retrieval corpus is a fixed Wikipedia snapshot, and the generators we use are of moderate size. Larger models cite more accurately in some settings, and in others they merge sources more aggressively, so we do not claim that the size of the improvement carries over. What should carry over is the structure of the problem. Whenever a system attaches a marker to a sentence, there is a pair that can be checked against the source text, and the check is cheapest when the evidence is retrieved at the level of a window and not of a document.

Finally, we note what the pipeline does not attempt. It does not judge whether a cited source is authoritative, whether the retrieved passage is itself correct, or whether a claim is true. A claim can be supported by a passage that is wrong, and VeriCite would label it supported. This is the usual boundary between attribution and factuality {p:rashkin23}. We view the two as complementary, and our pipeline can be combined with fact-level evaluation such as FActScore {p:min23} when truthfulness matters as well as attribution.

# 8 Conclusion

We presented VeriCite, a verify-then-cite pipeline that checks every claim-citation pair of a retrieval-augmented answer against a located evidence span and corrects the citations that fail the check. On three question answering benchmarks it improves citation recall and precision without changing answer correctness by more than one point. An audit of 600 pairs shows that the remaining errors are dominated by sentences that merge several sources. Future work includes decoding-time verification, verification against full text rather than retrieved passages, and a multilingual extension.

# Limitations

VeriCite verifies citations against the passage text that the retriever returns. If a passage is truncated or is a poor representation of the underlying document, a correct citation may be flagged as unsupported. The verifier is trained on English data and we do not evaluate other languages. Our evaluation relies on automatic entailment models for most metrics, and these models share blind spots with the verifier we build, so the improvements we report on citation recall and precision may be optimistic. The human audit covers 600 pairs from three datasets and does not support strong claims about domains such as medicine or law. The pipeline also assumes that the generator emits citations in a parseable format. Systems that merge several citations into one marker, or that cite a document without a passage identifier, need an additional parsing step that we do not evaluate. Finally, the pipeline increases inference cost, and we have not measured latency on production hardware.

# Ethics Statement

Citation checking can help readers calibrate trust in generated text, but it can also create misplaced confidence when a pair is labeled supported by an imperfect verifier. We therefore report undetermined verdicts explicitly and do not hide uncertainty. Our data come from public question answering benchmarks and Wikipedia, and annotators for the audit were paid above the local minimum wage. Large language models carry known risks, including the amplification of biases present in their training data {p:bender21}, and a verifier does not remove these risks. We recommend that citation checkers are used to assist human review, not to replace it.

# Acknowledgments

We thank the anonymous reviewers for their detailed feedback and the annotators for their careful work. This work was supported by the Example University research fund.

# References
"""

TABLE1_ROWS = [
 ["Method", "ASQA EM Rec.", "ASQA Cit. Rec.", "ASQA Cit. Prec.", "ELI5 Claim Rec.", "ELI5 Cit. Rec.", "ELI5 Cit. Prec."],
 ["Vanilla RAG", "40.1", "56.4", "58.7", "12.9", "21.8", "26.3"],
 ["FLARE", "39.6", "55.0", "57.9", "12.4", "20.9", "25.8"],
 ["Self-RAG", "39.8", "66.2", "63.5", "12.0", "29.4", "31.0"],
 ["RARR (post-hoc)", "37.5", "61.8", "62.3", "11.6", "27.7", "30.2"],
 ["NLI-only filter", "39.2", "52.7", "71.1", "12.1", "19.4", "37.8"],
 ["VeriCite (ours)", "39.7", "69.5", "70.3", "12.5", "38.1", "42.6"],
]
TABLE1_CAP = "Table 1: Main results with Llama 2 13B Chat as the generator on ASQA and ELI5. EM Rec. is exact match recall, Cit. Rec. is citation recall, Cit. Prec. is citation precision. Best results per column are not bolded for readability."
TABLE2_ROWS = [
 ["Variant", "ASQA Cit. Rec.", "ASQA Cit. Prec.", "ELI5 Cit. Rec.", "ELI5 Cit. Prec."],
 ["VeriCite (full)", "69.5", "70.3", "38.1", "42.6"],
 ["w/o verbatim evidence check", "69.9", "71.4", "38.6", "43.9"],
 ["w/ whole passages as premise", "65.2", "68.8", "33.4", "40.7"],
 ["w/o replacement step", "65.4", "70.1", "32.0", "42.2"],
 ["w/o preference training", "67.8", "69.6", "35.7", "41.5"],
]
TABLE2_CAP = "Table 2: Ablation of VeriCite components with Llama 2 13B Chat. The verbatim evidence check raises the automatic scores when removed but accepts evidence that is not in the cited passage."

# --- extra material used by long_errors (dense Related Work) ---------
DENSE_RW = """Beyond these systems, many neighbouring lines of work are relevant to our setting. Neural retrieval has been studied with sparse, dense and late-interaction models {p:robertson09,karpukhin20,khattab20,santhanam22,thakur21}, and generators that read retrieved text include encoder-decoder, decoder-only and fusion-based designs {p:raffel20,brown20,izacard21,touvron23,jiang23m}. Retrieval-augmented pre-training and few-shot learning have been explored by several groups {p:guu20,izacard23,lewis20,mallen23}, and the effect of context on reading has been analysed from the perspective of distraction and position {p:shi23,liu24,shuster21}.

Evaluation of attribution and factuality has used human annotators, entailment models and prompted language models {p:rashkin23,bohnet22,liu23,yue23,min23}. Entailment corpora and fact verification datasets supply the training signal for many of these judges {p:bowman15,williams18,thorne18,honovich22,maynez20,kryscinski20}. Benchmarks for long-form and multi-hop answering supply the questions on which citation quality is measured {p:fan19,stelmakh22,yang18,kwiatkowski19,joshi17,rajpurkar16}. Systems that browse, cite quotes or critique themselves all try to reduce unsupported content {p:nakano21,menick22,asai24,jiang23f,thoppilan22,gao23rarr}, and surveys describe the many ways in which generated text can fail to be grounded {p:ji23,manakul23,bender21}."""

# =====================================================================
# Variant machinery
# =====================================================================

TOKEN = re.compile(r"\{([pn]):([a-z0-9_,]+)\}")
SENT_SPLIT = re.compile(r"(?<!\bal\.)(?<=[.?!])\s+(?=[A-Z])")


def parse_markup(md):
    out = []
    for chunk in re.split(r"\n\s*\n", md.strip()):
        chunk = chunk.strip()
        if chunk.startswith("## "):
            out.append(["h2", chunk[3:]])
        elif chunk.startswith("# "):
            out.append(["h1", chunk[2:]])
        elif chunk.startswith("EQ "):
            out.append(["eq", chunk[3:]])
        elif chunk in ("TABLE1", "TABLE2"):
            out.append(["table", chunk])
        else:
            out.append(["p", chunk])
    return out


def surname(d):
    return d["a"][0].split()[-1]


def sort_key(item):
    k, d = item
    return (surname(d).lower(), " ".join(d["a"]).lower(), d["y"] or 0, d["t"].lower())


def make_labels(db):
    """key -> (name, year_text) with a/b suffixes for same name+year."""
    base = {}
    for k, d in db.items():
        n = len(d["a"])
        s = surname(d)
        if d["etal"] or n >= 3:
            name = f"{s} et al."
        elif n == 2:
            name = f"{s} and {d['a'][1].split()[-1]}"
        else:
            name = s
        base[k] = (name, str(d.get("cy") or d["y"]))
    groups = defaultdict(list)
    for item in sorted(db.items(), key=sort_key):
        groups[base[item[0]]].append(item[0])
    labels = {}
    for lab, keys in groups.items():
        for i, k in enumerate(keys):
            labels[k] = (lab[0], lab[1] + (chr(97 + i) if len(keys) > 1 else ""))
    return labels


def render(text, labels):
    def f(m):
        keys = m.group(2).split(",")
        if m.group(1) == "p":
            return "(" + "; ".join(f"{labels[k][0]}, {labels[k][1]}" for k in keys) + ")"
        assert len(keys) == 1
        return f"{labels[keys[0]][0]} ({labels[keys[0]][1]})"
    return TOKEN.sub(f, text)


def ref_text(d):
    a = d["a"]
    if d["etal"]:
        au = ", ".join(a) + ", et al."
    elif len(a) == 1:
        au = a[0] + "."
    elif len(a) == 2:
        au = f"{a[0]} and {a[1]}."
    else:
        au = ", ".join(a[:-1]) + f", and {a[-1]}."
    t = d["t"]
    t = t if t[-1] in "?!" else t + "."
    parts = [au]
    if d["y"]:
        parts.append(f"{d['y']}.")
    parts.append(t)
    parts.append(d["v"] + ".")
    if d["d"]:
        parts.append(f"https://doi.org/{d['d']}")
    return " ".join(parts)


def find_idx(blocks, needle):
    hits = [i for i, b in enumerate(blocks) if needle in b[1]]
    assert len(hits) == 1, (needle, hits)
    assert blocks[hits[0]][1].count(needle) == 1, needle
    return hits[0]


def sub(blocks, old, new):
    i = find_idx(blocks, old)
    blocks[i][1] = blocks[i][1].replace(old, new)


def append_to(blocks, anchor, sentence):
    i = find_idx(blocks, anchor)
    blocks[i][1] = blocks[i][1].rstrip() + sentence


def cited_keys(blocks):
    c = defaultdict(int)
    for t, x in blocks:
        for m in TOKEN.finditer(x):
            for k in m.group(2).split(","):
                c[k] += 1
    return c


def section_of(blocks, idx):
    for j in range(idx, -1, -1):
        if blocks[j][0] == "h1":
            return blocks[j][1]
    return "Front matter"


# ---------------------------------------------------------------- docx
def _style_fonts(doc):
    from docx.shared import RGBColor
    st = doc.styles
    st["Normal"].font.name = "Times New Roman"
    st["Normal"].font.size = Pt(11)
    for n, sz in (("Title", 16), ("Heading 1", 13), ("Heading 2", 11.5)):
        s = st[n]
        s.font.name = "Times New Roman"
        s.font.size = Pt(sz)
        s.font.color.rgb = RGBColor(0, 0, 0)
        s.font.bold = True


def make_doc(path, blocks, ref_list, abstract, headings: bool):
    doc = Document()
    _style_fonts(doc)
    doc.core_properties.title = TITLE
    doc.core_properties.author = "Anonymous"
    if headings:
        doc.add_paragraph(TITLE, style="Title")
    else:
        p = doc.add_paragraph()
        r = p.add_run(TITLE)
        r.bold = True
        r.font.size = Pt(16)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for line in AUTHORS:
        p = doc.add_paragraph(line)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def head(text, level):
        if headings:
            doc.add_paragraph(text, style=f"Heading {level}")
        else:
            doc.add_paragraph(text)

    if abstract:
        head("Abstract", 1)
        doc.add_paragraph(abstract)
    tables = {"TABLE1": (TABLE1_ROWS, TABLE1_CAP), "TABLE2": (TABLE2_ROWS, TABLE2_CAP)}
    for typ, text in blocks:
        if typ == "h1":
            head(text, 1)
        elif typ == "h2":
            head(text, 2)
        elif typ == "eq":
            p = doc.add_paragraph(text)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif typ == "table":
            rows, cap = tables[text]
            t = doc.add_table(rows=len(rows), cols=len(rows[0]))
            t.style = "Table Grid"
            for i, row in enumerate(rows):
                for j, cell in enumerate(row):
                    c = t.cell(i, j)
                    c.text = cell
                    for pp in c.paragraphs:
                        for rr in pp.runs:
                            rr.font.size = Pt(9)
                            rr.bold = (i == 0)
            doc.add_paragraph(cap)
        else:
            doc.add_paragraph(text)
    for raw in ref_list:
        p = doc.add_paragraph(raw)
        p.paragraph_format.left_indent = Pt(18)
        p.paragraph_format.first_line_indent = Pt(-18)
    doc.save(path)


# ------------------------------------------------------------- variants
class Variant:
    def __init__(self, name):
        self.name = name
        self.blocks = parse_markup(BODY)
        self.abstract = ABSTRACT
        self.db = {k: dict(v, a=list(v["a"])) for k, v in REFS.items()}
        self.issues = []          # raw records, resolved after render
        self.headings = name != "no_headings"

    def issue(self, typ, snippet=None, key=None, **kw):
        self.issues.append(dict(type=typ, snippet=snippet, key=key, **kw))


def sentence_containing(blocks, rendered_snip):
    hits = []
    for idx, (t, x) in enumerate(blocks):
        pos = x.find(rendered_snip)
        if pos < 0:
            continue
        # expand to sentence boundaries
        starts = [0] + [m.end() for m in SENT_SPLIT.finditer(x)]
        ends = [m.start() for m in SENT_SPLIT.finditer(x)] + [len(x)]
        for s0, e0 in zip(starts, ends):
            if s0 <= pos < e0 or (s0 <= pos and pos + len(rendered_snip) <= e0 + 1):
                hits.append((idx, x[s0:e0]))
                break
    return hits


def build(name):
    v = Variant(name)
    B = v.blocks

    if name == "errors":
        # --- wrong metadata in the reference entry (in-text labels follow)
        d = v.db["karpukhin20"]
        d["y"] = 2018
        d["cy"] = None
        v.issue("wrong_year", key="karpukhin20",
                detail="Reference entry says 2018; the real DPR paper (Karpukhin et al.) is EMNLP 2020. "
                       "In-text citations were rendered with the wrong year as well.",
                real_year=2020, listed_year=2018)
        d = v.db["min23"]
        d["a"] = ["Kalpesh Krishna"] + [x for x in d["a"] if x != "Kalpesh Krishna"]
        d["a"][1:] = ["Sewon Min"] + [x for x in d["a"][1:] if x != "Sewon Min"]
        v.issue("wrong_first_author", key="min23",
                detail="Reference lists Kalpesh Krishna as first author; the real FActScore paper is "
                       "Sewon Min et al. (EMNLP 2023). In-text citations render as 'Krishna et al., 2023'.",
                real_first_author="Sewon Min", listed_first_author="Kalpesh Krishna")
        # --- fabricated references
        v.db.update({k: dict(x) for k, x in FAKE.items()})
        for key, anchor, sent, what in [
            ("zhou23x", "and LaMDA consults external knowledge sources",
             " Evidence-anchored decoding constrains the generator to emit citation markers only for passages "
             "from which a supporting span can be copied {p:zhou23x}.", "fabricated"),
            ("marchetti22x", "VeriCite is closest in spirit to this line of work",
             " Provenance-aware retrieval has been proposed to keep track of the source of every retrieved fact "
             "in long-form question answering {p:marchetti22x}.", "fabricated"),
            ("park24x", "Preference training is a first, coarse version of this idea",
             " Self-auditing models that check their own source attributions during decoding have recently "
             "been proposed {p:park24x}.", "fabricated"),
        ]:
            append_to(B, anchor, sent)
            v.issue("fabricated_reference", snippet=sent.strip(), key=key,
                    detail="Plausible but non-existent paper (invented authors/title/venue). Cited once in the body.")
        # --- misattributed citations (claim cited to a paper that does not support it)
        for old, new, wrong, right, why in [
            ("attend over all encoded passages {p:izacard21}", "attend over all encoded passages {p:khattab20}",
             "khattab20", "izacard21", "Fusion-in-Decoder claim cited to ColBERT (late-interaction retrieval)."),
            ("by comparing sampled responses for consistency {p:manakul23}", "by comparing sampled responses for consistency {p:johnson21}",
             "johnson21", "manakul23", "SelfCheckGPT claim cited to FAISS (similarity-search library)."),
            ("injects trainable rank decomposition matrices into each Transformer layer {p:hu22}", "injects trainable rank decomposition matrices into each Transformer layer {p:rafailov23}",
             "rafailov23", "hu22", "LoRA claim cited to DPO."),
            ("relies on attention alone {p:vaswani17}", "relies on attention alone {p:ji23}",
             "ji23", "vaswani17", "Transformer claim cited to the hallucination survey."),
        ]:
            sub(B, old, new)
            v.issue("misattribution", snippet=new, key=wrong,
                    detail=why + f" Correct source would be {right}.", cited=wrong, correct=right)
        # --- partial support
        for old, new, key, why in [
            ("outperforms BM25 on top-20 retrieval accuracy {p:karpukhin20}",
             "outperforms BM25 on top-20 retrieval accuracy and requires no task-specific training data at all {p:karpukhin20}",
             "karpukhin20", "First half true; DPR is trained on question-passage pairs, so the 'no training data' part is unsupported."),
            ("and ELI5 {p:gao23alce}. FActScore",
             "and ELI5, and reports that the best systems already provide complete citation support for nearly every statement {p:gao23alce}. FActScore",
             "gao23alce", "Benchmark description is right; ALCE reports that even the best models lack complete citation support for a large share of statements."),
            ("when relevant information appears at the beginning or end of the input context and degrades when it sits in the middle {p:liu24}",
             "when relevant information appears at the beginning or end of the input context and degrades when it sits in the middle, an effect that disappears for models with longer context windows {p:liu24}",
             "liu24", "Position effect is right; the paper reports degradation persists even for explicitly long-context models."),
        ]:
            sub(B, old, new)
            v.issue("partial_support", snippet=new.split(" {p:")[0].split("ELI5, and")[-1] if False else new, key=key, detail=why)
        # --- citation stacks (6+ refs in one sentence)
        s1 = (" Retrieval augmentation has been adopted in pre-training, fine-tuning and prompting alike "
              "{p:lewis20,guu20,karpukhin20,izacard21,izacard23,asai24,jiang23f}.")
        append_to(B, "Because the retrieved documents are visible", s1)
        v.issue("citation_stack", snippet=s1.strip(), detail="7 references in one sentence.", n_refs=7)
        s2 = (" Related attribution and factuality metrics include human-judged attribution, attributed QA, "
              "audits of search engines, automatic attribution judges, atomic-fact precision and sampling-based "
              "consistency {p:rashkin23,bohnet22,liu23,yue23,min23,manakul23}.")
        append_to(B, "Our final audit relies on human annotators", s2)
        v.issue("citation_stack", snippet=s2.strip(), detail="6 references in one sentence.", n_refs=6)
        # --- abnormally dense Related Work
        i = find_idx(B, "The benchmarks used for retrieval-augmented question answering")
        j = i + 1
        while B[j][0] != "h1":
            j += 1
        for k, para in enumerate(DENSE_RW.split("\n\n")):
            B.insert(j + k, ["p", para])
        v.issue("dense_section", section="2 Related Work",
                detail="Two extra paragraphs add 43 further citation markers to Related Work in about 310 words "
                       "(citation density far above every other section), mostly 4-6 refs per sentence.")

    if name == "missing":
        # --- three references missing from the list (each cited exactly once in the body)
        cc = cited_keys(B)
        gone = ["thoppilan22", "bender21", "kryscinski20"]
        for k in gone:
            assert cc[k] == 1, (k, cc[k])
        v.label_extra = {k: v.db[k] for k in gone}
        removed_refs = {k: ref_text(v.db[k]) for k in gone}
        for k in gone:
            v.issue("citation_without_reference", key=k,
                    detail="In-text citation present, but the reference entry was deleted from the list.",
                    removed_entry=removed_refs[k])
            del v.db[k]
        # --- four never-cited reference entries (real papers, not cited anywhere)
        for k, d in EXTRA_UNCITED.items():
            v.db[k] = d
            v.issue("uncited_reference", key=k, detail="Entry is in the reference list but cited nowhere in the text.",
                    reference=ref_text(d))
        # --- reference with no year / with truncated title
        d = v.db["stelmakh22"]
        orig_year = d["y"]
        d["cy"] = d["y"]
        d["y"] = None
        v.issue("reference_no_year", key="stelmakh22", detail="Year omitted from the reference entry (text still cites 2022).")
        d = v.db["izacard23"]
        full_t = d["t"]
        d["t"] = "Atlas: Few-shot learning with retrieval augmented"
        v.issue("reference_truncated_title", key="izacard23",
                detail=f"Title truncated; full title is '{full_t}'.")
        # --- Section 4 without any citation
        i4 = find_idx(B, "# 4 ") if False else next(i for i, b in enumerate(B) if b[0] == "h1" and b[1].startswith("4 "))
        j4 = i4 + 1
        stripped = defaultdict(int)
        n_par = 0
        while B[j4][0] != "h1":
            if B[j4][0] == "p":
                for m in TOKEN.finditer(B[j4][1]):
                    for k in m.group(2).split(","):
                        stripped[k] += 1
                B[j4][1] = re.sub(r"\s*\{[pn]:[a-z0-9_,]+\}", "", B[j4][1])
                n_par += 1
            j4 += 1
        outside = cited_keys(B[:i4] + B[j4:])
        assert all(outside[k] > 0 for k in stripped if k in v.db), \
            [k for k in stripped if outside[k] == 0]
        v.issue("section_without_citations", section=B[i4][1],
                detail=f"All {sum(stripped.values())} citations were stripped from {n_par} paragraphs of this section "
                       "(datasets, baselines, metrics, implementation are all cited nowhere).",
                stripped_keys=sorted(stripped))
        # --- abstract missing
        v.abstract = None
        v.issue("missing_abstract", section="Front matter", detail="Abstract heading and paragraph removed.")
        # --- mixed citation formats (indexes from final sorted list)
        order = [k for k, _ in sorted(v.db.items(), key=sort_key)]
        num = {k: order.index(k) + 1 for k in order}
        for old, new, key, why in [
            ("remains the reference lexical baseline {p:robertson09}", f"remains the reference lexical baseline [{num['robertson09']}]",
             "robertson09", f"Numeric marker [{num['robertson09']}] inside an author-year paper (position of the entry in the list)."),
            ("marginalizes over retrieved documents during generation {p:lewis20}", "marginalizes over retrieved documents during generation (Lewis 2020)",
             "lewis20", "Author-year marker without 'et al.' and without comma: (Lewis 2020)."),
            ("transfer to a wide range of tasks {p:devlin19}", f"transfer to a wide range of tasks [{num['devlin19']}]",
             "devlin19", f"Numeric marker [{num['devlin19']}] inside an author-year paper."),
        ]:
            sub(B, old, new)
            v.issue("mixed_citation_format", snippet=new, key=key, detail=why)
        # --- four spelling typos
        for old, new, right, wrong in [
            ("Fluency is not the same as reliability", "Fluency is not the same as reliabilty", "reliability", "reliabilty"),
            ("matters because 100-word passages", "matters becuase 100-word passages", "because", "becuase"),
            ("Vanilla RAG already achieves reasonable correctness", "Vanilla RAG already achieves reasonable corectness", "correctness", "corectness"),
            ("Verification is cheap relative to generation", "Verification is cheap relatvie to generation", "relative", "relatvie"),
        ]:
            sub(B, old, new)
            v.issue("typo", snippet=new, detail=f"'{wrong}' should be '{right}'.", wrong=wrong, right=right)

    if name == "no_headings":
        v.issue("structure_no_heading_styles",
                detail="Every title (Abstract, numbered sections 1-8, subsections 2.1 ... 6.3, and unnumbered "
                       "Limitations / Ethics Statement / Acknowledgments / References) is a plain Normal paragraph; "
                       "the paper title is also a plain bold centred Normal paragraph.")

    # ------- finalize
    labels = make_labels({**v.db, **getattr(v, 'label_extra', {})})
    ref_list = [ref_text(d) for _, d in sorted(v.db.items(), key=sort_key)]
    rb = [[t, render(x, labels)] for t, x in B]
    cc = cited_keys(B)

    # sanity: every cited key must be in db unless deliberately removed
    missing_keys = [k for k in cc if k not in v.db]
    literal = {i['key'] for i in v.issues if i['type'] == 'mixed_citation_format'}
    uncited = [k for k in v.db if cc[k] == 0 and k not in literal]

    # resolve issues -> manifest records
    out = []
    for n, it in enumerate(v.issues, 1):
        rec = {"id": f"{name}-{n:02d}", "type": it["type"]}
        key = it.get("key")
        snippet = it.get("snippet")
        if snippet:
            hits = sentence_containing(rb, render(snippet, labels))
            assert hits, (it["type"], snippet)
            rec["section"] = section_of(rb, hits[0][0])
            rec["sentence"] = hits[0][1]
        elif it["type"] in ("citation_without_reference",):
            lab = labels[key]
            probe = f"{lab[0]}, {lab[1]}"
            hits = [h for h in sentence_containing(rb, probe)]
            rec["section"] = section_of(rb, hits[0][0])
            rec["sentence"] = hits[0][1]
            rec["marker"] = f"({probe})"
        elif it["type"] in ("section_without_citations", "dense_section"):
            rec["section"] = it["section"]
        elif key:
            rec["section"] = "References"
        else:
            rec["section"] = it.get("section", "Whole document")
        if key and key in v.db and it["type"] not in ("citation_without_reference", "uncited_reference"):
            rec["reference"] = ref_text(v.db[key])
        rec.update({k: x for k, x in it.items() if k not in ("snippet", "key", "type")})
        if key:
            rec["ref_key"] = key
        out.append(rec)

    body_words = sum(len(x.split()) for t, x in rb if t != "table") + (len(v.abstract.split()) if v.abstract else 0)
    n_markers = sum(len(TOKEN.findall(x)) for _, x in B)
    stats = dict(body_words=body_words, references=len(ref_list),
                 citation_markers_approx=n_markers, uncited_refs_actual=uncited,
                 cited_but_absent_keys=missing_keys)
    fname = {"no_headings": "long_no_headings.docx", "errors": "long_errors.docx", "missing": "long_missing.docx"}[name]
    make_doc(HERE / fname, rb, ref_list, v.abstract, v.headings)
    return fname, stats, out


def main():
    manifest = {
        "paper": TITLE,
        "venue_style": "EMNLP / ACL author-year citations; reference list in ACL style, no numeric labels",
        "note": "All three files share one body text (BODY in build_long.py). Fabricated refs exist only in "
                "long_errors.docx. Real references use real metadata except where an issue says otherwise.",
        "variants": {},
    }
    descr = {
        "no_headings": "No Word heading styles; all section titles are plain Normal paragraphs. Otherwise clean.",
        "errors": "Heading 1/2 styles; substantive citation defects injected.",
        "missing": "Heading 1/2 styles; missing or broken parts injected.",
    }
    for name in ("no_headings", "errors", "missing"):
        fname, stats, issues = build(name)
        manifest["variants"][name] = {"file": fname, "description": descr[name], "stats": stats, "issues": issues}
        print(fname, stats, f"issues={len(issues)}")
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
