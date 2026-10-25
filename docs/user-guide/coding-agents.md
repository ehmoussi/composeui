# Using a coding agent

ComposeUI ships a skill for coding agents: a `SKILL.md` file that an agent loads when it
writes or changes a ComposeUI app. It holds the rules that keep an app correct on every
backend, a minimal app, and links to this documentation. It does not replace the guides: the
agent reads them for the details.

## Install the skill

Download the file into the skills directory of your project. For Claude Code:

```bash
mkdir -p .claude/skills/composeui
curl -o .claude/skills/composeui/SKILL.md \
  https://ehmoussi.github.io/composeui/skills/composeui/SKILL.md
```

Other agents that read `.agents/skills/` need the same file in `.agents/skills/composeui/`.

The skill is for the app's code, not for ComposeUI's own: to change ComposeUI, read the
[technical guide](../technical-guide.md) and `AGENTS.md`.

## Point the agent at the documentation

The site publishes an [`llms.txt`](https://ehmoussi.github.io/composeui/llms.txt): a list of
its pages, each with a line that says what it holds. Give an agent that link when it has no
skills, or when it needs a page of the user guide.
