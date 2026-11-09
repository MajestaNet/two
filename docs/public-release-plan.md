# Proposal: make Majesta Two public

This is a proposal. Merging it does not make the repository public, does
not rewrite history, and does not cut a release. The maintainer can
accept or reject each recommendation.

The audit base is remote `main` at `d5f73b3df90b0199da86a759d170e6e21147302c`
(`feat: add shared ESPHome nodes behind climate zones (#72)`, 29 October
2026, 17:19 Australia/Melbourne). `gh repo view` on 29 October 2026
reported `MajestaNet/two` as **private**. Apache License 2.0 and the
MajestaNet copyright in `NOTICE` stay as they are (ADR 0002, ADR 0008).

`docs/architecture.md` stays the spec. Where a later change would add
distribution behavior the spec does not describe, write an ADR under
`docs/adrs/` and leave the spec alone until that ADR is accepted.

## Verdict

| Outcome | Verdict | Single biggest blocker |
| --- | --- | --- |
| A. Nothing personal and no credentials in the public history | Not ready | Fourteen commits on `origin/main` record `stev333 <stev333@users.noreply.github.com>`. The root commit is one of them, so every branch carries the machine hostname. |
| B. A stranger can configure this machine in operator mode | Not ready | Closed operator tools refuse secret values, and television pairing, vacuum nickname listing, and ESPHome flashing still happen in a shell or a vendor site. |
| C. A download link is enough to run the app | Not ready | `npm run package` builds an unsigned unpacked directory, and no GitHub Release workflow uploads it. |

No live secret was found. Placeholder strings in tests stay described
below as placeholders.

## How a recommendation is written

Each item has a finding, the evidence, the risk, and the concrete next
step. Two lists at the end separate work that is safe before the
repository is public from work that waits for an explicit maintainer
approval.

## What was searched

Commands run against the fetched remote refs (157 commits, 61 GitHub
branches):

- `git log --all --format` for author and committer identities
- `git log --all -G 'stev333|redacted-host|/Users/operator'` (no matching
  patch text)
- `git rev-list --objects --all` and a read of 1,845 unique blobs under
  2 MB, including blobs that are no longer on `HEAD`
- `git log --all --full-history` for `.env`, `*.pem`, `*.key`,
  `*.sqlite`, `*.db`, and credential filenames
- `gh repo view`, `gh pr list`, `gh issue list`, `gh release list`,
  `gh run list`, and the Actions artifact list
- A marker scan of two Actions logs (latest `main` success
  `40828514669`, and the failed `open router model support` run
  `40489833805`)

Blob patterns included email addresses, `/Users/` and `/home/` paths,
`*.local` and `*.ts.net` names, MAC addresses, IPv4 literals, private
keys, AWS access-key ids, GitHub token prefixes, OpenRouter-style
`sk-` keys, Slack token prefixes, JWTs, `TWO_API_TOKEN` assignments,
and the words downstairs, upstairs, bedroom, lounge, steve, and zinke.

Gap: `gh secret list` returned HTTP 403 (`Resource not accessible by
integration`). Secret *names* configured on the repository were not
visible from this run. The CI workflow file does not pass any secret
into the job.

## A. Personal data and credentials

### A1. Machine hostname in commit authors

Finding. Fourteen commits use author and committer
`stev333 <stev333@users.noreply.github.com>`. That email is a
personal machine name. `git log -G` found those strings in commit
headers only, not in file contents. GitHub already has the objects:
`gh api repos/MajestaNet/two/commits/350d8de04f05e7b69c3585e23d3035e051505e6d`
returns that author email. The same identity is the root commit
(`git rev-list --max-parents=0 --all`), so all 61 branches contain it.

Evidence. Times below are Australia/Melbourne, taken from the commit
offsets (`+1100` in October, `+1000` on 30 August).

