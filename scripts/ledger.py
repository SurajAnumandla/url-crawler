"""Number ledger for the Part 2 scale design.

Every quantity Part 2 quotes is a row here. Rows are measured (say where, n),
assumed (say why), or derived (computed from other rows — never typed by hand).
Run:  python scripts/ledger.py            -> markdown table
      python scripts/ledger.py --regime few -> few-domain regime table
      python scripts/ledger.py --write   -> regenerate docs/part2-numbers.md
      python scripts/ledger.py --check docs/part2-scale-design.md
"""

import math
import pathlib
import re
import sys
from dataclasses import dataclass

# --- inputs -------------------------------------------------------------------
MONTH_S = 30 * 86_400
URLS = 10e9                       # assumed: brief says "billions"; upper planning case
HOSTS_FEW = 3                     # assumed: brief's example names three domains
HTML_KB = 200                     # assumed: planning median; fixtures are 1.6 and 5.6 MB outliers
COMPRESSION = 5.0                 # measured: gzip on both fixtures, 5.0 and 5.2, n=2
PARSE_MS = (392 + 530) / 2        # measured: mean of CNN/Amazon, n=5 each, Apple M4
TOPICS_MS = (31 + 46) / 2         # measured: same runs
CPU_MS = round(PARSE_MS + TOPICS_MS)  # 500 ms: the rounded value every derivation uses
PROD_FACTOR = 1.5                 # assumed: server core vs M4; PoC validates
VCPU_PER_INSTANCE = 16
UTIL_TARGET = 0.7                 # assumed: headroom for peak
META_KB = 10                      # measured: compact JSON 9,609 / 6,064 B (docs/samples, n=2 successes); 10 KB rounds up
META_COMPRESSION = 4.0            # assumed: column compression on text-heavy rows
FETCH_LATENCY_S = 2.0             # assumed: mean fetch latency for Little's law
PROC_RSS_MB = 400                 # measured: 352-379 MB RSS after one parse, n=1 each -> 400
PAGES_PER_OBJECT = 1_000          # Part 2 decision 6: 1,000 pages per raw object
READS_PER_DAY = 10e6              # assumed: "millions of requests"
CACHE_HIT = 0.9                   # assumed
DEDUP_UNCHANGED = 0.6             # assumed until PoC cycle 2
URL_BYTES = 80                    # assumed mean URL length

# prices: assumed us-east-1 list prices
P_CORE_H = 0.02                   # Graviton spot, per vCPU-hour
P_S3_STD, P_S3_IA, P_S3_DA = 0.023, 0.0125, 0.00099   # per GB-month
P_S3_PUT = 0.005 / 1_000
P_NAT_GB = 0.045
P_IPV4_H = 0.005
P_SQS_M = 0.40
P_DDB_WRU_M = 1.25
P_DDB_GB = 0.25
P_GP3_GB = 0.08
P_EFS_GB = 0.30                   # rejected alternative in Part 2 decision 5
P_LAMBDA_GBS = 0.0000166667
P_LAMBDA_REQ_M = 0.20
# fixed monthly floor for the few-domain regime (assumed list prices, on-demand)
URL_ROW_BYTES = 200               # assumed: frontier row incl. ~80 B URL, tuple header and index entries
CH_REPLICATION = 2                # assumed: production ClickHouse keeps two replicas of each part
FIXED_MANY = {                    # assumed list prices, on-demand, many-domain regime
    "ClickHouse m6g.4xlarge × 6, EBS-backed (3 shards × 2 replicas)": 0.616 * 720 * 6,
    "Aurora PostgreSQL r6g.2xlarge × 2 (control plane + frontier)": 1.038 * 720 * 2,
    "Aurora I/O for frontier refills and released_at updates": 2_500.0,
    "ElastiCache cache.r7g.xlarge × 4 (back queues, buckets, read cache)": 0.44 * 720 * 4,
    "Ingest sort and dedup join (EMR, once per batch)": 500.0,
    "Cross-AZ replication traffic, ClickHouse + Aurora": 500.0,
    "Read API 3 × Fargate tasks + CloudFront": 300.0,
    "Managed Prometheus/Grafana + CloudWatch": 300.0,
}
FIXED_FLOOR = {
    "RDS db.r6g.large (control plane)": 0.24 * 720,
    "ElastiCache cache.r7g.large × 2 (frontier + cache)": 0.22 * 720 * 2,
    "ClickHouse i4i.2xlarge × 2": 0.686 * 720 * 2,
    "Managed Prometheus/Grafana + CloudWatch": 100.0,
    "Worker instances × 2 (16 vCPU spot, HA)": 2 * 16 * 720 * P_CORE_H,
}


