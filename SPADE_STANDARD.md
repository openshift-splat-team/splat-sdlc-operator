# Security Posture Artifact Documentation Standard (SPADE) v0.1

**By: [Máirín Duffy](mailto:duffy@redhat.com)  [Roman Zhukov](mailto:rzhukov@redhat.com)**   
**Status:** Draft   
**Last Updated:** Apr 17, 2026 (Initial draft Apr 12, 2026\)   
**License:** CC-BY-4.0

---

## Overview

This document defines a standard for five security artifacts intended for placement in open source code repositories. The artifacts are designed to serve a multi-audience readership — maintainers, security researchers, downstream integrators, compliance auditors, and AI scanning agents — and to interoperate with existing machine-readable standards including OpenSSF Security Insights, CycloneDX/SPDX SBOMs, MITRE CWE/ATT\&CK, and CVSS.

### The Artifacts

| Repo Artifact | One-sentence description | Primary Update Trigger |
| :---- | :---- | :---- |
| `SECURITY.md` | Defines how the project classifies, receives, and handles vulnerability reports — including severity model, embargo process, what does and does not count as a security bug, and incident response. | On release; on policy change |
| `TRUST_BOUNDARIES.md` | Maps every point in the codebase where trust changes hands — which components accept untrusted input, what isolation exists, and where historical CVEs have crossed. | On release; on architectural change |
| `CVE_HISTORY.md` | A structured record of every CVE assigned to the project, the CWE patterns they reveal, the subsystems most frequently implicated, and what the history tells downstream consumers about supply-chain risk. | On each new CVE; on release |
| `THREAT_MODEL.md` | Documents who threatens this project, in what deployment contexts, via what attack scenarios, and what the project does — or explicitly does not do — to mitigate each threat. | On release; on significant architectural change |
| `SECURITY_HARDENING.md` | Declares the deliberate security shape of the software: how it is built and hardened, what risks are knowingly accepted by design, and what assumptions about the environment must hold for its security properties to be valid. | On release; on design change |

### Design Principles

**Format.** Each artifact is a Markdown file with embedded YAML code blocks. These blocks carry machine-parseable structured data; Markdown prose carries human-readable context. A consuming agent MAY parse only the YAML blocks; a human reader MAY ignore them entirely.

**Conformance.** All five artifacts are fully optional. However, any section that is present MUST conform to the schema defined in this specification. Partial conformance within a section is not permitted — include a section fully or omit it.

**Conformance marker.** A repo claiming conformance to SPADE SHOULD include the following in its root `README.md` or `security-insights.yml`:

```
spade-conformance:
  version: "0.1"
  artifacts:
    - SECURITY.md
    - TRUST_BOUNDARIES.md
    - CVE_HISTORY.md
    - THREAT_MODEL.md
    - SECURITY_POSTURE.md
```

