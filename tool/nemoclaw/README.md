# nemoclaw: NVIDIA NemoClaw, agents in OpenShell sandboxes

[NemoClaw](https://github.com/NVIDIA/NemoClaw) (Apache-2.0, alpha) runs OpenClaw (its default agent), Hermes or
LangChain Deep Agents Code inside [NVIDIA OpenShell](../openshell/README.md) sandboxes. It adds guided onboarding,
managed inference and network policies. Its CLI `nemoclaw` is a Node.js program and needs Node 22.19 or newer.

```sh
cx tool setup nemoclaw                       # detect, else build the pinned release tag (0.0.135)
cx tool run nemoclaw -- --version
cx tool run nemoclaw -- agents list          # the agent runtimes it can onboard
cx tool run nemoclaw -- profiles list        # the serving profiles and whether this host suits them
cx tool run nemoclaw -- onboard              # in a terminal: an inference provider and a sandbox
```

## How it is installed

npm has no NemoClaw: the npm package `nemoclaw` is a placeholder of 222 bytes, not NVIDIA's. Upstream's installer
(`curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`) clones the repository and builds it, and also changes the
system: nvm, a global `npm link`, the OpenShell package. cMeta builds it the same way into its cache entry and
changes nothing else:

1. `git clone --depth 1 --branch v<version>` with cMeta's git;
2. the installer's own build steps with cMeta's Node.js (`tool/node-js`) and npm's cache inside the entry:
   `node scripts/lib/openshell-sdk-install.mts prepare`, `npm install --ignore-scripts ...`, `... check`, `npm run
   build:cli`, then `npm ci` and `npm run build` of its OpenClaw plugin;
3. a launcher `content/bin/nemoclaw` that runs `bin/nemoclaw.js` with that Node and sets `NEMOCLAW_OPENSHELL_BIN` to
   cMeta's OpenShell CLI (`tool/openshell`).

Linux and macOS. Windows: set it up in WSL2 (`cx tool setup nemoclaw --on=wsl`).

## Onboarding

`nemoclaw onboard` asks for an inference provider (NVIDIA's endpoints with an API key, or a local model) and creates
its own OpenShell gateway and sandbox. It runs in a terminal. A local OpenShell gateway of cMeta is
[`run-openshell-gateway`](../../task/run-openshell-gateway/README.md).
