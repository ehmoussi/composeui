# Using a coding agent

ComposeUI ships a skill for coding agents: a `SKILL.md` file that an agent loads when it
writes or changes a ComposeUI app. It holds the rules that keep an app correct on every
backend, a minimal app, and links to this documentation. It does not replace the guides: the
agent reads them for the details. These sections say how to install the skill, and how to
point an agent at the documentation.

## Install the skill

Download the file into `.agents/skills/composeui/` in your project, the skills folder
that many coding agents read:

```bash
mkdir -p .agents/skills/composeui
curl -o .agents/skills/composeui/SKILL.md \
  https://ehmoussi.github.io/composeui/skills/composeui/SKILL.md
```

Claude Code reads `.claude/skills/` instead. Make it a symbolic link to `.agents/skills/`,
so that both folders hold the same files and one download updates them:

```bash
mkdir -p .claude
ln -s ../.agents/skills .claude/skills
```

When `.claude/skills/` already holds skills of its own, link only the ComposeUI skill:
`ln -s ../../.agents/skills/composeui .claude/skills/composeui`.

On Windows, create the link in a Command Prompt with
`mklink /D .claude\skills ..\.agents\skills`. It needs Developer Mode or an administrator.
Git for Windows checks out a link as a link only when `core.symlinks` is `true`.

The site publishes the skill of the `main` branch, which changes with the API. Run the same
command again to update your copy, for example when you update ComposeUI. The skill names
the version of ComposeUI that it describes, and the agent compares it with the installed
one: when ComposeUI is newer, the agent reads the current skill, and tells you to update
your copy.

When your app installs ComposeUI from a commit of GitHub's `main`, not from a release,
download the skill of that commit, and download it again when the app moves to a new
commit:

```bash
curl -o .agents/skills/composeui/SKILL.md \
  https://raw.githubusercontent.com/ehmoussi/composeui/<commit>/docs/_site/skills/composeui/SKILL.md
```

The version of a commit, such as `0.2.1.dev4+g1a2b3c4`, starts with the minor version of
the previous release. So the agent cannot tell from it that the copy is older than the code.

The skill is for the app's code, not for ComposeUI's own: to change ComposeUI, read the
[technical guide](../technical-guide.md) and `AGENTS.md`.

## Point the agent at the documentation

The site publishes an [`llms.txt`](https://ehmoussi.github.io/composeui/llms.txt): a list of
its pages, each with a line that says what it holds. Give an agent that link when it has no
skills, or when it needs a page of the user guide.