@dataclass
class Row:
    id: str
    quantity: str
    value: str
    label: str
    working: str


def money(x: float) -> str:
    """Two significant figures: these are estimates, and cents would claim a precision they lack."""
    if x == 0:
        return "$0"
    digits = int(math.floor(math.log10(abs(x))))
    rounded = round(x, 1 - digits)
    if rounded >= 100:
        return f"${rounded:,.0f}"
    if rounded >= 10:
        return f"${rounded:.0f}"
    return f"${rounded:.2g}" if rounded < 1 else f"${rounded:.1f}"


def s3_stock_bill(gb_per_month: float, months: int) -> float:
    """Monthly bill after `months` of accumulation under Standard(1) -> IA(2-3) -> Deep Archive."""
    return sum(
        gb_per_month * (P_S3_STD if age == 1 else P_S3_IA if age <= 3 else P_S3_DA)
        for age in range(1, months + 1)
    )


def ch_stock_bill(gb_per_month: float, months: int, hot: int = 3) -> float:
    """Hot tier on gp3 with CH_REPLICATION copies; cold tier on S3-backed storage (S3 handles redundancy)."""
    return sum(
        gb_per_month * (P_GP3_GB * CH_REPLICATION if age <= hot else P_S3_STD)
        for age in range(1, months + 1)
    )


