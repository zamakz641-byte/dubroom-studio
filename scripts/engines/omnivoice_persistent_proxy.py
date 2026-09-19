from __future__ import annotations
import argparse, importlib.util, json, os, socket, socketserver, subprocess, sys, threading, time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DUBROOM_ROOT = HERE.parents[1]
STATE_DIR = DUBROOM_ROOT / "data" / "tts"
STATE_PATH = STATE_DIR / "omnivoice_persistent_worker.json"
LOCK_PATH = STATE_DIR / "omnivoice_persistent_worker.lock"
IDLE_TIMEOUT_S = int(os.environ.get("DUBROOM_OMNIVOICE_IDLE_TIMEOUT", "1200"))
_MAX_MESSAGE = 32 * 1024 * 1024

def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def _read_state() -> dict[str, Any]:
    try:
        x = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}

def _send(port: int, payload: dict[str, Any], timeout: float = 1800.0) -> dict[str, Any]:
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.create_connection(("127.0.0.1", int(port)), timeout=2.0) as s:
        s.settimeout(timeout)
        s.sendall(raw)
        line = s.makefile("rb").readline(_MAX_MESSAGE)
    if not line:
        raise RuntimeError("Persistent worker closed connection")
    value = json.loads(line.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Invalid persistent worker response")
    return value

def _ping(state: dict[str, Any]) -> bool:
    try:
        return bool(_send(int(state.get("port") or 0), {"cmd":"ping"}, 5.0).get("ok"))
    except Exception:
        return False

class _FileLock:
    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(LOCK_PATH, "a+b")
        self.f.seek(0, os.SEEK_END)
        if self.f.tell() == 0:
            self.f.write(b"0"); self.f.flush()
        self.f.seek(0)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.1)
        else:
            import fcntl
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        return self
    def __exit__(self, *exc):
        try:
            self.f.seek(0)
            if os.name == "nt":
                import msvcrt; msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl; fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()

def _spawn() -> dict[str, Any]:
    env = os.environ.copy()
    env["DUBROOM_OMNIVOICE_DAEMON_CHILD"] = "1"
    env.setdefault("HF_HUB_OFFLINE","1")
    env.setdefault("TRANSFORMERS_OFFLINE","1")
    env.setdefault("HF_DEACTIVATE_ASYNC_LOAD","1")
    env.setdefault("HF_ENABLE_PARALLEL_LOADING","false")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess,"CREATE_NO_WINDOW",0) | getattr(subprocess,"DETACHED_PROCESS",0) | getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--daemon"],
        cwd=str(DUBROOM_ROOT), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, close_fds=(os.name!="nt")
    )
    deadline=time.time()+30
    while time.time()<deadline:
        st=_read_state()
        if st and _ping(st): return st
        time.sleep(.15)
    raise RuntimeError("Timed out starting persistent OmniVoice worker")

def _ensure() -> dict[str, Any]:
    st=_read_state()
    if st and _ping(st): return st
    with _FileLock():
        st=_read_state()
        if st and _ping(st): return st
        STATE_PATH.unlink(missing_ok=True)
        return _spawn()

def submit_request(request: dict[str, Any]) -> dict[str, Any]:
    last=None
    for attempt in range(2):
        try:
            st=_ensure()
            resp=_send(int(st["port"]), {"cmd":"generate","request":request})
            if not resp.get("ok"):
                raise RuntimeError(str(resp.get("error") or "worker failed"))
            result=resp.get("result")
            if not isinstance(result,dict): raise RuntimeError("missing result")
            result["_persistent_worker"]={
                "pid":resp.get("pid"),
                "model_reused":resp.get("model_reused"),
                "prompt_cache_entries":resp.get("prompt_cache_entries"),
                "model_load_s":resp.get("model_load_s"),
            }
            if isinstance(resp.get("events"),list):
                result["_events"]=resp["events"]
            return result
        except Exception as exc:
            last=exc
            STATE_PATH.unlink(missing_ok=True)
            if attempt==0: time.sleep(.2)
    raise RuntimeError(f"Persistent OmniVoice worker failed after restart: {last}")

def stop_worker() -> bool:
    st=_read_state()
    if not st: return True
    try:
        return bool(_send(int(st.get("port") or 0), {"cmd":"shutdown"}, 5.0).get("ok"))
    except Exception:
        return False
    finally:
        STATE_PATH.unlink(missing_ok=True)

def _load_runner():
    path=HERE/"run-tts.py"
    spec=importlib.util.spec_from_file_location("dubroom_run_tts_persistent", path)
    if spec is None or spec.loader is None: raise RuntimeError(f"Cannot import {path}")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

