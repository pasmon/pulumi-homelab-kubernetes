"""A Kubernetes Python Pulumi program"""
import base64

import pulumi
from pulumi import ResourceOptions
from pulumi_kubernetes.meta.v1 import ObjectMetaArgs
from pulumi_kubernetes.core.v1 import Secret, Namespace
from pulumi_kubernetes.helm.v3 import Release, RepositoryOptsArgs
from pulumi_kubernetes.helm.v3 import ReleaseArgs as HelmReleaseArgs

from pulumi_kubernetes.apiextensions import CustomResource
from pulumi_kubernetes.yaml import ConfigFile
from pulumi_kubernetes_cert_manager import CertManager, ReleaseArgs, CertManagerStartupAPICheckArgs, CertManagerWebhookArgs


config = pulumi.Config()
if config.require('environment') != 'test':
    email = config.require('email')
    dns_token = config.require('dns_token')
    domain = config.require('domain')
    traefik_dashboard_users = config.require('traefik_dashboard_users')

    metallb_configmap = ConfigFile(
        "metallb_configmap",
        file="external/metallb-configmap.yaml"
    )
else:
    email = 'no_reply@example.com'
    dns_token = 'somethingsomething'
    domain = 'example'
    traefik_dashboard_users = 'YWRtaW46JGFwcjEkYm1XRFRuVkEkU3VsUk1YbTRtL2NrTnpqMDVuS21UMAoK'

domain_dashed = domain.replace('.', '-')


# Create a sandbox namespace.
ns_name = 'cert-manager'
certmanager_namespace = Namespace('cert-manager-namespace',
                                  metadata={
                                    'name': ns_name
                                  }
                                  )

# Install cert-manager into our cluster.
# https://github.com/jetstack/cert-manager/blob/master/deploy/charts/cert-manager/values.yaml
certmanager = CertManager('cert-manager',
                          install_crds=True,
                          startupapicheck=CertManagerStartupAPICheckArgs(
                            enabled=True,
                            timeout="10m",
                            backoff_limit=8,
                          ),
                          webhook=CertManagerWebhookArgs(
                            timeout_seconds=30,
                          ),
                          helm_options=ReleaseArgs(
                            name='cert-manager',
                            namespace=ns_name,
                            values={
                                "webhook": {
                                    "timeoutSeconds": "600"
                                },
                                "startupapicheck": {
                                    "enabled": False,
                                    "timeout": "10m",
                                    "backoffLimit": 8
                                }
                            },
                            timeout=600
                          )
                          )


def define_ns(obj):
    obj["metadata"]["namespace"] = "cert-manager"


dns_secret = Secret(
    "duckdns-secret",
    metadata=ObjectMetaArgs(
        name="duckdns-token",
        namespace=ns_name,
    ),
    type="Opaque",
    data={
        "token": str(base64.b64encode(bytes(dns_token, "utf-8"), None), "utf-8"),
    },
    opts=ResourceOptions(depends_on=certmanager_namespace)
    )

# https://github.com/ebrianne/cert-manager-webhook-duckdns/blob/master/deploy/cert-manager-webhook-duckdns/values.yaml
certmanager_webhook = HelmReleaseArgs(
    chart="cert-manager-webhook-duckdns",
    name="cert-manager-webhook-duckdns",
    repository_opts=RepositoryOptsArgs(
        repo="https://ebrianne.github.io/helm-charts"
    ),
    version="v1.2.4",
    namespace="cert-manager",
    values={
            "groupName": "acme.duckdns.org",
            "logLevel": 6,
            "clusterIssuer": {
                "email": email,
                "production": {
                    "create": True
                }
            },
            "secret": {
                "existingSecret": True,
                "existingSecretName": "duckdns-token"
            },
            "certManager": {
                "serviceAccountName": certmanager.status.name
            },
            "duckdns": {
                "token": dns_token,
            }
        },
    # By default Release resource will wait till all created resources
    # are available. Set this to true to skip waiting on resources being
    # available.
    skip_await=False)

certmanager_webhook_release = Release("certmanager-webhook-duckdns", args=certmanager_webhook, opts=pulumi.ResourceOptions(depends_on=[dns_secret, certmanager]))

wildcard_certificate = CustomResource('production-certificate',
                                      api_version='cert-manager.io/v1',
                                      kind='Certificate',
                                      metadata={
                                            'name': domain_dashed,
                                            'namespace': ns_name
                                      },
                                      spec={
                                            'secretName': f'{domain_dashed}-tls',
                                            'issuerRef': {
                                                'name': certmanager_webhook_release.resource_names['ClusterIssuer.cert-manager.io/cert-manager.io/v1'][0],
                                                'kind': 'ClusterIssuer',
                                            },
                                            'dnsNames': [f'*.{domain}'],
                                      }, opts=ResourceOptions(depends_on=certmanager_webhook_release)
                                      )

traefik_namespace = Namespace("traefik-namespace", metadata={'name': "traefik"})

traefik_dashboard_secret = Secret(
    "traefik-dash-secret",
    metadata=ObjectMetaArgs(
        name="traefik-auth",
        namespace=traefik_namespace.metadata["name"],
    ),
    type="Opaque",
    data={
        "users": traefik_dashboard_users
    },
    opts=ResourceOptions(depends_on=traefik_namespace),
    )

