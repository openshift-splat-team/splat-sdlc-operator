# OpenShift Repository Dependency Map

## Tier 0 — Foundation Libraries
These are depended on by 30–50+ repos each. Changes here cascade widely.
A PR to any Tier 0 repo must be merged and vendored before downstream work can proceed.

| Repository | Module path | Role |
|---|---|---|
| openshift/api | github.com/openshift/api | Canonical OpenShift API types (CRDs, versioned structs). Every operator and control plane component imports this. |
| openshift/library-go | github.com/openshift/library-go | Shared operator utilities: controllers, informers, cert management, status reporting. |
| openshift/client-go | github.com/openshift/client-go | Generated Go clients for OpenShift API types. Wraps openshift/api. |
| openshift/build-machinery-go | github.com/openshift/build-machinery-go | Shared Makefile targets and build tooling used by virtually all OpenShift repos. |
| openshift/apiserver-library-go | github.com/openshift/apiserver-library-go | Shared apiserver utilities (admission, authorization) for OpenShift API servers. |

## Tier 1 — Core Control Plane
Tightly coupled. Must be kept in sync with each other and Tier 0.

| Repository | Role |
|---|---|
| openshift/origin | Main OpenShift codebase — CLI (oc), integration tests, bootstrap code. |
| openshift/openshift-apiserver | OpenShift-specific API server extending kube-apiserver. Handles Build, Image, Route, OAuth APIs. |
| openshift/openshift-controller-manager | Controllers for Builds, DeploymentConfigs, ImageStreams. |
| openshift/kubernetes | OpenShift's fork of kubernetes/kubernetes. Carries downstream patches. |
| openshift/openshift-tests | End-to-end test suite for OpenShift. |

## Tier 2 — Cluster Operators
Each operator owns one area of cluster functionality. All follow the same structure:
import openshift/api + openshift/library-go + openshift/client-go.

### Control Plane Operators
| Repository | Manages |
|---|---|
| openshift/cluster-version-operator (CVO) | Applies and reconciles all other operators via ClusterVersion. Entry point for all upgrades. |
| openshift/cluster-kube-apiserver-operator | kube-apiserver configuration and lifecycle. |
| openshift/cluster-kube-controller-manager-operator | kube-controller-manager. |
| openshift/cluster-kube-scheduler-operator | kube-scheduler. |
| openshift/cluster-openshift-apiserver-operator | Manages openshift-apiserver deployment. |
| openshift/cluster-openshift-controller-manager-operator | Manages openshift-controller-manager. |
| openshift/cluster-etcd-operator | etcd cluster management and backup. |
| openshift/cluster-authentication-operator | OAuth server, identity providers. |
| openshift/cluster-config-operator | Core cluster config (infrastructure, network type, proxy). |

### Infrastructure Operators
| Repository | Manages |
|---|---|
| openshift/machine-config-operator (MCO) | Node OS configuration, CRI-O, kubelet. Highest blast radius for node changes. |
| openshift/cluster-node-tuning-operator | Node performance tuning (NTO/TuningProfile). |
| openshift/cluster-image-registry-operator | Internal image registry. |
| openshift/cluster-samples-operator | OpenShift sample templates and imagestreams. |

### Networking & Storage
| Repository | Manages |
|---|---|
| openshift/cluster-network-operator | SDN/OVN-Kubernetes network plugin lifecycle. |
| openshift/cluster-dns-operator | CoreDNS deployment and config. |
| openshift/cluster-ingress-operator | IngressController / HAProxy router. |
| openshift/cluster-storage-operator | CSI driver operators, default storage class. |
| openshift/csi-operator | Unified CSI driver operator framework. |

### User-Facing Operators
| Repository | Manages |
|---|---|
| openshift/console-operator | Web console deployment. |
| openshift/cluster-monitoring-operator | Prometheus/Alertmanager/Grafana stack. |
| openshift/cluster-logging-operator | Log forwarding (Loki, Elasticsearch). |
| openshift/oc | `oc` CLI (also in openshift/origin). |

### Operator Framework
| Repository | Role |
|---|---|
| operator-framework/operator-sdk | SDK for building operators. |
| operator-framework/operator-lifecycle-manager (OLM) | Installs and manages operator subscriptions in-cluster. |
| openshift/operator-framework-operator-controller | Controller for operator lifecycle. |
| openshift/operator-framework-catalogd | Catalog of available operators. |