Projects adopting SPADE are strongly RECOMMENDED to also maintain a `security-insights.yml` per the [OpenSSF Security Insights specification](https://github.com/ossf/security-insights). The two standards are complementary and together cover the full picture: 

* Security Insights is the project's **identity and contact card** — it declares who maintains the project, where to send vulnerability reports, what the lifecycle stage is, and where packages are distributed.   
* SPADE is the **deep policy and threat context** — it documents how vulnerabilities are classified and handled, what the trust boundaries and threat model are, what CVE history reveals about the codebase, and what security posture deployers are accepting. Neither standard duplicates the other. A consuming agent or auditor that has both files has everything; one without the other has half the picture.

**Update cadence.** Artifacts MUST be updated on every release tag and on every CVE assigned to the project. Maintainers SHOULD configure CI/CD to flag stale artifacts (i.e., `last-updated` date older than the most recent release tag or CVE publication date).

**AI agent guidance.** YAML blocks use consistent key names across all five artifacts to allow an agent to extract a unified security context from a single pass over all five files. The `spade-metadata` block at the top of each file is the primary machine-readable entry point.

---

## 1\. SECURITY.md

### Purpose

Communicates the project's vulnerability handling policy, private reporting process, public disclosure timeline, supported versions (or link to lifecycle handling documents such as CLE or OpenEoX), hardening recommendations, and defense-in-depth posture.

### Relationship to Existing Standards

- Extends the conventions established by GitHub's default SECURITY.md and OpenSSF Security Insights (`vulnerability-reporting` section).  
- The `supported-versions` block is compatible with the OpenSSF Security Insights `project.lifecycle` field.  
- Hardening recommendations reference CIS Benchmark controls where applicable.

### Schema

#### Block: `spade-metadata` (required if file is present)

```
spade-artifact: SECURITY.md
spade-version: "0.1"
last-updated: "YYYY-MM-DD"
last-updated-reason: "release | policy-change | cve-published | manual"
security-insights-url: ""        # URL to the project's security-insights.yml — project identity,
                                 # contacts, and basic lifecycle data live there, not here
sbom-url: ""                     # URL to CycloneDX or SPDX SBOM if present
security-txt: "" # link to rfc9116 url e.g., "https://example.com/.well-known/security.txt"
security-policy-details: "" # link or links to security policy that can be maintained at the higher project or organizatioal level (e.g, website, doc protal, etc.)

```

#### Block: `vulnerability-reporting`

```
spade-block: vulnerability-reporting
# Reporting contact details (email, PGP key, HackerOne URL, etc.) belong in security-insights.yml.
# This block covers the policy and process fields that Security Insights does not.
public-bugtracker-url: ""        # Public issue tracker URL (for non-security bugs)
disclosure-policy: "coordinated | immediate | no-disclosure"
embargo-days: 90                 # typical embargo window before public disclosure
distro-notification-days: 7     # how many days before release distros are notified (e.g. distros@openwall)
cna: true | false               # is this project a CVE Numbering Authority?

severity-model:
  type: "cvss | custom | none"   # curl-style projects may reject CVSS in favour of a custom scale
  cvss-version: "3.1 | 4.0"     # only if type is cvss
  custom-levels:                 # only if type is custom; list levels low-to-high
    - name: ""                   # e.g. "Low", "Medium", "High", "Critical"
      description: ""            # qualitative definition of this severity level

not-a-vulnerability:             # Classes of issues the project explicitly will NOT treat as security bugs
  - category: ""                 # e.g. "small-memory-leaks", "null-dereferences", "api-misuse"
    rationale: ""                # Why this class is out of scope as a security issue

incident-response:
  major-incident-defined: true | false   # Does the project have a declared major incident process?
  major-incident-criteria: ""            # Brief description of what triggers a major incident declaration
  incident-lead-role: ""                 # e.g. "curl-security team member"
  communication-lead-role: ""
  communication-channels:               # Official channels used during a major incident
    - ""                                # e.g. "security@example.com", "IRC #project on libera.chat"
```

#### Block: `supported-versions`

```
spade-block: supported-versions
# This block defines the machine-readable matrix guiding autonomous backporting. 
# Agents are hardcoded to ignore branches where support-tier is "eol". 
versions:
  - version: ""
    branch-regex: "" # e.g., "^release-v2\.[0-9]+$" 
    status: "active | lts | eol | maintanance (critical fixex ony)"
    support-tier: "current | lts" 
    eol-date: ""                 # ISO 8601 date or null
    security-fixes: true | false
    autonomous-backport-enabled: true | false # If true, the Developer Agent will attempt automated cherry-picks 
```

### Prose Sections (recommended)

The Markdown prose SHOULD include the following sections. Any section may be omitted if not applicable.

**`## What Counts as a Security IssueBug`** — Define the project's criteria for classifying a defect as security-relevant . Reference the `severity-model` from the YAML block and explain the rationale if the project deviates from CVSS (e.g., uses a qualitative four-level scale). Document any subsystems with non-standard classification rules (analogous to glibc's "Security Exceptions" section). MUST be consistent with the `not-a-vulnerability` list in the `vulnerability-reporting` block. A bug (code error) causes a weakness (flawed design), which becomes a vulnerability (potentially exploitable gap), which can be taken advantage of by a threat (attacker) to cause a negative impact.

**`## What Is NOT a Security IssueBug`** — Explicit, maintainer-authored enumeration of issue classes that will not be treated as security vulnerabilities, drawn from the `not-a-vulnerability` block. This is a first-class section: it sets expectations for reporters, reduces invalid reports, and tells AI agents not to flag these patterns as security findings. Examples from mature projects include: small memory leaks, null dereferences with no exploitable consequence, API misuse not covered by documented contracts, busy-loops that eventually terminate, and behavior that requires a local attacker already present on the system.

**`## Reporting a Vulnerability`** — Human-readable summary of the private reporting path, expected response times, embargo process, distro notification timeline, and what happens at public disclosure. MUST be consistent with the `vulnerability-reporting` block. If the project is a CNA, note this here.

**`## Severity Levels`** — Human-readable description of the project's severity scale, consistent with the `severity-model` block. If using a custom scale, define each level with qualitative criteria covering attack vector, complexity, privilege requirements, and impact dimensions. If using CVSS, note the version and any project-specific scoring guidance.

**`## Major Incident Response`** — If `major-incident-defined` is true, describe what constitutes a major incident (e.g., RCE with public exploit, premature embargo break, critical infrastructure compromise), how one is declared, who the named roles are, and what communication cadence is maintained. MUST be consistent with the `incident-response` block.

**`## Supported Versions`** — Human-readable table of supported versions, consistent with the `supported-versions` block.

**`## Security Architecture Notes`** — Brief orienting description of security-relevant design decisions (e.g., privilege separation, sandboxing, cryptographic dependencies). Links to `TRUST_BOUNDARIES.md`, `THREAT_MODEL.md`, and `SECURITY_POSTURE.md` SHOULD appear here. This section is intentionally brief — detailed hardening and build-assurance content lives in `SECURITY_POSTURE.md`.

---

## 2\. TRUST\_BOUNDARIES.md

### Purpose