| Commit | When | Subject |
| --- | --- | --- |
| `f72c414e904db1417b67eb20135efdc5626b9d48` | 28 Oct 2026 19:36 | vacs working |
| `94f6cc51eb365cfd83ea6d094d2a59fd1cfb6490` | 28 Oct 2026 16:46 | mlx working |
| `1b20a15b6c0e252645dc248a3d47110f895c4c33` | 28 Oct 2026 13:03 | Merge origin/main into local main. |
| `5c9e2cc9965be15bdadeee644762378046f1ffdb` | 28 Oct 2026 12:09 | model options |
| `e5dde6908e9eef89e4a43eee921499081c827195` | 27 Oct 2026 21:36 | open router model support |
| `c4438716bb86835eea14cf641ec284605a4107cf` | 27 Oct 2026 19:29 | majesta colours |
| `3f22cf0462928ff8aabdaf72afed7f889f762b39` | 27 Oct 2026 19:15 | majesta colours |
| `8cf6d4237a37a9881e20700e15733ade4b9feb8f` | 26 Oct 2026 20:50 | faster simple commands |
| `27f55d56790a25c5652f8858165f78e0f1fda976` | 26 Oct 2026 17:26 | faster testing |
| `d3d95655d4926e27a999e4c38f979f03c5455f8c` | 25 Oct 2026 18:24 | local ui working |
| `368005186db78bb2e580960ecdc494b15983be84` | 24 Oct 2026 18:56 | feat: perform Samsung television tools on the home-action profile |
| `74628585c123ab36a65e155da20c15b3b3b0500b` | 23 Oct 2026 22:30 | ac connect |
| `4d036f0845321af49622d49f78b2648a44cef9c3` | 22 Oct 2026 19:38 | chat working |
| `350d8de04f05e7b69c3585e23d3035e051505e6d` | 30 Aug 2026 08:46 | architecture for scaffold |

Other identities on the same history, and not a hostname leak:
`stev333 <stev333@users.noreply.github.com>` (57 commits; GitHub's
noreply form, which still shows the account `stev333`),
`Cursor Agent <cursoragent@cursor.com>` (78 commits), and
`dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>`
(8 commits). There is no `.mailmap`.

Risk. The moment visibility flips, the hostname is on the public commit
pages, in clones, and in every open pull request that contains the root
commit. A `.mailmap` changes only how some `git log` invocations
display a name. `git cat-file commit` and GitHub's commit page keep
the original identity until the objects are replaced.

Next step. Treat this as a publication choice. Either accept the
hostname the same way the public contact address is accepted, or
rewrite every ref that contains `350d8de` so the author and committer
match the existing noreply identity, then ask GitHub to garbage-collect
the old objects while the repository is still private. That rewrite is
in the "do not do until approved" list. This proposal does not perform
it.

### A2. Contact address is intentional

Finding. `hello@majesta.net` appears only in `SECURITY.md` and
`CODE_OF_CONDUCT.md` (five blobs in history, both paths). The unique-blob
email set is otherwise `two-test@example.com`, `two-eval@example.com`,
`two-agent@noreply.local`, and `i@izs.me`.

Evidence. `SECURITY.md` line 7 and `CODE_OF_CONDUCT.md` line 59.
`i@izs.me` is the npm `glob` / `tar` deprecation notice inside
`apps/console/package-lock.json`, a third-party maintainer address, not
this project's contact.

Risk. The published contact is a shared Majesta mailbox, not a
personal inbox.

Next step. Keep hello@majesta.net as the public contact. Do not
publish a personal mailbox.

### A3. No live credential in reachable blobs

Finding. No private key, live token, sqlite database, or real home
directory was found in any reachable blob. Tracked names on `HEAD` do
not include `.env`, `.pem`, or sqlite. History adds only
`src/two/validation/secrets.py` (a detector) and
`config/runtime/models.lock.example` (empty digests, public harness pin).

Evidence. Unique-blob hits that look like secrets are fixtures:

