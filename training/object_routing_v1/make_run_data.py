"""Create a size-limited copy of the routing dataset (deterministic shuffle)."""
import argparse, json, os, random, shutil


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(os.path.join(args.src, "train.jsonl"), encoding="utf-8") if l.strip()]
    random.Random(args.seed).shuffle(rows)
    take = rows[: args.rows] if args.rows > 0 else rows
    os.makedirs(args.dst, exist_ok=True)
    with open(os.path.join(args.dst, "train.jsonl"), "w", encoding="utf-8") as fh:
        for row in take:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    for name in ("validation.jsonl", "test.jsonl"):
        shutil.copyfile(os.path.join(args.src, name), os.path.join(args.dst, name))
    pos = {
        label: sum(1 for r in take if r["labels"][label])
        for label in ("SOCIAL", "PROJECT", "DIRECT_SUPPLY")
    }
    print("rows=%d of %d positives=%s" % (len(take), len(rows), pos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())