Documents the trust boundaries present in the codebase — where privilege transitions occur, which components handle untrusted input, and what isolation mechanisms are in place. Enables AI agents to reason about which code paths are high-risk when reviewing PRs and to contextualize CVE impact.

### Relationship to Existing Standards

- Trust boundary taxonomy is drawn from OWASP Threat Modeling terminology.  
- Component identifiers SHOULD use the `purl` (Package URL) format from CycloneDX/SPDX where applicable.  
- ATT\&CK technique IDs may annotate boundaries where relevant lateral movement or privilege escalation techniques apply.

### Schema

#### Block: `spade-metadata` (required if file is present)

```
spade-artifact: TRUST_BOUNDARIES.md
spade-version: "0.1"
last-updated: "YYYY-MM-DD"
last-updated-reason: "release | architectural-change | manual"
```

#### Block: `trust-boundary-registry`

```
spade-block: trust-boundary-registry
boundaries:
  - id: "TB-001"                 # Short stable identifier, referenced from CVE_HISTORY and THREAT_MODEL
    name: ""                     # Human-readable name, e.g. "Network-to-Parser Boundary"
    type: "network | process | privilege | filesystem | ipc | trust-zone | other"
    crossing-direction: "inbound | outbound | bidirectional"
    components-inside:           # Components on the trusted side
      - purl: ""                 # pkg:type/name@version or empty
        label: ""
    components-outside:          # Components on the untrusted side
      - purl: ""
        label: ""
    input-validation-present: true | false
    sanitization-notes: ""
    isolation-mechanism: "none | seccomp | namespace | chroot | vm | enclave | lsm | ebpf | other"
    attack-surface-notes: ""
    mitre-attack-techniques:     # Optional; relevant ATT&CK technique IDs
      - "T1059"
    historical-cves:             # CVE IDs that crossed this boundary; cross-reference to CVE_HISTORY.md
      - "CVE-YYYY-NNNNN"
```

#### Block: `privilege-levels`

```
spade-block: privilege-levels
levels:
  - id: "PL-001"
    name: ""                     # e.g. "root / kernel", "daemon user", "unprivileged user", "network"
    components:
      - label: ""
        purl: ""
    notes: ""
```

### Mermaid Diagram (normative)

`TRUST_BOUNDARIES.md` MUST include a Mermaid `graph` diagram as the canonical visual representation of the trust boundary topology. The diagram is generated from the `trust-boundary-registry` and `privilege-levels` blocks and MUST be kept in sync with them.

**Diagram conventions:**

- Each privilege level (`PL-*`) is rendered as a Mermaid `subgraph`.  
- Each trust boundary crossing is rendered as a directed edge between nodes on either side of the boundary, labeled with the boundary `id`.  
- Nodes represent components (the `label` field). Where a `purl` is present, it SHOULD appear as a comment alongside the node.  
- Boundaries with `input-validation-present: false` MUST use a dashed edge (`-.->`) to visually flag missing validation.  
- Boundaries with historical CVEs MUST annotate the edge label with `⚠` followed by the CVE count (e.g., `TB-001 ⚠3`).

**Example:**

```
graph TD
  subgraph PL-001["Root / Kernel"]
    kernel["Kernel syscall interface"]
  end

  subgraph PL-002["Daemon"]
    nscd["nscd (name service cache)"]
  end

  subgraph PL-003["Unprivileged User"]
    app["Application process"]
    regex["Regex engine (regcomp/regexec)"]
  end

  subgraph NETWORK["Network (untrusted)"]
    dns["DNS responses"]
  end

  dns -.->|"TB-001 ⚠4"| nscd
  app -->|"TB-002"| kernel
  app -->|"TB-003"| regex
```

The diagram SHOULD appear immediately after the `spade-metadata` block, before any other prose, so that human readers and rendering tools encounter it at the top of the file.

### Prose Sections (recommended)

**`## Overview`** — A brief narrative (2–5 sentences) describing the overall trust architecture. The Mermaid diagram serves as the visual anchor; this section provides the interpretive context.

**`## Boundary Descriptions`** — For each entry in `trust-boundary-registry`, a paragraph explaining the context, the validation story, and any known weaknesses or historical incidents. MUST reference the `id` field from the YAML block (e.g., "**TB-001: Network-to-Parser Boundary**").

**`## High-Risk Crossing Points`** — Narrative summary of which boundaries have the highest historical CVE density or the weakest isolation. Cross-references to `CVE_HISTORY.md` and `THREAT_MODEL.md`.

---

## 3\. CVE\_HISTORY.md

### Purpose

A machine-readable and human-readable scorecard of all CVEs assigned to the project, the CWE patterns they represent, the codebase areas most frequently implicated, remediation quality, and analyst guidance for downstream consumers assessing supply-chain risk.

### Relationship to Existing Standards

