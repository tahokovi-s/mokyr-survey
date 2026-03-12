# Avner Student Ambiguous Item Review

Date: March 8, 2026

This file is a second-pass review of the risky rows from Claude's audit. I focused only on cases where the problems were guessed emails, identity merges, duplicate rows, or uncertain Greif-student links.

## Practical Outcome

- `0` rows moved from "ambiguous" to fully safe new outreach contacts without caveat.
- `3` rows have a plausible public/current email but still need manual confirmation of the Greif-student link before use:
  - Jeff David Miner -> Jeffrey Miner -> `jeffrey.miner@wku.edu`
  - George Qian -> likely George Qiao -> `gqiao@amherst.edu`
  - Diego Sasson -> `diego.sasson@gmail.com` is plausible but old/unverified
- `1` row has only an organization contact:
  - Irena Asmundson -> `info@pi-economics.com`
- `1` row is a strong name correction but should be removed from outreach:
  - Elizabeth Sin -> Isabelle Sin -> already responded
- `5` rows should not be used for outreach as they currently stand:
  - Gregory Beshrov
  - Mu Yang
  - Jeff Minner
  - Robert Ebhart
  - Katherine de Fontaine

## Main Corrections To Claude's Audit

1. Gregory Besharov appears to be the right identity, but `gb87@cornell.edu` was inferred, not publicly shown. That row should be demoted.
2. George Qiao's Amherst email appears public/current, but the step from `George Qian` to `George Qiao` is still not proven strongly enough to treat as a clean recovery.
3. Jeff Minner should not be treated as a separate recovered contact. It looks like a duplicate/misspelling of Jeff David Miner.
4. Robert Eberhart looks like a real person with a real email, but the Greif-student link is too weak.
5. Isabelle Sin is resolved enough to remove from outreach entirely because she already responded.

## Recommended Use Rule

- Safe to use without extra work: none from this ambiguous subset.
- Use only after manual confirmation: Jeffrey Miner, George Qiao, Diego Sasson, Irena Asmundson.
- Remove or hold entirely: Gregory Besharov, Mu Yang, Jeff Minner, Robert Eberhart, Katherine de Fontaine, Isabelle Sin.
