# SET 7 — Runbook per pod RunPod (consenso a due modelli)

Test dell'architettura a doppio modello per l'agente di update.
Coppie a confronto: A = gemma4 + gpt-oss, B = gemma4 + qwen3:32b.
Pilastro comune: gemma4. Esecuzione in sequenza, un modello alla volta.

## Quant di esercizio (una per modello, alla loro qualita ottimale reale)

- gemma 4 26B (MoE A4B)  -> Q4 QAT (UD-Q4_K_XL). NOTA: per Gemma 4 il produttore
  dichiara che precisioni superiori a Q4 QAT degradano l'accuratezza invece di
  migliorarla. La Q4 QAT NON e un ripiego di memoria: e la quant ottimale del
  modello. Niente Q6 per gemma.
- gpt-oss 20B            -> MXFP4 nativo (gia forma piena, nessun GGUF).
- qwen3:32b (denso)      -> Q6_K (il suo massimo ragionevole; e il motivo per cui
  serve il pod, a Q6 denso non sta nei 24 GB usabili di casa).

## 1. GPU consigliata

A100 80GB (banda HBM ~2 TB/s, veloce in inferenza, ~1,19 $/h indicativo da verificare
all'accensione). In sequenza basta ospitare un modello alla volta: il picco e
qwen3:32b a Q6 (~26 GB) + context. 80 GB danno ampio margine. RTX 6000 Ada 48GB
e un ripiego valido se l'A100 non e disponibile.

## 2. Setup pod

Template: Ollama CUDA (ollama/ollama:latest). Container 40GB. Volume 100GB su /workspace.
Env:
    OLLAMA_MODELS=/workspace/ollama
    OLLAMA_HOST=0.0.0.0:11434
    OLLAMA_FLASH_ATTENTION=1

    apt update && apt install -y git python3-pip tmux
    pip install --break-system-packages pyyaml requests huggingface_hub hf_transfer
    cd /workspace && git clone https://github.com/anpaiss/suite-set4.git && cd suite-set4

## 3. Modelli

### gemma 4 26B — Q4 QAT
Via Ollama (preferibile se il tag esiste; VERIFICARE il nome esatto su ollama.com/library):
    ollama pull gemma4:26b
Se serve la QAT esplicita di Unsloth via GGUF:
    cd /workspace
    hf download unsloth/gemma-4-26B-A4B-it-qat-GGUF --include "*UD-Q4_K_XL*" --local-dir gemma4qat
    # individuare il file .gguf scaricato in gemma4qat/ e puntarlo nel Modelfile
    printf 'FROM /workspace/gemma4qat/<NOME_FILE>.gguf\n' > Modelfile.gemma
    ollama create gemma4:26b -f Modelfile.gemma

### gpt-oss 20B — nativo
    ollama pull gpt-oss:20b

### qwen3:32b — Q6_K
Via Ollama (verificare disponibilita del tag a Q6):
    ollama pull qwen3:32b
Oppure GGUF Q6_K (repo da confermare al momento, es. Qwen ufficiale o bartowski):
    cd /workspace
    hf download Qwen/Qwen3-32B-GGUF --include "*Q6_K*" --local-dir qwen32
    printf 'FROM /workspace/qwen32/<NOME_FILE>.gguf\n' > Modelfile.qwen
    ollama create qwen3:32b -f Modelfile.qwen

## 4. Lancio (in tmux, scarico automatico tra modelli)

    printf 'gemma4:26b\ngpt-oss:20b\nqwen3:32b\n' > /workspace/modelli_set7.txt
    tmux new -s set7
    EVAL_MODELS_FILE=/workspace/modelli_set7.txt \
    EVAL_CASES_FILE=eval_cases_set7.yaml \
    EVAL_REPS=3 EVAL_NUM_CTX=16384 \
    EVAL_THINK=true \
    EVAL_OUTPUT_DIR=/workspace/suite-set4/output/set7 \
    OLLAMA_URL=http://localhost:11434 \
    python3 batch_eval.py
    # stacca: Ctrl-b d   |   riattacca: tmux attach -t set7

### Parametri rilevanti per il thinking

- EVAL_THINK=true   attiva il ragionamento sui modelli che lo supportano.
  Ollama separa nativamente thinking e risposta: il motore preserva entrambi
  nel JSONL (campo "thinking") ed estrae la decisione dal content ripulito.
- EVAL_FORCE_JSON   default true. Forza format=json a livello API: robusto su
  qwen3 e gemma, MA problematico su gpt-oss (Harmony tende a produrre JSON
  sporco). Se nel giro gpt-oss desse output malformati o vuoti, ripetere il
  suo giro con EVAL_FORCE_JSON=false: il JSON si chiede solo nel prompt e il
  motore di estrazione lo recupera in modo tollerante.
  Esempio mirato solo su gpt-oss:
    printf 'gpt-oss:20b\n' > /workspace/solo_gptoss.txt
    EVAL_MODELS_FILE=/workspace/solo_gptoss.txt EVAL_FORCE_JSON=false \
    EVAL_CASES_FILE=eval_cases_set7.yaml EVAL_REPS=3 EVAL_NUM_CTX=16384 \
    EVAL_THINK=true EVAL_OUTPUT_DIR=/workspace/suite-set4/output/set7 \
    python3 batch_eval.py

Nota: il motore di estrazione (estrazione.py) gestisce i tre formati
(think-tag di qwen3/gemma, Harmony di gpt-oss, separazione nativa di Ollama),
prende sempre la decisione FINALE (l'ultima, non un valore considerato nel
reasoning) e ripiega su regex se il JSON e malformato. Il thinking non viene
scartato: resta nel JSONL per l'analisi dei disaccordi.

## 5. Analisi del consenso (a fine giro)

    python3 analisi_consenso.py /workspace/suite-set4/output/set7

Stampa, per le due coppie: accordo sui casi normali (pochi falsi stop = meglio),
copertura sugli stop (almeno uno ferma; i BUCHI devono essere 0), divergenza sui
grigi. Sintesi finale = quale coppia scegliere.

## Verifiche da fare sul momento (nomi soggetti a cambiamento)

- Nome esatto del tag Ollama per Gemma 4 26B e per la sua quant QAT.
- Nome del file GGUF UD-Q4_K_XL dentro il repo unsloth (cambia con gli update).
- Disponibilita di qwen3:32b a Q6 come tag Ollama vs GGUF da importare.