- CVE records are sourced from NVD/NIST. The `nvd-url` field links directly to the NVD entry.  
- CVSS scores use CVSSv3.1 (or CVSSv4.0 where available) base scores from NVD.  
- CWE identifiers come from the MITRE CWE taxonomy.  
- Pipeline tooling SHOULD query the NVD API (`https://services.nvd.nist.gov/rest/json/cves/2.0`) to auto-populate new CVE entries on publication.

### Schema

#### Block: `spade-metadata` (required if file is present)

```
spade-artifact: CVE_HISTORY.md
spade-version: "0.1"
last-updated: "YYYY-MM-DD"
last-updated-reason: "release | cve-published | manual"
nvd-vendor-string: ""            # Vendor string as it appears in NVD CPE, e.g. "gnu"
nvd-product-string: ""           # Product string as it appears in NVD CPE, e.g. "glibc"
```

#### Block: `cve-summary-stats`

This block is intended to be auto-generated by pipeline tooling from the `cve-entries` block below. Maintainers MAY author it manually if no pipeline is in place.

```
spade-block: cve-summary-stats
total-cves: 0
open-cves: 0
severity-distribution:
  critical: 0                    # CVSS >= 9.0
  high: 0                        # CVSS 7.0–8.9
  medium: 0                      # CVSS 4.0–6.9
  low: 0                         # CVSS < 4.0
top-cwes:                        # CWEs appearing 2 or more times, sorted by frequency
  - cwe-id: "CWE-119"
    label: "Improper Restriction of Operations within the Bounds of a Memory Buffer"
    count: 0
cwe-classes-not-applicable:      # CWE classes maintainers assert do NOT apply to this codebase
  - cwe-id: "CWE-89"
    label: "SQL Injection"
    rationale: "Project does not use a SQL database."
high-risk-areas:                 # Source paths or subsystems with 2 or more historical CVEs
  - path-or-subsystem: ""
    cve-count: 0
    trust-boundary-ids:
      - "TB-001"
mean-time-to-fix-days: 0
patch-backport-rate: 0.0         # Fraction of CVEs backported to all supported branches (0.0–1.0)
```

#### Block: `cve-entries`

One entry per CVE. Pipeline tooling SHOULD populate `nvd-*` fields automatically; maintainers SHOULD populate the remaining fields.

```
spade-block: cve-entries
entries:
  - cve-id: "CVE-YYYY-NNNNN"
    nvd-url: "https://nvd.nist.gov/vuln/detail/CVE-YYYY-NNNNN"
    nvd-published: "YYYY-MM-DD"
    nvd-cvss-version: "3.1 | 4.0"
    nvd-cvss-score: 0.0
    nvd-cvss-vector: ""          # e.g. CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
    nvd-cwes:
      - "CWE-119"
    status: "open | fixed | disputed | wont-fix"
    fix-released-version: ""     # First release containing the fix; null if not fixed
    fix-commit: ""               # Commit hash or PR URL
    days-to-fix: 0
    affected-subsystem: ""       # e.g. "regex engine", "nscd", "malloc"
    trust-boundary-ids:
      - "TB-001"
    maintainer-notes: ""         # Root cause, contributing factors, notable fix complexity
    repeat-pattern: true | false # True if same CWE recurred in same subsystem as a prior CVE

```

### Prose Sections (recommended)

**`## Summary`** — Narrative summary of the project's CVE history: total count, severity distribution, trend over time, and overall risk characterization. Intended for downstream integrators and auditors assessing supply-chain risk.

**`## CWE Patterns`** — Discussion of which vulnerability classes repeatedly affect this codebase and which do not. The `cwe-classes-not-applicable` list is as important as `top-cwes` — it tells AI agents and auditors where not to focus.

**`## High-Risk Areas`** — Narrative description of repeat-offender subsystems. For each, explain the structural reason for recurring vulnerabilities and what architectural or process changes have been made. Cross-reference to `TRUST_BOUNDARIES.md` boundary IDs.

**`## Remediation Quality`** — Discuss mean time to fix, backport quality, and any patterns in fix regressions.

**`## Guidance for Downstream Consumers`** — Which CVEs are likely to affect a typical deployment, which are only relevant under unusual configurations, and how to monitor for new CVEs against this project (e.g., NVD CPE watch, OSV subscription).

**`## Vulnerability Enrichment`** — Bridges raw CVE information with dynamic threat context. Agent uses this file to aggregate data from external intelligence databases (NVD, osv.dev, CISA KEV, EUVD, EPSS, patchthis.app) and vendor advisories (in machine readable formats like CSAF or OpenVEX). If the repo is part of the bigger project, a reference to the place where the security metadata is published (instead of downloading all databases)  is sufficient and recommended. Based on this enriched data and internal reachability analysis, the agent autonomously can writes its own OpenVEX or CSAF-compliant VEX attestations here in the repo (or the parent project repo) to consistently document non-exploitable CVEs.

---

## 4\. THREAT\_MODEL.md

### Purpose

Documents the intended deployment environments, threat actors, attack scenarios, and mitigations for the project. Structured to allow AI agents to assess whether an incoming CVE or PR is relevant to a particular deployment context, and to allow downstream integrators to determine whether the project's threat model matches their own.

