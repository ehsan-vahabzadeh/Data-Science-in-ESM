# Issue tracker: GitHub

Issues and specs live in GitHub Issues for `ehsan-vahabzadeh/weather-forecast`.
Use the authenticated `gh` CLI from this repository.

## Conventions

- Before the first issue write in a session, run `gh repo view --json nameWithOwner` and check that it names this repository.
- Create: `gh issue create --title "..." --body-file <file>`.
- Read: `gh issue view <number> --json number,title,body,labels,comments`.
- List: `gh issue list --state open --json number,title,body,labels,comments`.
- Comment: `gh issue comment <number> --body-file <file>`.
- Label: `gh issue edit <number> --add-label "<label>"` or `--remove-label "<label>"`.
- Close: explain the outcome in a comment, then run `gh issue close <number>`.
- For child tickets, use GitHub sub-issues when available. Otherwise put `Part of #<parent>` in the child body.
- Record blockers with GitHub issue dependencies when available. Otherwise put `Blocked by: #<number>` in the child body.
- Pull requests as a triage request surface: no.

## Skill phrases

- “Publish to the issue tracker” means create a GitHub issue.
- “Fetch the relevant ticket” means read its GitHub issue.

## Wayfinder

Keep one map issue labelled `wayfinder:map`, with linked child tickets.
Use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or
`wayfinder:task` for children. Choose the first open, unblocked, unclaimed
child. Claim it by assigning it to the working developer; resolve it with
an answer and close it, then record the decision in the map issue.
