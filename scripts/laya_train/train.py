"""Fine-tune Laya's English checkpoint on WorldFin's sector question, on one CUDA GPU.

Adapted from the upstream notebook (NandhaKishorM/laya,
notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb) for a single GPU and our
data: `sector_train.json` next to this file (or --data), never the gold set.

    python scripts/laya_train/train.py OUTPUT_DIR [--mode lora|full] [--epochs 4]

Needs a CUDA build of torch plus `laya`, `transformers`, `safetensors`,
`huggingface_hub`. Load the result with FINSCRAPE_LAYA_MODEL=OUTPUT_DIR.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from laya import Agent
from laya.agent import _fix_tokenizer_config
from laya.common import (
    QTYPES,
    build_model,
    build_sequence,
    proper_reward,
    render_options,
)
from safetensors.torch import load_file, save_file
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from finscrape.analysis.laya import _QUESTIONS  # noqa: E402

BASE = "convaiinnovations/laya"
SEED = 20260929
PROGRESS = (
    Path(os.environ.get("LAYA_FT_HOME", Path.home() / "laya-ft")) / "progress.txt"
)


class Meter:
    """Prints and rewrites PROGRESS about once a minute with rate and ETA."""

    def __init__(self, phase: str, total: int):
        self.phase, self.total, self.t0, self.last = (
            phase,
            max(total, 1),
            time.time(),
            0.0,
        )
        self.base = 0  # work done before this process started (a resumed run)

    def __call__(self, done: int, extra: str = "", force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last < 60:
            return
        self.last = now
        rate = (done - self.base) / max(now - self.t0, 1e-9)
        eta = (self.total - done) / rate if rate else 0.0
        gpu = (
            torch.cuda.max_memory_reserved() / 2**30 if torch.cuda.is_available() else 0
        )
        line = (
            f"{time.strftime('%d %b %H:%M')}  {self.phase} {done}/{self.total}"
            f" ({100 * done / self.total:.1f}%)  {rate:.2f}/s"
            f"  eta {eta / 3600:.1f}h (~{time.strftime('%H:%M', time.localtime(now + eta))})"
            f"  gpu {gpu:.1f}G {extra}"
        )
        print(line, flush=True)
        PROGRESS.write_text(line + "\n", "utf-8")


def item(tok, cfg, state: str, q: dict, target: list[float]) -> dict | None:
    crit = q["criteria"]
    seq, markers = build_sequence(
        tok,
        state,
        {"t": "choice", "ins": q["instructions"], "crit": crit},
        cfg["max_len"],
        cfg["head_max_len"],
    )
    if len(markers) != len(render_options({"t": "choice", "crit": crit})):
        return None
    return {"ids": seq, "markers": markers, "qtype": QTYPES["choice"], "target": target}


def collate(items: list[dict], pad_id: int) -> dict:
    n, width = len(items), max(len(it["ids"]) for it in items)
    kmax = max(len(it["markers"]) for it in items)
    ids = torch.full((n, width), pad_id, dtype=torch.long)
    att = torch.zeros((n, width), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long)
    mmask = torch.zeros((n, kmax), dtype=torch.bool)
    target = torch.zeros((n, kmax))
    for i, it in enumerate(items):
        ids[i, : len(it["ids"])] = torch.tensor(it["ids"])
        att[i, : len(it["ids"])] = 1
        k = len(it["markers"])
        mpos[i, :k] = torch.tensor(it["markers"])
        mmask[i, :k] = True
        target[i, :k] = torch.tensor(it["target"])
    qtype = torch.tensor([it["qtype"] for it in items])
    return {
        "w": torch.tensor([it.get("w", 1.0) for it in items]),
        "ids": ids,
        "att": att,
        "mpos": mpos,
        "mmask": mmask,
        "target": target,
        "qtype": qtype,
    }


def fit_temperature(pairs: list[tuple[list[float], list[float]]]) -> float:
    """Softmax temperature that best fits held-out targets (upstream `fit_one_temp`)."""
    if len(pairs) < 10:
        return 1.0
    kmax = max(len(z) for z, _ in pairs)
    logits = torch.full((len(pairs), kmax), -1e4)
    target = torch.zeros((len(pairs), kmax))
    for i, (z, t) in enumerate(pairs):
        logits[i, : len(z)] = torch.tensor(z)
        target[i, : len(t)] = torch.tensor(t)
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():
        opt.zero_grad()
        loss = -(target * torch.log_softmax(logits / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss

    opt.step(closure)
    return float(torch.clamp(log_t.exp(), 0.1, 10.0).item())


def build_items(
    model_dir: str, tok, cfg, data: Path, balance: bool = False, limit: int = 0
) -> list[dict]:
    """Sector and direction items. A case missing its direction label is trained on
    the starting model's own direction answer, so sector training does not drift it."""
    cases = json.loads(data.read_text("utf-8"))["cases"]
    if limit:
        cases = cases[:: max(1, len(cases) // limit)][:limit]
    sector_q, direction_q = _QUESTIONS["sector"], _QUESTIONS["direction"]
    keys = list(sector_q["criteria"])
    directions = list(direction_q["criteria"])
    base = Agent(model_dir, device="cuda")
    items = []
    meter = Meter("building items", len(cases))
    for n, case in enumerate(cases):
        meter(n)
        state, sector, direction = (
            case["subject"],
            case.get("sector"),
            case.get("direction"),
        )
        if sector:
            # "other" is not an option; a flat target teaches low confidence, which
            # finscrape.analysis.laya reads as "other".
            target = (
                [1.0 if k == sector else 0.0 for k in keys]
                if sector in keys
                else [1.0 / len(keys)] * len(keys)
            )
            if it := item(tok, cfg, state, sector_q, target):
                items.append(it)
        if direction in directions:
            target = [1.0 if k == direction else 0.0 for k in directions]
        elif sector:
            probs = base.predict(state, {"direction": direction_q})["answers"][
                "direction"
            ]
            probs = probs.get("probabilities") or probs.get("probs") or {}
            target = [float(probs.get(k, 0.0)) for k in directions]
            target = [v / (sum(target) or 1.0) for v in target]
        else:
            continue
        if it := item(tok, cfg, state, direction_q, target):
            if direction in directions:
                it["label"] = direction
            items.append(it)
    del base
    torch.cuda.empty_cache()
    if balance:
        # Weight hard direction labels so each class carries equal total loss,
        # instead of repeating the rarer ones.
        counts = Counter(it["label"] for it in items if "label" in it)
        for it in items:
            if "label" in it:
                it["w"] = sum(counts.values()) / (len(counts) * counts[it["label"]])
        print(
            "direction weights:",
            {
                k: round(sum(counts.values()) / (len(counts) * v), 2)
                for k, v in counts.items()
            },
            flush=True,
        )
    return items


def plain_state(model) -> dict:
    """State dict in the stock checkpoint layout, with any LoRA adapters merged in."""
    enc = model.encoder
    if not hasattr(enc, "merge_adapter"):
        return model.state_dict()
    enc.merge_adapter()
    base = enc.get_base_model()
    sd = {
        f"encoder.{k.replace('.base_layer', '')}": v.detach().clone()
        for k, v in base.state_dict().items()
        if "lora_" not in k
    }
    enc.unmerge_adapter()
    sd.update(
        {k: v for k, v in model.state_dict().items() if not k.startswith("encoder.")}
    )
    return sd


def save(model, tok, cfg: dict, out: Path, temps: list[float]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    save_file(
        {k: v.half().contiguous().cpu() for k, v in plain_state(model).items()},
        str(out / "model.safetensors"),
    )
    enc = model.encoder
    (
        enc.get_base_model() if hasattr(enc, "get_base_model") else enc
    ).config.save_pretrained(str(out / "encoder"))
    tok.save_pretrained(str(out / "tokenizer"))
    cfg = {
        **cfg,
        "fine_tuned": True,
        "model_name": "laya-worldfin-sector",
        "temperature": temps,
    }
    cfg.pop("temperature_by_options", None)
    (out / "rl_agent_config.json").write_text(json.dumps(cfg, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("output_dir")
    ap.add_argument(
        "--data", type=Path, default=Path(__file__).with_name("sector_train.json")
    )
    # Start from a local checkpoint (the stage-1 full fine-tune) instead of the Hub.
    ap.add_argument("--base", default="")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--micro-batch", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=8)
    # LoRA freezes the encoder and learns low-rank adapters: less overfit on a few
    # hundred headlines, and each daily run starts again from the stock weights.
    ap.add_argument("--mode", choices=["lora", "full"], default="lora")
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--balance-direction", action="store_true")
    ap.add_argument(
        "--smoke", action="store_true", help="overfit a tiny batch, then exit"
    )
    ap.add_argument("--save-every-min", type=float, default=45.0)
    args = ap.parse_args()

    device = torch.device("cuda")
    model_dir = args.base or snapshot_download(
        BASE, ignore_patterns=["multilingual/*", "typed-decisions/*"]
    )
    _fix_tokenizer_config(model_dir)
    cfg = json.loads(Path(model_dir, "rl_agent_config.json").read_text())
    tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    torch.set_float32_matmul_precision("high")
    # Building items runs the base model over every case (up to an hour on stage 1);
    # the cache lets a resumed run skip it and guarantees the same data order.
    cache, ckpt = out / "items.pt", out / "resume.pt"
    key = f"{args.data.resolve()}|{args.data.stat().st_mtime_ns}|{args.balance_direction}|{model_dir}"
    cached = (
        torch.load(cache, weights_only=False)
        if cache.exists() and not args.smoke
        else None
    )
    if cached and cached["key"] == key:
        all_items = cached["items"]
        print(f"{len(all_items)} items from cache", flush=True)
    else:
        all_items = build_items(
            model_dir,
            tok,
            cfg,
            args.data,
            args.balance_direction,
            64 if args.smoke else 0,
        )
        if not args.smoke:
            torch.save({"key": key, "items": all_items}, cache)
            ckpt.unlink(missing_ok=True)  # a checkpoint of other data cannot resume
    order = list(range(len(all_items)))
    random.Random(SEED).shuffle(order)
    n_calib = max(10, len(all_items) // 10)
    calib = [all_items[i] for i in order[:n_calib]]
    train = [all_items[i] for i in order[n_calib:]]
    print(
        f"{len(train)} train items, {len(calib)} held out for calibration", flush=True
    )

    model = build_model(cfg, encoder_dir=os.path.join(model_dir, "encoder"))
    model.load_state_dict(
        load_file(os.path.join(model_dir, "model.safetensors")), strict=True
    )
    model.encoder.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    model.head_checkpointing = True
    enc_lr = 2.5e-5
    if args.mode == "lora":
        from peft import LoraConfig, get_peft_model

        model.encoder = get_peft_model(
            model.encoder,
            LoraConfig(
                r=args.lora_r,
                lora_alpha=2 * args.lora_r,
                lora_dropout=0.05,
                target_modules=["Wqkv", "Wo", "Wi"],
            ),
        )
        enc_lr = 2e-4
    model.to(device).train()

    # No weight decay on biases, norms and embeddings: it only shrinks them toward zero.
    groups = []
    for part, lr in (("encoder.", enc_lr), ("", 1e-4)):
        params = [
            (n, p)
            for n, p in model.named_parameters()
            if p.requires_grad and n.startswith("encoder.") == bool(part)
        ]
        flat = [p for n, p in params if p.ndim < 2 or "embed" in n]
        rest = [p for n, p in params if not (p.ndim < 2 or "embed" in n)]
        groups += [
            {"params": rest, "lr": lr, "weight_decay": 0.01},
            {"params": flat, "lr": lr, "weight_decay": 0.0},
        ]
    print(
        f"{args.mode}: {sum(p.numel() for g in groups for p in g['params']) / 1e6:.1f}M trainable params",
        flush=True,
    )
    if args.mode == "full":
        # fp32 Adam state for 421M params spills past 8 GB into shared memory,
        # which ran stage 1 several times slower; 8-bit state fits.
        import bitsandbytes as bnb

        opt = bnb.optim.AdamW8bit(groups)
    else:
        opt = torch.optim.AdamW(groups)
    group, sigma_start, sigma_end = 4, 0.4, 0.1

    def batch_loss(items: list[dict], sigma: float) -> torch.Tensor:
        b = collate(items, tok.pad_token_id)
        mask = b["mmask"].to(device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logits, act = model(
                b["ids"].to(device),
                b["att"].to(device),
                b["mpos"].to(device),
                mask,
                b["qtype"].to(device),
            )
        logits = logits.float()
        k = mask.sum(-1, keepdim=True).float()
        target = b["target"].to(device)
        # Upstream objective: policy gradient on noisy logits scored by a proper
        # rule, plus soft cross-entropy toward the target.
        eps = torch.randn((group, *logits.shape), device=device) * sigma * mask
        eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
        z = logits.detach().unsqueeze(0) + eps
        q = torch.softmax(z.masked_fill(~mask, -1e4), -1)
        with torch.no_grad():
            r = proper_reward(
                q,
                target.unsqueeze(0),
                b["qtype"].to(device),
                mask,
                w_sph=0.75,
                w_rps=1.0,
            )
            adv = (r - r.mean(0, keepdim=True)) / (
                (r - r.mean(0, keepdim=True)).std() + 1e-6
            )
        logp = -(((z - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma**2)
        w = b["w"].to(device)
        ce = -(target * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)).sum(-1)
        return -(adv * logp * w).mean() + (ce * w).mean() + 0.0 * act.sum()

    gpu_total = torch.cuda.get_device_properties(0).total_memory

    if args.smoke:
        # Overfit the longest items for a few steps: the loss must fall and the peak
        # memory (optimizer state included) must fit the card, or the long run won't.
        longest = sorted(train, key=lambda it: -len(it["ids"]))[: args.micro_batch]
        losses = []
        for _ in range(30):
            loss = batch_loss(longest, sigma_start)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            losses.append(loss.item())
        peak = torch.cuda.max_memory_reserved()
        first, last = sum(losses[:3]) / 3, sum(losses[-3:]) / 3
        print(
            f"smoke: loss {first:.3f} -> {last:.3f}, peak gpu {peak / 2**30:.2f} of {gpu_total / 2**30:.2f} GB"
        )
        if not all(math.isfinite(x) for x in losses) or last >= first:
            raise SystemExit("smoke test failed: loss did not fall")
        if peak > 0.95 * gpu_total:
            raise SystemExit("smoke test failed: would spill past GPU memory")
        print("SMOKE OK")
        return

    updates = max(1, len(train) // (args.micro_batch * args.grad_accum)) * args.epochs
    warmup = max(1, updates // 30)
    sched = torch.optim.lr_scheduler.SequentialLR(
        opt,
        [
            torch.optim.lr_scheduler.LinearLR(opt, 0.01, 1.0, warmup),
            torch.optim.lr_scheduler.CosineAnnealingLR(
                opt, T_max=updates - warmup, eta_min=1e-6
            ),
        ],
        [warmup],
    )
    metrics = (
        PROGRESS.parent
        / "logs"
        / f"metrics-{out.name}-{time.strftime('%Y%m%d-%H%M')}.jsonl"
    )
    metrics.parent.mkdir(parents=True, exist_ok=True)

    def val_loss(n: int = 512) -> float:
        model.eval()
        with torch.no_grad():
            vals = []
            for s in range(0, min(n, len(calib)), 8):
                chunk = calib[s : s + 8]
                b = collate(chunk, tok.pad_token_id)
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    logits, _ = model(
                        b["ids"].to(device),
                        b["att"].to(device),
                        b["mpos"].to(device),
                        b["mmask"].to(device),
                        b["qtype"].to(device),
                    )
                lp = torch.log_softmax(
                    logits.float().masked_fill(~b["mmask"].to(device), -1e4), -1
                )
                vals += (-(b["target"].to(device) * lp).sum(-1)).tolist()
        model.train()
        return sum(vals) / len(vals)

    epoch0, first_start, total, steps = 0, 0, 0.0, 0
    if ckpt.exists():
        # Load to CPU: a GPU copy of the 2.5 GB checkpoint would push training into
        # shared memory for the rest of the run.
        state = torch.load(ckpt, map_location="cpu", weights_only=False)
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        sched.load_state_dict(state["sched"])
        torch.set_rng_state(state["cpu_rng"])
        torch.cuda.set_rng_state(state["cuda_rng"])
        epoch0, first_start, total, steps = (
            state["epoch"],
            state["start"],
            state["total"],
            state["steps"],
        )
        del state
        gc.collect()
        torch.cuda.empty_cache()
        print(f"resumed at epoch {epoch0 + 1}, item {first_start}", flush=True)

    def save_ckpt(epoch: int, start: int) -> None:
        tmp = ckpt.with_suffix(".tmp")
        torch.save(
            {
                "model": model.state_dict(),
                "opt": opt.state_dict(),
                "sched": sched.state_dict(),
                "cpu_rng": torch.get_rng_state(),
                "cuda_rng": torch.cuda.get_rng_state(),
                "epoch": epoch,
                "start": start,
                "total": total,
                "steps": steps,
            },
            tmp,
        )
        os.replace(tmp, ckpt)

    meter = Meter(f"training ({args.mode})", len(train) * args.epochs)
    meter.base = (
        epoch0 * len(train) + first_start
    )  # ETA counts only this session's pace
    last_save = time.time()
    t0 = time.time()
    for epoch in range(epoch0, args.epochs):
        # Shuffle a fresh copy per epoch so a resumed run replays the same order.
        batch_order = train[:]
        random.Random(SEED + epoch).shuffle(batch_order)
        sigma = sigma_start + (sigma_end - sigma_start) * epoch / max(
            1, args.epochs - 1
        )
        if epoch > epoch0 or not first_start:
            total, steps = 0.0, 0
        opt.zero_grad(set_to_none=True)
        start0 = first_start if epoch == epoch0 else 0
        for start in range(start0, len(batch_order), args.micro_batch):
            chunk = batch_order[start : start + args.micro_batch]
            loss = batch_loss(chunk, sigma)
            value = loss.item()
            if not math.isfinite(value) or value > 100:
                raise SystemExit(
                    f"loss diverged ({value}) at item {start}; resume.pt holds the last good state"
                )
            (loss / args.grad_accum).backward()
            steps += 1
            total += value
            if steps % args.grad_accum == 0 or start + args.micro_batch >= len(
                batch_order
            ):
                grad_norm = torch.nn.utils.clip_grad_norm_(
                    model.parameters(), 1.0
                ).item()
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                row = {
                    "t": round(time.time() - t0),
                    "epoch": epoch + 1,
                    "item": start + len(chunk),
                    "loss": round(total / steps, 4),
                    "lr": sched.get_last_lr()[0],
                    "grad_norm": round(grad_norm, 3),
                    "gpu_gb": round(torch.cuda.max_memory_reserved() / 2**30, 2),
                }
                if time.time() - last_save > args.save_every_min * 60:
                    row["val_loss"] = round(val_loss(), 4)
                    save_ckpt(epoch, start + len(chunk))
                    last_save = time.time()
                    print(
                        f"checkpoint at item {start + len(chunk)}, val loss {row['val_loss']}",
                        flush=True,
                    )
                with metrics.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
            spill = (
                " SPILLING"
                if torch.cuda.max_memory_reserved() > 0.95 * gpu_total
                else ""
            )
            meter(
                epoch * len(train) + start + len(chunk),
                f"epoch {epoch + 1}/{args.epochs} loss {total / steps:.4f}{spill}",
            )
        print(
            f"epoch {epoch + 1}/{args.epochs}: loss {total / steps:.4f} ({time.time() - t0:.0f}s)",
            flush=True,
        )
        save_ckpt(epoch + 1, 0)

    print(f"final val loss {val_loss(len(calib)):.4f}", flush=True)
    model.eval()
    pairs = []
    with torch.no_grad():
        for start in range(0, len(calib), 8):
            chunk = calib[start : start + 8]
            b = collate(chunk, tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits, _ = model(
                    b["ids"].to(device),
                    b["att"].to(device),
                    b["mpos"].to(device),
                    b["mmask"].to(device),
                    b["qtype"].to(device),
                )
            for row, it in zip(logits.float().cpu().tolist(), chunk):
                pairs.append((row[: len(it["markers"])], it["target"]))
    temps = list(cfg.get("temperature") or [1.2, 1.2, 1.2])
    temps[QTYPES["choice"]] = fit_temperature(pairs)
    print("choice temperature:", round(temps[QTYPES["choice"]], 3))

    save(model, tok, cfg, out, temps)
    cache.unlink(missing_ok=True)
    ckpt.unlink(missing_ok=True)
    print("saved", out)
    PROGRESS.write_text(
        f"{time.strftime('%d %b %H:%M')}  training done: {out}\n", "utf-8"
    )


if __name__ == "__main__":
    main()
