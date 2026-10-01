# MyComp Bot for Windows

MyComp Bot คือ MCP server ที่รันบนเครื่อง Windows ของเรา เพื่อให้ ChatGPT เรียกใช้เครื่องนั้นผ่าน connector ได้ โดยตัวโปรแกรมรันในเครื่องและเก็บค่าไว้ในบัญชี Windows ปัจจุบัน การเชื่อมต่อใช้ HTTPS ของ Tailscale Funnel

คู่มือนี้ตั้งใจให้เปิดแล้วทำงานต่อได้ แม้เป็นเครื่องใหม่หรือเปิดแชต Codex/ChatGPT หน้าต่างใหม่

> อย่าใส่ token, OAuth callback, owner consent code, log ทั้งก้อน หรือชื่อเครื่องจริงลงใน GitHub Issue สาธารณะ

## ลิงก์สำคัญ

- [ดาวน์โหลดตัวติดตั้งล่าสุด](https://github.com/apinanautan/mycomp-bot-windows/releases/latest/download/Install-MyComp-Bot.bat)
- [หน้า Releases](https://github.com/apinanautan/mycomp-bot-windows/releases)
- [Source code](https://github.com/apinanautan/mycomp-bot-windows)
- [แจ้งปัญหา](https://github.com/apinanautan/mycomp-bot-windows/issues)

ไม่จำเป็นต้องติดตั้ง Git บนเครื่องที่จะใช้งาน ตัวติดตั้ง `.bat` จะดาวน์โหลด source ที่ต้องใช้เองจาก GitHub

## ใช้งานแบบเร็วบนเครื่อง Windows ใหม่

สิ่งที่ต้องมี:

1. Windows ที่เข้าอินเทอร์เน็ตได้
2. [Tailscale](https://tailscale.com/download/windows) ติดตั้งและ Sign in แล้ว
3. tailnet ที่อนุญาตให้ใช้ **Tailscale Funnel** บน HTTPS port 443
4. สิทธิ์เปิดไฟล์ `.bat` ในบัญชี Windows ปัจจุบัน

ขั้นตอน:

1. ดาวน์โหลด `Install-MyComp-Bot.bat` จากหน้า **Releases** ไม่ใช่หน้าดู source code ของ GitHub
2. ดับเบิลคลิกไฟล์ `.bat` และรอจนติดตั้งเสร็จ
3. ถ้า Windows ถามเรื่อง Python ตัวติดตั้งจะพยายามติดตั้ง Python 3.11 ผ่าน `winget` ให้เอง
4. เมื่อสำเร็จ ตัวติดตั้งจะแสดงและคัดลอก MCP URL ลักษณะนี้:

   ```text
   https://ชื่อเครื่อง.tailnet.ts.net/mcp
   ```

5. หน้าต่าง MyComp Bot จะเปิดขึ้น ให้ตรวจว่า Local service เป็น `Running` และ Funnel ทำงานอยู่
6. ทำ OAuth ใน ChatGPT ตามหัวข้อถัดไป

ไฟล์ที่ลงไว้ในเครื่องอยู่ที่:

```text
%LOCALAPPDATA%\MyComp Bot Source
%LOCALAPPDATA%\MyComp Bot
```

## เชื่อมกับ ChatGPT ผ่าน OAuth

ใน ChatGPT ให้สร้างหรือเปิด connector ของ MyComp Bot แล้วใส่ MCP endpoint ที่คัดลอกมา ซึ่งต้องจบด้วย `/mcp`

ตัวอย่าง:

```text
https://ชื่อเครื่อง.tailnet.ts.net/mcp
```

จากหน้าตั้งค่า OAuth ของ connector ให้กด **Copy Callback URL** แล้วกลับมาที่ MyComp Bot:

1. ลบข้อความเดิมในช่อง **Your ChatGPT callback URI** ทั้งหมด
2. วาง callback ที่คัดลอกมา **เพียง 1 URL**
3. ห้ามมี comma (`,`) ช่องว่าง URL เก่า หรือ callback สองอันต่อกัน
4. กด **Save & Restart**
5. กลับไปที่ ChatGPT แล้วเชื่อมต่อ/Approve ใหม่

หน้าตั้งค่า connector ควรใช้ OAuth endpoint ที่ MyComp Bot ประกาศจาก MCP server ไม่ต้องนำ token หรือ client secret ของตัวเองไปใส่ เว้นแต่หน้าของ ChatGPT ระบุให้ทำเช่นนั้นโดยชัดเจน

## การใช้งานประจำวัน

หลังติดตั้งครั้งแรก ให้เปิด MyComp Bot จาก Start menu หรือไฟล์นี้:

```text
%LOCALAPPDATA%\MyComp Bot Source\Start MyComp Bot (Tray).bat
```

เมื่อปิดหน้าต่างหลัก โปรแกรมจะซ่อนอยู่ที่ system tray ด้านขวาล่างของ Windows:

- คลิกไอคอนเพื่อเปิดหน้าต่างอีกครั้ง
- คลิกขวาแล้วเลือก **Open MyComp Bot**, **Report Error on GitHub** หรือ **Exit**
- ติ๊ก **Start MyComp Bot automatically when I sign in to Windows** ถ้าต้องการให้เปิดเองทุกครั้งที่ sign in
- ติ๊ก **Start Remote Desktop Commander automatically with MyComp Bot** เพื่อให้ MyComp เรียก `npx -y @wonderwhy-er/desktop-commander@latest remote` เมื่อเปิดขึ้นมา และใช้ **Start Remote Desktop Commander now** เพื่อเริ่มทันที

MyComp Bot ใช้ Windows single-instance lock หากโปรแกรมเปิดอยู่แล้ว การกดเปิดซ้ำจะไม่สร้าง process/tray icon ชุดใหม่ แต่ส่งสัญญาณให้หน้าต่างเดิมแสดงขึ้นมาแทน หลังอัปเดตจากรุ่นเก่าที่เปิดซ้ำอยู่ ให้ Exit ไอคอนเก่าทั้งหมดหนึ่งครั้งแล้วเปิดรุ่นใหม่

การติ๊ก autostart จะสร้างค่า startup เฉพาะผู้ใช้ Windows ปัจจุบัน ไม่ได้ตั้งเป็น Windows service และไม่ต้องใช้สิทธิ์ Administrator
Remote Desktop Commander ใช้ค่า autostart แยกต่างหาก โดย MyComp จะตรวจ process เดิมก่อนเริ่มเพื่อป้องกันการเปิดซ้ำ และเขียน output ไว้ที่ `%LOCALAPPDATA%\MyComp Bot\remote-desktop-commander.log`.

### อัปเดตจากในโปรแกรม

กด **Update MyComp Bot** ในหน้าต่างหรือเมนู tray โปรแกรมจะตรวจ GitHub Release ล่าสุด ถ้ามีรุ่นใหม่ให้ยืนยันเพื่อติดตั้ง จากนั้นโปรแกรมจะปิดและเปิดกลับเอง ไม่ต้องดาวน์โหลดตัวติดตั้งใหม่ทุกครั้ง ค่า OAuth, Allowed folders, permission profile และ Tailscale ที่เก็บไว้ในเครื่องยังใช้ต่อได้

การอัปเดตต้องใช้อินเทอร์เน็ตเพื่อดาวน์โหลด source และ dependency หากติดตั้ง dependency ไม่สำเร็จ ตัวอัปเดตจะคืนไฟล์ source เดิมก่อนเปิดโปรแกรมกลับ รายละเอียดอยู่ที่ `%LOCALAPPDATA%\MyComp Bot\update.log` ส่วน checkout สำหรับพัฒนาที่มีการแก้ไขใน Git จะต้องเก็บการแก้ไขก่อนจึงอัปเดตได้

รุ่นก่อน 1.1.4 ยังไม่มีปุ่มนี้ ต้องติดตั้งรุ่น 1.1.4 ครั้งเดียวก่อน แล้วรุ่นถัดไปกดอัปเดตจากโปรแกรมได้

### สิทธิ์ที่ควรรู้

MyComp Bot จำกัดการทำงานด้วย Allowed folders, permission profile และ executable allowlist อย่าเพิ่มโฟลเดอร์หรือโปรแกรมโดยไม่จำเป็น หากต้องอนุญาต shell ค่าเริ่มต้นรองรับ `cmd.exe` และ `powershell.exe`; ถ้าเรียก shell ไม่ได้ ให้ตรวจค่าพวกนี้ในหน้าต่างโปรแกรมก่อน

## เลือกวิธีเชื่อมต่อ

เลือกใช้เพียงหนึ่งวิธีในแต่ละครั้ง:

| วิธี | ใช้เมื่อ | URL คงที่ไหม | หมายเหตุ |
| --- | --- | --- | --- |
| **Tailscale Funnel** | ติดตั้งผ่าน release `.bat` และใช้งานจริง | คงที่ตราบเท่าที่ชื่อ MagicDNS เดิม | วิธีมาตรฐานของโปรเจกต์นี้ |
| **Cloudflare Quick Tunnel** | ทดสอบชั่วคราวจากปุ่ม Start Free Temporary Tunnel | ไม่คงที่ | ต้องติดตั้ง `cloudflared` เอง และ URL เปลี่ยนเมื่อเริ่มใหม่ |

หากติดตั้งผ่าน release แล้ว ไม่ต้องกด Start Free Temporary Tunnel เพื่อให้ Tailscale ทำงานอยู่แล้ว การเปลี่ยนไป Quick Tunnel ทำให้ต้องแก้ endpoint และ OAuth callback ใหม่ตาม URL ชั่วคราวนั้น

## อาการเสียที่พบบ่อย

| อาการ | สาเหตุที่เป็นไปได้ | วิธีตรวจ/แก้ |
| --- | --- | --- |
| `503: OAuth token request failed, try again later` | callback ผิด, ซ้ำ, หรือ OAuth endpoint ติดต่อไม่ได้ | คัดลอก callback ใหม่จาก ChatGPT แล้ววางเพียง URL เดียว จากนั้น Save & Restart และ Connect ใหม่ |
| `Cannot connect to host ...:443 ssl:default` | เครื่อง offline, Tailscale ไม่ได้ Sign in, Funnel ไม่ทำงาน หรือ DNS/เครือข่ายไปไม่ถึง | เปิด Tailscale ให้สถานะ Connected, ตรวจ Local service และ Funnel ใน MyComp Bot แล้วลองเชื่อมใหม่ |
| กด Approve แล้วไม่กลับ ChatGPT | callback URI ไม่ตรงกับ connector หรือ flow เก่าหมดอายุ | ปิดหน้า authorize เก่า เริ่ม Connect ใหม่จาก ChatGPT และใช้ callback URL ปัจจุบันเพียงหนึ่งค่า |
| `You cannot call a method on a null-valued expression` ใน installer | installer รุ่นเก่ามีปัญหากับไฟล์ `.env` ว่างใน Windows PowerShell 5 | ดาวน์โหลด installer รุ่นล่าสุดจาก Releases แล้วรันใหม่ |
| บอกว่า `pystray` หรือ `Pillow` ไม่มี | dependency ติดตั้งไม่ครบหรือใช้ release เก่า | ใช้ installer ล่าสุด; ถ้ายังเกิด ให้ดู `host-error.log` และ `host-output.log` |
| `local health check did not become ready` | เป็นข้อความสรุป ไม่ใช่สาเหตุสุดท้าย | เปิด log ของ host ด้านล่างเพื่ออ่าน Python traceback จริง แล้วใช้ข้อความนั้นในการแก้ |
| BAT บอก error กว้าง ๆ | การดาวน์โหลดหรือ PowerShell installer ล้มเหลว | อ่าน error ที่หน้าต่าง, Notepad ที่เปิดขึ้น, และ `install-error.log`; BAT รุ่นล่าสุดจะไม่ซ่อน error จริง |
| เครื่องอื่นไม่มี Git | ไม่ใช่ปัญหา | ใช้ `.bat` จาก Releases ได้เลย Git ไม่ใช่ dependency |
| มี tray icon MyComp Bot สองอัน | โปรแกรมรุ่นเก่าถูกเปิดมากกว่าหนึ่งครั้ง | Exit ทั้งสองอันแล้วเปิดรุ่นล่าสุดหนึ่งครั้ง; รุ่นใหม่มี single-instance lock |
| กด Exit แล้วไอคอน/process ไม่หาย | โปรแกรมรุ่นเก่าไม่ได้หยุด `pystray` loop | ใช้รุ่นล่าสุด; Exit จะหยุด tray icon, tunnels, engine และ Tk main loop ครบ |

## Log และการรายงานปัญหา

เมื่อ install หรือเริ่มโปรแกรมไม่สำเร็จ ให้ดูไฟล์เหล่านี้ก่อน:

```text
%LOCALAPPDATA%\MyComp Bot\install-error.log
%LOCALAPPDATA%\MyComp Bot\host-error.log
%LOCALAPPDATA%\MyComp Bot\host-output.log
```

ตัวติดตั้งจะแสดง error จริงในหน้าต่าง, คัดลอกข้อความไว้ใน clipboard และเปิด log ด้วย Notepad เมื่อทำได้ นอกจากนี้อาจเปิดหน้า GitHub Issue แบบร่างให้ แต่ **จะไม่ส่ง log ขึ้น GitHub อัตโนมัติ**: ผู้ใช้ต้องตรวจข้อมูลลับแล้วกด Submit เอง

ก่อนส่ง issue ให้ลบข้อมูลเหล่านี้ออก:

- OAuth callback URL, authorization code, token, secret, owner consent code
- ชื่อเครื่อง, URL ส่วนตัว, ที่อยู่ไฟล์ที่เปิดเผยข้อมูลส่วนบุคคล
- เนื้อหาจาก screenshot/log ที่ไม่เกี่ยวกับ error

## กู้คืนหลังลง Windows ใหม่หรือเผลอลบโปรแกรม

1. ติดตั้งและ Sign in Tailscale บนเครื่องนั้นก่อน
2. ดาวน์โหลด `.bat` ล่าสุดจาก [Releases](https://github.com/apinanautan/mycomp-bot-windows/releases)
3. รัน installer แล้วรอ MCP URL ใหม่/ปัจจุบัน
4. เปิด MyComp Bot แล้ววาง **callback URL ปัจจุบัน** จาก connector ของ ChatGPT
5. Save & Restart แล้ว Connect/Approve ใหม่ใน ChatGPT
6. ติ๊ก autostart หากต้องการ

ชื่อ MagicDNS เดิมอาจเปลี่ยนเมื่อเปลี่ยนเครื่องหรือเอาเครื่องออกจาก tailnet หาก MCP URL เปลี่ยน ต้องแก้ URL ใน connector และทำ OAuth ใหม่ การมี GitHub repository และ release ช่วยให้ติดตั้งซ้ำได้ แต่ไม่ควรนำ OAuth secret หรือไฟล์ตั้งค่าส่วนตัวไป commit

## เริ่มงานต่อใน Codex/ChatGPT หน้าต่างใหม่

คัดลอกข้อความนี้ไปเปิดแชตใหม่ได้:

```text
โปรเจกต์คือ apinanautan/mycomp-bot-windows บน Windows
โปรดอ่าน README.md ก่อนทำงาน
เป้าหมาย: ตรวจ MyComp Bot แบบไม่ทำลายค่า OAuth/Allowed folders
ตรวจตามลำดับ: Tailscale Connected → Funnel/HTTPS → Local service 127.0.0.1:8645 → MCP URL /mcp → callback URL มีเพียงหนึ่งค่า → log ใน %LOCALAPPDATA%\MyComp Bot
ห้าม commit token, OAuth callback, owner consent code, log หรือ .env
ถ้าจะแก้โค้ด ให้ตรวจ git status ก่อนและรายงาน error จริงจาก host-error.log/host-output.log
```

สำหรับ source checkout ให้เริ่มจาก:

```powershell
git status --short --branch
Get-Content -Raw README.md
Get-Content -Raw AGENTS.md
```

การแก้โค้ดที่กระทบ host ควรทดสอบบน Windows จริง และรันชุดทดสอบตาม `AGENTS.md` เมื่อเกี่ยวข้อง

## สำหรับผู้พัฒนา

หาก clone source แล้ว ต้องมี Python 3.11 จากนั้นรัน:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

launcher จะสร้าง `.venv` ใน repository และติดตั้ง dependency จาก `requirements.lock` อย่า commit `.venv`, `.env`, token, logs หรือ build output

---

คู่มือ Windows ฉบับย่ออยู่ที่ [windows/README.md](windows/README.md) แต่ให้ยึด README หน้านี้เป็นข้อมูลการติดตั้งและแก้ปัญหาหลัก
