# Homelab with Python and Pulumi

I used Ansible (https://www.ansible.com/) to configure basic things like users and firewall, and to install
lightweight Kubernetes k3s (https://k3s.io/) without the default Traefik ingress and it's load balancers as 
Traefik is installed and customized with Pulumi (https://www.pulumi.com/).


## Tech Stack In Kubernetes

Basic stack from this repository:
- Pulumi for installing the following:
  - MetalLB for load balancing: https://metallb.org/ 
  - Traefik for ingress: https://traefik.io/
  - cert-manager for wildcard SSL certificates from Let's Encrypt: https://cert-manager.io/
  - Argo CD for installing applications to Kubernetes: https://argoproj.github.io/cd/

Applications to be installed by Argo CD:
- Prometheus
- Home Assistant


## Requirements

- Kubernetes distribution with container network interface (CNI) installed and configured
  - k3s works for this


## Get running

```
# Install Python pip and pdm
pip3 install pdm
pdm install

### Configure private settings
# Create passphrase for Pulumi
export PULUMI_CONFIG_PASSPHRASE='<your awesome passphrase>'

# Use a local Pulumi state file
pdm run pulumi login --local

# Create a Pulumi stack
pdm run pulumi stack init

# Create Traefik dashboard user and password
ADMINPASS=$(htpasswd -nb <your username> '<your awesome password>' | openssl base64)
pulumi config set --secret traefik_dashboard_users ${ADMINPASS}

# Get the token from duckdns.org to manage your SSL certificates
pulumi config set --secret dns_token <duckdns token>

# Figure out a free subdomain name for your use with duckdns.org
pulumi config set domain <duckdns domain e.g. yourname.duckdns.org>

# Set your email address for notifications about expiring SSL certificates
pulumi config set --secret email <your email address>

pdm run pulumi up
```

## Troubleshooting

### Pod connectivity issues

https://github.com/k3s-io/k3s/issues/535


### containerIPForwarding

https://github.com/projectcalico/calico/issues/4842


### Traefik LB crashing

https://github.com/k3s-io/k3s/issues/201


### Generic troubleshooting documentation

https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/

https://containersolutions.github.io/runbooks/posts/kubernetes/pod-stuck-in-terminating-state/

https://www.digitalocean.com/community/tutorials/how-to-inspect-kubernetes-networking


## Helpful Tools

https://github.com/corneliusweig/konfig

https://k8slens.dev/

https://helm.sh/

https://k9scli.io/

https://github.com/atombender/ktail

https://github.com/ahmetb/kubectx


## Ramblings

I had 2 Raspberry PIs in their separate networks, and this caused pod connectivity issues when using Flannel.


ArgoCD not arm64 yet:

https://github.com/argoproj/argo-cd/issues/8394


Falco not arm64 yet:

https://github.com/falcosecurity/falco/issues/520