| Kind | Where | What it is |
| --- | --- | --- |
| OpenRouter-shaped key | `tests/unit/test_openrouter_backend.py`, `apps/console/test/bridge.test.cjs` | The test placeholder `sk-or-v1-testkeyvalue0001` |
| Shorter `sk-or-` fixture | `tests/unit/test_esphome_climate.py`, `tests/unit/test_operator_profile.py` | `sk-or-abcdefghijklmnop` |
| GitHub token shape | `tests/unit/test_chat_profile.py`, `tests/unit/test_climate_home_action.py` | The literal `ghp_secret` |
| AWS example key id | `tests/unit/test_validation_profiles.py`, `tests/integration/test_validation.py`, `tests/unit/test_api_config.py` | `AKIAIOSFODNN7EXAMPLE` |
| Bearer fixture | several `tests/unit/test_api*.py` and device tests | `secret-token` or `super-secret-token` |
| Private-key text | `tests/unit/test_evals.py` | An assertion that the corpus does not contain `BEGIN OPENSSH PRIVATE KEY` |
| PEM marker | `src/two/validation/secrets.py` | The detector prefix `-----BEGIN` |

`TWO_API_TOKEN` occurs as a documented variable name in `.env.example`
(commented), `src/two/api/bind.py`, `src/two/client.py`, and the setup
docs. No assignment of a real bearer value was found. Home paths in
tests and the console test are `/Users/op`, `/Users/operator`,
`/Users/ada`, `/Users/x`, and `/home/op`, `/home/ada`. The false
`/home/cordis.patch.yml` hit is a sentence in
`docs/adrs/0028-home-action-acp-client.md` about
`$TWO_DATA_DIR/harness/home/cordis.patch.yml`.

Risk. A later commit, or a file that exists only on the maintainer's
Mac, can still add a real value. This audit cannot see a working tree
that was never pushed.

Next step. Before any push of work that is not in `d5f73b3`, repeat
`git log -G` and the blob scan on that delta. Do not commit `.env`,
`config/runtime/models.lock`, databases, or model weights.

### A4. Example devices and the vacuum nicknames

Finding. Example bindings are disabled and use documentation addresses.
Vacuum nicknames `Downstairs` and `Upstairs` are declared placeholders
in `config/AGENTS.md`. The Ecovacs section of `docs/setup.md` is written
as if the reader already has that pair of robots on one account.

Evidence.

- `config/devices/vacuum.example.yaml` sets `enabled: false`,
  `token_env: ECO_API_KEY`, and nicknames `Downstairs` / `Upstairs`.
  The comment says the key goes in `$TWO_DATA_DIR/env`.
- `config/AGENTS.md` says those nicknames are placeholders.
- `docs/setup.md` Ecovacs steps tell the reader to sign in to the
  account that "already shows both robots", warn that "a new email on
  that site will not see these robots", and say to leave the two
  placeholder robots.
- Television, climate, and ESPHome examples use `192.168.1.10`,
  `192.168.1.40`, `192.168.1.41`, `192.168.1.50`, `192.168.1.51`, and
  `192.168.1.60`, with MACs `02:00:00:00:00:01` and `02:00:00:00:00:02`
  (`config/devices/tv.example.yaml`). Those MACs are locally
  administered documentation values. The only other private address in
  the blob scan that is not in that `192.168.1.0/24` example set is
  `192.168.50.20` in `tests/unit/test_doctor_supervisor.py`, a fake
  Ollama URL. `10.1.2.3`, `10.0.0.5`, `10.0.0.8`, and `100.64.1.8` are
  test literals. `homeassistant.local`, `mac-mini.local`, and
  `bridge.local` are example hostnames in tests and ADR 0013, not
  `example.invalid`. No Tailscale DNS name (`*.ts.net`) appears.
  `tailscale0` in `config/access/remote.yaml` is the interface example.

Risk. If `Downstairs` and `Upstairs` are also the live Ecovacs account
names, the public tree shows the floor names of two robots and the
setup guide assumes that household. They are not device ids, tokens, or
MAC addresses. Replacing them on `HEAD` leaves the old text in
`f72c414` and later commits. A history rewrite just for those words is
out of proportion to a hostname rewrite.

Next step. The maintainer confirms whether those two nicknames are the
live account names. If they are, replace them, and rephrase the Ecovacs
section so it tells a stranger to use their own Open Platform login and
copy the names `two vacuum robots` prints. If they are only
placeholders, leave the example file and still rephrase "these robots"
so it does not sound like one existing account.

### A5. GitHub metadata around the history