### Relationship to Existing Standards

- Structure is informed by the OWASP Threat Modeling Cheat Sheet (STRIDE methodology).  
- Deployment environment descriptions are compatible with CycloneDX `metadata.component` context fields.  
- Threat actor taxonomy draws from MITRE ATT\&CK groups where relevant.  
- This file extends (and does not replace) OpenSSF Security Insights — the `security-insights.yml` file's `project` block should cross-reference this file.

### Schema

#### Block: `spade-metadata` (required if file is present)

```
spade-artifact: THREAT_MODEL.md
spade-version: "0.1"
last-updated: "YYYY-MM-DD"
last-updated-reason: "release | architectural-change | new-threat | manual"
threat-modeling-methodology: "STRIDE | PASTA | LINDDUN | attack-tree | other"
```

#### Block: `deployment-contexts`

```
spade-block: deployment-contexts
contexts:
  - id: "DC-001"
    name: ""                     # e.g. "Embedded in Linux userspace as libc"
    description: ""
    typical-privilege-level: "root | daemon | user | unprivileged | varies"
    network-exposed: true | false
    internet-facing: true | false
    typical-co-deployed-with:
      - name: ""
        purl: ""                 # Optional
    data-sensitivity: "none | low | medium | high | critical"
    regulatory-context:
      - "FedRAMP | SOC2 | PCI-DSS | HIPAA | ISO27001 | none"
```

#### Block: `threat-actors`

```
spade-block: threat-actors
actors:
  - id: "TA-001"
    name: ""                     # e.g. "Remote unauthenticated attacker"
    type: "external | insider | supply-chain | automated-scanner | nation-state"
    motivation: ""
    typical-access: ""           # e.g. "network", "crafted input file", "malicious dependency"
    mitre-attack-groups:         # Optional; relevant ATT&CK group IDs
      - "G0016"
    applicable-deployment-contexts:
      - "DC-001"
```

#### Block: `threats`

```
spade-block: threats
threats:
  - id: "TH-001"
    stride-category: "Spoofing | Tampering | Repudiation | Information Disclosure | Denial of Service | Elevation of Privilege"
    name: ""
    description: ""
    threat-actor-ids:
      - "TA-001"
    trust-boundary-ids:
      - "TB-001"
    deployment-context-ids:
      - "DC-001"
    likelihood: "low | medium | high | critical"
    impact: "low | medium | high | critical"
    mitre-attack-techniques:
      - "T1059"
    mitigations:
      - description: ""
        status: "implemented | partial | planned | accepted-risk | not-applicable"
        notes: ""
    related-cves:
      - "CVE-YYYY-NNNNN"
    residual-risk: "low | medium | high | critical"
```

#### Block: `out-of-scope`

```
spade-block: out-of-scope
items:
  - description: ""              # e.g. "Attacks requiring physical access to the host"
    rationale: ""
```

### Prose Sections (recommended)

**`## System Overview`** — Brief description of what the project is, what it does, and what it is not. Reference the `deployment-contexts` block. MAY include a Mermaid diagram of the system model.

**`## Threat Actors`** — Narrative description of who threatens this project and how. Reference the `threat-actors` block. For each actor, describe their realistic capabilities and motivation.

**`## Threat Analysis`** — For each entry in the `threats` block, a paragraph explaining the threat scenario, the evidence base (historical CVEs, academic research, real-world incidents), the mitigation status, and the residual risk. Organized by STRIDE category or by deployment context at the author's discretion.

**`## Out of Scope`** — Explicit enumeration of threat scenarios the project does not attempt to mitigate and why. This is a first-class section — it tells AI agents and auditors not to flag certain classes of findings as gaps.

**`## Integration Guidance`** — Written for downstream integrators: how to extend this threat model for a specific deployment, which threats become more or less relevant depending on deployment context, and what integrator-side controls are expected to complement the project's own mitigations.

---

## 5\. SECURITY\_POSTURE.md

### Purpose

Documents the accepted residual risks, design-level security assumptions, and usage preconditions that users and deployers must understand and accept when adopting the software. This is distinct from `THREAT_MODEL.md` (which describes threats and active mitigations) and `CVE_HISTORY.md` (which tracks past vulnerabilities). `SECURITY_POSTURE.md` answers the question: *"What is knowingly true about this software's security envelope, by design, that I need to account for in my deployment?"*

These are not bugs awaiting fixes. They are the product of deliberate design decisions, inherent constraints of the problem domain, or security properties the project explicitly does not guarantee. Documenting them clearly reduces invalid vulnerability reports, sets accurate expectations for integrators and auditors, and gives AI agents a ground-truth list of findings to suppress when reviewing this codebase.

### Relationship to Existing Standards

- Complements the `not-a-vulnerability` list in `SECURITY.md`, which defines what the project won't classify as a security bug. `SECURITY_POSTURE.md` goes further, describing *why* certain risks exist and what mitigating controls (if any) the user is responsible for.  
- Residual risks documented here SHOULD cross-reference the `out-of-scope` block in `THREAT_MODEL.md` where applicable.  
- Particularly relevant for supply-chain consumers performing due diligence under frameworks like SLSA, FedRAMP, or SOC 2\.

