# Publishing Camo Fleet through Traefik on k3s

k3s ships with Traefik installed by default. The manifest in this folder wires the Services created by the Helm chart to the public host `https://camofleet.services.synestra.tech/`.

## Before you apply the manifest

1. **Install the Helm release first.** Follow `deploy/helm/README.md` to deploy the workloads and Services in the `camofleet` namespace. Если вы переопределили `nameOverride` или `fullnameOverride`, отредактируйте `service.name` в манифесте так, чтобы он совпадал с реальными сервисами (например, `custom-control`).
2. **Make sure Traefik knows about TLS for the domain.** By default the manifest expects a certResolver named `letsencrypt`. Adjust the `tls` block in `camofleet-ingressroute.yaml` if your environment differs:
   - **Existing secret.** Replace the `tls` section with `tls: { secretName: camofleet-services-tls }` and create that secret in the `camofleet` namespace:
     ```bash
     kubectl create secret tls camofleet-services-tls \
       --namespace camofleet \
       --cert /path/to/fullchain.pem \
       --key /path/to/privkey.pem
     ```
   - **Different certResolver.** Change the `certResolver` value to match the name configured in Traefik (for example `lehttp`).
3. **Double-check DNS.** `camofleet.services.synestra.tech` must point to the public IP address of your k3s node or load balancer.

## Apply the IngressRoute

Once the prerequisites are satisfied, publish the services with:

```bash
kubectl apply -f deploy/traefik/camofleet-ingressroute.yaml
```

Verify that Traefik created the route:

```bash
kubectl get ingressroute -n camofleet camofleet
```

The `STATUS` column should read `True`. If you see `False`, describe the resource to view the error:

```bash
kubectl describe ingressroute -n camofleet camofleet
```

## What the manifest does

- `/` → `camofleet-ui:80`
- `/api` → `camofleet-control:9000`
- `/vnc` → `camofleet-worker-vnc:6080` (контейнер gateway внутри worker отвечает за noVNC)
- `/websockify` → проксирование на `camofleet-worker-vnc:6080` без дополнительного префикса, чтобы внешние noVNC WebSocket-URL выглядели как `https://camofleet.services.synestra.tech/websockify?token=...`

## Remove the publication

To stop serving the application publicly, delete the IngressRoute (and the TLS secret if you created one):

```bash
kubectl delete -f deploy/traefik/camofleet-ingressroute.yaml
kubectl delete secret camofleet-services-tls -n camofleet  # optional
```
