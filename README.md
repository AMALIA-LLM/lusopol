# lusopol

Research code and data on political preference behaviour of LLMs in Portuguese and English.

The prompt set covers seven topics in Portuguese politics and history — the Estado Novo,
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