def many_domain() -> list[Row]:
    rate = URLS / MONTH_S
    cpu_s = CPU_MS / 1000 * PROD_FACTOR
    cores = rate * cpu_s
    inst = cores / VCPU_PER_INSTANCE               # at 100% utilisation
    deployed = round(inst / UTIL_TARGET)           # what is actually run and billed
    core_h = deployed * VCPU_PER_INSTANCE * 24 * 30
    wire_kb = HTML_KB / COMPRESSION
    raw_gb = URLS * wire_kb * 1e3 / 1e9
    meta_gb = URLS * META_KB * 1e3 / 1e9 / META_COMPRESSION
    put_batched = URLS / PAGES_PER_OBJECT * P_S3_PUT
    nat = raw_gb * P_NAT_GB
    ipv4 = deployed * P_IPV4_H * 720
    sqs = URLS * 3 / 10 / 1e6 * P_SQS_M
    compute = core_h * P_CORE_H
    per_m = {
        "compute": compute / 10_000,
        "put": put_batched / 10_000,
        "nat": nat / 10_000,
        "s3": raw_gb * P_S3_STD / 10_000,
        "ch": meta_gb * P_GP3_GB / 10_000,
        "sqs": sqs / 10_000,
    }
    total_nat = sum(per_m.values())
    total_ipv4 = total_nat - per_m["nat"] + ipv4 / 10_000
    flat = compute + put_batched + ipv4 + sqs + sum(FIXED_MANY.values()) + URLS*URL_ROW_BYTES/1e9*0.10
    reads_s = READS_PER_DAY / 86_400
    lam = URLS * cpu_s * 0.5 * P_LAMBDA_GBS + URLS / 1e6 * P_LAMBDA_REQ_M
    return [
        Row("N-00", "URLs per month", "10e9", "assumed", "brief: 'billions'; upper planning case"),
        Row("N-01", "Sustained fetch rate", f"{rate:,.0f}/s", "derived", "N-00 / (30 × 86,400)"),
        Row("N-02", "2× diurnal peak", f"{2*rate:,.0f}/s", "derived", "2 × N-01 (2× is a planning convention, assumed)"),
        Row("N-03", "HTML per page", f"{HTML_KB} KB", "assumed", "planning median; fixtures 5.6 MB and 1.6 MB are large-publisher outliers"),
        Row("N-04", "Wire compression", f"{COMPRESSION:.0f}:1", "measured", "gzip on fixtures: 5.0 and 5.2, n=2"),
        Row("N-04b", "Wire bytes per page", f"{wire_kb:.0f} KB", "derived", "N-03 / N-04"),
        Row("N-05", "CPU per page (dev)", f"{CPU_MS} ms", "measured", f"parse {PARSE_MS:.0f} + topics {TOPICS_MS:.1f} = {PARSE_MS+TOPICS_MS:.1f}, rounded; n=5 per fixture; Apple M4"),
        Row("N-05b", "CPU per page (production)", f"{cpu_s*1000:.0f} ms", "assumed", f"{PROD_FACTOR}× N-05; PoC Phase 0 validates"),
        Row("N-06", "Cores", f"{cores:,.0f}", "derived", "N-01 × N-05b"),
        Row("N-07", "Instances (16 vCPU) at 100% / deployed at 70%", f"{inst:,.0f} / {deployed:,.0f}", "derived", "N-06 / 16; / 0.7, rounded"),
        Row("N-08", "Billed core-hours per month / per M URLs", f"{core_h:,.0f} / {core_h/10_000:,.0f}", "derived", "deployed instances × 16 × 720; / 10,000"),
        Row("N-09", "Compute per month / per M", f"{money(compute)} / {money(compute/10_000)}", "derived", f"N-08 × ${P_CORE_H}/core-h (spot Graviton, assumed)"),
        Row("N-10", "Metadata record", f"{META_KB} KB", "measured → assumed", "compact JSON of docs/samples: 9,609 B (Amazon), 6,064 B (CNN); n=2; 10 KB rounds up"),
        Row("N-10b", "Metadata per month raw / compressed", f"{URLS*META_KB*1e3/1e12:,.0f} TB / {meta_gb/1000:,.0f} TB", "derived", f"N-00 × N-10; / {META_COMPRESSION:.0f}:1 (assumed)"),
        Row("N-11", "Raw HTML stored per month", f"{raw_gb/1000:,.0f} TB", "derived", "N-00 × N-04b"),
        Row("N-11b", "Raw HTML uncompressed per month", f"{URLS*HTML_KB*1e3/1e15:.1f} PB", "derived", "N-00 × N-03"),
        Row("N-12", "Raw S3 bill at 1 / 12 / 24 months", f"{money(s3_stock_bill(raw_gb,1))} / {money(s3_stock_bill(raw_gb,12))} / {money(s3_stock_bill(raw_gb,24))} per month", "derived", "Standard age 1, IA ages 2–3, Deep Archive after; prices assumed"),
        Row("N-13", "ClickHouse storage at 1 / 12 / 24 months (hot tier × 2 replicas)", f"{money(ch_stock_bill(meta_gb,1))} / {money(ch_stock_bill(meta_gb,12))} / {money(ch_stock_bill(meta_gb,24))} per month", "derived", "gp3 × 2 replicas for 3 months, S3-backed tier after; prices assumed"),
        Row("N-14", "S3 PUT, one object per page", f"{money(URLS*P_S3_PUT)}/mo; {rate:,.0f} PUT/s", "derived", "N-00 × $0.005/1,000"),
        Row("N-14b", "S3 PUT, packed 1,000 pages per (server, minute) object", f"{money(put_batched)}/mo; {rate/PAGES_PER_OBJECT:.1f} PUT/s; {wire_kb*PAGES_PER_OBJECT/1000:.0f} MB objects", "derived", f"N-00 / {PAGES_PER_OBJECT} × $0.005/1,000"),
        Row("N-15", "NAT Gateway processing", f"{money(nat)}/mo", "derived", "N-11 × $0.045/GB (wire bytes)"),
        Row("N-15a", "NAT if bytes were uncompressed", f"{money(URLS*HTML_KB*1e3/1e9*P_NAT_GB)}/mo", "derived", "N-11b × $0.045/GB — shows the weight of N-04"),
        Row("N-15b", "Public IPv4 instead of NAT", f"{money(ipv4)}/mo", "derived", "deployed instances × $0.005/h × 720"),
        Row("N-16", "SQS", f"{money(sqs)}/mo batched; {money(sqs*10)} unbatched", "derived", "3 requests/URL / 10 × $0.40/M"),
        Row("N-17", "Dedup saving at 60% unchanged (upper bound)", f"{money(compute*DEDUP_UNCHANGED)}/mo compute + {money(put_batched*DEDUP_UNCHANGED)} PUT", "derived", "0.6 × N-09; 0.6 × N-14b; 60% assumed; fleet shrinks in proportion"),
        Row("N-18", "Bloom 1% FPR false duplicates", f"{URLS*0.01/1e6:,.0f}M URLs/mo", "derived", "0.01 × N-00"),
        Row("N-20", "Read traffic mean / 2× peak / store misses", f"{reads_s:,.0f}/s / {2*reads_s:,.0f}/s / {reads_s*(1-CACHE_HIT):,.1f}/s", "assumed→derived", "10M/day; × 2; × (1 − 0.9 hit)"),
        Row("N-21", "DynamoDB full replica writes", f"{money(URLS*META_KB*P_DDB_WRU_M/1e6)}/mo", "derived", "N-00 × 10 WRU (10 KB / 1 KB) × $1.25/M"),
        Row("N-21b", "DynamoDB replica storage", f"{money(URLS*META_KB*1e3/1e9*P_DDB_GB)}/mo, accumulating", "derived", "100 TB × $0.25/GB"),
        Row("N-24", "Per million URLs (NAT) / (public IPv4)", f"{money(total_nat)} / {money(total_ipv4)}", "derived", " + ".join(f"{k} {v:.2f}" for k, v in per_m.items())),
        Row("N-24e", "Fixed infrastructure, many-domain (incl. Aurora I/O, ingest, cross-AZ)", money(sum(FIXED_MANY.values())) + "/mo", "assumed", "; ".join(f"{k} {money(v)}" for k, v in FIXED_MANY.items())),
        Row("N-29", "Frontier table (10e9 rows)", f"{URLS*URL_ROW_BYTES/1e12:.1f} TB; {money(URLS*URL_ROW_BYTES/1e9*0.10)}/mo", "derived", "N-00 × 200 B (assumed) ; × $0.10/GB-mo Aurora storage (assumed)"),
        Row("N-24f", "Total month 1 / per M all lines month 1", f"{money(flat+s3_stock_bill(raw_gb,1)+ch_stock_bill(meta_gb,1))} / {money((flat+s3_stock_bill(raw_gb,1)+ch_stock_bill(meta_gb,1))/10_000)}", "derived", "N-24c flat + N-12 + N-13 at month 1; / 10,000"),
        Row("N-24g", "Variable flat lines (compute + PUT + IPv4 + SQS)", money(compute + put_batched + ipv4 + sqs), "derived", "N-09 + N-14b + N-15b + N-16"),
        Row("N-24h", "Egress + queue + object writes", money(ipv4 + sqs + put_batched), "derived", "N-15b + N-16 + N-14b"),
        Row("N-24c", "Flat lines / total at 12 / 24 months", f"{money(flat)} / {money(flat+s3_stock_bill(raw_gb,12)+ch_stock_bill(meta_gb,12))} / {money(flat+s3_stock_bill(raw_gb,24)+ch_stock_bill(meta_gb,24))}", "derived", "compute + PUT + IPv4 + SQS + N-24e + N-29; + N-12 + N-13 at 12 / 24 months"),
        Row("N-24d", "IPv4 per M / KV summary tier", f"{money(ipv4/10_000)} / {money(URLS*1*P_DDB_WRU_M/1e6)}", "derived", "N-15b / 10,000; N-00 × 1 WRU × $1.25/M"),
        Row("N-25", "Memory per process / per instance", f"{PROC_RSS_MB} MB / {PROC_RSS_MB*VCPU_PER_INSTANCE/1000:.1f} GB", "measured→derived", "RSS 352–379 MB after one parse, n=1 each; × 16"),
        Row("N-26", "In-flight fetches total / per deployed instance", f"{rate*FETCH_LATENCY_S:,.0f} / {rate*FETCH_LATENCY_S/deployed:.0f}", "derived", "N-01 × 2 s (assumed latency); / deployed instances"),
        Row("N-27", "Lambda comparison", f"{money(lam)}/mo", "derived", "N-00 × N-05b × 0.5 GB × $0.0000166667 + N-00 × $0.20/M"),
        Row("N-28", "Ingest file size", f"{URLS*URL_BYTES/1e9:,.0f} GB", "derived", "N-00 × 80 B (assumed URL length)"),
    ]


