#!/bin/bash
# Despliegue de FinLens en la instancia EC2. Lo ejecuta el workflow de GitHub vía SSM (AWS-RunShellScript).
# Uso: deploy.sh <imagen_completa_con_tag>
# Lee los secretos de Secrets Manager (finlens/app) con el rol de la instancia: nunca pasan por GitHub ni por SSM.
set -euo pipefail

IMAGEN="${1:?Falta la imagen (registro/finlens:tag)}"
REGION="${AWS_REGION:-eu-west-1}"
REGISTRO="${IMAGEN%%/*}"
DIR=/opt/finlens
mkdir -p "$DIR"

# Nombre público: <ip-con-guiones>.sslip.io resuelve a la IP; Caddy obtiene el certificado HTTPS.
TOKEN=$(curl -sfX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
IP=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
HOST="${IP//./-}.sslip.io"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRO"
# Disco pequeño (12 GB) e imágenes de ~1,5 GB: antes de descargar la nueva se borran las que no usa ningún
# contenedor (la versión en marcha sigue en uso y se conserva para poder volver atrás si el pull falla).
docker image prune -af >/dev/null 2>&1 || true
docker builder prune -af >/dev/null 2>&1 || true
echo "Disco libre antes del pull: $(df -h / | awk 'NR==2 {print $4}')"
docker pull "$IMAGEN"

# Secretos -> fichero de entorno legible solo por root (no se imprime nada).
umask 077
aws secretsmanager get-secret-value --region "$REGION" --secret-id finlens/app \
  --query SecretString --output text \
  | python3 -c 'import json,sys; [print(f"{k}={v}") for k, v in json.load(sys.stdin).items() if v]' \
  > "$DIR/app.env"

docker network inspect finlens >/dev/null 2>&1 || docker network create finlens
docker rm -f finlens >/dev/null 2>&1 || true
docker run -d --name finlens --restart unless-stopped --network finlens \
  --memory 900m --env-file "$DIR/app.env" -e LOG_LEVEL=INFO "$IMAGEN"

# Caddy: proxy inverso con HTTPS automático (Let's Encrypt) y soporte de WebSocket (Streamlit lo necesita).
if [ "$(docker inspect -f '{{.State.Running}}' caddy 2>/dev/null || echo false)" != "true" ]; then
  docker rm -f caddy >/dev/null 2>&1 || true
  docker run -d --name caddy --restart unless-stopped --network finlens \
    -p 80:80 -p 443:443 -v caddy_data:/data -v caddy_config:/config \
    caddy:2 caddy reverse-proxy --from "$HOST" --to finlens:8501
fi

# Espera a que la app responda (healthcheck de Streamlit) antes de dar el despliegue por bueno.
for _ in $(seq 1 30); do
  if docker exec finlens python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" 2>/dev/null; then
    docker image prune -af >/dev/null 2>&1 || true  # tras el cambio, la versión anterior ya no se usa
    echo "FinLens desplegado en https://$HOST ($IMAGEN)"
    exit 0
  fi
  sleep 4
done
echo "La app no respondió al healthcheck" >&2
docker logs --tail 50 finlens >&2 || true
exit 1
