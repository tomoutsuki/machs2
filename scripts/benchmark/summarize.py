import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="inp", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.inp, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    lines = ["# Benchmark Summary", "", "| Mode | Write ms | Read ms | Decrypt ms | Avg bytes |", "|---|---:|---:|---:|---:|"]
    for mode, metrics in data["modes"].items():
        lines.append(
            "| {0} | {1:.2f} | {2:.2f} | {3:.2f} | {4:.1f} |".format(
                mode,
                metrics["write_latency_ms_avg"],
                metrics["read_latency_ms_avg"],
                metrics["decrypt_latency_ms_avg"],
                metrics["storage_overhead_bytes_avg"],
            )
        )

    lines.extend(["", "## Notes", "- CPU/memory: run `docker stats` while benchmark executes."])

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    main()