# https://github.com/traefik/traefik-helm-chart/blob/master/traefik/values.yaml
traefik_args = HelmReleaseArgs(
    chart="traefik",
    repository_opts=RepositoryOptsArgs(
        repo="https://helm.traefik.io/traefik"
    ),
    version="10.15.0",
    name='traefik-helm',
    namespace=traefik_namespace.metadata["name"],

    values={
        "ingressRoute": {
            "dashboard": {
                "enabled": "false"
            }
        },
        "ports": {
            "web": {
                "redirectTo": "websecure"
            },
            "websecure": {
                "tls": {
                    "enabled": "true"
                }
            }
        },
        "additionalArguments": [
                "--entryPoints.web.http.redirections.entryPoint.to=websecure",
                "--entryPoints.web.http.redirections.entryPoint.scheme=https",
                f"--entrypoints.websecure.http.tls.domains[0].main={domain}",
                f"--entrypoints.websecure.http.tls.domains[0].sans=*.{domain}",
                "--log.level=DEBUG",
            ],
    },
    skip_await=False)

traefik_release = Release("traefik",
                          args=traefik_args,
                          opts=pulumi.ResourceOptions(
                            depends_on=[traefik_namespace, traefik_dashboard_secret, certmanager_webhook_release, wildcard_certificate]
                          )
                          )

traefik_auth = CustomResource(
    "traefik-auth-object",
    api_version="traefik.containo.us/v1alpha1",
    kind="Middleware",
    metadata={
        "name": "auth",
        "namespace": traefik_namespace.metadata["name"],
    },
    spec={
        "basicAuth": {
            "namespace": traefik_namespace.metadata["name"],
            "secret": "traefik-auth"
        }
    },
    opts=pulumi.ResourceOptions(depends_on=traefik_release))

traefik_tls_store = CustomResource(
    "traefik-tls-store",
    api_version="traefik.containo.us/v1alpha1",
    kind="TLSStore",
    metadata={
        "name": "default",
        "namespace": ns_name,
    },
    spec={
        "defaultCertificate": {
            "secretName": f"{domain_dashed}-tls",
        }
    },
    opts=pulumi.ResourceOptions(depends_on=traefik_release))

traefik_dashboard = CustomResource(
    "traefik-dashboard-ingressroute",
    api_version="traefik.containo.us/v1alpha1",
    kind="IngressRoute",
    metadata={
        "name": "traefik-dashboard",
        "namespace": traefik_namespace.metadata["name"],
    },
    spec={
        "entryPoints": ["web", "websecure"],
        "routes": [{
            "kind": "Rule",
            "match": f"Host(`traefik.{domain}`) && (PathPrefix(`/api`) || PathPrefix(`/dashboard`))",
            "priority": 10,
            "services": [{
                "name": "api@internal",
                "kind": "TraefikService",
            }],
            "middlewares": [{
                "name": "auth",
                "namespace": traefik_namespace.metadata["name"]
            }]}
        ]
        },
    opts=pulumi.ResourceOptions(depends_on=[traefik_release]))


def define_namespace(obj):
    obj["metadata"]["namespace"] = "argocd"


argocd_namespace = Namespace(
    "argocd-namespace",
    metadata={
        "name": "argocd"
    }
    )

argocd = ConfigFile(
    "argocd",
    file="external/argocd.yaml",
    transformations=[define_namespace],
    opts=pulumi.ResourceOptions(depends_on=[traefik_release, argocd_namespace])
    )

argocd_ingress = CustomResource(
    "argocd-ingressroute",
    api_version="traefik.containo.us/v1alpha1",
    kind="IngressRoute",
    metadata={
        "name": "argocd-server",
        "namespace": argocd_namespace,
    },
    spec={
        "entryPoints": ["web", "websecure"],
        "routes": [{
            "kind": "Rule",
            "match": f"Host(`argocd.{domain}`)",
            "priority": 10,
            "services": [{
                "name": "argocd-server",
                "namespace": argocd_namespace,
                "port": 80
            }]},
            {
            "kind": "Rule",
            "match": f"Host(`argocd.{domain}`) && Headers(`Content-Type`, `application/grpc`)",
            "priority": 11,
            "services": [{
                "name": "argocd-server",
                "namespace": argocd_namespace,
                "port": 80,
                "scheme": "h2c"
            }]}]
        },
    opts=pulumi.ResourceOptions(depends_on=[traefik_release, argocd_namespace, argocd]))

root_app = CustomResource(
    "root-app",
    api_version="argoproj.io/v1alpha1",
    kind="Application",
    metadata={
        "name": "root-app",
        "namespace": 'argocd',
    },
    spec={
        "project": "default",
        "destination": {
            "namespace": "default",
            "name": "in-cluster",
        },
        "source": {
            "path": "apps",
            "repoURL": "https://github.com/argoproj/argocd-example-apps",
            "targetRevision": "HEAD"
        }
        },
    opts=pulumi.ResourceOptions(depends_on=[argocd_namespace, argocd]))