Finding. The repository is private, has no releases, no issues, and no
discussion posts. The wiki feature is enabled and the wiki git remote
returns "Repository not found", so there are no wiki pages. Eight open
pull requests are all Dependabot bumps (checkout, setup-python,
setup-uv, fastapi, uvicorn, mypy, ruff, types-pyyaml). A search of
issues and pull requests for `redacted-host`, `stev333`, `downstairs`,
and `ECO_API_KEY` returned nothing. Actions has no stored artifacts.
170 workflow runs were listed. CI is `.github/workflows/ci.yml`:
`permissions: contents: read`, then `make ci`. The two sampled logs
contained none of the hostname, private-key, or live-token markers.

Evidence. `gh repo view MajestaNet/two --json visibility,isPrivate`
(`PRIVATE` / `true`). `gh release list` empty. `gh issue list --state all`
empty. `gh api repos/MajestaNet/two` reports `has_wiki: true`,
`has_pages: false`, `has_discussions: false`.

Risk. Changing a private repository to public exposes every branch, the
Dependabot pull requests, and retained Actions logs. The sampled logs
are clean, and the workflow does not inject secrets, but this run did
not read all 170 logs and could not list Actions secret names.

Next step. On the day visibility is under consideration, re-read the
secret-name gap with a token that can list Actions secrets, and decide
whether retained logs stay. That decision is in the approval list.

### A6. Work that may exist only on the maintainer's Mac

Finding. The request described uncommitted local work for operator chat
approval (ADR 0041), Ecovacs device-list GET (ADR 0042), and
vacuum/operator code, and said that work was not on remote `main`
unless this audit found it. It is on remote `main`. Commit `f72c414`
("vacs working", 28 October 2026, 19:36 Australia/Melbourne) adds
`docs/adrs/0041-operator-chat-approval.md`,
`docs/adrs/0042-ecovacs-device-list-get.md`, and the matching operator
and vacuum code. `d5f73b3` then adds ADR 0043. Anything still only in a
local working tree, and absent from `d5f73b3`, was not in this cloud
snapshot.

Evidence. `git log --diff-filter=A` for those ADR paths.
`git merge-base --is-ancestor f72c414 origin/main` succeeds.
`git log --oneline f72c414..origin/main` is only `d5f73b3`.

Risk. A dirty tree on the Mac can contain a real key, a real nickname,
or a hostname that this snapshot never saw. Pushing it after the
visibility flip publishes it immediately.

Next step. Diff that working tree against `d5f73b3` and run the same
secret scan before pushing. Do not assume this proposal covered it.

## B. Operator mode on a fresh machine

### B1. What a current install can already do

Finding. Explicit operator mode is implemented on this branch. It is a
fourth harness profile. The console can select it. Closed tools run in
this process. Bindings stay off until a local file enables them.
Secrets in a binding are refused.

Evidence.

- ADR 0039 (`docs/adrs/0039-operator-install-profile.md`) and ADR 0041
  are accepted on this branch. Schema version is 12
  (`src/two/store/schema.py`, `SCHEMA_VERSION = 12`).
- `docs/setup.md` status table says harness profile `operator` works
  through `two operator send`, `show`, `approve`, and `reject`, and
  through `profile=operator` on `POST /v1/voice/turns`. An omitted
  profile does not route there.
- `apps/console/src/renderer/index.html` offers `Unset`, `chat`,
  `home-action`, and `operator`. The first option is empty.
  `apps/console/src/renderer/policy.js` `chatRequest` omits `profile`
  when the select is empty, and accepts `operator` only when it is
  explicit.
- `src/two/operator/assist.py` advertises `install.status`,
  `install.read_guide`, `install.propose_binding`, and
  `install.propose_change`. Binding slots are `climate`, `tv`,
  `vacuum`, and `esphome`. `install.status` is a redacted snapshot
  (doctor, backend, harness pin, topology, adapter menu) and does not
  read a key file. `_reject_secrets` refuses token, password, secret,
  and API-key fields, and refuses values that look like `sk-` keys or
  URLs with userinfo.
- ADR 0041 applies a stored digest when a later operator transcript is
  only `approved` or `rejected`. Silence is still not approval. The
  watch principal cannot select `operator`.
