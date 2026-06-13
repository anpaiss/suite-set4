# LEGGIMI — SET 4 (giro definitivo, decisione hardware)

Questo giro serve a decidere **una cosa sola**: la qualita sui task reali di
PaissanGroup giustifica un hardware con memoria ampia (Strix Halo 128GB, modelli
70B+) rispetto a una GPU da 32GB (R9700, modelli fino a ~27B)? Si gira su una
macchina a noleggio veloce (es. RunPod A100 80GB) perche fa girare anche i 70B in
GPU in tempi ragionevoli, cosa impossibile in ufficio o a casa.

## Cosa c'e nel pacchetto

- `batch_eval.py`            motore v2 (ripetizioni, salvataggio incrementale, temp/think)
- `eval_cases_set4.yaml`     31 casi su 5 use case + matrice prompt veto
- `eval_cases_stab4.yaml`    8 casi-spia per il test di stabilita
- `eval_models_fascia_a.txt` modelli che stanno in 32GB (la rosa "no cambio hardware")
- `eval_models_fascia_b.txt` modelli che richiedono i 128GB / l'A100 (il "si cambio")
- `eval_models_ancora.txt`   solo gemma4:26b, per la stabilita
- `Dockerfile`, `entrypoint.sh`, `docker-compose.yml`  per montare il giro su GPU

## Cosa testa (5 use case con i PROMPT REALI di produzione)

- **TRIAGE (T1-T6)**: classificazione email nei 5 bucket reali dell'email-agent
  (agisci/informativo/notifica/rumore/dubbio). T6 e il caso "dubbio": misura se
  il modello sa dichiarare incertezza invece di forzare una categoria.
- **VETO (A1-A6 e A1-v2..A6-v2)**: la scala dell'astensione, in DOPPIA versione.
  Gli A1-A6 usano il prompt veto attuale; gli A*-v2 usano lo STESSO input col
  prompt veto_v2 (definizione operativa dell'astensione). Questa e la **matrice
  che decide l'hardware**: separa quanto un modello migliora per TAGLIA da quanto
  migliora per PROMPT. Se gemma4:26b con veto_v2 regge l'astensione (A5/A6
  CHIEDI_INFO stabile, A3/A4 CAUTELA), la taglia non serve e la R9700 vince.
- **INGANNO/INJECTION (I1-I5)**: phishing, BEC e prompt injection nelle email.
  I5 e lo specchio anti-falso-positivo.
- **SICUREZZA (W1-W4)**: confine ATTACCO/APPROFONDIRE/ROUTINE con sicurezza_v2.
- **DIAGNOSI (D1-D2) e SEQUENZIAMENTO (SEQ1-SEQ2)**: ragionamento causale e
  ordinamento con vincoli e conflitti.

Verdetti attesi principali — TRIAGE: agisci, rumore, notifica, agisci,
informativo, dubbio. VETO (entrambe le versioni): PROCEDI, PROCEDI, CAUTELA,
CAUTELA, CHIEDI_INFO, CHIEDI_INFO. INJECTION: INGANNO x4, LEGITTIMA (I5).
SICUREZZA: APPROFONDIRE, ATTACCO, ROUTINE, APPROFONDIRE.

## Le due fasce di modelli

FASCIA A (sta in 32GB): qwen3:14b (FP16, pieno), gpt-oss:20b (MXFP4 nativo),
mistral-small 24b (Q8), gemma4:26b (Q6), qwen3.6:27b (Q6), qwen3:32b (Q6). E'
la rosa se NON si cambia hardware. CRITERIO: ogni modello alla quant MASSIMA
che la R9700 ospita con contesto 32K - su 32GB i modelli <=32B stanno ben oltre
il Q4, quindi non si strozza dove c'e spazio. gemma4:26b a Q6 e' anche l'ANCORA
del giro fascia B (stessa quant in entrambi i giri, per un confronto pulito):
e' il metro contro cui si misura se la taglia 70B+ compra qualcosa.

FASCIA B (richiede memoria ampia): i tre 70B (llama3.3, qwen2.5:72b,
deepseek-r1:70b), Mistral Large 123B, Qwen3 235B MoE. E' il "vale la pena
salire di hardware?". gemma4:26b e in entrambi i giri come ANCORA: e il metro
contro cui si misura se la taglia compra qualcosa.

