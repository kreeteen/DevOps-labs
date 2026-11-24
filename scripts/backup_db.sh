#!/usr/bin/env bash
set -euo pipefail

CTX="${CTX:-multi}"
NS="${NS:-shop}"
CLUSTER="${CLUSTER:-shop-db}"
DB="${DB:-app}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
MAX_DISK_PCT="${MAX_DISK_PCT:-90}"

export PATH=/usr/local/bin:/usr/bin:/bin
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

log() { echo "$(date '+%F %T') $*"; }
k()   { kubectl --context "$CTX" -n "$NS" "$@"; }
trap 'log "FAILED at line $LINENO"' ERR

# 1. место на диске до начала
used=$(df --output=pcent "$BACKUP_DIR" | tail -1 | tr -dc '0-9')
[ "$used" -lt "$MAX_DISK_PCT" ] || { log "disk ${used}% >= ${MAX_DISK_PCT}%, abort"; exit 1; }

# 2. дамп делаем с реплики, чтобы не нагружать primary
primary=$(k get cluster "$CLUSTER" -o jsonpath='{.status.currentPrimary}')
pod=$(k get pods -l "cnpg.io/cluster=$CLUSTER" -o name | sed 's|pod/||' | grep -vx "$primary" | head -1 || true)
pod="${pod:-$primary}"
log "dump from $pod (primary: $primary)"

file="$BACKUP_DIR/${CLUSTER}_$(date +%F_%H-%M).sql.gz"
k exec "$pod" -c postgres -- pg_dump -d "$DB" | gzip > "$file.part"

# 3. проверка: архив целый и не пустой
gzip -t "$file.part"
[ -s "$file.part" ] || { log "empty dump"; exit 1; }
mv "$file.part" "$file"
log "ok: $file ($(du -h "$file" | cut -f1))"

# 4. ротация
find "$BACKUP_DIR" -name "${CLUSTER}_*.sql.gz" -mtime +"$KEEP_DAYS" -delete

# 5. здоровье приложения после бэкапа
want=$(k get deploy shop-app -o jsonpath='{.spec.replicas}')
have=$(k get deploy shop-app -o jsonpath='{.status.readyReplicas}')
[ "${have:-0}" -eq "$want" ] || { log "shop-app ready ${have:-0}/$want"; exit 2; }
log "done"
