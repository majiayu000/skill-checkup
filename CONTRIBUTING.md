# Contributing

```bash
git clone https://github.com/majiayu000/skill-checkup.git
cd skill-checkup
python3 -m pip install pytest
python3 -m pytest -q
python3 -m skill_checkup --out -    # run against your own machine
```

- Python 3.10+, standard library only. Please keep it dependency-free.
- The tool must stay read-only and offline. Never add code that edits skills, logs or settings, or sends data anywhere.
- Add a test for parser changes, using a small hand-written log line rather than a real transcript.
- False positives are the most useful bug reports. Include the finding line and, if you can, the relevant SKILL.md snippet. Do not paste private session logs.
- Commit messages: `<type>: <description>` (feat, fix, docs, test, refactor, chore). Sign off with `git commit -s`.
