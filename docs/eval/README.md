# Supply chain evaluation reports

Reports from `python -m eval.supply_chain_eval` (run from `backend/`; how it works: [docs/supply-chain-graph.md](../supply-chain-graph.md#evaluation-set-133)). Each run saves `<date>-<label>.md` (read this), `.json` (the figures) and `.raw.json` (everything the run produced, for `--rescore`). A `--runs N` set adds `<date>-<label>.md` / `.json` with the mean, lowest and highest of each figure, and each run's own report as `-run<i>`.

## Reading a report

- **Found** counts known relationships matched by an output link. **Wrong links** match nothing in the truth file: each one is a wrong link or a true relationship the file lacks.
- The truth file is **frozen** (28 Oct 2026: 90 known relationships, 35 optional, 27 traps). True relationships a run shows that the file lacks are listed in the write-up as *possibly missing from truth*. They are not added to the file unless the user decides to, because adding entries after seeing the output flatters recall. The 18 entries marked `late` (7 known, 11 optional) were added from reviewing runs before the freeze.
- Costs are in US dollars. "Cost (read afresh)" counts cached Reader answers at what they cost when first read.

## Known limits

- **Verifier variance.** The Verifier (claude-sonnet-5-5, effort medium) gives different verdicts on the same claims from run to run. Wrong links ranged **0 to 4** between runs of one setting, for example 4, 0 and 3 in the three runs of [2026-10-28-after-341-verifier](2026-10-28-after-341-verifier.md). A difference of one or two wrong links between two settings is within this noise. This is not fixed for now.
- **Reader variance.** The Reader varies more: 31 to 42 found in single runs of one setting before #341. Reader answers are cached, so a change that doesn't touch the Reader is measured on the same Reader output, and a Reader prompt change is measured with `--fresh --runs 3`.
- **Truth coverage.** The file only covers what was annotated: relationships the chunker doesn't send to the Reader (6 quotes, listed by `--check`) can't be found, and a wrong link may be a true one the file lacks.
- **Spending.** Eval runs are capped at US$3 a local day (`--cap` to change it for one command).
