import re
from server.config import Config

_DELEG = re.compile(r'([a-zA-Z0-9_\-#]+)\s*:\s*"([^"]*)"')
_ATTACH = re.compile(r'([a-zA-Z0-9_\-#]+)\s*:\s*(.+)')

def parse_markers(text: str) -> dict:
    delegate = []
    for block in re.findall(r'\[DELEGATE([^\]]*)\]', text):
        delegate += [(n, t) for n, t in _DELEG.findall(block)]
    attach = []
    for block in re.findall(r'\[ATTACH([^\]]*)\]', text):
        m = _ATTACH.match(block.strip())
        if m:
            attach.append((m.group(1).strip(), m.group(2).strip()))
    # [MSG name:"..."] = tin nhắn agent→agent (bus). name có thể là 'all' (broadcast).
    msg = []
    for block in re.findall(r'\[MSG([^\]]*)\]', text):
        msg += [(n, t) for n, t in _DELEG.findall(block)]
    say = re.search(r'\[SAY:\s*(.*?)\]', text, re.S)
    ask = re.search(r'\[ASK:\s*(.*?)\]', text, re.S)
    return {"delegate": delegate, "attach": attach, "msg": msg,
            "say": say.group(1).strip() if say else None,
            "ask": ask.group(1).strip() if ask else None}

def _lead(cfg: Config):
    return next((i for i in cfg.instances if i.role == "Lead"), cfg.instances[0])

def _by_name(cfg: Config, name: str):
    return next((i for i in cfg.instances if i.name == name), None)

def _apply_attach(task: str, inst_name: str, attach: list) -> str:
    from server.context_manager import route_context
    prefix = ""
    for name, path in attach:
        if name != inst_name:
            continue
        r = route_context(path)
        if r["mode"] == "inline":
            prefix += f"[Context từ {path}]\n{r['content']}\n\n"
        elif r["mode"] == "rag":
            prefix += f"[Context lớn tại {path}] {r['hint']}\n\n"
        # mode == "skip": bỏ qua, không chèn gì
    return prefix + task if prefix else task

def _deliver_inbox(bus, inst_name: str, task: str) -> str:
    """Nạp tin CHƯA đọc gửi cho inst_name (bus A2A) vào đầu prompt rồi consume."""
    pending = bus.inbox(inst_name)
    if not pending:
        return task
    lines = "\n".join(f"- {m.sender}: {m.text}" for m in pending)
    bus.consume([m.id for m in pending])
    return f"[📨 Tin từ đồng đội (qua bus)]\n{lines}\n\n{task}"


def run_turn(cfg, bb, user_text, agent_runner) -> str:
    from server.adapters import run_agent
    from server.bus import BUS
    agent_runner = agent_runner or run_agent
    lead = _lead(cfg)
    bb.add("user", "User", user_text)
    max_rounds = cfg.settings.get("max_rounds", 3)
    prompt = (f"Transcript:\n{bb.transcript_text()}\n\n"
              "Bạn là Lead. Phân việc bằng marker [DELEGATE inst:\"...\"] nếu cần. "
              "Muốn 2 agent trao đổi trực tiếp (không qua bạn) thì nhắn bằng bus: "
              "[MSG tên-agent:\"nội dung\"] (tên 'all' = gửi mọi agent); tin sẽ được nạp "
              "vào prompt của agent đó ở lượt sau. Khi đủ thông tin trả lời cuối bằng "
              "[SAY: ...]. Instances: "
              + ", ".join(f"{i.name}({i.role})" for i in cfg.instances if i.role != "Lead"))
    for _ in range(max_rounds):
        out = agent_runner(lead, prompt)
        bb.add(lead.name, "Lead", out)
        m = parse_markers(out)
        for to, txt in m["msg"]:            # Lead có thể nhắn thẳng cho agent (bus)
            BUS.post(lead.name, to, txt)
        if m["say"]:
            return m["say"]
        if m["ask"]:
            return m["ask"]
        results = []
        for name, task in m["delegate"]:
            inst = _by_name(cfg, name)
            if not inst:
                results.append(f"{name}: (không có instance)"); continue
            task = _apply_attach(task, inst.name, m["attach"])
            task = _deliver_inbox(BUS, inst.name, task)   # nạp tin đồng đội gửi trước đó
            res = agent_runner(inst, task)
            bb.add(inst.name, inst.role, res)
            for to, txt in parse_markers(res)["msg"]:      # agent nhắn agent khác (bus)
                BUS.post(inst.name, to, txt)
            results.append(f"{inst.name}: {res}")
        prompt = (f"Transcript:\n{bb.transcript_text()}\n\n"
                  "Kết quả delegate ở trên. Nếu đủ, trả lời cuối bằng [SAY: ...].")
        if not m["delegate"]:
            return out  # Lead trả thẳng không marker
    return "Đã đạt giới hạn vòng, chưa có kết luận."
