# MyComp Bot Windows: คู่มือย่อ

คู่มือติดตั้ง, OAuth, Tailscale Funnel, log และการกู้คืนหลังลง Windows ใหม่ อยู่ที่ [README หลัก](../README.md)

สำหรับผู้พัฒนาที่ clone source แล้ว:

```powershell
PowerShell -ExecutionPolicy Bypass -File '.\windows\Run MyComp Bot.ps1'
```

โปรดอย่า commit `.env`, OAuth token/callback, owner consent code, logs, `.venv` หรือ build output

ตั้งแต่รุ่น 1.1.4 กด **Update MyComp Bot** ในหน้าต่างหรือเมนู tray เพื่ออัปเดตจาก GitHub Release ได้ โปรแกรมจะติดตั้งแล้วเปิดกลับเอง และเก็บการตั้งค่าเดิมไว้ รายละเอียดการอัปเดตอยู่ใน `%LOCALAPPDATA%\MyComp Bot\update.log`.
