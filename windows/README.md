# MyComp Bot Windows: คู่มือย่อ

คู่มือติดตั้ง, OAuth, Tailscale Funnel, log และการกู้คืนหลังลง Windows ใหม่ อยู่ที่ [README หลัก](../README.md)

สำหรับผู้พัฒนาที่ clone source แล้ว:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

โปรดอย่า commit `.env`, OAuth token/callback, owner consent code, logs, `.venv` หรือ build output

ตั้งแต่รุ่น 1.1.4 กด **Update MyComp Bot** ในหน้าต่างหรือเมนู tray เพื่ออัปเดตจาก GitHub Release ได้ โปรแกรมจะติดตั้งแล้วเปิดกลับเอง และเก็บการตั้งค่าเดิมไว้ รายละเอียดการอัปเดตอยู่ใน `%LOCALAPPDATA%\MyComp Bot\update.log`.
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
