# org-ci

CI for the static-ai-apps organization: it checks pull requests, merges what passes, keeps the library's data current, creates apps and forwards alerts. The maintainer agent maintains it. Agents are started by the core, which lives in the governance repo along with the setup guide, [INFRASTRUCTURE.md](https://github.com/static-ai-apps/governance/blob/main/INFRASTRUCTURE.md).

## Workflows

| Workflow | Runs | Does |
|---|---|---|
| `pipeline` | Every 10 minutes; on dispatch from the core | Validates open pull requests on published repos, merges the ones that pass, comments on the rest, closes strangers' pull requests, raises detector alerts |
| `bake` | Daily; after every merge | Rewrites the library's app list and star counts |
| `create-app` | On dispatch from the core | Creates a repository pair for a new app |
| `alerts` | Daily | Forwards `Needs human` notes and Safe Browsing verdicts to the private `alerts` repo |
| `housekeeping` | Weekly and monthly | Re-applies repo settings; heartbeat commit so schedules keep running |
| `self-test` | When CI's code changes | Runs the detectors against the fixtures in `tests/` |

The pipeline splits work so that untrusted code never runs next to a credential: `validate` checks out and runs the proposed app with no secrets at all, and only `act`, which never runs app code, gets the CI App's token.

## Layout of this repo

| Path | What |
|---|---|
| `config/config.json` | Org name, identities, whitelist, limits, detector thresholds |
| `config/blocklist.txt` | Hosts whose use blocks a merge |
| `config/excluded-stargazers.txt` | Accounts whose stars don't count toward Q |
| `scripts/` | Everything the workflows run |
| `tests/` | Detector fixtures and their runner |
| `NOTES.md` | The maintainer's working notes. Its instructions are [MAINTAINER.md](https://github.com/static-ai-apps/governance/blob/main/MAINTAINER.md) in the governance repo |

## Running checks locally

```sh
pip install pyyaml psutil playwright && python -m playwright install chromium
python tests/run_fixtures.py
python scripts/validate.py --repo my-app --pr-dir path/to/app --license path/to/LICENSE --out result.json
```

Set `CHROME_PATH` to use an installed Chrome instead of Playwright's.

Read-only scripts work against the live org with no token: `python scripts/discover.py`, or `DRY_RUN=1 python scripts/bake.py` to print the data the library would get.