PRINCIPIO DI QUANTIZZAZIONE + CONTESTO (critico per la validita della prova):
ogni modello fascia B e testato alla quant massima che sta nei ~115GB
utilizzabili dello Strix Halo CONSIDERANDO ANCHE la KV cache della finestra di
contesto. Il contesto non e gratis: su un modello grande, una finestra a 32K
costa 6-11GB di memoria OLTRE ai pesi. E i due ruoli hanno bisogni diversi - il
triage email sta in 4-8K, ma il veto/sequenziamento (changelog + stato sito +
lista plugin) puo richiedere 16-32K. Si dimensiona quindi sul ruolo piu
esigente (veto, 32K).

Tabella di ammissibilita (pesi + KV cache a 32K, su tetto ~115GB):
  - 70B  @ Q8 : ~75GB + ~8GB  = ~83GB  -> STA comodo ("praticamente pieno")
  - 123B @ Q5 : ~85GB + ~12GB = ~97GB  -> STA. (Q6 a 32K = ~110GB, margine
    troppo sottile: scelto Q5 per garantire la finestra ampia del veto)
  - 235B @ Q3 : ~105GB + ~6GB = ~111GB -> AL LIMITE (4GB margine). CONDIZIONATO:
    con contesto ampio potrebbe non entrare sullo Strix Halo reale; certo solo
    a contesto ridotto (<=8K). E' quant COMPRESSA, non il 235B "pieno".

NOTA SUL CONTESTO NEL TEST: i 31 casi sono brevi (poche centinaia di token), il
batch gira anche a contesto piccolo. Il calcolo a 32K NON serve a eseguire i
casi ma a decidere chi e utilizzabile in PRODUZIONE con la finestra del ruolo.
E' un criterio di ammissibilita, non un parametro d'esecuzione. Il batch gira a
EVAL_NUM_CTX=16384 (margine abbondante per i casi); il dimensionamento 32K
serve alla decisione hardware. I limiti di memoria sopra valgono per lo Strix
Halo reale e vanno confermati sull'hardware target: sulla macchina di noleggio
(piu grande) i modelli ci stanno comunque.

ATTENZIONE TAG: verificare i tag con `ollama search` PRIMA del giro. Q4_K_M e
Q8_0 sono di solito pubblicati su Ollama; le quant intermedie (Q6_K, Q3_K_M)
spesso NO e vanno importate come GGUF da HuggingFace (bartowski/unsloth) con un
Modelfile: scaricare il .gguf, poi `ollama create <nome> -f Modelfile` con
`FROM ./file.gguf`. deepseek-r1:70b e un distillato reasoning: con think:false
+ format json va controllato sul primo caso che la risposta resti JSON valido
(come phi4 nel SET 2); se esce "(non estratto)" sistematicamente, gestire il
think diversamente.

MACCHINA DI NOLEGGIO: il giro fascia B NON sta in una A100 80GB singola.
- I 70B a Q8 (~75GB) riempiono quasi tutta una A100 80GB: ci stanno a malapena,
  uno per volta, con poco margine per il contesto.
- Mistral Large Q6 (~100GB) e Qwen3 235B Q3 (~105GB) NON entrano negli 80GB.
Serve quindi una macchina con >=120-140GB: una H200 (141GB) e il candidato
ideale per girare tutto senza compromessi, oppure 2x A100 80GB (160GB). La
fascia A e i tre 70B-Q8 si possono fare anche su A100 80GB; Mistral Large e il
235B richiedono la macchina grande. Dimensionare il pod di conseguenza, disco
persistente >=400GB (i pesi fascia B a queste quant sommano ~350GB+).

## PROCEDURA RUNPOD — opzione Docker (consigliata)

Prerequisiti pod: GPU (A100 80GB ideale), disco persistente **almeno 350GB**
(i modelli fascia A+B sommano ~250-300GB), nvidia-container-toolkit.

1. Trasferire la cartella del pacchetto sul pod (scp o volume).
2. Build dell'immagine:
       docker build -t set4-eval .
3. Giro FASCIA A (veloce, ~30-50 min):
       docker run --gpus all \
         -e MODELS_FILE=eval_models_fascia_a.txt -e REPS=3 \
         -v $(pwd)/output:/suite/output \
         -v ollama_models:/root/.ollama \
         set4-eval
   I risultati compaiono in ./output. Il volume ollama_models conserva i
   modelli scaricati: i giri successivi con SKIP_PULL=1 non riscaricano.
