"""Convert a legacy `pytorch_model.bin` checkpoint to `model.safetensors`.

WHY THIS IS NEEDED

transformers >= 4.56 refuses to call `torch.load` unless torch >= 2.6, because
pickle deserialisation can execute arbitrary code (CVE-2025-32434). The last
PyTorch with Intel-Mac wheels is 2.2.2, so on this machine every legacy
checkpoint is unloadable — and all three encoders this project evaluates
(InLegalBERT, Legal-BERT, DeBERTa-v3) predate safetensors and ship only `.bin`.

WHAT THIS SCRIPT ACTUALLY DOES, AND THE TRADE-OFF

It calls `torch.load` directly, bypassing the transformers guard. That is only
acceptable because of what is being loaded: named repositories from established
research groups, fetched over TLS from the Hugging Face hub, with the hash
recorded below. **Do not point this at a checkpoint from an untrusted source.**
Unpickling a hostile file executes code as you, and the guard exists for a
reason. The safe alternative, where available, is always a repo that already
publishes safetensors.

After conversion the model loads through the normal safetensors path and the
guard is satisfied, so this runs once per model rather than on every load.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TRUSTED_REPOS = {
    "law-ai/InLegalBERT",
    "nlpaueb/legal-bert-base-uncased",
    "microsoft/deberta-v3-base",
}


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def convert(repo_id: str, *, force: bool = False) -> Path:
    import torch
    from huggingface_hub import snapshot_download
    from safetensors.torch import save_file

    if repo_id not in TRUSTED_REPOS and not force:
        raise SystemExit(
            f"{repo_id} is not in the trusted list. Converting means unpickling a "
            f"file, which can execute arbitrary code. Add it to TRUSTED_REPOS "
            f"deliberately, or pass --force if you know what the file is."
        )

    local = Path(
        snapshot_download(
            repo_id=repo_id,
            allow_patterns=["*.json", "*.txt", "*.bin", "*.model", "*.safetensors"],
        )
    )

    target = local / "model.safetensors"
    if target.exists():
        print(f"{repo_id}: already has safetensors, nothing to do")
        return local

    source = local / "pytorch_model.bin"
    if not source.exists():
        raise SystemExit(f"{repo_id}: no pytorch_model.bin at {local}")

    digest = _sha256(source)
    print(f"{repo_id}\n  {source}\n  sha256 {digest}")

    state = torch.load(source, map_location="cpu", weights_only=True)

    # BERT ties the input embeddings to the output decoder, so several entries
    # share one storage. safetensors refuses shared storage, and transformers
    # re-ties on load anyway, so cloning is both necessary and harmless.
    tensors = {
        k: v.clone().contiguous()
        for k, v in state.items()
        if hasattr(v, "clone")
    }
    save_file(tensors, target, metadata={"format": "pt"})

    (local / "converted_by_kwys.json").write_text(
        json.dumps(
            {
                "repo_id": repo_id,
                "source_file": source.name,
                "source_sha256": digest,
                "tensors": len(tensors),
                "reason": "transformers>=4.56 blocks torch.load below torch 2.6 "
                "(CVE-2025-32434); Intel-Mac torch caps at 2.2.2",
            },
            indent=2,
        )
    )
    size = target.stat().st_size / 1e6
    print(f"  wrote {target.name} ({len(tensors)} tensors, {size:.0f} MB)")
    return local


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repos", nargs="*", default=sorted(TRUSTED_REPOS))
    ap.add_argument("--force", action="store_true", help="convert an untrusted repo anyway")
    args = ap.parse_args()
    for repo in args.repos:
        convert(repo, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
