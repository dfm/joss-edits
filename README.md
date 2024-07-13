Automate some JOSS editorial tasks.

```bash
pixi run edit https://REPO_URL -b JOSS_BRANCH
```

To do copy editing, put a Gemini API key in a file called `api_key` and run:

```bash
pixi run edit https://REPO_URL -b JOSS_BRANCH --copy-edit
```
