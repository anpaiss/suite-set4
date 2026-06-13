# Dockerfile - ambiente di valutazione modelli SET 4 per GPU da data center.
# Base ufficiale Ollama (include il runtime CUDA e il binario ollama). Vi si
# aggiunge Python e le dipendenze del motore, e si copia la suite. Pensato per
# RunPod o qualunque host con GPU NVIDIA e nvidia-container-toolkit.

FROM ollama/ollama:latest

# Python e dipendenze del motore. La base e Ubuntu, quindi apt e disponibile.
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Le dipendenze sono minime: il motore parla l'API HTTP di Ollama.
RUN pip3 install --no-cache-dir --break-system-packages requests pyyaml

WORKDIR /suite
COPY batch_eval.py eval_cases_set4.yaml eval_cases_stab4.yaml ./
COPY eval_models_fascia_a.txt eval_models_fascia_b.txt eval_models_ancora.txt ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# La base Ollama imposta ENTRYPOINT ["ollama"]: va sovrascritto, altrimenti il
# container interpreta i comandi come sottocomandi di ollama.
ENTRYPOINT ["/bin/bash"]
CMD ["/suite/entrypoint.sh"]