- The window can install official Ollama, locate or install `mlx-lm`,
  pull one typed tag, sign in to OpenRouter with PKCE, and install the
  pinned DeepSeek Harness when `dsh` is missing (ADR 0032, ADR 0034,
  ADR 0035, ADR 0037, ADR 0040). `docs/setup.md` records the same
  status. The API process does not call Ollama or mlx-lm.
- A packaged process uses the bundle as its working directory when
  `config/inference/profiles.yaml` is present
  (`apps/console/src/main.cjs` `installRoot`). `stage-bundle.sh` copies
  `config/` plus `docs/setup.md`, `docs/adapters.md`, and
  `docs/local-16k.md`. `discover_repo_root` finds that tree by the
  profiles file, so `install.read_guide` can see the allowlist without
  a git checkout.

Risk. The status line "Works" is accurate for the closed tools and
wrong if a reader thinks the selected model can edit the product or
store a token.

Next step. Keep the status sentence, and keep the following limits in
the operator guide a stranger reads.

### B2. What still blocks "configure this machine"

Finding. Operator mode can draft a binding and can draft a self-build
task. It cannot finish either one inside the window. The coding child
for that task is still the ADR 0011 JSONL placeholder, and adoption of
a worktree onto the running tree at process restart is not implemented.
`CODING_NOTE` in `assist.py` says both facts to the model.

Evidence. ADR 0039 consequences and the "Status" line. ADR 0011.
`src/two/operator/assist.py` lines that set `CODING_NOTE`. A search of
`src/two` for an adoption implementation finds that sentence and no
adopter. The console has no editor for `$TWO_DATA_DIR/env` and no
button for `two tv pair`, `two vacuum robots`, or `two esphome entities`
(`apps/console/src` has no matches for those commands).

Risk. A stranger who selects `operator` and asks the model to set up
the house gets a proposal, then has to leave the chat to create vendor
credentials and paste them into an env file. A stranger who asks it to
change the product gets a task the placeholder child does not implement,
and a restart that does not adopt the result. ADR 0017 says this
installation is the development subject and that adoption is a separate
controller operation. Do not paper over that by rewriting
`docs/architecture.md`.

Next step. Keep self-build on the accepted ADR 0011 limit until a later
ADR moves the coding child to pinned `dsh --profile acp` and defines
adoption. For first-run configuration, add window or CLI steps that
write only env *names* the operator already created, and that launch
the existing pair, robots, and entities commands. Do not teach
`install.propose_binding` to accept a raw token. That would break ADR
0039. Any new runtime dependency is ask-first.

### B3. Climate, television, vacuum, ESPHome

Finding. All three device slots ship default off. A stranger's own
hardware still needs out-of-band steps. Nothing in the tree is the
maintainer's live token or hostname. The guides do assume the shape of
this household (living room, bedroom, two vacuums, one ESPHome IR
bridge).

Evidence. `docs/setup.md` status row for the adapter menu: only `cli`
is enabled. `config/adapters/catalog.yaml` is the menu `two adapters`
prints. Device files:

| Slot | Example | What a stranger still does by hand |
| --- | --- | --- |
| Climate, Home Assistant | `config/devices/climate.example.yaml`, `enabled: false`, `token_env: TWO_CLIMATE_TOKEN`, upstream `http://192.168.1.10:8123` | Run Home Assistant, create a long-lived token, put the token in `$TWO_DATA_DIR/env`, copy the example, set the private IP and zone entity ids. Hostnames are refused. |
| Climate, ECHONET Lite | `config/devices/climate-echonet.example.yaml`, zones `living` and `bedroom` | Enable ECHONET on the unit. No token. The binding is the unit's private IPv4. Do not enable this and the Home Assistant file together. |
| Climate via ESPHome | `config/devices/esphome.example.yaml`, `config/devices/climate-esphome.example.yaml`, ADR 0043 | Flash the vendor sample in the ESPHome dashboard, put `TWO_ESPHOME_KEY` in the env file, run `two esphome entities`, then name that object id on a climate zone. The key is an env name in the example (`key_env`), not a value. |
| Television | `config/devices/tv.example.yaml`, sets `living-room` and `bedroom` | Write real private addresses and router MACs, restart, run `two tv pair --set …` while accepting the Allow prompt on the screen, put the printed token in the env file, run `two tv apps` for application ids. |
| Vacuum | `config/devices/vacuum.example.yaml`, ADR 0038, ADR 0042 | Create a server access key at `open.ecovacs.com` (or `open.ecovacs.cn` for a mainland login) on the same ECOVACS HOME account that owns the robots. Put it in `ECO_API_KEY`. Run `two vacuum robots` and copy those exact nicknames. There is no vacuum approval table. A known robot is pre-authorized. |

