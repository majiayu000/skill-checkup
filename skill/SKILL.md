---
name: skill-checkup
description: Check the agent skills installed on this machine across Claude Code and Codex for problems - broken links or files, same-name copies that drifted apart, descriptions that compete or miss requests their skill already handles, and skills loaded by both agents but used by only one. Use when the user asks to check, audit, clean up or tidy their skills, compare Claude Code and Codex skills, or asks why a skill did not trigger. For unused Claude Code skills and their token cost alone, /skill-doctor is enough.
---

# skill-checkup

Run the read-only checkup and summarize it for the user.

1. Run it from the user's current project so project-level skills are included:

   ```bash
   uvx --from git+https://github.com/majiayu000/skill-checkup@v0.2.1 skill-checkup --out skill-checkup-report.md
   ```

   If `uvx` is missing, use `pipx run --spec git+https://github.com/majiayu000/skill-checkup@v0.2.1 skill-checkup` instead.
2. Show the user the summary it prints, then read `skill-checkup-report.md` and explain the top actions in plain words.
3. Do not move, edit or delete any skill unless the user asks for that specific change. The tool itself never changes files.
4. Only add `--show-examples` if the user wants to see which of their own requests were matched; those quotes stay on this machine.
5. To check whether a reworded description would match better, run `skill-checkup replay <skill> --description "<new text>"` and compare the two rows.
