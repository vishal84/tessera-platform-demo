# Captured output

Text fallbacks for talking through a beat when the console is not available.
When you use one, say so — the audience cares about the shape of the workflow,
not about watching tokens stream.

| File | Beat | What it shows |
|---|---|---|
| `act2-triage.md` | 1.3 | The triage chain: inflection, the docstring trap, the causing commit, the fix |
| `act3-validation.md` | 2.2 | The leakage finding, quantified |

The console's own fallbacks are richer and preferred:

- **Play recording** on the incident page replays a real headless run
  (`demo/recordings/triage-INC-4412/`) with the same feed, stepper, PR card
  and timeline as a live run, and restores the branch and PR at the end.
- `./demo/reset-demo.sh --restore-notebook` drops the executed investigation
  notebook (`demo/recordings/03_v3_shadow_investigation.executed.ipynb`) in
  place.

`demo/` is read-denied to the agent, so none of this leaks into a live run.
