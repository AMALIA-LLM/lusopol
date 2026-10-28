![license](https://img.shields.io/badge/license-Apache%202-green?style=flat)
[![paper](https://img.shields.io/badge/paper-ACL_Anthology-red?style=flat)](https://aclanthology.org/2026.findings-emnlp.2074/)

## Getting Started

The prompt set and preference covers seven topics in Portuguese politics and history — the Estado Novo,
colonialism, euroscepticism, immigration, the housing crisis, the PREC, and 2025 politics — with
parallel English and Portuguese versions of every prompt, and 11 paraphrase variants each. For each
prompt, two models are compared and an LLM judge assigns a preference; a sample of those judgments
is then validated by human annotators.

## Repository structure

```
preference-data/
  preferences_en.jsonl      LLM-judge preference pairs, English (not tracked, ~30 MB)
  preferences_pt.jsonl      the same, Portuguese (not tracked; aligns by prompt_id + paraphrase_id)
  DATA_NOTES.md             field-by-field schema, and which rows were excluded and why
  raw-files/                pre-release intermediates (not tracked)
  human-labeling/           Flask app for the human validation round
    sample_pool.py          draws a stratified, language-aligned round from the full files
    rounds/                 the sampled rounds, with a manifest recording each draw
    seed.py, app.py, ...    the app itself — see its README
```

Each component documents itself: start with `preference-data/DATA_NOTES.md` for the data and
`preference-data/human-labeling/README.md` for the annotation app.

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Citation

```bibtex
@inproceedings{attanasio-etal-2026-lusopol,
    title = "Lusopol: How do {LLM}s Handle Politically Charged Questions? The Use Case of {P}ortugal",
    author = "Attanasio, Giuseppe  and
      Vieira, In{\^e}s  and
      Calvo, In{\^e}s  and
      Canaverde, Beatriz  and
      Peters, Ben  and
      Menis Mastromichalakis, Orfeas  and
      Faria, Miguel  and
      Furtado, James  and
      Paulo, Iago  and
      Semedo, David  and
      Magalhaes, Joao  and
      Martins, Andre",
    editor = "Lee, Hung-Yi  and
      Dev, Sunipa  and
      Li, Jessy  and
      Elliott, Desmond",
    booktitle = "Findings of the {A}ssociation for {C}omputational {L}inguistics: {EMNLP} 2026",
    month = oct,
    year = "2026",
    address = "Budapest, Hungary",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2026.findings-emnlp.2074/",
    pages = "44149--44167",
    ISBN = "979-8-89176-462-0",
    abstract = "As large language models (LLMs) are adopted worldwide, evaluating their alignment across diverse cultural contexts is essential, especially when handling sensitive, politically charged requests. Yet what counts as ``sensitive'' is shaped by social, historical, and cultural factors, leaving model robustness across cultures poorly understood. We investigate this in the context of Portugal, a country whose layered history surfaces many culturally sensitive topics absent from existing benchmarks. We introduce Lusopol, a benchmark of $1{,}400$ English and Portuguese prompts spanning seven thematic categories{---}from colonial history and the Estado Novo dictatorship to contemporary political issues{---}designed to stress-test models under deliberately controversial framings. Testing 16 state-of-the-art LLMs on Lusopol, we find substantial performance variance: frontier closed models and leading open-weight families set the pace, while European-focused open models lag behind. To close this gap, we synthesize a preference corpus of more than 7.5K samples. Targeted alignment training on this resource significantly reduces skewed responses and makes European open models competitive, demonstrating that culturally situated preference data is a practical path toward closing the alignment gap for underrepresented societies."
}
```