`install.propose_binding` can write `$TWO_DATA_DIR/devices/<slot>.yaml`
after a digest. It does not create the vendor account, flash ESPHome,
or pair a television. `docs/setup.md` already says the operator profile
should walk the vacuum steps and call `install.propose_binding` only
after the nicknames are confirmed, and that it must not paste the
example YAML or invent a nickname.

Risk. Shipping the packages is the right public shape (ADR 0021, ADR
0022, ADR 0027, ADR 0029, ADR 0038, ADR 0043). Enabling a slot in
`config/adapters/catalog.yaml`, or committing a filled
`$TWO_DATA_DIR/devices/*.yaml`, would publish one household's binding.
The setup guide's "both robots" wording makes a stranger follow the
maintainer's account instead of their own.

Next step. Leave `climate`, `tv`, and `vacuum` default off. Do not
enable a slot by adding a directory. After the maintainer confirms the
nicknames (A4), edit the Ecovacs section so the account, the key, and
the nicknames are the stranger's. Point climate and television at the
same rule: copy the example, replace the documentation addresses, keep
tokens in env names.

### B4. A note a stranger can misread

Finding. `config/runtime/models.lock.example` says Majesta Two does not
speak ACP yet. Chat, home-action, and operator on this branch launch
pinned `dsh --profile acp`. Coding stays on the ADR 0011 fixture.

Evidence. `config/runtime/models.lock.example` notes. ADR 0025, ADR
0028, ADR 0039, ADR 0011. `docs/setup.md` harness row pins
`dsh-v0.1.2-alpha.1`.

Risk. A fresh operator who trusts the lock example will think the
pinned client is unused.

Next step. Correct that note in a later docs commit so it matches the
ADRs. Do not change the pin and do not reimplement DeepSeek Harness.

## C. A downloadable Mac app

### C1. What `npm run package` does today

Finding. The desktop build is a local unpacked directory. It is not a
GitHub Release asset, not a signed app, and not an npm publish. The
npm package is marked private. DeepSeek Harness and model weights are
not inside the directory.

Evidence. `apps/console/package.json`:

- `"private": true`, `"license": "Apache-2.0"`, version `0.1.0`
- `"package": "npm run stage-bundle && electron-builder --dir"`
- mac and linux `target` are both `["dir"]`
- mac `identity` is `null`
- no `build.publish` block
- `files` are `src/**/*`, `assets/**/*`, `scripts/mlx_hub.py`, and
  `package.json`
- `extraResources` copies `build/bundle` to `bundle`

`apps/console/scripts/stage-bundle.sh` installs CPython 3.12, creates a
relocatable venv, `uv pip install`s this repository, and copies
`config/` plus three docs. The script comment says DeepSeek Harness is
not included. ADR 0034 decision 1 and ADR 0035 decision 3 say the same,
and say model weights stay in Ollama. `.github/workflows/ci.yml` runs
`make ci` on `ubuntu-latest` only. `gh release list` is empty.

Risk. A stranger who is told to download the app has nothing to
download. Cloning is still the way to run it. An unpacked `--dir`
build also has no stable URL.

Next step. Describe the artifact in a new ADR before adding a workflow.
Do not rewrite `docs/architecture.md` to mention a release URL first.
Architecture §12.6 already says a packaged build carries this control
plane and does not need a second clone. It does not specify GitHub
Releases, a file name, or code signing. Section 12 also says unattended
mode does not publish packages. A release workflow must be a maintainer
action, not something the worker or `two up` triggers.

### C2. What the first public artifact should be

