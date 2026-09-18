#!/usr/bin/env python3
"""Validate the current twelve-file Online Search task contract.

No source manifest, site allowlist, decision log, or evaluator metadata is part
of the task. Capture/verify modes perform a best-effort live URL health check;
only repeat 404/410 responses are hard failures. Package mode is offline and
requires the exact publication tree.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import re
import socket
import tomllib
from pathlib import Path
from urllib.parse import urldefrag, urlsplit

import httpx

REQUIRED_FILES = {
    "environment/Dockerfile", "instruction.md", "solution/evidence_graph.json",
    "solution/report.md", "solution/solve.sh", "task.toml", "tests/Dockerfile",
    "tests/reference/ground_truth.json", "tests/rubrics.json", "tests/test.sh",
    "tests/test_outputs.py", "tests/test_utils.py",
}
BYTE_IDENTICAL_FILES = {
    "environment/Dockerfile", "solution/solve.sh", "tests/Dockerfile",
    "tests/test.sh", "tests/test_outputs.py", "tests/test_utils.py",
}
RUBRIC_TOP = {"schema_version", "task_id", "scoring", "criteria"}
CRITERION_KEYS = {"id", "axis", "category", "requirement", "weight", "claim_ids"}
GT_TOP = {"schema_version", "task_id", "rubric_artifact_id", "collection_method",
          "source_selection_method", "conflict_adjudication_method", "known_limitations",
          "claims", "rubric_mappings"}
CLAIM_KEYS = {"id", "kind", "statement", "basis", "report_location",
              "accepted_citations", "rejected_citations", "conflict_resolution"}
MAPPING_KEYS = {"criterion_id", "claim_ids", "justification"}
GRAPH_TOP = {"schema_version", "task_id", "rubric_claims", "nodes", "edges",
             "required_paths", "conflicts", "calculations", "recommendations",
             "decoys", "task_data"}
GRAPH_RUBRIC_KEYS = {"id", "claim_ids", "description", "basis", "justification"}
NODE_KEYS = {"id", "type", "label", "url", "source_ids"}
EDGE_KEYS = {"source", "target", "type"}
ACCEPTED_CITATION_KEYS = {"url", "role", "authority_basis"}
REJECTED_CITATION_KEYS = {"url", "reason"}
URL_RE = re.compile(r"https?://[^\s\"'<>`]+")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
SECRET_RE = re.compile(r"(?:sk-or-v1-[A-Za-z0-9]{40,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")

class ValidationFailure(RuntimeError): pass

def load_json(path: Path) -> dict:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValidationFailure(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict): raise ValidationFailure(f"JSON root must be an object: {path}")
    return value

def require(condition: bool, message: str) -> None:
    if not condition: raise ValidationFailure(message)

def canonical_rubric_hash(rubric: dict) -> str:
    raw = json.dumps(rubric, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

def normalized_url(value: object) -> str:
    raw = str(value or "").strip().strip("`<>{}[]()\"'").rstrip(".,;:!?)]}>`*_")
    raw, _ = urldefrag(raw)
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password: return ""
    try: port = parsed.port
    except ValueError: return ""
    if port not in {None, 80, 443}: return ""
    return raw

def public_host(url: str) -> bool:
    parsed = urlsplit(url)
    try: addresses = {row[4][0] for row in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError: return True  # transient DNS is not a package defect
    return bool(addresses) and all(ipaddress.ip_address(value).is_global for value in addresses)

def table_errors(text: str) -> list[int]:
    lines=text.splitlines(); errors=[]; i=0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j=i
            while j < len(lines) and lines[j].lstrip().startswith("|"): j += 1
            block=lines[i:j]; counts=[len(re.findall(r"(?<!\\)\|", row)) for row in block]
            if len(block)<2 or not TABLE_SEPARATOR.fullmatch(block[1]) or len(set(counts))>1: errors.append(i+1)
            i=j
        else: i += 1
    return errors

def non_ascii_outside_urls(text: str) -> list[str]:
    scrubbed=text
    for match in reversed(list(URL_RE.finditer(text))): scrubbed=scrubbed[:match.start()]+(" "*len(match.group()))+scrubbed[match.end():]
    return sorted({f"U+{ord(ch):04X}" for ch in scrubbed if ord(ch)>127})

def validate_instruction(text: str) -> None:
    words=len(re.findall(r"\b[\w'-]+\b", text))
    require(words <= 350, f"instruction exceeds 350 words: {words}")
    require("—" not in text, "instruction contains em dash")
    require(text.count(",") <= 13, "instruction contains more than 13 commas")
    low=text.casefold()
    require(re.search(r"public[- ]web|live\s+(?:public[- ]?)?web|web research", low) is not None,
            "instruction must explicitly require public-web research")
    require(re.search(r"exact.{0,50}(?:url|link)|cite.{0,50}(?:url|link)", low) is not None,
            "instruction must require exact citations")
    require("/app/output/report.md" in text, "instruction must name /app/output/report.md")
    for phrase in ("approved domains", "limit research to", "fixed list of sites", "fixed list of domains",
                   "do not restrict yourself to", "decision log", "source_manifest", "context goal", "peak call"):
        require(phrase not in low, f"instruction contains forbidden guidance/metadata: {phrase}")
    require(
        re.search(r"decision[- ]log|source[- ]tier|authority[- ]tier|tier\s*[0-3]", low)
        is None,
        "instruction contains forbidden decision-log or source-tier language",
    )
    require(not non_ascii_outside_urls(text), "instruction contains non-ASCII text outside URLs")
    require(not table_errors(text), f"instruction has malformed Markdown table(s): {table_errors(text)}")

def validate_report(text: str) -> None:
    require(len(text.split()) >= 300, "reference report is too short for decision-ready analysis")
    low=text.casefold()
    for phrase in ("rubric_artifact_id", "schema_version", "peak call context", "context goal", "judge model", "solver model", "decision log", "source tier"):
        require(phrase not in low, f"reference report leaks forbidden metadata: {phrase}")
    require(
        re.search(
            r"decision[- ]log|source[- ]tier|authority[- ]tier|evidence[- ]tier|tier\s*[0-3]|source[- ]role",
            low,
        )
        is None,
        "reference report contains decision-log or tier/role metadata",
    )
    require(not non_ascii_outside_urls(text), "report contains non-ASCII text outside URLs")
    require(not table_errors(text), f"report has malformed Markdown table(s): {table_errors(text)}")
    require(bool(URL_RE.search(text)), "reference report contains no exact URL citations")

def validate_task_toml(root: Path, task_id: str) -> None:
    try: cfg=tomllib.loads((root/"task.toml").read_text(encoding="utf-8"))
    except (OSError,tomllib.TOMLDecodeError) as exc: raise ValidationFailure(f"invalid task.toml: {exc}") from exc
    require(cfg.get("artifacts")==["/app/output/report.md"], "task must expose only report.md")
    require(cfg.get("task",{}).get("name")==f"parsewave/{task_id}", "task.toml task name mismatch")
    require(float(cfg.get("agent",{}).get("timeout_sec",0))==10800, "agent timeout must be 10800 seconds")
    require(float(cfg.get("verifier",{}).get("timeout_sec",0))==1600, "verifier timeout must be 1600 seconds")
    require(cfg.get("environment",{}).get("allow_internet") is True, "solver internet must be enabled")
    env=cfg.get("verifier",{}).get("env",{})
    require(env.get("LLM_JUDGE_MODEL")=="deepseek/deepseek-v4.1-flash", "judge model mismatch")
    require(env.get("LLM_JUDGE_REASONING_EFFORT")=="xhigh", "judge reasoning must be xhigh")

def validate_json_contracts(root: Path, task_id: str) -> list[str]:
    rubric=load_json(root/"tests/rubrics.json"); gt=load_json(root/"tests/reference/ground_truth.json"); graph=load_json(root/"solution/evidence_graph.json")
    require(set(rubric)==RUBRIC_TOP and rubric.get("schema_version")=="online-search-rubrics" and rubric.get("scoring")=="binary", "rubric top-level schema mismatch")
    require(set(gt)==GT_TOP and gt.get("schema_version")=="online-search-ground-truth", "ground-truth top-level schema mismatch")
    require(set(graph)==GRAPH_TOP and graph.get("schema_version")=="online-search-evidence-graph", "evidence-graph top-level schema mismatch")
    require(rubric.get("task_id")==task_id and gt.get("task_id")==task_id and graph.get("task_id")==task_id, "JSON task_id mismatch")
    criteria=rubric.get("criteria"); require(isinstance(criteria,list) and criteria, "rubric criteria missing")
    claims=gt.get("claims"); mappings=gt.get("rubric_mappings"); require(isinstance(claims,list) and isinstance(mappings,list), "ground-truth arrays missing")
    for field in ("collection_method","source_selection_method","conflict_adjudication_method"):
        require(isinstance(gt.get(field),str) and gt[field].strip(), f"ground-truth {field} is empty")
    require(isinstance(gt.get("known_limitations"),list), "ground-truth known_limitations must be a list")
    require(all(isinstance(x,dict) and set(x)==CRITERION_KEYS for x in criteria), "criterion key set mismatch")
    require(all(isinstance(x,dict) and set(x)==CLAIM_KEYS for x in claims), "claim key set mismatch")
    require(all(isinstance(x,dict) and set(x)==MAPPING_KEYS for x in mappings), "mapping key set mismatch")
    ids=[x["id"] for x in criteria]; claim_ids=[x["id"] for x in claims]
    require(len(ids)==len(set(ids)) and len(claim_ids)==len(set(claim_ids)), "duplicate criterion or claim ID")
    pos=[x for x in criteria if x["weight"]>0]; neg=[x for x in criteria if x["weight"]<0]
    require(0 < len(neg) < len(pos), "positive criterion count must exceed negative count")
    require(len(criteria)<=50, "rubric exceeds 50 criteria")
    require(all(type(x["weight"]) is int and 1<=x["weight"]<=20 and str(x["id"]).startswith("P") for x in pos), "positive criterion contract mismatch")
    require(all(type(x["weight"]) is int and -100<=x["weight"]<=-1 and str(x["id"]).startswith("N") for x in neg), "negative criterion contract mismatch")
    require(all(str(x["axis"]).strip() and str(x["category"]).strip() and str(x["requirement"]).strip() for x in criteria), "criterion text fields must be nonempty")
    positive=sum(x["weight"] for x in pos); negative=-sum(x["weight"] for x in neg)
    require(positive>300 and positive>negative, "rubric weight balance mismatch")
    require(len({x["requirement"] for x in criteria})==len(criteria), "duplicate rubric requirement")
    claim_set=set(claim_ids); by_mapping={x["criterion_id"]:x for x in mappings}
    require(set(by_mapping)==set(ids) and len(mappings)==len(criteria), "rubric mappings are incomplete")
    for item in criteria:
        require(isinstance(item["claim_ids"],list) and item["claim_ids"] and all(x in claim_set for x in item["claim_ids"]), f"unknown claim in {item['id']}")
        require(by_mapping[item["id"]]["claim_ids"]==item["claim_ids"] and str(by_mapping[item["id"]]["justification"]).strip(), f"mapping mismatch for {item['id']}")
    require(gt.get("rubric_artifact_id")==canonical_rubric_hash(rubric), "stale rubric_artifact_id")
    nodes=graph.get("nodes"); edges=graph.get("edges"); gr=graph.get("rubric_claims")
    require(isinstance(nodes,list) and all(isinstance(x,dict) and set(x)==NODE_KEYS for x in nodes), "graph node schema mismatch")
    require(isinstance(gr,list) and all(isinstance(x,dict) and set(x)==GRAPH_RUBRIC_KEYS for x in gr), "graph rubric_claim schema mismatch")
    require({x["id"] for x in gr}==set(ids) and len(gr)==len(criteria), "graph rubric coverage mismatch")
    graph_map={x["id"]:x for x in gr}
    require(all(graph_map[x["id"]]["claim_ids"]==x["claim_ids"] for x in criteria), "graph rubric linkage mismatch")
    node_ids=[x["id"] for x in nodes]; require(len(node_ids)==len(set(node_ids)), "duplicate graph node ID")
    require(all(str(x["id"]).strip() and str(x["type"]).strip() and str(x["label"]).strip() and isinstance(x["source_ids"],list) for x in nodes), "graph node fields are invalid")
    node_set=set(node_ids)
    require(isinstance(edges,list) and all(isinstance(x,dict) and set(x)==EDGE_KEYS for x in edges), "graph edge schema mismatch")
    require(all(x["source"] in node_set and x["target"] in node_set for x in edges), "dangling graph edge")
    for collection in ("required_paths","conflicts","calculations","recommendations","decoys"):
        require(isinstance(graph.get(collection),list), f"graph {collection} must be a list")
    require(isinstance(graph.get("task_data"),dict), "graph task_data must be an object")
    urls=[]
    for claim in claims:
        require(claim.get("kind") in {"fact","report_requirement","prohibited_error"}, f"invalid claim kind: {claim.get('id')}")
        require(all(isinstance(claim.get(field),str) and claim[field].strip() for field in ("statement","basis","report_location")), f"claim text fields are empty: {claim.get('id')}")
        for field in ("accepted_citations","rejected_citations"):
            require(isinstance(claim[field],list), f"invalid citation list: {claim['id']}")
            for citation in claim[field]:
                require(isinstance(citation,dict), f"invalid citation object: {claim['id']}")
                if field == "accepted_citations":
                    require(
                        "url" in citation and set(citation) <= ACCEPTED_CITATION_KEYS,
                        f"citation schema mismatch: {claim['id']} {field}",
                    )
                else:
                    require(
                        set(citation) == REJECTED_CITATION_KEYS,
                        f"citation schema mismatch: {claim['id']} {field}",
                    )
                url=normalized_url(citation.get("url")); require(bool(url), f"invalid citation URL: {claim['id']}")
                require(public_host(url), f"citation resolves to a private address: {url}"); urls.append(url)
    for node in nodes:
        if node["url"] is not None:
            url=normalized_url(node["url"]); require(bool(url), f"invalid graph node URL: {node['id']}")
            require(public_host(url), f"graph URL resolves to a private address: {url}"); urls.append(url)
    return sorted(set(urls))

def verify_url(url: str) -> tuple[str,str]:
    headers={"User-Agent":"Mozilla/5.0 (compatible; ParsewaveOnlineSearchValidator/1.0)","Range":"bytes=0-2047"}
    statuses=[]
    for _ in range(2):
        try:
            with httpx.Client(follow_redirects=True,timeout=15.0,headers=headers) as client:
                response=client.get(url)
            final=normalized_url(str(response.url))
            if not final or not public_host(final):
                return url,"private_redirect"
            status=response.status_code
            statuses.append(status)
            if status not in {404,410}: break
        except httpx.HTTPError: return url,"transient"
    return url,"hard_dead" if statuses and all(x in {404,410} for x in statuses) else "reachable_or_blocked"

def validate(root: Path, task_id: str, mode: str) -> dict:
    actual={str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "task-planning" not in p.parts and "output" not in p.parts}
    require(REQUIRED_FILES <= actual, f"missing files: {sorted(REQUIRED_FILES-actual)}")
    if mode=="package": require(actual==REQUIRED_FILES, f"publication package has extras: {sorted(actual-REQUIRED_FILES)}")
    for forbidden in ("source_manifest.json","docker-compose.yaml","docker-compose.yml"):
        require(not any(p.name==forbidden for p in root.rglob("*")), f"forbidden file present: {forbidden}")
    require(not any(p.suffix in {".pyc",".pyo"} or p.name=="__pycache__" for p in root.rglob("*")), "bytecode artifact present")
    validate_task_toml(root,task_id)
    canonical=Path(__file__).resolve().parents[1]/"canonical"
    for relative in BYTE_IDENTICAL_FILES:
        expected=canonical/relative
        require(expected.is_file(), f"canonical file missing: {relative}")
        require((root/relative).read_bytes()==expected.read_bytes(), f"shared file differs from canonical: {relative}")
    validate_instruction((root/"instruction.md").read_text(encoding="utf-8"))
    report=(root/"solution/report.md").read_text(encoding="utf-8")
    validate_report(report)
    urls=validate_json_contracts(root,task_id)
    for raw_url in URL_RE.findall(report):
        url=normalized_url(raw_url)
        require(bool(url), f"invalid report URL: {raw_url}")
        require(public_host(url), f"report URL resolves to a private address: {url}")
        urls.append(url)
    urls=sorted(set(urls))
    for path in root.rglob("*"):
        if path.is_file(): require(not SECRET_RE.search(path.read_text(encoding="utf-8",errors="ignore")), f"credential-like text in {path.relative_to(root)}")
    hard=[]
    if mode in {"capture","verify"} and urls:
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            for url,status in pool.map(verify_url,urls):
                if status in {"hard_dead","private_redirect"}: hard.append(url)
        require(not hard, f"confirmed dead or non-public URLs: {hard}")
    return {"task_id":task_id,"mode":mode,"files":len(actual),"citation_urls":len(urls),"hard_dead_urls":hard,"status":"pass"}

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--task-root",type=Path,required=True); parser.add_argument("--task-id",required=True); parser.add_argument("--mode",choices=("capture","verify","package"),required=True); args=parser.parse_args()
    root=args.task_root.resolve(); require(ID_RE.fullmatch(args.task_id) is not None,"invalid task id")
    try: result=validate(root,args.task_id,args.mode)
    except ValidationFailure as exc: print(json.dumps({"status":"fail","error":str(exc)})); return 1
    print(json.dumps(result,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
