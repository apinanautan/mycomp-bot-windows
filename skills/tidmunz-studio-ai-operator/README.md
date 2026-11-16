# Tidmunz Studio AI Operator

Portable source package for the Tidmunz Studio AI Operator ChatGPT plugin, version 0.3.11.

## Install on another ChatGPT personal account

1. Download this folder as part of the repository or package it as a ZIP containing plugin.json, .codex-plugin/, .app.json and skills/.
2. In the destination ChatGPT account, use its available private-plugin creation/import flow to import the archive. This GitHub folder does **not** automatically install a ChatGPT plugin or make the original personal plugin publicly discoverable.
3. Connect an authorized MyComp Bot / Tailscale plugin in the destination account. Update the app dependency manifest (.app.json) with the destination account's actual installed app binding, if supported by its importer. The included manifest intentionally has no account-specific app ID.
4. Select and verify the target computer's authenticated device ID, then verify the local Tidmunz Studio installation and project before taking actions.
5. Replace the generic <TIDMUNZ_SOURCE_DIR> and <TIDMUNZ_INSTALL_DIR> examples in skills with paths discovered on the target Windows machine.

Never publish tokens, Mobile Web URLs, OAuth secrets, Tailscale endpoints, personal machine IDs, or production receipts. Do not share credentials from the original computer. Importing the plugin alone does not grant remote computer access.

Source repository: https://github.com/tidmunzsocial-lab/tidmunz-studio
## Central skill source

GitHub contains the portable, credential-free skill instructions. A separate ChatGPT plugin instance does **not** auto-update when these files change. An installed plugin or connected agent must explicitly fetch relevant skill instructions at task time, and updating a plugin's embedded skills requires its platform-supported release/import mechanism. Keep personal machine paths, account-specific .app.json bindings, credentials and workstation IDs out of this public source.