## Tier 3 — Installation & Bootstrap
| Repository | Role |
|---|---|
| openshift/installer | `openshift-install` — provisions cloud infra and bootstraps clusters. |
| openshift/hive | Cluster provisioning operator (uses installer under the hood). |
| openshift/machine-api-operator | Manages Machine/MachineSet CRDs for node scaling. |
| openshift/cluster-autoscaler-operator | Wraps cluster-autoscaler for OpenShift. |
| openshift/hypershift | Hosted control planes (control plane runs as pods in a management cluster). |

## Tier 4 — Release & Payload
| Repository | Role |
|---|---|
| openshift/release | CI configuration (Prow jobs, rehearsal), release branch management. All operator repos' CI is defined here. |
| openshift/release-controller | Watches image streams, drives nightly and release builds. |
| openshift/cluster-version-operator | (also Tier 2) Consumes release payload, drives upgrades. |
| openshift/cincinnati-graph-data | Update graph — which versions can upgrade to which. |
| openshift/oc-mirror | Mirrors release payloads to disconnected registries. |

## Tier 5 — CI Infrastructure
| Repository | Role |
|---|---|
| openshift/ci-tools | ci-operator, applyconfig, sanitize-prow-jobs, promotion tooling. |
| openshift/ci-operator | Executes test workflows defined in openshift/release. |
| openshift/prow | OpenShift's Prow fork (GitHub bot, job scheduling). |
| openshift/ci-chat-bot | Slack bot for launching on-demand CI clusters. |

## Tier 6 — Cloud Provider Integrations
| Repository | Role |
|---|---|
| openshift/cloud-provider-aws | AWS cloud controller manager. |
| openshift/cloud-provider-azure | Azure cloud controller manager. |
| openshift/cloud-provider-gcp | GCP cloud controller manager. |
| openshift/cluster-cloud-controller-manager-operator | Manages cloud provider integrations. |

---

## Dependency Cascade Rules

1. **Tier 0 change → vendor bump required in ALL consumers before their CI passes.**
   Typical sequence: merge Tier 0 PR → run `make update-vendor` in each consumer → open bump PRs.

2. **API-first rule**: New CRDs or API type changes must land in `openshift/api` first.
   Operators cannot reference types that don't exist in the vendored api package.

3. **CVO payload order**: The cluster-version-operator applies manifests in dependency order.
   An operator whose CRDs are required by another must appear earlier in the payload.

4. **MCO is the riskiest**: Machine Config Operator changes affect all nodes.
   Always requires a reboot test and multi-version upgrade test in CI.

5. **Release branch discipline**: Each OCP minor version (4.14, 4.15, 4.16…) has a
   corresponding branch in every repo. PRs to `main`/`master` target the next release.
   Backports require separate PRs to the release branches.

---

## Common Feature Development Paths

### New cluster operator feature
1. Add/update types in `openshift/api`
2. Vendor bump `openshift/api` in `openshift/library-go` if shared logic needed
3. Implement in the operator repo
4. Add CI job in `openshift/release`
5. E2E tests in `openshift/openshift-tests`

### New API resource (CRD)
1. Design API in `openshift/api` (types, validation, defaulting)
2. Generate clients via `openshift/client-go`
3. Implement controller in `openshift/openshift-controller-manager` or a dedicated operator
4. Register in `openshift/openshift-apiserver` if it needs aggregated API server

### Node-level change
1. Assess whether MCO or NTO owns it
2. MachineConfig changes → `openshift/machine-config-operator`
3. Kernel/tuning → `openshift/cluster-node-tuning-operator`
4. Requires reboot test in CI

### OLM-managed operator
1. Develop operator using `operator-framework/operator-sdk`
2. Create bundle (CSV, CRDs, RBAC)
3. Submit to `operator-framework/community-operators` or Red Hat catalog
4. OLM installs via Subscription → InstallPlan

### Installer / infrastructure change
1. Cloud resource changes → `openshift/installer` (Terraform/IPI)
2. Post-install cluster config → Day-2 operator
3. Machine provisioning → `openshift/machine-api-operator`
