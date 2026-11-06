# MyComp Bot Windows: คู่มือย่อ

คู่มือติดตั้ง, OAuth, Tailscale Funnel, log และการกู้คืนหลังลง Windows ใหม่ อยู่ที่ [README หลัก](../README.md)

สำหรับผู้พัฒนาที่ clone source แล้ว:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

โปรดอย่า commit `.env`, OAuth token/callback, owner consent code, logs, `.venv` หรือ build output

ตั้งแต่รุ่น 1.1.4 กด **Update MyComp Bot** ในหน้าต่างหรือเมนู tray เพื่ออัปเดตจาก GitHub Release ได้ โปรแกรมจะติดตั้งแล้วเปิดกลับเอง และเก็บการตั้งค่าเดิมไว้ รายละเอียดการอัปเดตอยู่ใน `%LOCALAPPDATA%\MyComp Bot\update.log`.
## Release 1.1.10: one-click updates from dirty source checkouts

Click **Update MyComp Bot** in the main window or system tray, approve the
version prompt, and let MyComp Bot download the release itself. Even when the
currently running copy is a Git checkout with local changes, the updater now
installs a **separate versioned app copy** under
`%LOCALAPPDATA%\\MyComp Bot\\versions\\vX.Y.Z`, creates its Python
virtual environment and installs locked dependencies there. It never writes
release files over the source checkout or removes its uncommitted changes.
The update helper runs only after user confirmation, waits for the old app to
exit, starts the newly installed app, checks its health, and retargets matching
MyComp Bot shortcuts and auto-start to the managed install. Existing user
settings remain in `%LOCALAPPDATA%\\MyComp Bot`; previous versions remain
available for recovery. A failure leaves the source checkout intact.

**Bootstrap note:** a previously running v1.1.9 instance still has its old
updater loaded; close and reopen it manually once after pulling this fix, or
launch the new v1.1.10 installation once. Subsequent releases update using
this new one-click flow. Do not bypass the old updater's dirty-check guard.

## Release 1.1.9: named dual-transport plugin prompt

In **OpenAI Tunnel**, click **พรอมต์สร้างปลั๊กอิน**. The app first asks
**ต้องการตั้งชื่อปลั๊กอินใหม่ว่าอะไร?** and then opens the prompt viewer
with **คัดลอกพรอมต์**. Cancelling the name question creates no prompt.

The generated prompt names the user-selected plugin and includes both the
saved Tailscale HTTPS MCP endpoint (including its actual path and port) and
the saved Secure MCP Tunnel ID and shared local runtime binding. It asks
the plugin builder to verify both transports, perform safe tools/list and
read-status tests, preserve existing authentication and permissions, and
use failover only if actually supported. Never replay an uncertain
side-effecting command on failover. Localhost is not a cloud endpoint.
No API key, token, or secret is included.

The original orange/yellow robot icon, system tray startup and existing
shortcut icon remain unchanged.

## Release 1.1.8: Secure MCP Tunnel plugin prompt

Open the **OpenAI Tunnel** settings window from the application menu or
**Tunnel / API key** in the system tray. Choose **พรอมต์สร้างปลั๊กอิน** to
see the generated instructions, then **คัดลอกพรอมต์** to copy them.
The text uses only the Tunnel ID currently saved in local settings and the
same local MCP endpoint passed to the Tunnel runtime; there is no fallback ID.
Invalid or missing IDs are rejected. The prompt never reads or copies the
API key, DPAPI secrets, tokens or .env. It warns ChatGPT that localhost is
not a public address and that runtime readiness is not evidence of successful
ChatGPT tool calls. Secure Tunnel plugin support must be verified before
claiming connectivity; no connector URL is invented.

## Release 1.1.7: tray and single-flight tools

MyComp Bot now starts **hidden in the Windows system tray**, keeping the
engine available without opening a foreground window. Double-click the tray
icon or select **Open MyComp Bot** to show its window. The same approved
orange robot icon is used in the window, system tray, and existing MyComp
desktop/Start Menu shortcuts that target this installation.

To enter or change Tunnel ID and the restricted API key, right-click the
tray icon and select **Tunnel / API key** (or open the window and use the
**OpenAI Tunnel** menu). The API key is stored using Windows DPAPI; never
commit or share it. Other Tailscale routes are not changed by this menu.

The eight fixed MCP tools use one in-flight call per verified OAuth client
and canonical tool name, with independent tools/clients able to run
concurrently. Duplicate calls are skipped and receive the last completed
result for that queue if available. Timeouts are still enforced by the
original individual tool executors. No new MCP tool is exposed.

To update yourself, right-click the tray icon, choose **Update MyComp Bot**,
review the version prompt and confirm. Updating from a dirty Git development
checkout is deliberately refused; use an installed copy. The updater
downloads the stable tag's GitHub source archive and only after you confirm
does it hand off to the update helper; nothing is installed as part of
publishing a GitHub Release.

# OpenAI Tunnel

Open the **OpenAI Tunnel** menu in MyComp Bot. Enter a Tunnel ID and a
restricted runtime API key with only **Tunnels Read/Use**, enable automatic
connection, then choose **Save and connect**. A blank key preserves the saved key.
The official `tunnel-client.exe` must be installed in `%LOCALAPPDATA%/MyComp Bot/bin`.

Settings live in `%LOCALAPPDATA%/MyComp Bot/openai-tunnel/settings.json`.
The key is stored separately as `key.dpapi`, encrypted for the current Windows
user. Do not copy it to other machines or include it in installers. Configure
each machine separately. Runtime retries use bounded backoff; errors are in
`runtime.log`. Readiness is not proof of ChatGPT access: configure the connector
and verify a real MyComp tool call before removing the old transport.