Finding. The product host is a Mac mini (ADR 0019). The first useful
download is one Mac build of the existing Electron window plus the
bundled control plane, attached to a GitHub Release, with a stable
asset URL of the form
`https://github.com/MajestaNet/two/releases/latest/download/<file>`.
That URL does not work until a public release exists. This repository
is still private, so the URL would not be anonymous even after a
release is drafted.

Evidence. ADR 0019, ADR 0031, ADR 0034, ADR 0035. `package.json` as in
C1. No release workflow in `.github/workflows/`.

Risk. `electron-builder --dir` does not produce a zip or dmg a browser
can save as one file. Linux `dir` is a second unpacked tree and is not
the product host. Publishing both is optional. Publishing from a dirty
builder is not: `stage-bundle.sh` copies the whole `config/` directory.
On a clean checkout that is the examples. On a machine that has a
filled `config/runtime/models.lock` or a stray env file inside `config/`,
those files would ride along. Hatchling installs the Python package
from `src/`; it does not by itself bundle `.env`. The copy of `config/`
is the path that needs a clean tree.

Next step. When the maintainer approves a release, the job should:

1. Run on a Mac runner from a clean checkout of a tagged commit.
2. Fail if `.env`, `*.pem`, `config/runtime/models.lock`, `*.sqlite`,
   or `models/` is present.
3. Run the existing `npm run stage-bundle` and then package a single
   archive of the `.app` (zip is enough for a first link).
4. Upload that archive to a GitHub Release the maintainer creates.
5. Leave DeepSeek Harness out. The Server page downloads pin
   `dsh-v0.1.2-alpha.1` later (ADR 0035).
6. Leave model weights out. The Model page pulls them into Ollama or
   `mlx-lm` on the stranger's machine.
7. Leave secrets and `$TWO_DATA_DIR` out. The window creates the
   platform data directory when `TWO_DATA_DIR` is unset (ADR 0035).

No new Python dependency is required for that job. Adding one is
ask-first.

### C3. Signing and notarization

Finding. `identity: null` means the Mac build is unsigned. There is no
notarization configuration.

Evidence. `apps/console/package.json` `build.mac.identity`. Apple
Gatekeeper treats a downloaded unsigned app as untrusted. ADR 0034
does not discuss Developer ID or notarization.

Risk. A stranger who downloads a zip can still be blocked from opening
it. Signing needs an Apple Developer ID certificate and an account the
maintainer controls. That is outside this repository. Putting the
certificate or an app-specific password into the repo, into Actions
logs, or into the artifact would undo outcome A.

Next step. Decide, separately from the first unsigned internal build,
whether the public download is signed and notarized. Until that
decision, the release ADR should say the public Mac artifact is signed
with Developer ID and notarized, or it should say the download page
tells the stranger the app is unsigned. Store the certificate in the
maintainer's Apple account and in GitHub Actions secrets, not in git.
This run could not list those secret names (HTTP 403).

This pass did not run `npm run package`. A Linux cloud builder cannot
produce the Mac artifact, and a local `--dir` build would not prove the
release URL.

## License alignment

Finding. The Python tree is Apache-2.0 and the header check passes.
Third-party pieces that ship in the repo use permissive licenses and
are already named where attribution is required. Nothing in the
dependency set uses GPL, AGPL, or SSPL. Do not relicense any of it.

Evidence.

- `LICENSE` is the Apache License 2.0 text. `NOTICE` copyright 2026 is
  MajestaNet, with trademark lines for Qwen, Ollama, and DeepSeek
  Harness.
- `NOTICE` records Inter and Josefin Sans under the SIL Open Font
  License 1.1, with copies in `apps/console/src/renderer/fonts/`.
  Inter's copyright line names The Inter Project Authors. Josefin Sans
  names The Josefin Sans Project Authors and a reserved font name.
- `NOTICE` records `aioesphomeapi` as MIT. `pyproject.toml` depends on
  `aioesphomeapi>=46` and sets `license = "Apache-2.0"`. Authors are
  `MajestaNet`.
- `bash scripts/check-license-headers.sh` prints `license headers ok`.
  It checks `src/**/*.py` for the MajestaNet copyright, the Apache
  boilerplate, and `SPDX-License-Identifier: Apache-2.0`.
