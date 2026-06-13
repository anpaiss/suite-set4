#!/usr/bin/env bash
# entrypoint.sh - orchestrazione del giro di valutazione su GPU.
#
# Flusso: avvia il server Ollama in background, attende che risponda, scarica i
# modelli elencati nel file scelto (un pull fallito viene segnalato ma non
# blocca il giro), poi lancia il motore. I risultati finiscono in /suite/output,
# che va montato come volume per recuperarli a container terminato.
#
# Variabili che governano il giro (con default sensati):
#   MODELS_FILE   file modelli da usare (default eval_models_fascia_a.txt)
#   CASES_FILE    file casi (default eval_cases_set4.yaml)
#   REPS          ripetizioni per caso (default 3)
#   TEMPERATURE   se impostata, forza la temperatura (default: di fabbrica)
#   THINK         false|true|low|medium|high (default false)
#   OUTPUT_DIR    cartella output (default /suite/output)
#   KEEP_ALIVE    quanto tenere i modelli in memoria (default 30m)
#   SKIP_PULL     se "1", salta il pull (modelli gia presenti nel volume)

set -u

MODELS_FILE="${MODELS_FILE:-eval_models_fascia_a.txt}"
CASES_FILE="${CASES_FILE:-eval_cases_set4.yaml}"
REPS="${REPS:-3}"
OUTPUT_DIR="${OUTPUT_DIR:-/suite/output}"
SKIP_PULL="${SKIP_PULL:-0}"

mkdir -p "$OUTPUT_DIR"

echo "=============================================="
echo " SET 4 - giro di valutazione"
echo " Modelli:  $MODELS_FILE"
echo " Casi:     $CASES_FILE"
echo " Reps:     $REPS   Temp: ${TEMPERATURE:-fabbrica}   Think: ${THINK:-false}"
echo " Output:   $OUTPUT_DIR"
echo "=============================================="

# 1. Avvio del server Ollama in background.
echo "[entrypoint] Avvio ollama serve..."
ollama serve > /suite/output/ollama_server.log 2>&1 &
OLLAMA_PID=$!

# 2. Attesa che l'API risponda (max ~60s).
echo "[entrypoint] Attendo che Ollama risponda..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "[entrypoint] Ollama pronto dopo ${i}s."
        break
    fi
    sleep 1
done

# 3. Pull dei modelli (salvo SKIP_PULL). Un fallimento non ferma il giro: il
#    modello mancante verra semplicemente saltato con ERRORE dal motore.
if [ "$SKIP_PULL" != "1" ]; then
    echo "[entrypoint] Scarico i modelli da $MODELS_FILE..."
    grep -vE '^\s*#|^\s*$' "$MODELS_FILE" | while read -r model; do
        model="$(echo "$model" | xargs)"   # trim
        [ -z "$model" ] && continue
        echo "[entrypoint] pull $model"
        if ! ollama pull "$model"; then
            echo "[entrypoint] ATTENZIONE: pull fallito per '$model' - verificare il tag. Proseguo."
        fi
    done
else
    echo "[entrypoint] SKIP_PULL=1: salto i download, uso i modelli gia nel volume."
fi

echo "[entrypoint] Modelli presenti:"
ollama list

# 4. Lancio del motore. Le variabili d'ambiente del motore sono mappate qui.
echo "[entrypoint] Avvio batch_eval..."
export EVAL_MODELS_FILE="$MODELS_FILE"
export EVAL_CASES_FILE="$CASES_FILE"
export EVAL_REPS="$REPS"
export EVAL_OUTPUT_DIR="$OUTPUT_DIR"
export OLLAMA_URL="http://localhost:11434"
export EVAL_NUM_CTX="${NUM_CTX:-16384}"
[ -n "${TEMPERATURE:-}" ] && export EVAL_TEMPERATURE="$TEMPERATURE"
[ -n "${THINK:-}" ] && export EVAL_THINK="$THINK"

python3 batch_eval.py
RC=$?

echo "[entrypoint] batch_eval terminato (codice $RC). Output in $OUTPUT_DIR."
echo "[entrypoint] Per fermare il server: kill $OLLAMA_PID"
exit $RC