def few_domain() -> list[Row]:
    cpu_s = CPU_MS / 1000 * PROD_FACTOR
    rows = [Row("F-00", "Hosts", str(HOSTS_FEW), "assumed", "brief's example: amazon.com, walmart.com, bestbuy.com"),
            Row("F-01", "URLs per host", "3.33e9", "derived", "N-00 / F-00")]
    for r in (1, 10, 100):
        per_month = HOSTS_FEW * r * MONTH_S
        years = (URLS / HOSTS_FEW) / (r * 365 * 86_400)
        rows.append(Row(f"F-{r:03d}", f"At {r} req/s/host: URLs/month · years per host · cores",
                        f"{per_month/1e6:,.1f}M · {years:,.1f} y · {HOSTS_FEW*r*cpu_s:.1f}", "derived",
                        f"3 × {r} × 2,592,000; F-01 / ({r} × 31,536,000); 3 × {r} × N-05b"))
    rows.append(Row("F-10", "Unnegotiated polite rate", "10 req/s/host", "assumed",
                    "no standard; common defaults are 1 req/s or Crawl-delay; 10 is the upper end tolerated without agreement"))
    urls = HOSTS_FEW * 10 * MONTH_S
    raw_gb = urls * HTML_KB / COMPRESSION * 1e3 / 1e9
    floor = sum(FIXED_FLOOR.values())
    variable = raw_gb * P_S3_STD + urls * META_KB * 1e3 / 1e9 / META_COMPRESSION * P_GP3_GB
    rows.append(Row("F-20", "Fixed monthly floor", money(floor), "assumed",
                    "; ".join(f"{k} {money(v)}" for k, v in FIXED_FLOOR.items())))
    rows.append(Row("F-21", "Variable per month at 10 req/s/host", money(variable), "derived",
                    f"raw {raw_gb/1000:.1f} TB × $0.023 + metadata × $0.08"))
    rows.append(Row("F-22", "Per million URLs at 10 req/s/host", money((floor + variable) / (urls / 1e6)), "derived",
                    f"(F-20 + F-21) / {urls/1e6:.1f}M — fixed cost dominates; compute is {money(FIXED_FLOOR['Worker instances × 2 (16 vCPU spot, HA)'])}"))
    return rows


