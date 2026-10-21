---
name: skill-checkup
description: Check the health of the agent skills installed on this machine and report which are broken, competing for the same requests, silent (asked for but not fired), heavy on context, or unused. Use when the user asks to check, audit, clean up or tidy their skills, or asks why a skill did not trigger.
---

# skill-checkup

Run the read-only checkup and summarize it for the user.

1. Run it from the user's current project so project-level skills are included:

   ```bash
   uvx --from git+https://github.com/majiayu000/skill-checkup skill-checkup --out skill-checkup-report.md
   ```

   If `uvx` is missing, use `pipx run --spec git+https://github.com/majiayu000/skill-checkup skill-checkup` instead.
2. Show the user the summary it prints, then read `skill-checkup-report.md` and explain the top actions in plain words.
3. Do not move, edit or delete any skill unless the user asks for that specific change. The tool itself never changes files.
4. Only add `--show-examples` if the user wants to see which of their own requests were matched; those quotes stay on this machine.
5. To check whether a reworded description would match better, run `skill-checkup replay <skill> --description "<new text>"` and compare the two rows.
