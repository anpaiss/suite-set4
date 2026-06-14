# Handover — Validazione futura degli agenti di produzione

> **Scopo di questo documento.** Da passare alla chat in cui si lavorerà sugli
> agenti già sviluppati (email-agent, wordfence-agent, dashboard) e sul futuro
> agente di update. Contiene: (1) lo stato reale del sistema oggi, così chi
> riprende ha il contesto; (2) i test di validazione rimandati dal piano SET 8,
> ciascuno agganciato a cosa serve davvero e *quando* ha senso eseguirlo.
>
> Questi test NON vanno eseguiti subito. Sono la roadmap di validazione da
> attivare quando il sistema raggiunge le condizioni indicate per ciascuno.

---

## 1. Stato del sistema oggi (contesto per chi riprende)

### Agenti in produzione
Tre agenti Docker su macchina di casa (Windows + Docker Desktop/WSL2), sempre
accesi, raramente usati in modo interattivo. Tutti in `C:\Progetti\`.

- **email-agent** — smista la posta `a.paissan@paissangroup.com` in **cinque
  categorie**: `agisci`, `informativo`, `notifica`, `rumore`, `dubbio`.
  (Nota: `rumore` = newsletter/promozioni/notifiche già gestite altrove; è la
  categoria definita in `sender_registry.py` e gestita a valle da `report.py`.)
  Applica la stella `\Flagged` su Thunderbird per le mail `agisci`. Bot Telegram.
- **wordfence-agent** — monitora gli avvisi Wordfence via `sucuri@paissan.com`.
  Container `wordfence_agent` + `wordfence_ollama`. Sportello stato su porta host
  **8082**. Distingue tentativo BLOCCATO (routine) da evento RIUSCITO (grave),
  bot/crawler da attacco mirato; silenzia i report attività settimanali (digest
  ridondanti). `num_ctx` a 16384.
- **agent-dashboard** — cruscotto PWA (FastAPI, porta **8700**), container
  `agent_dashboard`. Legge il socket Docker (sola lettura) per lo stato
  running/fermo dei container. Predisposta a interrogare sportelli `/status`
  degli agenti (contratto `stats` + `log_tail`, registro in `config/agents.yaml`),
  ma gli sportelli non sono ancora implementati su tutti. Cache SW aggressiva
  (su mobile usare ricarica forzata/incognito).

### Ollama condivisa
**Una sola** istanza Ollama (`host.docker.internal:11434`) condivisa da tutti gli
agenti. **Saboteur noto:** la system tray di Ollama si riavvia da sola e punta al
path modelli di default su C: invece del disco esterno, causando "model not found"
che manda tutte le classificazioni in `dubbio`. Guardia obbligatoria prima di
qualsiasi test: `ollama list` deve mostrare i modelli giusti, non basta che
"Ollama risponda".

### Modelli
- Produzione attuale agenti: storicamente `qwen3:14b`. Da valutare migrazione a
  `gemma4:26b` (vincitore delle valutazioni) dove l'hardware lo consente.
- **Agente di update (in costruzione):** coppia a consenso **gemma4:26b +
  qwen3:32b**, decisa nel SET 7. La quant di qwen è indifferente (Q4 = Q6).

### Stato della valutazione modelli
SET 4-7 completati e versionati su GitHub (`github.com/anpaiss/suite-set4`).
SET 7 ha scelto la coppia di consenso. SET 8 "ridotto" (contesto lungo + falsi
positivi) eseguibile sul pod — vedi `SET8_test_da_fare_ora.md`.

### Questioni di produzione aperte (da chiudere)
- Applicare il prompt `sicurezza_v2` al wordfence-agent.
- **Revocare il token bot Telegram via BotFather** (appare in chiaro nei log,
  segnalato più volte, ancora da fare).
- Allineare commento obsoleto nel `.env` wordfence (modello).
- Aggiungere `__pycache__/` al `.gitignore` del repo suite-set4.
- Heartbeat centralizzato sulla dashboard (vedi sezione dedicata sotto).

---

## 2. Heartbeat centralizzato (progetto discusso, in attesa di dati)

**Idea:** spostare il concetto di heartbeat dal wordfence-agent (dove oggi è
self-reported: la classe `Heartbeat` invia un messaggio di stato agli orari
`HEARTBEAT_HOURS`, default 8/14/20, finestra 6h, via Telegram) alla **dashboard**,
che diventa l'osservatore esterno ed emette un battito unico "tutti vivi / X fermo".

**Perché è meglio:** l'heartbeat self-reported ha un punto cieco — se l'agente
muore del tutto non manda niente, e l'assenza è facile da non notare. Un
osservatore esterno *attivamente* dice "X è morto".

**Cosa manca per implementarlo** (serve guardare il codice reale, non a memoria):
- Lo stato reale degli sportelli `/status`: quali agenti li espongono e con quale
  contratto esatto di campi.
- Se la dashboard ha già un canale Telegram d'uscita per inviare (oggi solo
  *mostra*, non invia), o se deve riusare il bot degli agenti.

**Modello consigliato:** push tramite traccia. Ogni agente scrive un timestamp di
"ultimo ciclo" (file/record); la dashboard legge i timestamp + lo stato dei
container Docker e calcola vivo/morto applicando una soglia. Meno invasivo del
modello pull (non serve aggiungere un server HTTP a ogni agente).

**Prerequisito:** allegare gli ZIP di tutti gli agenti per vedere il contratto
`/status` reale e il canale di notifica della dashboard.

---

## 3. Test di validazione rimandati (la roadmap)

I quattro test seguenti erano nel piano SET 8 originale come "criteri per agenti
futuri". Sono ben concepiti ma presuppongono condizioni che oggi non esistono.
Per ciascuno: cosa testa, perché è rimandato, e **quando** attivarlo.

### 3.1 Latenza e throughput sull'hardware reale
**Cosa:** misurare TTFT (time to first token), token/secondo in generazione del
piano, e latenza totale della catena di consenso (gemma + qwen interrogati in
serie o parallelo).

**Perché rimandato:** misurarlo ora sul pod RunPod (A100/H200 a noleggio) non
dice nulla di utile, perché l'agente girerà sull'hardware locale definitivo, che
ha caratteristiche diverse. I numeri presi sul pod sono carta straccia per
dimensionare il sistema reale.

**Quando attivarlo:** **appena disponibile l'hardware di produzione** (la GPU
R9700 32GB o la macchina scelta). Lì si misura la latenza vera e si verifica che
la catena di decisione (generazione piani + verifica consenso) stia dentro i
timeout dei processi batch aziendali.

**Verifica chiave:** la coppia a consenso raddoppia il tempo (due modelli). Va
misurato se la latenza combinata è accettabile, e se conviene interrogarli in
parallelo (più VRAM, più veloce) o in serie (meno VRAM, più lento). Dipende dalla
VRAM disponibile sull'hardware finale: gemma4:26b ~17GB + qwen3:32b ~20GB (Q4)
sono ~37GB insieme — serve verificare se stanno entrambi in VRAM
contemporaneamente o se vanno caricati a turno (col costo di caricamento).

### 3.2 Limite di quantizzazione di gemma
**Cosa:** confrontare gemma4:26b nativo vs Q8 vs Q4 sugli scenari avversariali
più complessi (SET 5/6), per trovare il punto in cui la compressione degrada la
capacità di usare la terminologia tecnica esatta o rilevare la manipolazione.

**Perché rimandato (e ridimensionato):** il SET 7 ha già mostrato che per qwen
Q4 = Q6. Per gemma c'è un fatto noto: **gemma 4 è QAT**, e le fonti del produttore
indicano che la sua quant ottimale è la Q4 e che salire sopra **degrada** invece
di migliorare. Quindi questo test rischia di confermare il contrario di quanto il
piano ipotizzava: non "Q4 regge bene" ma "per gemma Q4 È il punto giusto, salire
non serve". Valore pratico basso.

**Quando attivarlo:** opzionale, solo se emerge un dubbio specifico sulla quant
di gemma in produzione. Non è bloccante per nulla.

### 3.3 Multi-Agent Drift e Cascade Failure
**Cosa:** testare la resilienza della catena quando l'output di un agente diventa
l'input del successivo (es. triage → sicurezza → update). Verificare che un
micro-errore del primo agente non si amplifichi fino a un'azione distruttiva o un
blocco ingiustificato a valle.

**Perché rimandato:** oggi gli agenti sono **isolati**, non si parlano. Non si può
testare una cascata che non è stata costruita.

**Quando attivarlo:** quando si costruisce la **pipeline integrata** — cioè
quando si decide di far passare l'output di un agente come input di un altro.
È un test da fare *contestualmente* a quella architettura, non prima.

**Nota di design:** prima ancora di testarlo, valutare se la pipeline a cascata
serve davvero. Agenti isolati che riferiscono a un umano sono più semplici e più
sicuri di una catena automatica. La cascata introduce il rischio di
amplificazione proprio perché toglie l'umano dai passaggi intermedi.

### 3.4 Tool Use / Function Calling (il salto vero)
**Cosa:** quando l'agente *agirà* davvero (eseguirà script, modificherà file,
chiamerà API) invece di produrre solo piani testuali, testare che non "allucini"
flag o parametri inesistenti. Fornire schemi API obsoleti, parametri incompleti,
risposte di errore inattese, e verificare che il modello si astenga e segnali
l'anomalia sintattica invece di lanciare comandi distruttivi.

**Perché rimandato:** oggi l'agente di update è in fase di **decisione** (genera
piani che un umano esegue). Il function calling si testa quando l'agente passa da
"consiglia" a "agisce".

**Quando attivarlo:** è il **prossimo grande step dopo l'attuale agente di
update**. Quando si decide di dare all'agente la capacità di eseguire, questo
diventa il test critico — probabilmente un "SET 9" a sé. È il più importante dei
quattro futuri, perché è il punto in cui un errore del modello smette di essere
un piano sbagliato e diventa un'azione distruttiva su un sito vivo.

**Verifica chiave:** la coppia a consenso si estende naturalmente qui — due
modelli devono concordare anche sui *comandi* da eseguire, non solo sulla
decisione di procedere. Un comando proposto da un solo modello e non confermato
dall'altro non viene eseguito.

### 3.5 State Persistence / Memoria a lungo termine
**Cosa:** scenari multi-turno e multi-sessione dove la decisione corretta dipende
da un evento memorizzato iterazioni prima (es. non reiterare un aggiornamento
fallito poche ore prima). Identificare contraddizioni temporali o perdite di
allineamento sul lungo periodo.

**Perché rimandato:** i test attuali operano su contesti isolati che si azzerano
a ogni iterazione. Gli agenti oggi non hanno memoria storica delle azioni passate.

**Quando attivarlo:** quando si introduce un **database di memoria/stato** per gli
agenti (es. "questo aggiornamento è già stato tentato e fallito"). È un test da
fare contestualmente a quella feature.

### 3.6 CI/CD di regressione comportamentale (Continuous Alignment)
**Cosa:** pipeline automatica che riesegue i dataset critici (SET 4/5/6/7) a ogni
variazione di prompt o di peso del modello, per garantire che la risoluzione di un
bug non comprometta le difese acquisite (astensione, stabilità decisionale).

**Perché rimandato:** ha senso quando i prompt e i modelli cambiano spesso. Oggi
la valutazione è ancora in fase di *prima definizione*, non di manutenzione.

**Quando attivarlo:** quando il sistema è **in esercizio stabile** e si comincia a
fare manutenzione iterativa (affinamento prompt, sotto-release dei modelli da
parte dei vendor). A quel punto questa pipeline "blinda" i successi: prima di
adottare un nuovo prompt o una nuova versione di gemma/qwen, si rilanciano i SET
storici e si verifica che i risultati non siano peggiorati.

**Fattibilità:** alta e a basso costo, perché i dataset esistono già
(`eval_cases_set*.yaml`) e gli script di esecuzione/analisi (`batch_eval.py`,
`analisi_consenso.py`) sono pronti. Serve solo orchestrare l'esecuzione periodica
e un confronto automatico col baseline. È il test futuro più semplice da
implementare quando arriva il momento.

---

## 4. Sequenza logica complessiva (dove si inseriscono i test)

1. **Ora (sul pod):** SET 8 ridotto — contesto lungo + falsi positivi. Chiude la
   validazione della coppia a consenso prima di costruire l'agente.
2. **Costruzione agente di update** (fase decisionale: genera piani per l'umano).
3. **Hardware di produzione disponibile:** test 3.1 (latenza reale) + eventuale
   3.2 (quant gemma).
4. **Agente di update passa ad agire** (esegue, non solo consiglia): test 3.4
   (function calling) — il vero SET 9.
5. **Introduzione memoria di stato:** test 3.5.
6. **Pipeline multi-agente** (se si decide di costruirla): test 3.3 (cascade).
7. **Esercizio stabile + manutenzione:** test 3.6 (CI/CD di regressione), attivo
   in permanenza da lì in poi.

L'ordine non è rigido, ma la logica è: ogni test si attiva quando esiste la
condizione che rende sensato eseguirlo, non prima. Eseguire un test su
un'architettura inesistente produce numeri privi di significato.