### Schema

#### Block: `spade-metadata` (required if file is present)

```
spade-artifact: SECURITY_POSTURE.md
spade-version: "0.1"
last-updated: "YYYY-MM-DD"
last-updated-reason: "release | design-change | manual"
```

#### Block: `hardening`

Documents secure configuration guidance and defense-in-depth controls. Moved here from `SECURITY.md` because this is deployer-facing posture information, not vulnerability reporting policy.

```
spade-block: hardening
default-config-secure: true | false   # Is the out-of-the-box config secure by default?
recommended-configs:
  - name: ""
    description: ""
    url: ""                      # Link to config file or documentation
mac-policies:
  - type: "selinux | apparmor | seccomp | other"
    status: "provided | third-party | none"
    url: ""
defense-in-depth:
  - control: ""                  # e.g. "stack canaries", "RELRO", "PIE"
    enabled-by-default: true | false
    notes: ""
```

#### Block: `code-quality-practices`

Documents the proactive code quality and security assurance practices the project applies. Moved here from `SECURITY.md` because build-time assurance is a posture concern, not a disclosure policy concern. Useful for AI agents assessing supply-chain trustworthiness and for compliance frameworks (e.g., OpenSSF Gold badge, SLSA).

```
spade-block: code-quality-practices
sast:
  - tool: ""                     # e.g. "CodeQL", "Coverity", "Semgrep"
    status: "ci | periodic | manual | none"
    url: ""                      # Link to workflow or results if public
fuzzing:
  - tool: ""                     # e.g. "OSS-Fuzz", "libFuzzer", "AFL++"
    status: "continuous | periodic | none"
    coverage-url: ""             # Link to fuzzing coverage or corpus if public
sanitizers:
  - type: "asan | msan | ubsan | tsan | other"
    applied-in-ci: true | false
memory-safe-components:          # Subsystems implemented in memory-safe languages
  - component: ""
    language: ""                 # e.g. "Rust", "Go"
    notes: ""
dependency-management:
  renovate-or-dependabot: true | false
  sbom-generated: true | false
  sbom-format: "CycloneDX | SPDX | none"
  pinned-dependencies: true | false
openssf-best-practices-url: ""  # URL to bestpractices.dev badge entry if present
openssf-scorecard-url: ""       # URL to scorecard results if present
```

#### Block: `accepted-risks`

The core of this artifact. Each entry describes a known, accepted risk — something that is true about the software by design, by constraint, or by explicit decision not to fix.

```
spade-block: accepted-risks
risks:
  - id: "AR-001"
    name: ""                     # Short name, e.g. "Insecure-protocol transfers"
    category: "design | dependency | operational | api-contract | platform | algorithm"
    description: ""              # What the risk is and why it exists
    affects:                     # Who or what deployment contexts are affected
      - deployment-context-id: "DC-001"   # Cross-reference to THREAT_MODEL.md
        notes: ""
    user-responsibility: ""      # What the user/deployer must do to mitigate this risk themselves
    project-mitigation: ""       # What the project does (if anything) to reduce the risk
    cannot-be-fixed-because: ""  # Why the project cannot or will not eliminate this risk
    related-cves: []             # CVEs that are related but were accepted, not fixed
    related-threat-ids: []       # Cross-reference to THREAT_MODEL.md threats[] ids
```

#### Block: `security-assumptions`

Explicit statements of what the project assumes to be true about the environment it runs in. If these assumptions are violated, the project's security properties do not hold.

```
spade-block: security-assumptions
assumptions:
  - id: "SA-001"
    description: ""              # e.g. "The host OS kernel is trusted and uncompromised"
    if-violated: ""              # What security properties break if this assumption is false
    deployment-context-ids:
      - "DC-001"
```

#### Block: `api-contract-risks`

Documents security risks that arise specifically from API misuse — calling the library in ways that are not documented or are explicitly documented as unsafe. Particularly important for libraries consumed by other software.

```
spade-block: api-contract-risks
risks:
  - id: "ACR-001"
    description: ""              # e.g. "Passing untrusted data to wordexp() causes exponential memory use"
    unsafe-pattern: ""           # The misuse pattern to avoid
    documented-safe-usage: ""    # What the correct usage is
    url: ""                      # Link to documentation of the safe API contract
```

#### Block: `weak-algorithm-usage`

Documents cases where the project supports or uses algorithms known to be cryptographically weak, explaining the rationale and any conditions under which they are active.

```
spade-block: weak-algorithm-usage
algorithms:
  - name: ""                     # e.g. "MD5", "DES", "RC4"
    used-for: ""                 # e.g. "NTLM authentication", "legacy HTTP Digest"
    enabled-by-default: true | false
    user-opt-in-required: true | false
    rationale: ""                # Why the project still supports this algorithm
    recommended-alternative: ""  # What users should migrate to
```

