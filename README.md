# enzo

Enzo is a Textual chat app for Termux and Acode that talks to OpenRouter. The
AI reads, writes and runs commands in the directory you start it from, and
nowhere else.

## Install with npm

```
npm install -g @fluctuateplus/enzocli
```

Then run it from the project you want the AI to work in:

```
cd ~/my-project
enzo
```

That gives you two commands, `enzo` and `enzocli`. The package installs the
Python dependencies (`textual` and `httpx`) for you on first install. You need
Python 3 on the device:

```
pkg install python
```

## Publishing under a different scope

The package name is `@fluctuateplus/enzocli`, which is the scope the npm
account `fluctuateplus` owns. npm only lets you create a new package name in a
scope you own, so publishing under `@enzorenz` needs you to log in as the
account or organisation that owns that scope:

```
npm login --scope=@enzorenz
npm run publish:enzorenz
```

If npm answers with `'@enzorenz/enzocli@1.0.0' is not in this registry`, the
token you used belongs to a different account than the scope. That is the one
error npm gives when the publisher and the scope do not match.

Publishing a private package needs a paid npm plan. On the free plan npm
answers with `402 Payment Required - You must sign up for private packages`.
Public packages under your own scope work on the free plan:

```
NPM_SCOPE=yourname npm run publish:public
```

Both publish commands take the usual npm options:

```
NPM_TOKEN=npm_xxx npm run publish     # a token that bypasses 2FA
NPM_OTP=123456 npm run publish        # a code from an authenticator app
```

A token that bypasses 2FA is created at
https://www.npmjs.com/settings/fluctuateplus/access-tokens. Pick
"Granular" -> "Read and write packages" -> tick "Bypass 2FA".

Put the token in `.npmrc` so the install works without a login prompt:

```
//registry.npmjs.org/:_authToken=YOUR_TOKEN
```

## Private installs

If you do not want the package on the public registry, three ways to install
it privately:

**From a tarball.** Works right now, no npm account needed. Run the command
from the folder that holds the tarball:

```
npm install -g ./fluctuateplus-enzocli-1.0.0.tgz
```

Or give the full path, which works from any directory:

```
npm install -g /path/to/fluctuateplus-enzocli-1.0.0.tgz
```

If npm complains with `ENOENT ... Could not read package.json`, you are in the
wrong folder. npm only looks for `package.json` in the current directory, so
either `cd` into the folder that has it, or use the absolute path above.

**From a git repo.** Put this folder in a private GitHub or GitLab repo, then:

```
npm install -g git+https://github.com/you/enzocli.git
```

**From the npm registry, privately.** Log in as the account that owns the
scope, then publish with restricted access:

```
npm login --scope=@yourname
npm run publish:private
```

Users need access granted from the npm package page, or on a paid plan it
stays private to your account.

## First run

The app asks for an OpenRouter API key:

```
/key sk-or-v1-...
```

You can also set it as an environment variable:

```
export OPENROUTER_API_KEY=sk-or-v1-...
```

The key is stored in `~/.config/ai-cli/config.json` with owner-only permissions.

## Commands

Type `/` in the chat box to see every command in a dropdown.

| Command | What it does |
| --- | --- |
| `/key <api-key>` | save your OpenRouter API key |
| `/model <id>` | set the model, e.g. `openai/gpt-4o-mini` |
| `/models <query>` | search the available models |
| `/system <text>` | set the system prompt |
| `/cd <dir>` | work in another directory, `..` works too (for this session) |
| `/dir` | show the directory the AI works in |
| `/tools on\|off` | let the AI read, write and run commands in that directory |
| `/autocompact on\|off` | compact the context when it gets large |
| `/interrupt` | stop the AI while it is replying |
| `/clear` | clear the conversation |
| `/restart` | restart the CLI |
| `/update` | install the latest Enzo from npm |
| `/connect` | connect another provider |
| `/help` | show the help |
| `/exit` or `/quit` | quit |

## Updating

Type this in the chat and Enzo installs the newest version of itself from npm:

```
/update
```

It works out the package name from the folder Enzo runs out of, runs
`npm install -g <package>@latest` and shows you what npm said. Run `/restart`
afterwards so the new version is used. Pass a name to update something else:

```
/update @scope/name
```

## Connecting a provider

Type this in the chat:

```
/connect
```

A small panel opens in front of the chat. Search for a provider, pick one with
the arrow keys and press enter. A second panel then asks for the API key, and
enter saves it. The esc button in the corner, the escape key, or a click on the
dimmed area all close the panel without changing anything.

OpenRouter is the only provider so far. Adding another one means putting an
entry in the PROVIDERS list in ai_cli.py with its name, its urls and where to
get a key.

## What the AI can do

The AI gets tools to list, read, write, rename and delete files, to run shell
commands, and to generate images. Everything is sandboxed to the working
directory, and the CLI config file stays off limits.

## Without npm

The app is a single Python file, so you can also just run it:

```
pkg install python
python -m pip install textual httpx
python ai_cli.py
```

## Development

```
npm test            # check the package and the launcher
npm pack            # build the tarball
```

`npm pack` writes `fluctuateplus-enzocli-1.0.0.tgz` next to the source. It is
excluded from the package itself, so it never ends up inside a published copy.