4. Giro FASCIA B (lento per i 70B):
       docker run --gpus all \
         -e MODELS_FILE=eval_models_fascia_b.txt -e REPS=3 \
         -v $(pwd)/output:/suite/output \
         -v ollama_models:/root/.ollama \
         set4-eval
5. STABILITA sull'ancora + finalisti (a fine giro principale):
       docker run --gpus all \
         -e CASES_FILE=eval_cases_stab4.yaml \
         -e MODELS_FILE=eval_models_ancora.txt \
         -e REPS=5 \
         -v $(pwd)/output:/suite/output -v ollama_models:/root/.ollama \
         -e SKIP_PULL=1 set4-eval
   e poi lo stesso con `-e TEMPERATURE=0.2` per il confronto a bassa temperatura.

## PROCEDURA RUNPOD — opzione senza Docker (template Ollama gia pronto)

Se il pod ha gia Ollama installato (template RunPod "Ollama"):
1. pip3 install requests pyyaml
2. Copiare i file .py / .yaml / .txt nella home.
3. Avviare il serve: `ollama serve &`
4. Scaricare i modelli: `ollama pull <ognuno del file fascia>`
5. Lanciare:
       EVAL_CASES_FILE=eval_cases_set4.yaml \
       EVAL_MODELS_FILE=eval_models_fascia_a.txt \
       EVAL_REPS=3 python3 batch_eval.py

## STIME DI TEMPO (indicative, A100 80GB)

I modelli grandi su A100 vanno molto piu veloci che su CPU: stimare 8-20s a
risposta per i 70B, 2-5s per la fascia A. Volume:
- Fascia A: 31 casi x 3 rep x 6 modelli = 558 risposte -> ~30-50 min
- Fascia B: 31 casi x 3 rep x 5 modelli = 465 risposte. Su H200, i 70B-Q8 a
  ~10-20s, Mistral Q6 e 235B Q3 piu lenti. Stimare ~1.5-2.5 ore.
- Stabilita: 8 casi x 5 rep x 1-2 modelli x 2 temp -> ~15-30 min
Totale tipico sotto le 2-3 ore di noleggio. Con il salvataggio incrementale
(eval_grezzo_*.jsonl) un'interruzione non perde nulla.

## OUTPUT DA RECUPERARE

Tutto in ./output:
- `eval_verdetti_*.csv`   verdetti affiancati; con REPS>1 ogni cella riassume
  i conteggi (es. "CHIEDI_INFO 5/5" oppure "CAUTELA 2/3; VETO 1/3").
- `eval_risposte_*.txt`   risposte complete per l'esame qualitativo (D, SEQ, T).
- `eval_grezzo_*.jsonl`   tracciato incrementale (rete di sicurezza).

## COME SI LEGGE IL RISULTATO (la decisione hardware)

La domanda non e "chi prende piu verdetti giusti", ma queste tre lette insieme:

1. **Matrice prompt sull'asse A.** Confrontare A5/A6 (prompt attuale) con
   A5-v2/A6-v2 (prompt v2) per ogni modello. Se la fascia A — gemma4:26b in
   testa — passa l'astensione SOLO con veto_v2 e in modo STABILE (5/5 nel giro
   stabilita), allora il problema del veto era il prompt, non la taglia: la
   R9700 basta e i 70B non servono.

2. **La fascia B batte l'ancora dove conta?** Se llama3.3:70b o qwen2.5:72b
   fanno A5 stabile dove gemma4:26b oscilla ANCHE con veto_v2, allora la taglia
   compra qualcosa di reale sul veto: e l'unico scenario che giustifica lo Strix
   Halo. Se invece i 70B oscillano come la fascia A (probabile: la taglia non ha
   comprato stabilita nei giri precedenti), la spesa non e giustificata.

3. **Stabilita prima di tutto.** Un modello che fa A5 giusto 3/5 non e migliore
   di uno che lo fa sbagliato 5/5: per il veto la riproducibilita conta quanto
   la correttezza. Guardare le celle miste nel CSV dei giri stabilita.

Riferimento dai giri precedenti (SET 1-3, su 32GB): gemma4:26b vincente su
triage/sicurezza/injection ma debole sull'astensione col prompt vecchio; nessun
modello fino a 32B aveva una soglia di astensione stabile e ben tarata. Il SET 4
verifica se veto_v2 e/o la taglia 70B chiudono quel buco.