class Runtime:
    def __init__(self):
        self.runner=_load_runner()
        self.model=None
        self.model_root=None
        self.prompt_cache={}
        self.model_load_s=0.0
        self.last_activity=time.time()
        self.lock=threading.RLock()

    def ensure_model(self, root: Path) -> bool:
        root=root.resolve()
        if self.model is not None and self.model_root==root: return True
        self.model=None; self.prompt_cache.clear()
        try:
            import torch
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        except Exception: pass
        t0=time.perf_counter()
        self.model=self.runner._load_omnivoice(root)
        self.model_root=root
        self.model_load_s=time.perf_counter()-t0
        return False

    def generate(self, request: dict[str,Any]):
        with self.lock:
            self.last_activity=time.time()
            reused=self.ensure_model(Path(str(request["model_root"])))
            variant=str(request.get("variant") or "")
            events=[]
            items=request.get("items")
            if isinstance(items,list):
                results=[]
                for pos,raw in enumerate(items,1):
                    item=dict(raw) if isinstance(raw,dict) else {}
                    output=Path(str(item.get("output_path") or "")).resolve()
                    item_id=str(item.get("id") or item.get("_batch_index") or pos)
                    output.parent.mkdir(parents=True,exist_ok=True)
                    try:
                        sr=self.runner._omnivoice_generate(item,self.model,output,variant,self.prompt_cache)
                        if not output.is_file() or output.stat().st_size<44: raise RuntimeError("invalid WAV")
                        ri={"id":item_id,"status":"completed","output_path":str(output),"sample_rate":int(sr),"duration":self.runner._duration(output)}
                    except Exception as exc:
                        ri={"id":item_id,"status":"failed","output_path":str(output),"error":str(exc)[-4000:]}
                    results.append(ri)
                    events.append({"event":"item_completed","index":pos,"total":len(items),**ri})
                final={"status":"completed","batch":True,"completed":sum(x.get("status")=="completed" for x in results),"failed":sum(x.get("status")=="failed" for x in results),"results":results}
                return final,events,reused
            output=Path(str(request["output_path"])).resolve()
            output.parent.mkdir(parents=True,exist_ok=True)
            sr=self.runner._omnivoice_generate(request,self.model,output,variant,self.prompt_cache)
            if not output.is_file() or output.stat().st_size<44: raise RuntimeError("invalid WAV")
            return {"status":"completed","output_path":str(output),"sample_rate":int(sr),"duration":self.runner._duration(output)},events,reused

RUNTIME=Runtime()

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            payload=json.loads(self.rfile.readline(_MAX_MESSAGE).decode("utf-8"))
            cmd=str(payload.get("cmd") or "")
            if cmd=="ping":
                result={"ok":True,"pid":os.getpid(),"loaded":RUNTIME.model is not None}
            elif cmd=="shutdown":
                result={"ok":True,"pid":os.getpid()}
                # daemon_main uses handle_request() rather than serve_forever(),
                # so TCPServer.shutdown() alone never leaves that loop.  Record
                # an explicit stop request that daemon_main consumes after this
                # reply has been flushed.
                self.server.stop_requested=True
            elif cmd=="generate":
                req=payload.get("request")
                if not isinstance(req,dict): raise ValueError("request must be object")
                final,events,reused=RUNTIME.generate(req)
                result={"ok":True,"pid":os.getpid(),"model_reused":reused,"model_load_s":RUNTIME.model_load_s,"prompt_cache_entries":len(RUNTIME.prompt_cache),"events":events,"result":final}
            else:
                raise ValueError(f"unsupported cmd {cmd}")
        except Exception as exc:
            result={"ok":False,"pid":os.getpid(),"error":f"{type(exc).__name__}: {exc}"}
        self.wfile.write((json.dumps(result,ensure_ascii=False)+"\n").encode("utf-8")); self.wfile.flush()

class Server(socketserver.TCPServer):
    allow_reuse_address=True
    stop_requested=False

def daemon_main():
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    with Server(("127.0.0.1",0),Handler) as server:
        _atomic_json(STATE_PATH,{"pid":os.getpid(),"port":int(server.server_address[1]),"python":sys.executable,"started_at":time.time(),"idle_timeout_s":IDLE_TIMEOUT_S})
        server.timeout=1.0
        try:
            while not server.stop_requested:
                server.handle_request()
                if RUNTIME.model is not None and time.time()-RUNTIME.last_activity>IDLE_TIMEOUT_S:
                    break
        finally:
            # Drop model references before the process exits so CUDA memory is
            # released promptly when Story Recapper moves from TTS to export.
            RUNTIME.model=None
            RUNTIME.prompt_cache.clear()
            try:
                import torch
                if torch.cuda.is_available(): torch.cuda.empty_cache()
            except Exception:
                pass
            st=_read_state()
            if int(st.get("pid") or -1)==os.getpid():
                STATE_PATH.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--daemon",action="store_true")
    p.add_argument("--stop",action="store_true")
    p.add_argument("--status",action="store_true")
    a=p.parse_args()
    if a.daemon: daemon_main()
    elif a.stop: print(json.dumps({"stopped":stop_worker()}))
    elif a.status:
        st=_read_state(); print(json.dumps({"state":st,"alive":bool(st and _ping(st))},indent=2))
    else: p.error("choose --daemon/--stop/--status")

if __name__=="__main__": main()