- Console JS and CJS files under `apps/console/src` carry the copyright
  line and the SPDX identifier. `apps/console/src/renderer/index.html`
  and `styles.css` do not. The checker does not look at them.
  `docs/public-repo.md` requires the boilerplate for original source
  under `src/`.
- `apps/console/package-lock.json` license counts are MIT, ISC,
  Apache-2.0, BSD, BlueOak-1.0.0, Python-2.0, WTFPL, and CC0. No copyleft
  license field. Electron and electron-builder are devDependencies used
  to build the window. `private: true` keeps the npm package off the npm
  registry.

Risk. OFL fonts cannot be relicensed as Apache. Shipping them with the
OFL text and the `NOTICE` line is the compatible path. Dropping the
OFL files, or replacing the font copyright with only MajestaNet, would
be a license break. A public reader may think `index.html` is
unlicensed because the header checker never sees it.

Next step. Leave `LICENSE`, `NOTICE`, and the font files as they are.
Optionally add the existing SPDX line to `index.html` and `styles.css`
in a later commit. Do not vendor DeepSeek Harness into the app, which
would add a second license surface ADR 0035 already refuses.

## Safe to do before the repository is public

These are ordinary commits or local checks. They do not rewrite
history, flip visibility, or upload a release.

1. Keep `MajestaNet/two` private until the approval list is decided.
2. Diff any Mac working tree against `d5f73b3` and repeat the blob and
   `git log -G` scan before pushing it (A6).
3. Confirm the vacuum nicknames. If they are live account names, replace
   them on `HEAD` and rephrase the Ecovacs section of `docs/setup.md`
   (A4, B3). If they are placeholders, still rephrase "these robots" so
   a stranger uses their own account.
4. Correct the ACP sentence in `config/runtime/models.lock.example` so
   it matches ADR 0011, ADR 0025, and ADR 0039 (B4).
5. Draft the release ADR (next free number after ADR 0043) describing
   one maintainer-cut Mac archive, what the archive excludes, and
   whether it is signed. Do not add the workflow in that same breath
   unless the ADR is accepted (C1, C2).
6. Optionally add SPDX lines to `index.html` and `styles.css`.

`docs/public-repo.md` in this change records two hygiene rules that were
already decided and easy to miss: private key files and
`config/runtime/models.lock` are gitignored, and a machine hostname in a
commit identity is a private-network hostname. `.gitignore` does not
rewrite old commits.

## Do not do until the maintainer approves

1. Do not rewrite git history, run `git filter-repo`, or force-push, to
   replace `stev333@users.noreply.github.com`. If that rewrite is
   approved, do it while the repository is still private, rewrite every
   branch that contains `350d8de` (all of them today), and ask GitHub to
   drop the old objects. Deleting the stale `cursor/*` branches is part
   of that cleanup and is also a destructive remote change.
2. Do not change repository visibility to public.
3. Do not create a GitHub Release, attach an artifact, or add a workflow
   that publishes one. Drafting the ADR is in the safe list. Cutting the
   release is not.
4. Do not enable the `climate`, `tv`, or `vacuum` catalog slots, and do
   not commit a filled binding, a real MAC, or a real LAN address.
5. Do not add a Python runtime dependency for signing, packaging, or
   device setup without the ask-first step in `AGENTS.md`.
6. Do not edit `docs/architecture.md` so it matches this proposal.
7. Do not delete the Actions log history, turn off the wiki feature, or
   rotate credentials from this proposal. Those are maintainer actions
   on the private repository. Do them only as part of an approved
   pre-flip pass. This audit found no live secret that needs rotation.
   The Actions secret-name list was not readable (HTTP 403), so a token
   that can list names should look before the flip.
8. Do not relicense the OFL fonts or `aioesphomeapi`.

## Suggested order, after approval

1. Decide the hostname: accept it, or rewrite and garbage-collect while
   private.
2. Land the stranger-facing setup edits (nicknames, Ecovacs wording,
   lock-file ACP note) on `HEAD`.
3. Accept the release ADR, then add a Mac release workflow that uploads
   one archive and publishes nothing else.
4. Sign and notarize, or document that the download is unsigned.
5. Re-run this audit on the commit that will be public, including the
   Mac working tree.
6. Only then change visibility.
