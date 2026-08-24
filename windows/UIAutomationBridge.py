import json, sys
from pywinauto import Desktop

def elem(w):
    r=w.rectangle()
    info=w.element_info
    return {"name":w.window_text(),"automation_id":getattr(info,"automation_id","") or "","control_type":getattr(info,"control_type","") or "","process_id":w.process_id(),"handle":int(w.handle or 0),"is_enabled":w.is_enabled(),"is_offscreen":not w.is_visible(),"bounds":{"x":r.left,"y":r.top,"width":r.width(),"height":r.height()},"value":None}

def matches(w,s):
    e=elem(w); n=e["name"] or ""
    if s.get("handle") is not None and e["handle"]!=int(s["handle"]): return False
    if s.get("process_id") is not None and e["process_id"]!=int(s["process_id"]): return False
    if s.get("pid") is not None and e["process_id"]!=int(s["pid"]): return False
    if s.get("name") and n!=str(s["name"]): return False
    q=s.get("name_contains") or s.get("app_name")
    if q and str(q).lower() not in n.lower(): return False
    if s.get("automation_id") and e["automation_id"]!=str(s["automation_id"]): return False
    if s.get("control_type") and e["control_type"]!=str(s["control_type"]).replace("ControlType.",""): return False
    return True

def find(s):
    desk=Desktop(backend="uia")
    if s.get("handle"):
        return desk.window(handle=int(s["handle"]))
    for w in desk.windows():
        if matches(w,s): return w
        try:
            for c in w.descendants():
                if matches(c,s): return c
        except Exception: pass
    raise RuntimeError("No Windows UI Automation element matched the selector.")

def main(req):
    action=req.get("action","status"); sel=req.get("selector") or req
    desk=Desktop(backend="uia")
    if action=="status": return {"backend":"pywinauto-uia","available":True}
    if action=="list_windows":
        lim=max(1,min(int(req.get("max_items",req.get("limit",200))),500)); ws=[]
        for w in desk.windows():
            try:
                if matches(w,sel): ws.append(elem(w))
            except Exception: pass
            if len(ws)>=lim: break
        return {"backend":"pywinauto-uia","windows":ws,"count":len(ws)}
    if action in ("observe","observe_summary","observe_changes","inspect_elements"):
        target=find(sel) if any(k in sel for k in ("handle","process_id","pid","name","name_contains","app_name","automation_id","control_type")) else None
        if target is None: raise RuntimeError("A window selector is required for element inspection on Windows.")
        lim=max(1,min(int(req.get("max_items",req.get("limit",100))),300)); max_depth=max(0,min(int(req.get("max_depth",4)),8)); out=[elem(target)]; queue=[(target,0)]; qi=0
        while qi < len(queue) and len(out) < lim:
            parent,depth=queue[qi]; qi+=1
            if depth>=max_depth: continue
            try: children=parent.children()
            except Exception: continue
            for c in children:
                try: out.append(elem(c))
                except Exception: continue
                if len(out)>=lim: break
                queue.append((c,depth+1))
        return {"backend":"pywinauto-uia","root":out[0],"elements":out,"count":len(out)}
    t=find(sel)
    if action=="find_element": return {"backend":"pywinauto-uia","found":True,"element":elem(t)}
    if action in ("focus","activate_app"): t.set_focus(); return {"backend":"pywinauto-uia","element":elem(t)}
    if action in ("click","menu_select"): t.click_input(); return {"backend":"pywinauto-uia","invoked":True,"method":"click_input","element":elem(t)}
    if action=="set_value": t.set_edit_text(str(req.get("value",""))); return {"backend":"pywinauto-uia","value_set":True,"element":elem(t)}
    if action=="close_window": t.close(); return {"backend":"pywinauto-uia","action":action}
    if action=="minimize_window": t.minimize(); return {"backend":"pywinauto-uia","action":action}
    raise RuntimeError(f"Unsupported action: {action}")

try:
    req=json.loads(sys.stdin.read().lstrip("\ufeff")); print(json.dumps({"ok":True,"result":main(req),"error":""},ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok":False,"result":None,"error":str(e)},ensure_ascii=False)); sys.exit(1)