#### Block: `compliance-posture`

Continuous compliance requires integrated, machine-readable documentation rather than external, point-in-time audits. To prevent architectural changes that violate regulatory baselines (e.g., downgrading cryptography in a FedRAMP boundary or bypassing logging in a PCI-DSS environment), a project must natively declare its regulatory adherence. The compliance-posture block acts as a machine-readable compliance ledger. By optional mapping project boundaries to specific regulatory frameworks and Open Security Controls Assessment Language (OSCAL) definitions, this block enables automated CI/CD tooling to cross-reference proposed architectural shifts against established constraints and automatically halt pipelines if violations are detected.

```
compliance-posture
spade-block: compliance-posture
# Machine-readable ledger of regulatory adherence.
frameworks:
  - framework-name: ""            # e.g., "NIST-SSDF", "PCI-DSS", "EU-CRA", "FINOS CCC"
    framework-version: ""         # e.g., "1.1", "v3", "v1.0"
    status: "certified | self-assessed | in-progress | exempt | best-effort"
    scoping-boundary: "global | component-specific"
    last-attestation-timestamp: "" # Strict ISO 8601 UTC format (e.g., 2026-04-17T12:00:00Z)
    compliance-declaration: "" # Link to a page or artifact that describes compliance declaration or expresses more details
    oscal-component: ""       # URI to the external OSCAL machine-readable component definitions
    agent-enforcement-mode: "strict-l3-halt | passive-audit-log" # Governs agent behavior upon detecting compliance drift
```

### Prose Sections (recommended)

**`## Overview`** — A short framing paragraph explaining that this document describes the deliberate security posture of the software: how it is built, how it is hardened, and what risks are knowingly accepted. Sets the tone clearly so it is not confused with a vulnerability list.

**`## Hardening Recommendations`** — Narrative guidance on secure configuration, consistent with the `hardening` block. Reference any MAC policies and defense-in-depth controls. MAY reference relevant CIS Benchmarks, DISA STIGs, or OSA architecture patterns by URL.

**`## Code Quality and Assurance Practices`** — Narrative description of the build-time security assurance pipeline, consistent with the `code-quality-practices` block. Describe what SAST tools run and how findings are triaged, what fuzzing coverage exists and how long it has run, which sanitizers gate CI, and the dependency management approach. This section gives downstream consumers and auditors concrete evidence of the project's proactive security investment.

**`## Accepted Risks`** — For each entry in `accepted-risks`, a paragraph providing full narrative context: what the risk is, why the project cannot or will not eliminate it, what the user must do about it, and any historical incidents where this risk materialized. Organized by `category` at the author's discretion.

**`## Security Assumptions`** — Narrative description of the environmental and operational assumptions the project relies on. For each assumption, explain what breaks if it does not hold and what steps deployers can take to validate their environment meets the assumption.

**`## API Contract Risks`** — For library projects especially: a clear description of which API usage patterns are unsafe and why, and what the correct documented usage looks like. Cross-reference relevant sections of the project's API documentation.

**`## Weak Algorithms`** — Transparent accounting of all cryptographically weak algorithms the project supports, under what conditions they activate, and what the migration path is. Explicitly note if any are enabled by default.

**`## What This Document Is Not`** — A brief closing section clarifying that the risks documented here are accepted design decisions, not an invitation to report them as vulnerabilities. Direct reporters to `SECURITY.md` for the vulnerability reporting process and to the `not-a-vulnerability` section for issue classification guidance.

---

## Cross-Artifact Linking

The four artifacts form a linked graph. The following cross-references SHOULD be maintained:

| From | Field | To |
| :---- | :---- | :---- |
| `CVE_HISTORY.md` | `cve-entries[].trust-boundary-ids` | `TRUST_BOUNDARIES.md` `boundaries[].id` |
| `CVE_HISTORY.md` | `cve-summary-stats.high-risk-areas[].trust-boundary-ids` | `TRUST_BOUNDARIES.md` `boundaries[].id` |
| `TRUST_BOUNDARIES.md` | `boundaries[].historical-cves` | `CVE_HISTORY.md` `cve-entries[].cve-id` |
| `THREAT_MODEL.md` | `threats[].trust-boundary-ids` | `TRUST_BOUNDARIES.md` `boundaries[].id` |
| `THREAT_MODEL.md` | `threats[].related-cves` | `CVE_HISTORY.md` `cve-entries[].cve-id` |
| `SECURITY.md` | prose links | `TRUST_BOUNDARIES.md` and `THREAT_MODEL.md` by filename |
| `SECURITY_POSTURE.md` | `accepted-risks[].deployment-context-ids` | `THREAT_MODEL.md` `deployment-contexts[].id` |
| `SECURITY_POSTURE.md` | `accepted-risks[].related-threat-ids` | `THREAT_MODEL.md` `threats[].id` |
| `SECURITY_POSTURE.md` | `accepted-risks[].related-cves` | `CVE_HISTORY.md` `cve-entries[].cve-id` |