NUMBERS_FILE = pathlib.Path(__file__).resolve().parents[1] / "docs" / "part2-numbers.md"


def numbers_markdown() -> str:
    """The generated numbers file: every input and result, both regimes, compact form."""
    out = ["# Part 2 — the numbers", "",
           "Generated by `scripts/ledger.py --write`; do not edit by hand. Money is rounded to two significant",
           "figures because these are estimates. The arithmetic for each derived row is in the script.",
           "Labels: **measured** (where and how), **assumed** (why this value), **derived** (arithmetic).", ""]
    for title, rows in (("Many hosts", many_domain()), ("Few hosts", few_domain())):
        out += [f"## {title}", "", "| ID | Quantity | Value | Label |", "|---|---|---|---|"]
        out += [f"| {r.id} | {r.quantity} | {r.value} | {r.label} |" for r in rows]
        out.append("")
    return "\n".join(out)


def check(doc_path: str) -> int:
    """Two checks: the numbers file is current, and every dollar figure in the design document
    is a value this script produced (so no cost figure is typed by hand). Exit 1 on any miss."""
    problems = []
    if not NUMBERS_FILE.exists() or NUMBERS_FILE.read_text(encoding="utf-8") != numbers_markdown():
        problems.append(f"{NUMBERS_FILE.name} is stale: run `python scripts/ledger.py --write`")
    produced = set()
    for r in many_domain() + few_domain():
        produced.update(re.findall(r"\$[\d,]+(?:\.\d+)?", r.value))
    doc = pathlib.Path(doc_path).read_text(encoding="utf-8")
    for token in sorted(set(re.findall(r"\$[\d,]+(?:\.\d+)?", doc))):
        if token not in produced and token not in PRICE_TOKENS:
            problems.append(f"{token} appears in {doc_path} but is not a ledger value or a stated unit price")
    for m in problems:
        print("PROBLEM", m)
    print(f"{len(problems)} problems")
    return 1 if problems else 0


# unit prices quoted in the document's assumptions and calculations
PRICE_TOKENS = {"$0.02", "$0.023", "$0.005", "$0.08", "$0.045", "$0.10", "$0.25", "$1.25", "$0.40", "$0.30"}


def main() -> int:
    if "--check" in sys.argv:
        return check(sys.argv[sys.argv.index("--check") + 1])
    if "--write" in sys.argv:
        NUMBERS_FILE.write_text(numbers_markdown(), encoding="utf-8")
        print(f"wrote {NUMBERS_FILE.relative_to(pathlib.Path.cwd())}")
        return 0
    rows = few_domain() if "--regime" in sys.argv and "few" in sys.argv else many_domain()
    if "--compact" in sys.argv:  # for the document appendix: the working stays in this file
        print("| ID | Quantity | Value | Label |")
        print("|---|---|---|---|")
        for r in rows:
            print(f"| {r.id} | {r.quantity} | {r.value} | {r.label} |")
        return 0
    print("| ID | Quantity | Value | Label | Inputs / working |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(f"| {r.id} | {r.quantity} | {r.value} | {r.label} | {r.working} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