An agent performing a holistic security review SHOULD construct this graph to answer questions like: "Which trust boundaries are both historically vulnerable and currently threatened?"

---

## Update Triggers

Artifacts have two natural update triggers, and both matter:

**On every release.** Update `last-updated` and `last-updated-reason` in all present artifacts. Review `supported-versions` in `SECURITY.md`, recompute `cve-summary-stats` in `CVE_HISTORY.md` from `cve-entries`, and check whether any `THREAT_MODEL.md` residual-risk assessments have changed as a result of code changes in the release.

**On every CVE publication.** Add a new entry to `cve-entries` in `CVE_HISTORY.md` (NVD-sourced fields can be populated automatically from the NVD API using the project's CPE string). Update `cve-summary-stats`. Then review `TRUST_BOUNDARIES.md` and `THREAT_MODEL.md` to determine whether the new CVE crosses a documented boundary or realizes a documented threat — if so, those files need a human review pass too.

---

## AI Agent Consumption Guide

An AI agent consuming these artifacts for security-relevant tasks SHOULD follow this protocol:

1. **Parse all four `spade-metadata` blocks** to establish recency and determine which artifacts are present.  
2. **For CVE triage:** Load `cve-summary-stats` for base rates, then load `TRUST_BOUNDARIES.md` boundaries to determine if the new CVE's attack path crosses a known high-risk boundary.  
3. **For PR review:** Load `TRUST_BOUNDARIES.md` and identify which boundaries the changed code touches. Cross-reference `historical-cves` on those boundaries. Load the relevant `threats` from `THREAT_MODEL.md` to assess whether the PR increases residual risk.  
4. **For compliance reporting:** Load all four `spade-metadata` blocks plus `cve-summary-stats`, `supported-versions`, `vulnerability-reporting`, and `deployment-contexts`. These blocks together provide the data required for a SOC 2 / FedRAMP supply-chain risk narrative.  
5. **For patch generation guidance:** Load the `threats` block for the affected component, `affected-subsystem` from the relevant `cve-entries`, and `hardening` from `SECURITY.md` to contextualize what a correct fix must preserve.

---

## Versioning

This standard uses semantic versioning. The `spade-version` field in each artifact's `spade-metadata` block identifies the version of this specification the artifact was authored against. Breaking schema changes increment the major version. Additive changes increment the minor version. Tooling SHOULD treat unknown fields as ignored rather than as errors, to allow forward compatibility.

---

## Relationship to OpenSSF Security Insights

SPADE and OpenSSF Security Insights (`security-insights.yml`) are complementary standards with a clean division of labour. Understanding that division is important for avoiding duplication and for knowing which file to consult for a given question.

**Security Insights is the identity and contact card.** It answers: Who maintains this project? Where do I report a vulnerability? What lifecycle stage is the project in? Where are packages distributed? Is there a bug bounty? It is a lightweight, broadly adopted YAML declaration designed to be filled out in under 30 minutes and kept current with periodic reminders.

**SPADE is the deep policy and threat context.** It answers: How does this project classify and handle vulnerabilities? What are the trust boundaries in the codebase? What does the CVE history reveal about recurring risk patterns? What threat actors and scenarios has the project modelled? What security posture is a deployer accepting? SPADE artifacts are richer, more technical, and more effort to maintain — written for security researchers, AI agents, auditors, and sophisticated integrators, not just reporters.

### What each standard owns

| Concern | Security Insights | SPADE |
| :---- | :---- | :---- |
| Project identity and homepage | ✓ | — |
| Security contacts and PGP key | ✓ | — |
| Vulnerability reporting URL | ✓ | — |
| Project lifecycle stage | ✓ | — |
| Distribution points / package URLs | ✓ | — |
| Bug bounty existence | ✓ | — |
| Supported versions (coarse) | ✓ | — |
| Supported versions (per-version security policy) | — | ✓ `SECURITY.md` |
| Embargo duration and distro notification | — | ✓ `SECURITY.md` |
| Severity model and definitions | — | ✓ `SECURITY.md` |
| What is / is not a vulnerability | — | ✓ `SECURITY.md` |
| Incident response process | — | ✓ `SECURITY.md` |
| CNA status | — | ✓ `SECURITY.md` |
| Trust boundary map | — | ✓ `TRUST_BOUNDARIES.md` |
| CVE history and CWE patterns | — | ✓ `CVE_HISTORY.md` |
| Threat model | — | ✓ `THREAT_MODEL.md` |
| Accepted risks and security assumptions | — | ✓ `SECURITY_POSTURE.md` |
| Hardening and build assurance practices | — | ✓ `SECURITY_POSTURE.md` |

### Linking the two

The `security-insights-url` field in `SECURITY.md`'s `spade-metadata` block points from SPADE to Security Insights. In the other direction, a project's `security-insights.yml` MAY use the `security-artifacts` section to reference its SPADE files. A consuming agent that finds both should treat them as a unified security profile — Security Insights for identity and contacts, SPADE for everything deeper.

